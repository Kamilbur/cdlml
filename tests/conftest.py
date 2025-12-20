import os
import subprocess
from pathlib import Path
from collections import namedtuple
import cdlml
import ctypes

import pytest


def _project_root() -> Path:
    # Adjust if your conftest.py is not under tests/
    # Common layout: repo_root/tests/conftest.py -> parents[1] == repo_root
    return Path(__file__).resolve().parents[1]


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
    root = _project_root()
    test_source_root = root / "tests" / "malloc_test"

    env = os.environ.copy()
    jobs = min(os.cpu_count(), 2)

    subprocess.run(["make", f"-j{jobs}"], cwd=test_source_root, env=env, check=True)

    so_paths = sorted(test_source_root.rglob("*.so"))
    so_names = [p.name for p in so_paths]

    if not so_names:
        pytest.fail(f"`make` produced no .so files under: {root}")

    libmalloc = first_ok(so_paths, key=lambda p: p.name, value="libmalloc.so")
    libfoo = first_ok(so_paths, key=lambda p: p.name, value="libfoo.so")
    libbar = first_ok(so_paths, key=lambda p: p.name, value="libbar.so")

    preloads = [
        cdlml.Preload(name=b"libmalloc.so", path=libmalloc, alias="malloc"),
    ]
    foo = cdlml.PreloadedCDLL(libfoo, preloads=preloads)
    bar = cdlml.PreloadedCDLL(libbar)

    mapping_enabled = ctypes.c_int.in_dll(foo.malloc, "mapping_enabled")

    yield fbhandles(foo=foo, bar=bar, enabled=mapping_enabled)
