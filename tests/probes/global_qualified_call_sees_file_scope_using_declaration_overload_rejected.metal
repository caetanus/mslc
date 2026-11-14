// EXPECT: error reference to "::f" is ambiguous
#include <metal_stdlib>
namespace A { int f(float v) { return 2; } }
int f(int v) { return 1; }
using A::f;
kernel void kern(device int *o [[buffer(0)]]) { o[0] = ::f(1.0f); }
