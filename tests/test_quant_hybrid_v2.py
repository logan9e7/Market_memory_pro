"""Verify hybrid engine numerical parity and API shape."""
import math
import unittest
from app.quant import black_scholes as reference_option, trade_stats as reference_stats
from app.quant_hybrid_v2 import black_scholes, trade_stats, engine_name

class HybridV2Tests(unittest.TestCase):
    def test_options(self):
        for args in [(100,100,1,0.05,0.2),(200,180,0.25,0.03,0.4),(50,70,2,-0.01,0.15)]:
            for kind in ("call","put"):
                actual=black_scholes(*args,kind)
                expected=reference_option(*args,kind)
                for key in ("theoretical_price","delta","gamma","vega_per_1_vol_unit"):
                    self.assertTrue(math.isclose(actual[key],expected[key],rel_tol=1e-10,abs_tol=1e-10),key)
    def test_trades(self):
        for returns in ([0.1,-0.05,0.2],[0.0],[0.1,0.2,0.3],[-0.1,-0.2,-0.3]):
            actual=trade_stats(returns)
            expected=reference_stats(returns)
            for key in ("count","wins","win_rate","mean_return","sample_std","profit_factor","compounded_return","max_drawdown"):
                if expected[key] is None:
                    self.assertIsNone(actual[key])
                else:
                    self.assertTrue(math.isclose(actual[key],expected[key],rel_tol=1e-10,abs_tol=1e-10),key)
    def test_engine(self):
        self.assertIn(engine_name(),("python","cpp"))

if __name__=="__main__":
    unittest.main()
