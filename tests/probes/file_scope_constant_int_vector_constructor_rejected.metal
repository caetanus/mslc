// EXPECT: error initialised with a braced list of its components
//
// Apple takes int4(1); mslc folds float and half vectors only, and says so.
constant int4 k = int4(1);
kernel void file_scope_constant_int_vector_constructor_rejected(device int *out [[buffer(0)]],
    uint i [[thread_position_in_grid]])
{
    out[i] = k.x;
}
