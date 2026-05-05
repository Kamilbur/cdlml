import ctypes
import math

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def call(lib, fn_name, argtypes, restype, args):
    fn = getattr(lib, fn_name)
    fn.argtypes = argtypes
    fn.restype = restype
    return fn(*args)


# ---------------------------------------------------------------------------
# Test cases: (fn_name, argtypes, restype, args, expected)
# ---------------------------------------------------------------------------

void_cases = [
    pytest.param("noop", [], None, (), None, id="noop"),
]

i32_cases = [
    pytest.param("add_i32",    [ctypes.c_int32]*2, ctypes.c_int32, (3, 4),            7,          id="add_positive"),
    pytest.param("add_i32",    [ctypes.c_int32]*2, ctypes.c_int32, (-5, 3),           -2,         id="add_negative"),
    pytest.param("add_i32",    [ctypes.c_int32]*2, ctypes.c_int32, (0, 0),            0,          id="add_zero"),
    pytest.param("negate_i32", [ctypes.c_int32],   ctypes.c_int32, (42,),             -42,        id="negate_positive"),
    pytest.param("negate_i32", [ctypes.c_int32],   ctypes.c_int32, (-1,),             1,          id="negate_neg1"),
    pytest.param("identity_i32",[ctypes.c_int32],  ctypes.c_int32, (2**31 - 1,),      2**31 - 1,  id="max_i32"),
    pytest.param("identity_i32",[ctypes.c_int32],  ctypes.c_int32, (-(2**31),),       -(2**31),   id="min_i32"),
    pytest.param("sum3_i32",   [ctypes.c_int32]*3, ctypes.c_int32, (10, 20, 30),      60,         id="sum3"),
]

i64_cases = [
    pytest.param("add_i64",    [ctypes.c_int64]*2, ctypes.c_int64, (10**15, 10**15),  2 * 10**15, id="add_large"),
    pytest.param("add_i64",    [ctypes.c_int64]*2, ctypes.c_int64, (-10**15, 10**15), 0,          id="add_cancel"),
    pytest.param("identity_i64",[ctypes.c_int64],  ctypes.c_int64, (2**63 - 1,),      2**63 - 1,  id="max_i64"),
    pytest.param("identity_i64",[ctypes.c_int64],  ctypes.c_int64, (-(2**63),),       -(2**63),   id="min_i64"),
]

u32_cases = [
    pytest.param("add_u32", [ctypes.c_uint32]*2, ctypes.c_uint32, (2**32 - 1, 1),  0,          id="overflow_wrap"),
    pytest.param("add_u32", [ctypes.c_uint32]*2, ctypes.c_uint32, (100, 200),       300,        id="add_basic"),
]

u64_cases = [
    pytest.param("add_u64", [ctypes.c_uint64]*2, ctypes.c_uint64, (2**63, 2**63),   0,          id="overflow_wrap"),
    pytest.param("add_u64", [ctypes.c_uint64]*2, ctypes.c_uint64, (2**64 - 1, 0),   2**64 - 1,  id="max_u64"),
]

f32_cases = [
    pytest.param("add_f32",    [ctypes.c_float]*2, ctypes.c_float, (1.0, 2.0),      pytest.approx(3.0,   rel=1e-5), id="add_basic"),
    pytest.param("add_f32",    [ctypes.c_float]*2, ctypes.c_float, (-1.5, 2.5),     pytest.approx(1.0,   rel=1e-5), id="add_negative"),
    pytest.param("add_f32",    [ctypes.c_float]*2, ctypes.c_float, (0.0, 0.0),      pytest.approx(0.0,   abs=1e-10), id="add_zeros"),
    pytest.param("scale_f32",  [ctypes.c_float]*2, ctypes.c_float, (math.pi, 2.0),  pytest.approx(2*math.pi, rel=1e-5), id="scale_pi"),
    pytest.param("scale_f32",  [ctypes.c_float]*2, ctypes.c_float, (10.0, 0.1),     pytest.approx(1.0,   rel=1e-5), id="scale_tenth"),
    pytest.param("identity_f32",[ctypes.c_float],  ctypes.c_float, (3.14,),         pytest.approx(3.14,  rel=1e-5), id="identity"),
    pytest.param("f64_to_f32", [ctypes.c_double],  ctypes.c_float, (1.0,),          pytest.approx(1.0,   rel=1e-5), id="cast_exact"),
    pytest.param("f64_to_f32", [ctypes.c_double],  ctypes.c_float, (3.14,),         pytest.approx(3.14,  rel=1e-5), id="cast_pi"),
]

f64_cases = [
    pytest.param("add_f64",    [ctypes.c_double]*2, ctypes.c_double, (1.0, 2.0),          pytest.approx(3.0),           id="add_basic"),
    pytest.param("add_f64",    [ctypes.c_double]*2, ctypes.c_double, (1e100, -1e100),      pytest.approx(0.0, abs=1e85), id="add_cancel"),
    pytest.param("scale_f64",  [ctypes.c_double]*2, ctypes.c_double, (math.pi, 2.0),      pytest.approx(2*math.pi),     id="scale_pi"),
    pytest.param("identity_f64",[ctypes.c_double],  ctypes.c_double, (math.e,),            pytest.approx(math.e),        id="identity_e"),
    pytest.param("identity_f64",[ctypes.c_double],  ctypes.c_double, (-0.0,),              pytest.approx(0.0, abs=1e-30), id="neg_zero"),
    pytest.param("sum3_f64",   [ctypes.c_double]*3, ctypes.c_double, (1.1, 2.2, 3.3),     pytest.approx(6.6),           id="sum3"),
    pytest.param("i32_to_f64", [ctypes.c_int32],    ctypes.c_double, (-1000000,),         pytest.approx(-1e6),          id="int_to_double"),
]

cstr_cases = [
    pytest.param("str_len", [ctypes.c_char_p], ctypes.c_uint32, (b"hello",),   5,  id="hello"),
    pytest.param("str_len", [ctypes.c_char_p], ctypes.c_uint32, (b"",),        0,  id="empty"),
    pytest.param("str_len", [ctypes.c_char_p], ctypes.c_uint32, (b"ab cd ef",), 8, id="with_spaces"),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fn_name,argtypes,restype,args,expected", void_cases)
def test_void(types_lib, fn_name, argtypes, restype, args, expected):
    result = call(types_lib, fn_name, argtypes, restype, args)
    assert result is expected


@pytest.mark.parametrize("fn_name,argtypes,restype,args,expected", i32_cases)
def test_i32(types_lib, fn_name, argtypes, restype, args, expected):
    assert call(types_lib, fn_name, argtypes, restype, args) == expected


@pytest.mark.parametrize("fn_name,argtypes,restype,args,expected", i64_cases)
def test_i64(types_lib, fn_name, argtypes, restype, args, expected):
    assert call(types_lib, fn_name, argtypes, restype, args) == expected


@pytest.mark.parametrize("fn_name,argtypes,restype,args,expected", u32_cases)
def test_u32(types_lib, fn_name, argtypes, restype, args, expected):
    assert call(types_lib, fn_name, argtypes, restype, args) == expected


@pytest.mark.parametrize("fn_name,argtypes,restype,args,expected", u64_cases)
def test_u64(types_lib, fn_name, argtypes, restype, args, expected):
    assert call(types_lib, fn_name, argtypes, restype, args) == expected


@pytest.mark.parametrize("fn_name,argtypes,restype,args,expected", f32_cases)
def test_f32(types_lib, fn_name, argtypes, restype, args, expected):
    assert call(types_lib, fn_name, argtypes, restype, args) == expected


@pytest.mark.parametrize("fn_name,argtypes,restype,args,expected", f64_cases)
def test_f64(types_lib, fn_name, argtypes, restype, args, expected):
    assert call(types_lib, fn_name, argtypes, restype, args) == expected


@pytest.mark.parametrize("fn_name,argtypes,restype,args,expected", cstr_cases)
def test_cstr_arg(types_lib, fn_name, argtypes, restype, args, expected):
    assert call(types_lib, fn_name, argtypes, restype, args) == expected
