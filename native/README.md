# Optional C++ numerical module

This is the first experimental Python/C++ hybrid slice. It is **not wired into
production API endpoints** and does not modify data or place trades.

Install a C++17 compiler, CMake and pybind11 in a development environment:

```sh
python -m pip install pybind11
cmake -S native -B native/build -Dpybind11_DIR="$(python -m pybind11 --cmakedir)"
cmake --build native/build --config Release
```

Copy the built `_quant_core` extension to `app/` for optional import, or
configure the build output there. Without it, `app.quant_hybrid` falls back
to the existing Python pricing formula.

Run parity tests:

```sh
python -m unittest tests.test_quant_hybrid
```

Before any production integration, benchmark native versus Python/NumPy on
representative batch workloads, test extreme parameters, and confirm numerical
agreement. Calling C++ once per option from Python may be slower than vectorized
NumPy for large batches due to boundary overhead.
