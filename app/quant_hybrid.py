"""Experimental hybrid calculation service; no trading execution."""
from app.quant import black_scholes as python_option, trade_stats as python_stats, wilson
try:
    from app import _quant_core as native
except ImportError:
    native=None

def engine_name():
    return "cpp-pybind11" if native is not None else "python"

def black_scholes(spot,strike,years,rate,volatility,kind):
    if kind not in ("call","put"):
        raise ValueError("kind must be call or put")
    if native is None:
        return python_option(spot,strike,years,rate,volatility,kind)
    data=dict(native.black_scholes(spot,strike,years,rate,volatility,kind=="call"))
    data.update(model="European Black-Scholes, no dividends",
                caveat="Not an observed option price or calibrated probability; ignores dividends, early exercise, market frictions and volatility smile.")
    return data

def trade_stats(returns):
    if not returns or native is None:
        return python_stats(returns)
    result=dict(native.trade_stats(returns))
    gross_profit=result.pop("gross_profit")
    gross_loss=result.pop("gross_loss")
    wins=result["wins"]
    count=result["count"]
    result.update(win_rate=wins/count,
                  win_rate_wilson_95=wilson(wins,count),
                  profit_factor=gross_profit/gross_loss if gross_loss else None,
                  caveat="Historical sample statistics, not forward probabilities. Returns must be decimal fractions net of costs.")
    return result


def black_scholes_price(spot,strike,years,rate,volatility,kind):
    return black_scholes(spot,strike,years,rate,volatility,kind)["theoretical_price"]
