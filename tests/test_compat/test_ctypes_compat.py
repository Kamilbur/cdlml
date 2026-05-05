import threading
import time
from pathlib import Path

import ctypes
import cdlml
import pytest


def test_sizeof_addressof_local():
    val = ctypes.c_int32(10)
    assert cdlml.sizeof(val) == 4
    assert cdlml.addressof(val) == ctypes.addressof(val)

    buf = (ctypes.c_char * 100)()
    assert cdlml.sizeof(buf) == 100
    assert cdlml.addressof(buf) == ctypes.addressof(buf)


def test_sizeof_addressof_remote(compat_lib):
    var = cdlml.get_var(compat_lib, ctypes.c_int32, "global_i32")
    assert cdlml.sizeof(var) == 4
    assert isinstance(cdlml.addressof(var), int)
    assert cdlml.addressof(var) > 0

    buf = cdlml.get_var(compat_lib, ctypes.c_char * 32, "global_buf")
    assert cdlml.sizeof(buf) == 32


def test_byref_local():
    val = ctypes.c_int32(10)
    # ctypes.byref returns a cparam object which can't be compared with int directly
    # but we can check it via another function or just ensure it's the right type
    # and that our addressof works on it if we wanted, but ctypes.addressof doesn't work on cparam.
    assert "cparam" in str(cdlml.byref(val))

    assert cdlml.byref(val, 2) == ctypes.addressof(val) + 2

    # Large offset
    assert cdlml.byref(val, 1000) == ctypes.addressof(val) + 1000


def test_byref_remote(compat_lib):
    var = cdlml.get_var(compat_lib, ctypes.c_int32, "global_i32")
    addr = cdlml.addressof(var)
    assert cdlml.byref(var) == addr
    assert cdlml.byref(var, 4) == addr + 4
    assert cdlml.byref(var, -4) == addr - 4


def test_cast_remote(compat_lib):
    var = cdlml.get_var(compat_lib, ctypes.c_int32, "global_i32")
    # Cast to char array to see raw bytes
    cast_var = cdlml.cast(var, ctypes.c_char * 4)
    assert cdlml.sizeof(cast_var) == 4
    # 42 in little-endian: 0x2A 0x00 0x00 0x00
    assert cast_var[0] == b"*"
    assert cast_var[1] == b"\x00"

    # Cast to different int type
    short_var = cdlml.cast(var, ctypes.c_int16)
    assert cdlml.sizeof(short_var) == 2
    assert short_var.value == 42


def test_fallback_function_attrs_are_cached(compat_lib):
    fn = compat_lib.reset_compat
    fn.argtypes = []
    fn.restype = None

    assert compat_lib.reset_compat is fn
    assert compat_lib.reset_compat.argtypes == []
    assert compat_lib.reset_compat.restype is None


def test_fallback_cdll_function_attrs_are_cached(compat_lib):
    lib = cdlml.FallbackCDLL(compat_lib)
    fn = lib.reset_compat
    fn.argtypes = []
    fn.restype = None

    assert lib.reset_compat is fn
    assert lib.reset_compat.argtypes == []
    assert lib.reset_compat.restype is None


def test_memset_remote(compat_lib):
    compat_lib.reset_compat()
    var = cdlml.get_var(compat_lib, ctypes.c_char * 8, "global_buf")

    # Full fill
    cdlml.memset(var, ord("A"), 8)
    for i in range(8):
        assert var[i] == b"A"

    # Partial fill using cast to offset address
    # byref returns an int which cdlml.memset now rejects for safety
    addr = cdlml.addressof(var)
    offset_var = cdlml.cast(
        cdlml.RemoteVar(var._pid, addr + 2, ctypes.c_char * 2, server=var._server),
        ctypes.c_char * 2,
    )

    cdlml.memset(offset_var, ord("B"), 2)
    assert var[1] == b"A"
    assert var[2] == b"B"
    assert var[3] == b"B"
    assert var[4] == b"A"

    # Zero length memset
    cdlml.memset(var, ord("Z"), 0)
    assert var[0] == b"A"


def test_memmove_remote_basic(compat_lib):
    compat_lib.reset_compat()
    var = cdlml.get_var(compat_lib, ctypes.c_char * 32, "global_buf")

    # Move "initial" to offset 10
    cdlml.memmove(cdlml.byref(var, 10), var, 7)
    assert var[10:17] == b"initial"

    # Move back
    cdlml.memset(var, 0, 7)
    assert var[0] == b"\x00"
    cdlml.memmove(var, cdlml.byref(var, 10), 7)
    assert var[0:7] == b"initial"


def test_memmove_remote_overlap(compat_lib):
    compat_lib.reset_compat()
    var = cdlml.get_var(compat_lib, ctypes.c_char * 32, "global_buf")
    # global_buf is "initial\0..."

    # Overlap forward: "initial" -> "iinitial"
    # i n i t i a l
    # 0 1 2 3 4 5 6
    # move 7 bytes from 0 to 1
    cdlml.memmove(cdlml.byref(var, 1), var, 7)
    assert var[0:8] == b"iinitial"

    # Overlap backward
    compat_lib.reset_compat()
    # "initial" -> "nitial" at 0
    cdlml.memmove(var, cdlml.byref(var, 1), 6)
    assert var[0:6] == b"nitial"


def test_memmove_remote_zero_count(compat_lib):
    compat_lib.reset_compat()
    var = cdlml.get_var(compat_lib, ctypes.c_char * 32, "global_buf")
    # Store original state
    original = var[0:32]
    cdlml.memmove(cdlml.byref(var, 10), var, 0)
    # Should be identical
    assert var[0:32] == original
    assert var[0] == b"i"


def test_memmove_remote_cross_types(compat_lib):
    compat_lib.reset_compat()
    i32_var = cdlml.get_var(compat_lib, ctypes.c_int32, "global_i32")
    buf_var = cdlml.get_var(compat_lib, ctypes.c_char * 32, "global_buf")

    # Move 42 (i32) into start of buffer
    cdlml.memmove(buf_var, i32_var, 4)
    assert buf_var[0] == b"*"
    assert buf_var[1] == b"\x00"


def test_pointer_remote_raises(compat_lib):
    var = cdlml.get_var(compat_lib, ctypes.c_int32, "global_i32")
    with pytest.raises(
        NotImplementedError, match=r"pointer\(\) for RemoteVar is not yet implemented"
    ):
        cdlml.pointer(var)


def test_remote_func_arg_passing_with_byref(compat_lib):
    # In src/cdlml/__init__.py, RemoteFuncProxy handles arguments with _addr
    # cdlml.byref returns an int (the address)
    # RemoteVar objects have __int__ returning address

    compat_lib.reset_compat()
    var = cdlml.get_var(compat_lib, ctypes.c_int32, "global_i32")

    # We can pass an int as a pointer to a function via RPC
    # memset on the server side is a good test for this logic
    cdlml.memset(var, 0x11, 4)
    assert var.value == 0x11111111


class CompatStruct(ctypes.Structure):
    _fields_ = [
        ("a", ctypes.c_int32),
        ("b", ctypes.c_double),
        ("c", ctypes.c_char * 16),
    ]


def test_struct_remote(compat_lib):
    compat_lib.reset_struct()
    var = cdlml.get_var(compat_lib, CompatStruct, "global_struct")

    assert var.value.a == 1
    assert var.value.b == 2.0
    assert var.value.c == b"struct"

    # Modify via memset
    # Use RemoteVar with offset to provide server context
    offset_var = cdlml.RemoteVar(
        var._pid, var._addr + CompatStruct.a.offset, ctypes.c_int32, server=var._server
    )
    cdlml.memset(offset_var, 0x7F, 4)
    assert var.value.a == 0x7F7F7F7F


def test_remote_func_struct_ptr(compat_lib):
    compat_lib.reset_struct()
    var = cdlml.get_var(compat_lib, CompatStruct, "global_struct")

    fn = compat_lib.sum_struct
    fn.argtypes = [ctypes.POINTER(CompatStruct)]
    fn.restype = ctypes.c_int32

    # Pass RemoteVar as a pointer
    assert fn(var) == 3  # 1 + 2

    var.value = CompatStruct(10, 20.0, b"new")
    assert fn(var) == 30


def test_slicing_edge_cases(compat_lib):
    var = cdlml.get_var(compat_lib, ctypes.c_char * 32, "global_buf")
    compat_lib.reset_compat()

    # Normal slice
    assert var[0:7] == b"initial"

    # Out of bounds
    assert len(var[0:100]) == 32
    assert var[100:110] == b""

    # Negative indices
    assert var[-7:] == var[25:32]
    assert var[:-25] == b"initial"

    # Step != 1 should raise
    with pytest.raises(NotImplementedError):
        var[::2]


def test_memmove_cross_server_error(compat_lib):
    # Create another server instance
    src_dir = Path(__file__).resolve().parent
    lib2 = cdlml.FallbackPreloadedCDLL(src_dir / "libcompat.so")

    var1 = cdlml.get_var(compat_lib, ctypes.c_char * 32, "global_buf")
    var2 = cdlml.get_var(lib2, ctypes.c_char * 32, "global_buf")

    with pytest.raises(ValueError, match="memmove between different remote servers not supported"):
        cdlml.memmove(var1, var2, 10)


def test_concurrency(compat_lib):
    compat_lib.reset_compat()
    var = cdlml.get_var(compat_lib, ctypes.c_char * 1024, "global_buf")

    def worker(offset, char):
        # Create a RemoteVar at the offset to carry server info
        target = cdlml.RemoteVar(var._pid, var._addr + offset, ctypes.c_char, server=var._server)
        for _ in range(50):
            cdlml.memset(target, ord(char), 1)
            time.sleep(0.001)

    threads = [threading.Thread(target=worker, args=(i, chr(ord("A") + i))) for i in range(10)]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i in range(10):
        assert var[i] == chr(ord("A") + i).encode()


def test_unaligned_memmove(compat_lib):
    compat_lib.reset_compat()
    var = cdlml.get_var(compat_lib, ctypes.c_char * 32, "global_buf")

    # Move "nitial" (from offset 1) to offset 11
    # Use var (RemoteVar) for src to identify the server
    cdlml.memmove(
        cdlml.byref(var, 11),
        cdlml.cast(
            cdlml.RemoteVar(var._pid, var._addr + 1, ctypes.c_char * 6, server=var._server),
            ctypes.c_char * 6,
        ),
        6,
    )
    assert var[11:17] == b"nitial"


class Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


class Rect(ctypes.Structure):
    _fields_ = [("top_left", Point), ("bottom_right", Point)]


class DataUnion(ctypes.Union):
    _fields_ = [("i", ctypes.c_int32), ("f", ctypes.c_float), ("bytes", ctypes.c_char * 4)]


class ComplexType(ctypes.Structure):
    _fields_ = [("rects", Rect * 2), ("u", DataUnion)]


def test_nested_struct_remote(compat_lib):
    compat_lib.reset_complex()
    var = cdlml.get_var(compat_lib, ComplexType, "global_complex")

    # Read nested
    assert var.value.rects[0].top_left.x == 0
    assert var.value.rects[1].bottom_right.y == 30

    # Write nested via value property (re-writes entire struct)
    val = var.value
    val.rects[0].top_left.x = 5
    var.value = val
    assert var.value.rects[0].top_left.x == 5

    # Write nested via memset to specific offset
    # rects[1].top_left.y is at: offset(rects) + sizeof(Rect) + offset(top_left) + offset(y)
    offset = ComplexType.rects.offset + ctypes.sizeof(Rect) + Rect.top_left.offset + Point.y.offset
    offset_var = cdlml.RemoteVar(var._pid, var._addr + offset, ctypes.c_int32, server=var._server)
    cdlml.memset(offset_var, 0x11, 4)
    assert var.value.rects[1].top_left.y == 0x11111111


def test_union_remote(compat_lib):
    compat_lib.reset_complex()
    var = cdlml.get_var(compat_lib, ComplexType, "global_complex")

    assert var.value.u.i == 12345

    # Modify as float
    val = var.value
    val.u.f = 3.14
    var.value = val
    assert pytest.approx(var.value.u.f) == 3.14


def test_remote_func_nested_ptr(compat_lib):
    compat_lib.reset_complex()
    var = cdlml.get_var(compat_lib, ComplexType, "global_complex")

    fn = compat_lib.get_rect_area
    fn.argtypes = [ctypes.POINTER(Rect)]
    fn.restype = ctypes.c_int32

    # Pass pointer to nested rect
    # We need a RemoteVar that points to the nested field
    rect1_addr = var._addr + ComplexType.rects.offset + ctypes.sizeof(Rect)
    rect1_var = cdlml.RemoteVar(var._pid, rect1_addr, Rect, server=var._server)

    # (30-20) * (30-20) = 100
    assert fn(rect1_var) == 100


def test_addressof_nested_field(compat_lib):
    var = cdlml.get_var(compat_lib, ComplexType, "global_complex")
    # Our addressof(RemoteVar) returns the base address.
    # To get address of a field, one must use byref or manual offset.
    base = cdlml.addressof(var)
    assert cdlml.byref(var, ComplexType.u.offset) == base + ComplexType.u.offset


def test_cast_consistency(compat_lib):
    var = cdlml.get_var(compat_lib, ctypes.c_int32, "global_i32")
    cast_var = cdlml.cast(var, ctypes.c_uint32)

    assert cast_var._pid == var._pid
    assert cast_var._addr == var._addr
    assert cast_var._server is var._server
    assert cast_var._ctype == ctypes.c_uint32


def test_slicing_comprehensive(compat_lib):
    compat_lib.reset_compat()
    var = cdlml.get_var(compat_lib, ctypes.c_char * 32, "global_buf")
    # "initial\0..."

    assert var[:] == var[0:32]
    assert var[1:4] == b"nit"
    assert var[7:8] == b"\x00"
    assert var[-10:] == b"\x00" * 10
    assert var[30:100] == b"\x00" * 2
    assert var[5:2] == b""


def test_sizeof_various_types():
    assert cdlml.sizeof(ctypes.c_int16(1)) == 2
    assert cdlml.sizeof(ctypes.c_char_p(b"abc")) == ctypes.sizeof(ctypes.c_char_p)

    class SmallStruct(ctypes.Structure):
        _fields_ = [("x", ctypes.c_byte)]

    assert cdlml.sizeof(SmallStruct()) == 1


def test_memmove_large(compat_lib):
    # Stress test RPC a bit with 1KB move
    compat_lib.reset_large_buf()
    var = cdlml.get_var(compat_lib, ctypes.c_char * 1024, "global_large_buf")

    # Copy first 512 bytes to the second 512 bytes
    cdlml.memmove(cdlml.byref(var, 512), var, 512)

    assert var[512:1024] == var[0:512]
    # Check some values
    assert var[512] == b"\x00"
    assert var[512 + 10] == b"\x0a"


def test_large_memset_stress(compat_lib):
    var = cdlml.get_var(compat_lib, ctypes.c_char * 1024, "global_large_buf")
    cdlml.memset(var, 0xCC, 1024)
    assert var[:] == b"\xcc" * 1024


def test_byref_offset_negative_local():
    val = (ctypes.c_char * 10)(*b"0123456789")
    ptr = cdlml.byref(val, 5)
    assert ptr == ctypes.addressof(val) + 5
    assert cdlml.byref(val, -1) == ctypes.addressof(val) - 1


def test_memmove_memset_local_addr():
    # This simulates GLIBC mode where we use raw int addresses
    a = (ctypes.c_char * 10)(*b"0123456789")
    b = (ctypes.c_char * 10)()

    addr_a = cdlml.addressof(a)
    addr_b = cdlml.addressof(b)

    # Should work and not raise TypeError
    cdlml.memmove(addr_b, addr_a, 10)
    assert b[:] == b"0123456789"

    cdlml.memset(addr_b, ord('X'), 5)
    assert b[:] == b"XXXXX56789"

def test_remote_var_repr(compat_lib):
    var = cdlml.get_var(compat_lib, ctypes.c_int32, "global_i32")
    r = repr(var)
    assert "RemoteVar" in r
    assert hex(var._addr) in r


def test_memset_invalid_val_type(compat_lib):
    var = cdlml.get_var(compat_lib, ctypes.c_int32, "global_i32")
    # val should be an int (byte). If we pass a string, cdlml.memset(RemoteVar)
    # should probably fail or handle it. Current impl uses val & 0xFF.
    # If val is "A", ord("A") is needed. Our memset(RemoteVar) expects int.
    with pytest.raises(TypeError):
        cdlml.memset(var, "A", 1)
