// EXPECT: error texture2d<int> is not lowered yet
// Apple accepts texture2d<int> sampled; its sample() is the next slice.
#include <metal_stdlib>
using namespace metal;
fragment float4 f(texture2d<int> t [[texture(0)]]) {
  return float4(0.0);
}
