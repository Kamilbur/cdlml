import subprocess
from pathlib import Path

import cdlml
import pytest


def _here() -> Path:
    return Path(__file__).resolve().parent


@pytest.fixture(scope="session")
def types_lib():
    src_dir = _here()
    subprocess.run(["make", "-j2"], cwd=src_dir, check=True)
    return cdlml.PreloadedCDLL(src_dir / "libtypes.so")
