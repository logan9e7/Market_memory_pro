#include "quant_math.hpp"
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
namespace py=pybind11;
PYBIND11_MODULE(_quant_core_v2,m) {
 m.doc()="Native quantitative calculations";
 m.def("normal_cdf",&mm::normal_cdf);
 m.def("black_scholes",[](double s,double k,double t,double r,double v,bool call){
   auto x=mm::black_scholes(s,k,t,r,v,call);
   py::dict d;
   d["theoretical_price"]=x.price;
   d["delta"]=x.delta;
   d["gamma"]=x.gamma;
   d["vega_per_1_vol_unit"]=x.vega;
   return d;
 });
 m.def("trade_stats",[](const std::vector<double>& returns){
   auto x=mm::trade_stats(returns);
   py::dict d;
   d["count"]=x.count;
   d["wins"]=x.wins;
   d["mean_return"]=x.mean;
   if(x.count>1) d["sample_std"]=x.stddev;
   else d["sample_std"]=py::none();
   d["gross_profit"]=x.gross_profit;
   d["gross_loss"]=x.gross_loss;
   d["compounded_return"]=x.compounded;
   d["max_drawdown"]=x.drawdown;
   return d;
 });
}
