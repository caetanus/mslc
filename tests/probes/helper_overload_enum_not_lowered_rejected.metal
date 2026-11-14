// EXPECT: error an enum or a texture or sampler; that is not lowered yet
// Apple calls f(E) for an enumerator and f(int) for an int. Picking by enum is a later
// slice of #266; the two are different signatures now, not one function.
#include <metal_stdlib>
using namespace metal;
enum E { ea, eb };
float f(E x) { return 1.0f; }
float f(int x) { return 2.0f; }
kernel void k(device float* out [[buffer(0)]], uint i [[thread_position_in_grid]])
{ out[i] = f(ea); }
