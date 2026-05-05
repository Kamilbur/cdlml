import ctypes
from cdlml import get_var
import pytest


def test_i32_ptr_access(array_lib):
    array_lib.reset_arrays()
    # Testing pointer access: int32_t *i32_ptr
    var = get_var(array_lib, ctypes.POINTER(ctypes.c_int32), "i32_ptr")

    get_i32 = array_lib.get_i32
    get_i32.restype = ctypes.c_int32
    get_i32.argtypes = [ctypes.c_int]
    assert var[0] == 10
    assert var[1] == 20
    assert var[4] == 50

    var[1] = 22
    assert var[1] == 22
    assert get_i32(1) == 22


def test_i64_ptr_access(array_lib):
    array_lib.reset_arrays()
    var = get_var(array_lib, ctypes.POINTER(ctypes.c_int64), "i64_ptr")

    get_i64 = array_lib.get_i64
    get_i64.restype = ctypes.c_int64
    get_i64.argtypes = [ctypes.c_int]

    assert var[0] == 100
    assert var[2] == 300

    var[2] = 333
    assert var[2] == 333
    assert get_i64(2) == 333


def test_f32_ptr_access(array_lib):
    array_lib.reset_arrays()
    var = get_var(array_lib, ctypes.POINTER(ctypes.c_float), "f32_ptr")

    get_f32 = array_lib.get_f32
    get_f32.restype = ctypes.c_float
    get_f32.argtypes = [ctypes.c_int]

    assert var[0] == pytest.approx(1.1)
    assert var[1] == pytest.approx(2.2)
    assert get_f32(0) == pytest.approx(1.1)

    var[1] = 2.5
    assert var[1] == pytest.approx(2.5)
    assert get_f32(1) == pytest.approx(2.5)


def test_f64_ptr_access(array_lib):
    array_lib.reset_arrays()
    var = get_var(array_lib, ctypes.POINTER(ctypes.c_double), "f64_ptr")

    get_f64 = array_lib.get_f64
    get_f64.restype = ctypes.c_double
    get_f64.argtypes = [ctypes.c_int]

    assert var[0] == pytest.approx(1.1)
    assert var[1] == pytest.approx(2.2)

    var[0] = 9.9
    assert var[0] == pytest.approx(9.9)
    assert get_f64(0) == pytest.approx(9.9)


def test_array_type_access(array_lib):
    array_lib.reset_arrays()
    # Testing array type access: int32_t i32_vals[5]
    # Using array type instead of pointer type
    var = get_var(array_lib, ctypes.c_int32 * 5, "i32_vals")

    get_i32 = array_lib.get_i32
    get_i32.restype = ctypes.c_int32
    get_i32.argtypes = [ctypes.c_int]

    assert var[0] == 10
    assert var[1] == 20

    var[2] = 35
    assert var[2] == 35
    assert get_i32(2) == 35
