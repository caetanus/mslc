// EXPECT: valid
// DISASM: Pow
#include <metal_stdlib>
using namespace metal;
kernel void math_powr(device float4* out [[buffer(0)]]) {
    float4 x = out[0];
    x = powr(x, 2.0f);
    x = metal::fast::powr(x, 0.5f);
    x = fast::powr(x, 2.0f);
    x = metal::precise::powr(x, 0.5f);
    out[0] = precise::powr(x, 2.0f);
}
