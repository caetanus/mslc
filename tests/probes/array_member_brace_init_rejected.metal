// EXPECT: error which has an array member, is not lowered yet
struct P { float s; float a[3]; };

kernel void array_member_brace_init_rejected(device float *o [[buffer(0)]], uint i [[thread_position_in_grid]]) {
  P q = {1.0f, {1.0f, 2.0f, 3.0f}};
  o[i] = q.a[1];
}
