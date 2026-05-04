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
    ctypes.c_float: _TYPE_F64,
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

    def __init__(self, pid: int, addr: int, ctype) -> None:
        self._pid = pid
        self._addr = addr
        self._ctype = ctype
        self._size = ctypes.sizeof(ctype)

    @property
    def value(self):
        with open(f"/proc/{self._pid}/mem", "rb") as f:
            f.seek(self._addr)
            data = f.read(self._size)
        return self._ctype.from_buffer_copy(data).value

    @value.setter
    def value(self, v) -> None:
        data = bytes(self._ctype(v))
        with open(f"/proc/{self._pid}/mem", "r+b") as f:
            f.seek(self._addr)
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

            if arg_type in (_TYPE_I32, _TYPE_U32):
                parts.append(bytes([arg_type]) + struct.pack("<I", int(arg) & 0xFFFFFFFF))
            elif arg_type in (_TYPE_I64, _TYPE_U64, _TYPE_PTR):
                parts.append(bytes([arg_type]) + struct.pack("<Q", int(arg) & 0xFFFFFFFFFFFFFFFF))
            elif arg_type == _TYPE_F64:
                parts.append(bytes([arg_type]) + struct.pack("<d", float(arg)))
            elif arg_type == _TYPE_CSTR:
                s = (
                    arg.encode()
                    if isinstance(arg, str)
                    else (arg if isinstance(arg, bytes) else bytes(arg))
                )
                parts.append(bytes([arg_type]) + struct.pack("<I", len(s)) + s)
            else:
                parts.append(bytes([_TYPE_I64]) + struct.pack("<Q", int(arg) & 0xFFFFFFFFFFFFFFFF))

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

    def __get_var__(self, name: str, ctype=ctypes.c_int) -> RemoteVar:
        srv = object.__getattribute__(self, "_server")
        return srv.__get_var__(name, ctype)

    def __getattr__(self, name: str) -> RemoteFuncProxy:
        if name.startswith("_"):
            raise AttributeError(name)
        srv = object.__getattribute__(self, "_server")
        return RemoteFuncProxy(name, srv)


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
    - Float/double function arguments require libffi (not bundled); only
      integer and pointer arguments are supported via the trampoline.
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
        return RemoteVar(self._proc.pid, addr, ctype)

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
        return RemoteFuncProxy(name, self)

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
