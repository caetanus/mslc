// EXPECT: error sizeof of a texture or sampler
// Apple answers for a sampler; mslc has no size for one and refuses rather than guess.
#include <metal_stdlib>
using namespace metal;

kernel void sizeof_sampler_rejected(device float *out [[buffer(0)]])
{
    out[0] = sizeof(sampler);
}
