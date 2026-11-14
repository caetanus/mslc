// EXPECT: error needs an instantiation, which is not lowered yet
// Refs #341: a template is parsed and accepted; a call to one that would need an
// instantiation is refused by name (it used to fail at the declaration).
#include <metal_stdlib>
using namespace metal;
template <typename T> T f(T x) { return x; }
kernel void k(device float* out [[buffer(0)]], uint i [[thread_position_in_grid]])
{ out[i] = f(1.0f); }
