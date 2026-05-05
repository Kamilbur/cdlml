import ctypes
from contextlib import contextmanager
import pytest


sizeof_int = ctypes.sizeof(ctypes.c_int)


@contextmanager
def enabled(enabled_flag):
    original = enabled_flag.value
    try:
        enabled_flag.value = 1
        yield
    finally:
        enabled_flag.value = original


def _bared(bar, n, ns, enabled_flag):
    return bar.bar(n)


def _fooed(foo, n, ns, enabled_flag):
    if enabled_flag.value and n > 1:
        ns.append(n + 1)
    return foo.foo(n)


def case_01(fooed, bared, enabled_flag):
    bared(1)

    with enabled(enabled_flag):
        bared(3)
        for n in range(3):
            fooed(n)
        bared(3)

    fooed(4)
    fooed(5)


def case_02(fooed, bared, enabled_flag):
    fooed(0)
    bared(10)

    with enabled(enabled_flag):
        for n in range(1, 5):
            fooed(n)
        bared(11)

    bared(10)
    fooed(15)


def case_03(fooed, bared, enabled_flag):
    bared(-1)

    with enabled(enabled_flag):
        bared(0)
        fooed(1)
        fooed(2)
        bared(0)

    bared(1)
    fooed(3)


def case_04(fooed, bared, enabled_flag):
    fooed(1)
    fooed(2)

    with enabled(enabled_flag):
        for n in range(3):
            bared(n)
        for n in range(3, 6):
            fooed(n)

    bared(8)


def case_05(fooed, bared, enabled_flag):
    bared(5)

    with enabled(enabled_flag):
        fooed(0)
        for n in range(2):
            fooed(10 + n)
        bared(6)

    fooed(13)
    bared(7)
    fooed(12)


def case_06(fooed, bared, enabled_flag):
    for n in range(2):
        bared(n)

    with enabled(enabled_flag):
        for n in range(2, 5):
            bared(n)
            fooed(n * 2)

    fooed(9)


def case_07(fooed, bared, enabled_flag):
    fooed(0)

    with enabled(enabled_flag):
        bared(1)
        for n in range(4):
            fooed(n)
            if n % 2 == 0:
                bared(10 + n)
        bared(2)

    fooed(5)


def case_08(fooed, bared, enabled_flag):
    bared(1)
    fooed(2)

    with enabled(enabled_flag):
        fooed(3)
        with enabled(enabled_flag):
            bared(4)
            for n in range(2):
                fooed(5 + n)
        bared(6)

    bared(7)
    fooed(8)


def case_09(fooed, bared, enabled_flag):
    with enabled(enabled_flag):
        bared(0)
        for n in range(3):
            fooed(n)
        for n in range(2, -1, -1):
            bared(n)

    fooed(42)


def case_10(fooed, bared, enabled_flag):
    bared(1)

    with enabled(enabled_flag):
        for n in range(1, 4):
            fooed(n)
        bared(2)

    with enabled(enabled_flag):
        bared(3)
        fooed(4)

    fooed(5)
    bared(6)


def case_11(fooed, bared, enabled_flag):
    for n in range(3):
        fooed(n)

    with enabled(enabled_flag):
        bared(10)
        for n in range(3):
            fooed(8 + n)
        bared(11)

    for n in range(2):
        bared(2 + n)


def case_12(fooed, bared, enabled_flag):
    bared(0)

    with enabled(enabled_flag):
        for n in range(5):
            if n == 2:
                bared(11)
            fooed(n)
        bared(1)

    fooed(5)


def case_13(fooed, bared, enabled_flag):
    fooed(-10)

    with enabled(enabled_flag):
        for n in range(3):
            fooed(-(n + 1))
        bared(-1)

    bared(0)
    fooed(0)


def case_14(fooed, bared, enabled_flag):
    bared(1)

    with enabled(enabled_flag):
        # interleaving calls
        for n in range(3):
            fooed(n)
            bared(n + 2)
        fooed(3)

    bared(1)
    fooed(4)


def case_15(fooed, bared, enabled_flag):
    # minimal outside, more inside
    fooed(1)

    with enabled(enabled_flag):
        bared(1)
        bared(2)
        for n in range(6, 9):
            fooed(n)
        bared(3)

    fooed(2)


test_cases = [
    case_01,
    case_02,
    case_03,
    case_04,
    case_05,
    case_06,
    case_07,
    case_08,
    case_09,
    case_10,
    case_11,
    case_12,
    case_13,
    case_14,
    case_15,
]


@pytest.mark.parametrize("test_case", test_cases, ids=[c.__name__ for c in test_cases])
def test_universal(test_case, foobar_handles, capfd):
    foo, bar, enabled_flag = foobar_handles
    enabled_flag.value = 0

    ns = []

    def fooed(n):
        return _fooed(foo, n, ns, enabled_flag)

    def bared(n):
        return _bared(bar, n, ns, enabled_flag)

    test_case(fooed, bared, enabled_flag)

    out, err = capfd.readouterr()
    assert err == "".join(["[interpose] malloc(size={})\n".format(n * sizeof_int) for n in ns])
