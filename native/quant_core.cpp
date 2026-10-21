// Optional numerical core for Market Memory Pro.
// Build separately; production Python remains the fallback.
#include <cmath>
#include <stdexcept>
#include <pybind11/pybind11.h>
namespace py = pybind11;

double normal_cdf(double x) {
    if (!std::isfinite(x)) throw std::invalid_argument("x must be finite");
    return 0.5 * std::erfc(-x / std::sqrt(2.0));
}
double black_scholes_price(double spot, double strike, double years,
                           double rate, double volatility, bool is_call) {
    if (!(std::isfinite(spot) && std::isfinite(strike) && std::isfinite(years) &&
          std::isfinite(rate) && std::isfinite(volatility)) ||
        spot <= 0 || strike <= 0 || years <= 0 || volatility <= 0)
        throw std::invalid_argument("Invalid Black-Scholes parameters");
    const double sqrt_t = std::sqrt(years);
    const double d1 = (std::log(spot / strike) +
                       (rate + 0.5 * volatility * volatility) * years) /
                      (volatility * sqrt_t);
    const double d2 = d1 - volatility * sqrt_t;
    const double discounted_strike = strike * std::exp(-rate * years);
    return is_call
        ? spot * normal_cdf(d1) - discounted_strike * normal_cdf(d2)
        : discounted_strike * normal_cdf(-d2) - spot * normal_cdf(-d1);
}
PYBIND11_MODULE(_quant_core, m) {
    m.doc() = "Optional deterministic C++ financial calculations";
    m.def("normal_cdf", &normal_cdf);
    m.def("black_scholes_price", &black_scholes_price,
          py::arg("spot"), py::arg("strike"), py::arg("years"),
          py::arg("rate"), py::arg("volatility"), py::arg("is_call"));
}
