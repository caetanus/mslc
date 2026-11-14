// EXPECT: valid
// The scalar return also converts its component type on the way (#351):
// 0.5f to half4 and 1.5f to int4 are accepted by Apple.
// DISASM: OpFConvert
fragment half4 entry_return_scalar_fills_half4() { return 0.5f; }
