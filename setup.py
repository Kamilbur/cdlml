import os
import shutil
import subprocess
import sys
from pathlib import Path

from setuptools import Extension, find_packages, setup
from setuptools.command.build_ext import build_ext as _build_ext

_DEBUG = os.environ.get("CDLML_DEBUG", "").strip() not in ("", "0")

_EXT_COMPILE_ARGS = (
    ["-ggdb", "-O0", "-Wall", "-Wextra"] if _DEBUG else ["-O3", "-Wall", "-Wextra", "-Werror"]
)

ext_modules = [
    Extension(
        name="_cdlml._cdlml",
        sources=[
            "src/_cdlml/_cdlml.c",
            "csrc/cdlml.c",
        ],
        include_dirs=["csrc"],
        extra_compile_args=_EXT_COMPILE_ARGS,
    )
]

SERVER_SRC = Path("csrc/cdlml_server.c")
SERVER_OUT = Path("src/cdlml/cdlml_server.exe")


def _get_ffi_flags():
    if shutil.which("pkg-config"):
        try:
            cflags = subprocess.check_output(
                ["pkg-config", "--cflags", "libffi"], stderr=subprocess.DEVNULL
            ).decode().split()
            libs = subprocess.check_output(
                ["pkg-config", "--libs", "libffi"], stderr=subprocess.DEVNULL
            ).decode().split()
            return cflags, libs
        except subprocess.CalledProcessError:
            pass
    return [], ["-lffi"]


def build_server() -> None:
    if not SERVER_SRC.exists():
        print(f"WARNING: {SERVER_SRC} not found, skipping cdlml_server build", file=sys.stderr)
        return
    ffi_cflags, ffi_libs = _get_ffi_flags()
    flags = ["-ggdb", "-O0"] if _DEBUG else ["-O2"]
    cmd = [
        "gcc", *flags, *ffi_cflags, "-Wall", "-Wextra",
        str(SERVER_SRC), "-o", str(SERVER_OUT), "-ldl", *ffi_libs,
    ]
    print(f"building cdlml_server: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


class build_ext(_build_ext):
    def build_extension(self, ext) -> None:
        try:
            super().build_extension(ext)
        except Exception as exc:
            print(
                f"WARNING: skipping {ext.name}: {exc}\n"
                "WARNING: GLIBCPreloadedCDLL unavailable; FallbackPreloadedCDLL will be used",
                file=sys.stderr,
            )

    def run(self) -> None:
        build_server()
        super().run()


setup(
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    package_data={"cdlml": ["cdlml_server.exe"]},
    include_package_data=True,
)
