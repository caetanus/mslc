// EXPECT: valid
// DISASM: 0.333
// DISASM: 0.00150000001
// DISASM: 3
// REFLECT: "lod_min": 0.333000004, "lod_max": 3
#include <metal_stdlib>
using namespace metal;
fragment float4 hit(texture2d<float> t [[texture(0)]]) {
  constexpr sampler s(lod_clamp(0.333f, 3.0F), filter::linear);
  return t.sample(s, float2(0.333, 1.5e-3)) + float4(3.0, 0.5h, 0.25H, 0.75F);
}
