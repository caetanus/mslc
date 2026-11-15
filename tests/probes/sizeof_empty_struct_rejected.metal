// EXPECT: error has no members
// Apple gives an empty struct size 1; mslc refuses rather than carry the empty-class rule.
#include <metal_stdlib>
using namespace metal;
struct Empty { };
kernel void sizeof_empty_struct_rejected(device float *out [[buffer(0)]])
{
    out[0] = sizeof(Empty);
}
