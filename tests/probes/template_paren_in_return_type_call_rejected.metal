// EXPECT: error a dependent type written with "typename" is not lowered
// Refs #341: the name is the one before the parameter list, not the one before the
// "(" inside the return type's angle brackets.
#include <metal_stdlib>
using namespace metal;
template <typename T> typename enable_if<(sizeof(T) > 2), T>::type g(T x) { return x; }
kernel void k(device float* out [[buffer(0)]], uint i [[thread_position_in_grid]])
{ out[i] = g(1.0f); }
