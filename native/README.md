# C++17/pybind11 numerical engine

The C++ module is optional and performs **only deterministic financial mathematics**.
FastAPI, database ownership, authorization and AI stay in Python. No live order execution.

## Build

```bash
python -m pip install -r requirements.lock pybind11
cmake -S native -B native/build -Dpybind11_DIR="$(python -m pybind11 --cmakedir)"
cmake --build native/build --config Release
cp native/build/_quant_core*.so app/
python -m unittest discover -s tests -p 'test_quant_hybrid.py' -v
```

Without a compiled extension the same API uses the existing Python formulas.
CI compiles the native module, runs standalone C++ checks and validates Python parity.
Native compilation is not currently part of the Render production build process.
