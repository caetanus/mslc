// EXPECT: error needs an instantiation, which is not lowered yet
// Refs #341: "f<float>(x)" would otherwise read as a chain of comparisons; it parses now, and the call is refused
// like any other call to a template until one is instantiated.
#include <metal_stdlib>
using namespace metal;
template <typename T> T f(T x) { return x; }
kernel void k(device float* out [[buffer(0)]], uint i [[thread_position_in_grid]])
{ out[i] = f<float>(1.0f); }
