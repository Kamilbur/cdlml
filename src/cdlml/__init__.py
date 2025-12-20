from __future__ import annotations

from _ctypes import (
    FUNCFLAG_USE_ERRNO as _FUNCFLAG_USE_ERRNO,
    FUNCFLAG_USE_LASTERROR as _FUNCFLAG_USE_LASTERROR,
    CFuncPtr as _CFuncPtr,
)
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import os
import pathlib

from _cdlml import _dlmopen, _dlmstop


@contextmanager
def dlnamespace():
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


class PreloadedCDLL(ctypes.CDLL):
    """A ctypes.CDLL subclass that supports preloading shared libraries.

    It enables LD_PRELOAD-like behavior by loading specified libraries
    into a separate namespace before loading the main library. The main
    difference from standard LD_PRELOAD is that this class allows
    preloading libraries on a per-instance basis, rather than globally
    for the entire process. As process global LD_PRELOAD affects everything,
    e.g. also the Python interpreter itself, this class provides a more
    controlled way to achieve similar functionality.

    Additionally, it supports aliasing preloaded libraries for easier access.

    Args:
        name (bytes): The name of the main shared library to load.
        preloads (list[Preload] | None): A list of Preload instances
            specifying libraries to preload.
        use_errno (bool): Whether to enable errno handling for function pointers.
        use_last_error (bool): Whether to enable last error handling for function pointers.

    """

    def __init__(self, name: bytes, preloads: list[Preload] | None = None,
                 use_errno: bool = False, use_last_error: bool = False):

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

    def __getattr__(self, name: str) -> ctypes.CFUNCTYPE:
        if name in self._aliases:
            try:
                return self._aliases[name]
            except KeyError:
                pass
        func = super().__getattr__(name)
        func.__class__ = self._FuncPtr
        return func
