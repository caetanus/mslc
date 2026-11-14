// EXPECT: error a float outside the integer range cannot be converted to the enum Mode
//
// Converting an out-of-range float is undefined in C++, and Apple folds it silently; mslc refuses it rather than fold a host-dependent value.
#include <metal_stdlib>
using namespace metal;
enum Mode { MA, MB };
constant Mode kf = (Mode)1e30f;
kernel void file_scope_constant_enum_cast_float_out_of_range_rejected(device int* o [[buffer(0)]], uint i [[thread_position_in_grid]])
{ o[i] = (int)kf; }
