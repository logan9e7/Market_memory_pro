#pragma once
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <vector>

namespace mm {
inline double normal_cdf(double x) {
    if (!std::isfinite(x)) throw std::invalid_argument("x must be finite");
    return 0.5 * std::erfc(-x / std::sqrt(2.0));
}
struct OptionResult { double price, delta, gamma, vega; };
inline OptionResult black_scholes(double s,double k,double t,double r,double vol,bool call) {
    if (!(std::isfinite(s)&&std::isfinite(k)&&std::isfinite(t)&&std::isfinite(r)&&std::isfinite(vol))
        || s<=0 || k<=0 || t<=0 || vol<=0)
        throw std::invalid_argument("Invalid Black-Scholes parameters");
    const double rt=std::sqrt(t), d1=(std::log(s/k)+(r+0.5*vol*vol)*t)/(vol*rt);
    const double d2=d1-vol*rt, disc=k*std::exp(-r*t);
    const double pdf=std::exp(-0.5*d1*d1)/std::sqrt(2*3.14159265358979323846);
    const double price=call ? s*normal_cdf(d1)-disc*normal_cdf(d2)
                            : disc*normal_cdf(-d2)-s*normal_cdf(-d1);
    return {price,normal_cdf(d1)-(call?0.0:1.0),pdf/(s*vol*rt),s*pdf*rt};
}
struct TradeResult {
    int count,wins;
    double mean,stddev,gross_profit,gross_loss,compounded,drawdown;
};
inline TradeResult trade_stats(const std::vector<double>& returns) {
    if (returns.empty()) throw std::invalid_argument("Returns cannot be empty");
    double sum=0.0, mean=0.0, m2=0.0, gp=0.0, gl=0.0;
    double equity=1.0,peak=1.0,dd=0.0;
    int wins=0,n=0;
    for(double x:returns) {
        if(!std::isfinite(x)||x<=-1.0||x>=1000.0)
            throw std::invalid_argument("Invalid decimal return");
        ++n;
        const double delta=x-mean;
        mean+=delta/n;
        m2+=delta*(x-mean);
        sum+=x;
        if(x>0){++wins;gp+=x;} else if(x<0){gl-=x;}
        equity*=1+x;
        peak=std::max(peak,equity);
        dd=std::max(dd,1-equity/peak);
    }
    return {n,wins,sum/n,n>1?std::sqrt(m2/(n-1)):0.0,gp,gl,equity-1,dd};
}
}
