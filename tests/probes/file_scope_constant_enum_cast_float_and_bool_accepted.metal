// EXPECT: valid
// DISASM: OpConstant %int 1
//
// Apple accepts (Mode)1.5f, which truncates to 1, and (Mode)true, which is 1.
#include <metal_stdlib>
using namespace metal;
enum Mode { MA, MB };
constant Mode kf = (Mode)1.5f;
constant Mode kb = (Mode)true;
kernel void file_scope_constant_enum_cast_float_and_bool_accepted(device int* o [[buffer(0)]], uint i [[thread_position_in_grid]])
{ o[i] = (int)kf + (int)kb; }
