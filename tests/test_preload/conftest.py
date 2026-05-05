import os
import subprocess
from pathlib import Path
from collections import namedtuple
import cdlml
import ctypes

import pytest


def _here() -> Path:
    return Path(__file__).resolve().parent


def first_ok(items, key, value):
    for item in items:
        if key(item) == value:
            return item

    raise ValueError("No items fulfilling criterion found.")


fbhandles = namedtuple("fbhandles", ["foo", "bar", "enabled"])


@pytest.fixture(scope="session")
def foobar_handles():
    """
    Builds the project via `make` and yields a list of produced .so filenames.

    Returns:
        malloc_so_files: A namedtuple with paths to the built shared libraries.
    """
    here = _here()

    env = os.environ.copy()
    jobs = min(os.cpu_count(), 2)

    subprocess.run(["make", f"-j{jobs}"], cwd=here, env=env, check=True)

    so_paths = sorted(here.rglob("*.so"))
    so_names = [p.name for p in so_paths]

    if not so_names:
        pytest.fail(f"`make` produced no .so files under: {here}")

    libmalloc = first_ok(so_paths, key=lambda p: p.name, value="libmalloc.so")
    libfoo = first_ok(so_paths, key=lambda p: p.name, value="libfoo.so")
    libbar = first_ok(so_paths, key=lambda p: p.name, value="libbar.so")

    preloads = [
        cdlml.Preload(name=b"libmalloc.so", path=libmalloc, alias="malloc"),
    ]
    foo = cdlml.PreloadedCDLL(libfoo, preloads=preloads)
    bar = cdlml.PreloadedCDLL(libbar)

    mapping_enabled = cdlml.get_var(foo.malloc, ctypes.c_int, "mapping_enabled")

    yield fbhandles(foo=foo, bar=bar, enabled=mapping_enabled)
