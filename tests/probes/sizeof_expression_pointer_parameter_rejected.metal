// EXPECT: error pointer parameter
// Apple gives 8; a parameter's name may be a local of another type by now, which mslc does not
// track, so it refuses sizeof of one and takes sizeof(device float *) instead.
kernel void sizeof_expression_pointer_parameter_rejected(device ulong *out [[buffer(0)]],
    device float *data [[buffer(1)]])
{
    out[0] = sizeof(data);
}
