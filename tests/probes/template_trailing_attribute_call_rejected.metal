// EXPECT: error needs an instantiation, which is not lowered yet
#include <metal_stdlib>
using namespace metal;
template <typename T> T conv(T c) __attribute__((always_inline)) { return c * 2.0f; }
float conv(float3 c) { return c.x; }
kernel void k(device float* out [[buffer(0)]], uint i [[thread_position_in_grid]])
{ out[i] = conv(1.0f); }
