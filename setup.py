from setuptools import setup, Extension, find_packages

ext_modules = [
    Extension(
        name="_cdlml._cdlml",
        sources=[
            "src/_cdlml/_cdlml.c",
            "csrc/cdlml.c",
        ],
        include_dirs=["csrc"],
        extra_compile_args=["-O3", "-Wall", "-Wextra", "-Werror"],
    )
]

setup(
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    ext_modules=ext_modules,
)
