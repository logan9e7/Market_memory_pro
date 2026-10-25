"""Build C++17 Python bindings as part of the normal dependency installation.

Render uses pip install -r requirements.lock. That file installs this project,
so every deployment compiles app._quant_core instead of silently falling back.
"""
from setuptools import setup
from pybind11.setup_helpers import Pybind11Extension, build_ext

setup(
    packages=["app"],
    ext_modules=[
        Pybind11Extension(
            "app._quant_core",
            ["native/quant_core.cpp"],
            include_dirs=["native"],
            cxx_std=17,
        )
    ],
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
)
