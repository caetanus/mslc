// EXPECT: error sizeof of this expression is not lowered
// Apple: packed_float3 + packed_float3 is a packed_float3, sizeof 12. The value of one is a
// float3 here, which would say 16, so an arithmetic operand that is packed is refused.
struct Rec { packed_float3 p; };
kernel void sizeof_expression_packed_arithmetic_rejected(device ulong *out [[buffer(0)]])
{
    Rec r;
    out[0] = sizeof(r.p + r.p);
}
