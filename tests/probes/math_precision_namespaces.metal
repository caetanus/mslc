// EXPECT: valid
// DISASM: NMax
// DISASM: NMin
// DISASM: NClamp
// DISASM: Normalize
// DISASM: Sin
#include <metal_stdlib>
using namespace metal;
kernel void precision_math(device float4* out [[buffer(0)]]) {
    float4 x = out[0];
    x = metal::fast::max(x, 0.25f);
    x = fast::min(x, 2.0f);
    x = metal::precise::clamp(x, 0.0f, 1.0f);
    x = precise::normalize(x);
    out[0] = metal::fast::sin(x);
}
