// EXPECT: error choosing by implicit conversion is not lowered yet
// Apple calls f(int) here (a bool promotes to int, and converts to float). Ranking the
// conversions is a later slice of #266: until then the call is refused, never guessed.
#include <metal_stdlib>
using namespace metal;
float f(int x) { return float(x); }
float f(float x) { return x; }
kernel void k(device float* out [[buffer(0)]], uint i [[thread_position_in_grid]])
{ out[i] = f(true); }
