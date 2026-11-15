// EXPECT: error worked out after parsing
// Apple takes sizeof(table) as an array length; the parser folds lengths before it knows
// declared types, so this is refused until it can (known-issues.md).
kernel void sizeof_expression_array_length_rejected(device float *out [[buffer(0)]])
{
    float table[6];
    float copy[sizeof(table)];
    out[0] = copy[0] + table[0];
}
