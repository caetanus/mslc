// EXPECT: error sizeof of this expression is not lowered
// Apple does not evaluate the operand, so sizeof(i++) is 4 and i stays 0. mslc refuses an
// operand that writes rather than build it and risk running it.
kernel void sizeof_expression_side_effect_rejected(device ulong *out [[buffer(0)]])
{
    int i = 0;
    out[0] = sizeof(i++);
    out[1] = i;
}
