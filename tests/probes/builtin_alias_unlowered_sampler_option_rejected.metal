// EXPECT: error the sampler option "max_anisotropy" is not lowered yet
// Apple accepts this; mslc does not lower the option. An option family reached through an alias gets its family-specific diagnostic, as through metal::.
#include <metal_stdlib>
namespace M = ::metal;
kernel void kern(device float* out [[buffer(0)]], M::texture2d<float> t [[texture(0)]]) {
  constexpr M::sampler s(M::max_anisotropy(2)); out[0] = t.sample(s, float2(0.5)).x; }
