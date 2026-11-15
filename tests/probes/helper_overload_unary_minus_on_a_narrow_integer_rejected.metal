// EXPECT: error narrower than int
// -a on a uchar is an int in Apple (f(int)); mslc keeps the uchar, so the choice is refused.
#include <metal_stdlib>
using namespace metal;
float f(int x) { return 1.0f; }
float f(uchar x) { return 2.0f; }
kernel void k(device float* out [[buffer(0)]]) { uchar a = 1; out[0] = f(-a); }
