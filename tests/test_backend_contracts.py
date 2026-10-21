"""Guard API compatibility and numerical parity when decoupling backend routers."""
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from app.main import create_app
from app.quant import black_scholes as python_option, trade_stats as python_trades
from app.quant_hybrid import black_scholes, trade_stats, engine_name

class BackendContracts(unittest.TestCase):
    def test_quantitative_parity(self):
        self.assertIn(engine_name(), ("python", "cpp-pybind11"))
        for args in ((100,100,1,0.05,0.2), (200,180,0.25,0.03,0.4),
                     (50,70,2,-0.01,0.15)):
            for kind in ("call", "put"):
                candidate=black_scholes(*args,kind)
                reference=python_option(*args,kind)
                for key in ("theoretical_price","delta","gamma","vega_per_1_vol_unit"):
                    self.assertAlmostEqual(candidate[key],reference[key],delta=1e-10)
        for returns in ([0.1,-0.05,0.2], [0.0], [-0.1,-0.2,-0.3], [0.1,0.2,0.3]):
            candidate=trade_stats(returns)
            reference=python_trades(returns)
            for key in ("win_rate","mean_return","sample_std","profit_factor",
                        "compounded_return","max_drawdown"):
                if reference[key] is None:
                    self.assertIsNone(candidate[key])
                else:
                    self.assertAlmostEqual(candidate[key],reference[key],delta=1e-10)

    def test_public_routes_and_auth(self):
        with tempfile.TemporaryDirectory() as folder:
            application=create_app(db_path=str(Path(folder)/"test.sqlite"))
            paths={route.path for route in application.routes}
            for path in ("/api/quant/option","/api/quant/trades","/api/markets/providers",
                         "/api/intelligence/analyze","/api/intelligence/history",
                         "/api/intelligence/evolution","/api/account/retention"):
                self.assertIn(path,paths)
            with TestClient(application) as client:
                self.assertEqual(client.get("/api/markets/providers").status_code,401)
                response=client.post("/api/register",
                    json={"username":"test-user","password":"Strong-Password123!"})
                self.assertEqual(response.status_code,201,response.text)
                price=client.post("/api/quant/option",
                    json={"spot":100,"strike":100,"years":1,"rate":0.05,
                          "volatility":0.2,"kind":"call"})
                self.assertEqual(price.status_code,200,price.text)
                self.assertIn("theoretical_price",price.json())
                self.assertEqual(client.get("/api/markets/providers").status_code,200)

if __name__=="__main__":
    unittest.main()
