// EXPECT: valid
// DISASM: OpAll
#include <metal_stdlib>
using namespace metal;
kernel void all_vector(device float2* input [[buffer(0)]], device bool* out [[buffer(1)]]) {
    out[0] = all(input[0] != float2(0.0f));
    out[1] = metal::all(input[1] != float2(0.0f));
}
