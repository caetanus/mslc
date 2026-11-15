// EXPECT: error sizeof of a texture or sampler
// Apple answers for a texture; mslc has no size for one and refuses rather than guess.
#include <metal_stdlib>
using namespace metal;

kernel void sizeof_texture_rejected(device float *out [[buffer(0)]])
{
    out[0] = sizeof(texture2d<float>);
}
