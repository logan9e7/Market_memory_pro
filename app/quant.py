"""Deterministic, educational statistics engine. No LLM calculations or forecasts."""
from math import erf, exp, log, sqrt
from statistics import mean, stdev

def normal_cdf(x):
    return 0.5 * (1 + erf(x / sqrt(2)))

def wilson(wins, trials, z=1.96):
    if not trials:
        return {"estimate": None, "lower": None, "upper": None}
    p = wins / trials
    d = 1 + z*z/trials
    center = (p + z*z/(2*trials))/d
    half = z*sqrt((p*(1-p)+z*z/(4*trials))/trials)/d
    return {"estimate": p, "lower": max(0,center-half), "upper": min(1,center+half)}

def trade_stats(returns):
    if not returns:
        return {"count":0,"warning":"No trades provided"}
    wins = sum(x>0 for x in returns)
    gross_profit=sum(x for x in returns if x>0)
    gross_loss=-sum(x for x in returns if x<0)
    equity=1.0
    peak=1.0
    max_drawdown=0.0
    for r in returns:
        equity *= (1+r)
        peak=max(peak,equity)
        max_drawdown=max(max_drawdown,1-equity/peak)
    return {"count":len(returns),"wins":wins,"win_rate":wins/len(returns),
        "win_rate_wilson_95":wilson(wins,len(returns)),
        "mean_return":mean(returns),"sample_std":stdev(returns) if len(returns)>1 else None,
        "profit_factor":gross_profit/gross_loss if gross_loss else None,
        "compounded_return":equity-1,"max_drawdown":max_drawdown,
        "caveat":"Historical sample statistics, not forward probabilities. Returns must be decimal fractions net of costs."}

def black_scholes(spot,strike,years,rate,volatility,kind):
    if min(spot,strike,years,volatility)<=0:
        raise ValueError("Spot, strike, time and volatility must be positive")
    d1=(log(spot/strike)+(rate+0.5*volatility**2)*years)/(volatility*sqrt(years))
    d2=d1-volatility*sqrt(years)
    if kind=="call":
        premium=spot*normal_cdf(d1)-strike*exp(-rate*years)*normal_cdf(d2)
        delta=normal_cdf(d1)
    else:
        premium=strike*exp(-rate*years)*normal_cdf(-d2)-spot*normal_cdf(-d1)
        delta=normal_cdf(d1)-1
    gamma=exp(-d1*d1/2)/sqrt(2*3.141592653589793)/(spot*volatility*sqrt(years))
    vega=spot*exp(-d1*d1/2)/sqrt(2*3.141592653589793)*sqrt(years)
    return {"theoretical_price":premium,"delta":delta,"gamma":gamma,"vega_per_1_vol_unit":vega,
        "model":"European Black-Scholes, no dividends",
        "caveat":"Not an observed option price or calibrated probability; ignores dividends, early exercise, market frictions and volatility smile."}
