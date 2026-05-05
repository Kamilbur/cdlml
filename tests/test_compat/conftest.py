import subprocess
from pathlib import Path
import cdlml
import pytest


def _here() -> Path:
    return Path(__file__).resolve().parent


@pytest.fixture(scope="session")
def compat_lib():
    src_dir = _here()
    subprocess.run(["make", "-j2"], cwd=src_dir, check=True)
    # Force FallbackPreloadedCDLL by setting CDLML_DEBUG=1 or just assuming if no dlmopen
    # Since we want to test the fallback mechanism specifically, we can use FallbackPreloadedCDLL directly
    return cdlml.FallbackPreloadedCDLL(src_dir / "libcompat.so")
