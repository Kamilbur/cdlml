from __future__ import annotations

from _ctypes import (
    FUNCFLAG_USE_ERRNO as _FUNCFLAG_USE_ERRNO,
    FUNCFLAG_USE_LASTERROR as _FUNCFLAG_USE_LASTERROR,
    CFuncPtr as _CFuncPtr,
)
import contextlib
import ctypes
from dataclasses import dataclass
import os
import pathlib
import select
import struct
import subprocess
import threading


__all__ = [
    "Preload",
    "PreloadedCDLL",
    "get_var",
    "sizeof",
    "addressof",
    "byref",
    "cast",
    "memmove",
    "memset",
    "pointer",
    "string_at",
    "dlnamespace",
]


def _has_dlmopen() -> bool:
    try:
        from _cdlml import _dlmopen as _  # noqa: F401

        return True
    except ImportError:
        return False


@contextlib.contextmanager
def dlnamespace():
    from _cdlml import _dlmopen as _, _dlmstop  # noqa: F401

    try:
        yield None
    finally:
        _dlmstop()


@dataclass
class Preload:
    name: bytes
    path: os.PathLike = b""
    alias: str = ""

    def __fspath__(self) -> bytes:
        path = self.path if self.path else self.name
        if isinstance(path, pathlib.Path):
            return str(path).encode()
        return os.fspath(path)


_OP_LOAD_LIB = 0x01
_OP_CALL_FUNC = 0x02
_OP_GET_VAR = 0x03
_OP_SHUTDOWN = 0x04
_OP_MEMMOVE = 0x05
_OP_MEMSET = 0x06
_OP_ALLOC = 0x07
_OP_FREE = 0x08
_OP_READ_MEM = 0x09
_OP_WRITE_MEM = 0x0A

_STATUS_OK = 0
_STATUS_ERR = 1

_TYPE_VOID = 0x00
_TYPE_I32 = 0x01
_TYPE_I64 = 0x02
_TYPE_U32 = 0x03
_TYPE_U64 = 0x04
_TYPE_F64 = 0x05
_TYPE_PTR = 0x06
_TYPE_CSTR = 0x07
_TYPE_F32 = 0x08

_CTYPES_TO_TYPE: dict = {
    ctypes.c_bool: _TYPE_U32,
    ctypes.c_int8: _TYPE_I32,
    ctypes.c_int16: _TYPE_I32,
    ctypes.c_int32: _TYPE_I32,
    ctypes.c_int: _TYPE_I32,
    ctypes.c_long: _TYPE_I64,
    ctypes.c_int64: _TYPE_I64,
    ctypes.c_ssize_t: _TYPE_I64,
    ctypes.c_uint8: _TYPE_U32,
    ctypes.c_uint16: _TYPE_U32,
    ctypes.c_uint32: _TYPE_U32,
    ctypes.c_uint: _TYPE_U32,
    ctypes.c_ulong: _TYPE_U64,
    ctypes.c_uint64: _TYPE_U64,
    ctypes.c_size_t: _TYPE_U64,
    ctypes.c_float: _TYPE_F32,
    ctypes.c_double: _TYPE_F64,
    ctypes.c_void_p: _TYPE_PTR,
    ctypes.c_char_p: _TYPE_CSTR,
    None: _TYPE_VOID,
}


def _read_exact(f, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            raise EOFError("cdlml_server closed unexpectedly")
        buf += chunk
    return buf


def _find_server_binary() -> str:
    pkg_dir = pathlib.Path(__file__).parent
    candidate = pkg_dir / "cdlml_server.exe"
    if candidate.exists():
        return str(candidate)
    msg = f"cdlml_server.exe binary not found at {candidate}; rebuild with pip install -e ."
    raise FileNotFoundError(msg)


class RemoteVar:
    """Proxy for a variable in the subprocess address space.

    Reads/writes via /proc/<pid>/mem so Python can control variables (e.g.
    interposer flags) that live inside the server process without the server
    needing to handle per-variable RPC round-trips on every access.
    """

    def __init__(self, pid: int, addr: int, ctype, server=None) -> None:
        self._pid = pid
        self._addr = addr
        self._ctype = ctype
        self._server = server
        self._size = ctypes.sizeof(ctype)

        # Detect if this is a pointer or array type to determine indexing behavior
        self._is_ptr = hasattr(ctype, "_type_") and not hasattr(ctype, "_length_")
        self._is_arr = hasattr(ctype, "_length_")

        if self._is_ptr or self._is_arr:
            self._base_type = ctype._type_
        else:
            self._base_type = ctype

    def __int__(self) -> int:
        return self._addr

    def __repr__(self) -> str:
        return f"<RemoteVar type={self._ctype!r} addr={hex(self._addr)}>"

    def _get_base_addr(self) -> int:
        if self._is_ptr:
            # For pointers, we must first read the pointer value stored at self._addr
            with open(f"/proc/{self._pid}/mem", "rb") as f:
                f.seek(self._addr)
                data = f.read(ctypes.sizeof(ctypes.c_void_p))
            return struct.unpack("<Q" if ctypes.sizeof(ctypes.c_void_p) == 8 else "<I", data)[0]
        return self._addr

    @property
    def value(self):
        with open(f"/proc/{self._pid}/mem", "rb") as f:
            f.seek(self._addr)
            data = f.read(self._size)
        obj = self._ctype.from_buffer_copy(data)
        if hasattr(obj, "value"):
            return obj.value
        return obj

    @value.setter
    def value(self, v) -> None:
        if isinstance(v, self._ctype):
            data = bytes(v)
        else:
            data = bytes(self._ctype(v))

        with open(f"/proc/{self._pid}/mem", "r+b") as f:
            f.seek(self._addr)
            f.write(data)

    def __getitem__(self, offset: int | slice):
        base_addr = self._get_base_addr()
        stride = ctypes.sizeof(self._base_type)

        if isinstance(offset, slice):
            start, stop, step = offset.indices(
                self._size // stride if hasattr(self._ctype, "_length_") else 1024 * 1024
            )  # reasonable default for pointers
            if step != 1:
                raise NotImplementedError("Slicing with step != 1 is not supported")

            count = stop - start
            if count <= 0:
                return b""

            with open(f"/proc/{self._pid}/mem", "rb") as f:
                f.seek(base_addr + start * stride)
                data = f.read(count * stride)
            return data

        with open(f"/proc/{self._pid}/mem", "rb") as f:
            f.seek(base_addr + offset * stride)
            data = f.read(stride)
        return self._base_type.from_buffer_copy(data).value

    def __setitem__(self, offset: int, v) -> None:
        base_addr = self._get_base_addr()
        stride = ctypes.sizeof(self._base_type)
        data = bytes(self._base_type(v))
        with open(f"/proc/{self._pid}/mem", "r+b") as f:
            f.seek(base_addr + offset * stride)
            f.write(data)


class RemoteFuncProxy:
    """Callable proxy for a function that executes inside the subprocess."""

    def __init__(self, name: str, server: FallbackPreloadedCDLL) -> None:
        self._name = name
        self._server = server
        self.argtypes: list | None = None
        self.restype = ctypes.c_int

    def __call__(self, *args):
        name_b = self._name.encode()
        ret_type = _CTYPES_TO_TYPE.get(self.restype, _TYPE_I64)
        argtypes = self.argtypes or []

        parts = [
            bytes([_OP_CALL_FUNC]),
            struct.pack("<I", len(name_b)),
            name_b,
            bytes([ret_type, len(args)]),
        ]

        for i, arg in enumerate(args):
            arg_type = (
                _CTYPES_TO_TYPE.get(argtypes[i], _TYPE_I64) if i < len(argtypes) else _TYPE_I64
            )

            arg_val = arg
            if hasattr(arg, "_addr"):
                arg_val = arg._addr
            elif hasattr(arg, "contents"):  # pointer objects
                arg_val = ctypes.addressof(arg.contents)

            if arg_type in (_TYPE_I32, _TYPE_U32):
                parts.append(bytes([arg_type]) + struct.pack("<I", int(arg_val) & 0xFFFFFFFF))
            elif arg_type in (_TYPE_I64, _TYPE_U64, _TYPE_PTR):
                parts.append(
                    bytes([arg_type]) + struct.pack("<Q", int(arg_val) & 0xFFFFFFFFFFFFFFFF)
                )
            elif arg_type == _TYPE_F32:
                parts.append(bytes([arg_type]) + struct.pack("<f", float(arg_val)))
            elif arg_type == _TYPE_F64:
                parts.append(bytes([arg_type]) + struct.pack("<d", float(arg_val)))
            elif arg_type == _TYPE_CSTR:
                s = (
                    arg_val.encode()
                    if isinstance(arg_val, str)
                    else (arg_val if isinstance(arg_val, bytes) else bytes(arg_val))
                )
                parts.append(bytes([arg_type]) + struct.pack("<I", len(s)) + s)
            else:
                parts.append(
                    bytes([_TYPE_I64]) + struct.pack("<Q", int(arg_val) & 0xFFFFFFFFFFFFFFFF)
                )

        with self._server._lock:
            self._server._send(b"".join(parts))
            r = self._server._r
            status = ord(_read_exact(r, 1))
            if status == _STATUS_ERR:
                msg_len = struct.unpack("<I", _read_exact(r, 4))[0]
                msg = _read_exact(r, msg_len).decode("utf-8", errors="replace")
                self._server._drain_streams()
                raise OSError(msg)

            result = None
            if ret_type == _TYPE_VOID:
                pass
            elif ret_type in (_TYPE_I32, _TYPE_U32):
                raw = struct.unpack("<I", _read_exact(r, 4))[0]
                result = -(0x100000000 - raw) if ret_type == _TYPE_I32 and raw & 0x80000000 else raw
            elif ret_type == _TYPE_F32:
                result = struct.unpack("<f", _read_exact(r, 4))[0]
            elif ret_type in (_TYPE_I64, _TYPE_U64, _TYPE_PTR, _TYPE_F64, _TYPE_CSTR):
                raw = struct.unpack("<Q", _read_exact(r, 8))[0]
                if ret_type == _TYPE_F64:
                    result = struct.unpack("<d", struct.pack("<Q", raw))[0]
                elif ret_type == _TYPE_I64 and raw & 0x8000000000000000:
                    result = -(0x10000000000000000 - raw)
                else:
                    result = raw

            self._server._drain_streams()
        return result


class FallbackCDLL:
    """Proxy for a library loaded inside the subprocess.

    Returned by FallbackPreloadedCDLL.__getitem__. Supports attribute-style
    function access (returns RemoteFuncProxy) and get_var() for variables.

    Note: ctypes.c_int.in_dll(lib, name) does not work with this class because
    it requires a valid dlopen handle in the calling process's address space.
    Use get_var(lib, ctype, name) instead.
    """

    def __init__(self, server: FallbackPreloadedCDLL) -> None:
        object.__setattr__(self, "_server", server)
        object.__setattr__(self, "_func_cache", {})

    def __get_var__(self, name: str, ctype=ctypes.c_int) -> RemoteVar:
        srv = object.__getattribute__(self, "_server")
        return srv.__get_var__(name, ctype)

    def __getattr__(self, name: str) -> RemoteFuncProxy:
        if name.startswith("_"):
            raise AttributeError(name)
        cache = object.__getattribute__(self, "_func_cache")
        if name not in cache:
            srv = object.__getattribute__(self, "_server")
            cache[name] = RemoteFuncProxy(name, srv)
        return cache[name]


class _PreloadedCDLLBase:
    """Abstract base for all PreloadedCDLL implementations."""


class GLIBCPreloadedCDLL(_PreloadedCDLLBase, ctypes.CDLL):
    """ctypes.CDLL subclass using glibc dlmopen for per-instance LD_PRELOAD.

    Loads all preload libraries and the main library into a private link-map
    namespace so the preloads interpose symbols only within that namespace,
    leaving the rest of the process unaffected.

    Args:
        name: Path to the main shared library.
        preloads: Libraries to load before the main one (interposers).
        use_errno: Propagate errno through function pointers.
        use_last_error: Propagate GetLastError through function pointers.
    """

    def __init__(
        self,
        name: bytes,
        preloads: list[Preload] | None = None,
        use_errno: bool = False,
        use_last_error: bool = False,
    ) -> None:
        from _cdlml import _dlmopen

        class _FuncPtr(_CFuncPtr):
            _flags_ = self._func_flags_
            _restype_ = self._func_restype_
            if use_errno:
                _flags_ |= _FUNCFLAG_USE_ERRNO
            if use_last_error:
                _flags_ |= _FUNCFLAG_USE_LASTERROR

        self._FuncPtr = _FuncPtr
        self._name = name
        self._handles = {}
        self._aliases = {}
        preloads = preloads or []

        with dlnamespace():
            for preload in preloads:
                path = os.fspath(preload)
                self._handles[preload.name] = ctypes.CDLL(None, handle=_dlmopen(path))
                if preload.alias:
                    self._aliases[preload.alias] = self._handles[preload.name]

            self._handle = _dlmopen(name)

    def __getitem__(self, name: bytes) -> ctypes.CDLL:
        if name in self._aliases:
            try:
                return self._aliases[name]
            except KeyError:
                pass
        if name in self._handles:
            try:
                return self._handles[name]
            except KeyError:
                pass
        return super().__getitem__(name)

    def __get_var__(self, name: str, ctype=ctypes.c_int):
        return ctype.in_dll(self, name)

    def __getattr__(self, name: str) -> ctypes.CFUNCTYPE:
        if name in self._aliases:
            try:
                return self._aliases[name]
            except KeyError:
                pass
        func = super().__getattr__(name)
        func.__class__ = self._FuncPtr
        return func


class FallbackPreloadedCDLL(_PreloadedCDLLBase):
    """Subprocess-based PreloadedCDLL for systems without glibc dlmopen.

    Spawns cdlml_server as a child process. Preload libraries are passed via
    LD_PRELOAD so the OS dynamic linker loads them before libc, giving true
    symbol interposition. The main library is then loaded via dlopen inside
    the server. Function calls and variable access are forwarded via a simple
    binary RPC protocol over explicit pipe file descriptors passed as argv to
    the server. The server's stdout and stderr remain available for loaded
    library I/O and are forwarded back to the client process by background
    daemon threads.

    Limitations vs GLIBCPreloadedCDLL:
    - ctypes.c_int.in_dll(lib, name) does not work; use get_var(lib, ctype, name).
    - Concurrent calls from multiple threads on the same instance are
      serialised by an internal lock.
    """

    def __init__(
        self,
        name,
        preloads: list[Preload] | None = None,
        use_errno: bool = False,
        use_last_error: bool = False,
    ) -> None:
        server_bin = _find_server_binary()
        preloads = preloads or []

        # Pass preloads via LD_PRELOAD so the OS dynamic linker loads them
        # before libc. dlopen at runtime cannot shadow already-loaded libc
        # symbols, but LD_PRELOAD guarantees interposition order at process start.
        env = os.environ.copy()
        if preloads:
            preload_paths = ":".join(os.fsdecode(os.fspath(p)) for p in preloads)
            existing = env.get("LD_PRELOAD", "")
            env["LD_PRELOAD"] = f"{preload_paths}:{existing}" if existing else preload_paths

        rpc_in_r, rpc_in_w = os.pipe()
        rpc_out_r, rpc_out_w = os.pipe()

        self._proc = subprocess.Popen(
            [server_bin, str(rpc_in_r), str(rpc_out_w)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(rpc_in_r, rpc_out_w),
            env=env,
        )
        os.close(rpc_in_r)
        os.close(rpc_out_w)

        self._w = os.fdopen(rpc_in_w, "wb")
        self._r = os.fdopen(rpc_out_r, "rb")
        self._stdout_fd = self._proc.stdout.fileno()
        self._stderr_fd = self._proc.stderr.fileno()
        self._lock = threading.Lock()

        self._func_cache: dict[str, RemoteFuncProxy] = {}
        self._preload_cdlls: dict[bytes, FallbackCDLL] = {}
        self._preload_aliases: dict[str, FallbackCDLL] = {}

        # Preloads are already loaded via LD_PRELOAD; just create proxy objects.
        # Their symbols are visible through dlsym(RTLD_DEFAULT) in the server.
        for preload in preloads:
            cdll = FallbackCDLL(self)
            self._preload_cdlls[preload.name] = cdll
            if preload.alias:
                self._preload_aliases[preload.alias] = cdll

        main_path = os.fsencode(os.fspath(name) if not isinstance(name, bytes) else name)
        self._rpc_load_lib(main_path, is_main=True)

    def _send(self, data: bytes) -> None:
        self._w.write(data)
        self._w.flush()

    def _drain_streams(self) -> None:
        """Forward all currently available server stdout/stderr to client fds.

        Called synchronously after each RPC response while the lock is held.
        Uses select(timeout=0) so it never blocks — only drains what the kernel
        already has buffered, which is everything the server wrote before sending
        the RPC response.
        """
        for src_fd, dst_fd in ((self._stdout_fd, 1), (self._stderr_fd, 2)):
            while select.select([src_fd], [], [], 0)[0]:
                chunk = os.read(src_fd, 65536)
                if not chunk:
                    break
                os.write(dst_fd, chunk)

    def _rpc_load_lib(self, path: bytes, *, is_main: bool) -> None:
        payload = (
            bytes([_OP_LOAD_LIB])
            + struct.pack("<I", len(path))
            + path
            + bytes([1 if is_main else 0])
        )
        with self._lock:
            self._send(payload)
            r = self._r
            status = ord(_read_exact(r, 1))
            if status == _STATUS_ERR:
                msg_len = struct.unpack("<I", _read_exact(r, 4))[0]
                msg = _read_exact(r, msg_len).decode("utf-8", errors="replace")
                self._drain_streams()
                raise OSError(f"cdlml_server load failed: {msg}")
            self._drain_streams()

    def __get_var__(self, name: str, ctype=ctypes.c_int) -> RemoteVar:
        name_b = name.encode() if isinstance(name, str) else name
        with self._lock:
            self._send(bytes([_OP_GET_VAR]) + struct.pack("<I", len(name_b)) + name_b)
            r = self._r
            status = ord(_read_exact(r, 1))
            if status == _STATUS_ERR:
                msg_len = struct.unpack("<I", _read_exact(r, 4))[0]
                msg = _read_exact(r, msg_len).decode("utf-8", errors="replace")
                self._drain_streams()
                raise OSError(msg)
            addr = struct.unpack("<Q", _read_exact(r, 8))[0]
            self._drain_streams()
        return RemoteVar(self._proc.pid, addr, ctype, server=self)

    def _rpc_alloc(self, size: int) -> int:
        payload = bytes([_OP_ALLOC]) + struct.pack("<Q", size)
        with self._lock:
            self._send(payload)
            r = self._r
            status = ord(_read_exact(r, 1))
            if status == _STATUS_ERR:
                msg_len = struct.unpack("<I", _read_exact(r, 4))[0]
                msg = _read_exact(r, msg_len).decode("utf-8", errors="replace")
                self._drain_streams()
                raise OSError(msg)
            addr = struct.unpack("<Q", _read_exact(r, 8))[0]
            self._drain_streams()
            return addr

    def _rpc_free(self, addr: int) -> None:
        payload = bytes([_OP_FREE]) + struct.pack("<Q", addr)
        with self._lock:
            self._send(payload)
            r = self._r
            status = ord(_read_exact(r, 1))
            if status == _STATUS_ERR:
                msg_len = struct.unpack("<I", _read_exact(r, 4))[0]
                msg = _read_exact(r, msg_len).decode("utf-8", errors="replace")
                self._drain_streams()
                raise OSError(msg)
            self._drain_streams()

    def _rpc_read_mem(self, addr: int, size: int) -> bytes:
        payload = bytes([_OP_READ_MEM]) + struct.pack("<QI", addr, size)
        with self._lock:
            self._send(payload)
            r = self._r
            status = ord(_read_exact(r, 1))
            if status == _STATUS_ERR:
                msg_len = struct.unpack("<I", _read_exact(r, 4))[0]
                msg = _read_exact(r, msg_len).decode("utf-8", errors="replace")
                self._drain_streams()
                raise OSError(msg)
            data = _read_exact(r, size)
            self._drain_streams()
            return data

    def _rpc_write_mem(self, addr: int, data: bytes) -> None:
        size = len(data)
        payload = bytes([_OP_WRITE_MEM]) + struct.pack("<QI", addr, size) + data
        with self._lock:
            self._send(payload)
            r = self._r
            status = ord(_read_exact(r, 1))
            if status == _STATUS_ERR:
                msg_len = struct.unpack("<I", _read_exact(r, 4))[0]
                msg = _read_exact(r, msg_len).decode("utf-8", errors="replace")
                self._drain_streams()
                raise OSError(msg)
            self._drain_streams()

    def _rpc_memmove(self, dst: int, src: int, count: int) -> None:
        payload = bytes([_OP_MEMMOVE]) + struct.pack("<QQQ", dst, src, count)
        with self._lock:
            self._send(payload)
            r = self._r
            status = ord(_read_exact(r, 1))
            if status == _STATUS_ERR:
                msg_len = struct.unpack("<I", _read_exact(r, 4))[0]
                msg = _read_exact(r, msg_len).decode("utf-8", errors="replace")
                self._drain_streams()
                raise OSError(msg)
            self._drain_streams()

    def _rpc_memset(self, dst: int, val: int, count: int) -> None:
        payload = bytes([_OP_MEMSET]) + struct.pack("<QBQ", dst, val & 0xFF, count)
        with self._lock:
            self._send(payload)
            r = self._r
            status = ord(_read_exact(r, 1))
            if status == _STATUS_ERR:
                msg_len = struct.unpack("<I", _read_exact(r, 4))[0]
                msg = _read_exact(r, msg_len).decode("utf-8", errors="replace")
                self._drain_streams()
                raise OSError(msg)
            self._drain_streams()

    def __getitem__(self, name) -> FallbackCDLL:
        if isinstance(name, str) and name in self._preload_aliases:
            return self._preload_aliases[name]
        if name in self._preload_cdlls:
            return self._preload_cdlls[name]
        msg = f"no preloaded library named {name!r}"
        raise KeyError(msg)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        aliases = object.__getattribute__(self, "_preload_aliases")
        if name in aliases:
            return aliases[name]
        cache = object.__getattribute__(self, "_func_cache")
        if name not in cache:
            cache[name] = RemoteFuncProxy(name, self)
        return cache[name]

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            with self._lock:
                self._send(bytes([_OP_SHUTDOWN]))
        try:
            self._proc.wait(timeout=2)
        except Exception:
            with contextlib.suppress(Exception):
                self._proc.kill()


def get_var(cdll, ctype, name: str):
    """Return a variable from cdll by name, as the appropriate type.

    Works with ctypes.CDLL, GLIBCPreloadedCDLL, FallbackCDLL, and
    FallbackPreloadedCDLL. Falls back to ctype.in_dll(cdll, name) for any
    object without the __get_var__ protocol.
    """
    if hasattr(cdll, "__get_var__"):
        return cdll.__get_var__(name, ctype)
    return ctype.in_dll(cdll, name)


class _RemotePointer(int):
    def __new__(cls, addr, server):
        obj = super().__new__(cls, addr)
        obj._addr = addr
        obj._server = server
        return obj


class RemoteRef:
    """Manages a temporary remote reference to a local ctypes object."""

    def __init__(self, obj, server: FallbackPreloadedCDLL):
        self._local_obj = obj
        self._server = server
        self._ctype = type(obj)
        self._size = ctypes.sizeof(obj)
        self._addr = server._rpc_alloc(self._size)
        # Initial sync to remote
        server._rpc_write_mem(self._addr, bytes(obj))

    def _sync_back(self):
        """Sync remote memory back to local ctypes object."""
        data = self._server._rpc_read_mem(self._addr, self._size)
        ctypes.memmove(ctypes.addressof(self._local_obj), data, self._size)

    def __int__(self) -> int:
        return self._addr

    def __del__(self):
        if hasattr(self, "_server") and hasattr(self, "_addr"):
            with contextlib.suppress(Exception):
                self._server._rpc_free(self._addr)


def sizeof(obj):
    if isinstance(obj, (RemoteVar, RemoteRef)):
        return obj._size
    return ctypes.sizeof(obj)


def addressof(obj):
    if isinstance(obj, (RemoteVar, RemoteRef)):
        return _RemotePointer(obj._addr, obj._server)
    return ctypes.addressof(obj)


def byref(obj, offset=0, cdll=None):
    if isinstance(obj, (RemoteVar, RemoteRef)):
        return _RemotePointer(obj._addr + offset, obj._server)

    if cdll and hasattr(cdll, "_server"):
        # Create a remote reference for the local object
        ref = RemoteRef(obj, cdll._server)
        if offset != 0:
            return _RemotePointer(ref._addr + offset, ref._server)
        return ref

    if offset == 0:
        return ctypes.byref(obj)
    return ctypes.addressof(obj) + offset


def cast(obj, typ, cdll=None):
    if isinstance(obj, (RemoteVar, RemoteRef)):
        return RemoteVar(obj._pid if hasattr(obj, "_pid") else -1, obj._addr, typ, server=obj._server)

    if isinstance(obj, int) and cdll and hasattr(cdll, "_server"):
        return RemoteVar(-1, obj, typ, server=cdll._server)

    return ctypes.cast(obj, typ)


def memmove(dst, src, count):
    srv_dst = getattr(dst, "_server", None)
    srv_src = getattr(src, "_server", None)

    if srv_dst and srv_src and srv_dst is not srv_src:
        raise ValueError("memmove between different remote servers not supported")

    if srv_dst and srv_src:
        # remote -> remote
        srv_dst._rpc_memmove(int(dst), int(src), count)
        return

    if srv_dst:
        # remote dst + local src
        # Read local bytes
        if isinstance(src, int):
            # We can't safely read from a raw int locally without ctypes help
            src_ptr = ctypes.cast(src, ctypes.POINTER(ctypes.c_char * count))
            data = bytes(src_ptr.contents)
        else:
            data = bytes(ctypes.cast(src, ctypes.POINTER(ctypes.c_char * count)).contents)
        srv_dst._rpc_write_mem(int(dst), data)
        return

    if srv_src:
        # local dst + remote src
        data = srv_src._rpc_read_mem(int(src), count)
        # Write to local
        dst_ptr = ctypes.cast(dst, ctypes.POINTER(ctypes.c_char * count))
        ctypes.memmove(dst_ptr, data, count)
        return

    ctypes.memmove(dst, src, count)


def memset(dst, val, count):
    srv = getattr(dst, "_server", None)
    if srv:
        srv._rpc_memset(int(dst), val, count)
        return

    ctypes.memset(dst, val, count)


def pointer(obj, cdll=None):
    if isinstance(obj, RemoteVar):
        raise NotImplementedError("pointer() for RemoteVar is not yet implemented")

    if isinstance(obj, RemoteRef):
        # pointer(remote_obj) needs to allocate remote storage for the pointer
        if obj._server:
            ptr_addr = obj._server._rpc_alloc(ctypes.sizeof(ctypes.c_void_p))
            # Write obj._addr into that storage
            fmt = "<Q" if ctypes.sizeof(ctypes.c_void_p) == 8 else "<I"
            data = struct.pack(fmt, obj._addr)
            obj._server._rpc_write_mem(ptr_addr, data)
            return RemoteVar(-1, ptr_addr, ctypes.POINTER(obj._ctype), server=obj._server)

    if cdll and hasattr(cdll, "_server"):
        # Allocate remote storage for obj address
        # First we need obj to be remote
        ref = RemoteRef(obj, cdll._server)
        ptr_addr = cdll._server._rpc_alloc(ctypes.sizeof(ctypes.c_void_p))
        fmt = "<Q" if ctypes.sizeof(ctypes.c_void_p) == 8 else "<I"
        data = struct.pack(fmt, ref._addr)
        cdll._server._rpc_write_mem(ptr_addr, data)
        return RemoteVar(-1, ptr_addr, ctypes.POINTER(type(obj)), server=cdll._server)

    return ctypes.pointer(obj)


def string_at(ptr, size=-1):
    srv = getattr(ptr, "_server", None)
    if srv:
        if size == -1:
            # We don't know the size, need to find null terminator
            # Let's read in chunks
            res = b""
            chunk_size = 32
            addr = int(ptr)
            while True:
                chunk = srv._rpc_read_mem(addr, chunk_size)
                null_idx = chunk.find(b"\x00")
                if null_idx != -1:
                    res += chunk[:null_idx]
                    break
                res += chunk
                addr += chunk_size
            return res
        return srv._rpc_read_mem(int(ptr), size)

    return ctypes.string_at(ptr, size)


class PreloadedCDLL:
    """Factory that returns GLIBCPreloadedCDLL when dlmopen is available,
    otherwise FallbackPreloadedCDLL (subprocess-based).

    See GLIBCPreloadedCDLL and FallbackPreloadedCDLL for full documentation.
    """

    def __new__(
        cls,
        name,
        preloads: list[Preload] | None = None,
        use_errno: bool = False,
        use_last_error: bool = False,
    ):
        if _has_dlmopen():
            return GLIBCPreloadedCDLL(name, preloads, use_errno, use_last_error)
        return FallbackPreloadedCDLL(name, preloads, use_errno, use_last_error)
