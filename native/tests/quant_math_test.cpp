#include "../quant_math.hpp"
#include <cassert>
#include <cmath>
#include <vector>
int main(){
 auto call=mm::black_scholes(100,100,1,0.05,0.2,true);
 auto put=mm::black_scholes(100,100,1,0.05,0.2,false);
 assert(std::abs(call.price-10.450583572185565)<1e-9);
 assert(std::abs(put.price-5.573526022256971)<1e-9);
 assert(std::abs(call.price-put.price-(100-100*std::exp(-0.05)))<1e-9);
 auto stats=mm::trade_stats(std::vector<double>{0.1,-0.05,0.2});
 assert(stats.count==3 && stats.wins==2);
 assert(std::abs(stats.compounded-(1.1*0.95*1.2-1))<1e-12);
 return 0;
}
