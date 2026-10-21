"""Opt-in native quantitative pricing with a safe Python fallback.

Native builds are optional; importing this module does not require a compiler.
No financial order execution is performed here.
"""
from app.quant import black_scholes as python_black_scholes

try:
    from app import _quant_core as native
except ImportError:
    native = None


def engine_name():
    return "cpp-pybind11" if native is not None else "python"


def black_scholes_price(spot, strike, years, rate, volatility, kind):
    if kind not in ("call", "put"):
        raise ValueError("kind must be call or put")
    if native is None:
        return python_black_scholes(
            spot, strike, years, rate, volatility, kind
        )["theoretical_price"]
    return native.black_scholes_price(
        spot, strike, years, rate, volatility, kind == "call"
    )
