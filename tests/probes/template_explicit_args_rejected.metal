// EXPECT: error explicit template arguments are not lowered yet
// Refs #341: "f<float>(x)" would otherwise read as a chain of comparisons.
#include <metal_stdlib>
using namespace metal;
template <typename T> T f(T x) { return x; }
kernel void k(device float* out [[buffer(0)]], uint i [[thread_position_in_grid]])
{ out[i] = f<float>(1.0f); }
