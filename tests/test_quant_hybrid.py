"""Parity tests: native and Python Black-Scholes should agree."""
import math
import unittest
from app.quant import black_scholes
from app.quant_hybrid import black_scholes_price, engine_name


class HybridQuantTests(unittest.TestCase):
    def test_engine_label(self):
        self.assertIn(engine_name(), ("python", "cpp-pybind11"))

    def test_parity(self):
        for spot, strike, years, rate, vol in (
            (100, 100, 1, 0.05, 0.2),
            (200, 180, 0.25, 0.03, 0.4),
            (50, 70, 2, -0.01, 0.15),
        ):
            for kind in ("call", "put"):
                expected = black_scholes(
                    spot, strike, years, rate, vol, kind
                )["theoretical_price"]
                actual = black_scholes_price(
                    spot, strike, years, rate, vol, kind
                )
                self.assertTrue(math.isclose(
                    expected, actual, rel_tol=1e-10, abs_tol=1e-10
                ))

    def test_invalid_kind(self):
        with self.assertRaises(ValueError):
            black_scholes_price(100, 100, 1, 0.05, 0.2, "invalid")


if __name__ == "__main__":
    unittest.main()
