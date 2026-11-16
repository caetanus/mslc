// EXPECT: valid
// DISASM: OpAny
#include <metal_stdlib>
using namespace metal;
kernel void any_vector(device float2* input [[buffer(0)]], device bool* out [[buffer(1)]]) {
    out[0] = any(input[0] != float2(0.0f));
    out[1] = metal::any(input[1] != float2(0.0f));
}
