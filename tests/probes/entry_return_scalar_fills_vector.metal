// EXPECT: valid
// A fragment entry point returning a scalar for a float4 return type: Apple
// fills every component, as it does for a helper's return and an initialiser
// (#351). Before the fix the entry point's return took the strict convert and
// failed "a scalar cannot be converted to a vector", with or without a helper
// call before it.
// DISASM: OpCompositeConstruct
namespace n { void g() {} }
fragment float4 entry_return_scalar_fills_vector() { n::g(); return 0; }
