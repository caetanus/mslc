// EXPECT: error a pointer field in value struct "S" is not lowered yet
// A threadgroup pointer member of a local struct is refused, not lowered as a scalar (#346).
struct S { threadgroup float *p; float q; };
kernel void struct_pointer_member_threadgroup_rejected(device float *o [[buffer(0)]],
    uint i [[thread_position_in_grid]])
{
    threadgroup float t[4];
    S s;
    s.p = t;
    s.q = 1;
    o[i] = s.q;
}
