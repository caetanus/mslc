// EXPECT: valid
// DISASM: OpSelect
kernel void integer_conversion(device int* out [[buffer(0)]]) {
    out[0] = (int(out[0] != 0) * (int(out[1] < 0) + int(out[1] > 1)));
}
