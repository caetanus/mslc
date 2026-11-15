// EXPECT: valid
// DISASM: OpCompositeConstruct %_struct_
struct I { int i; uint u; bool b; half h; };
kernel void k(device float* out [[buffer(0)]], constant int* in [[buffer(1)]]) { I v{.u=2u,.i=in[0],.h=1.0h,.b=true,.u=3u}; out[0]=float(v.i); out[1]=float(v.u); out[2]=v.b ? 1.0f : 0.0f; out[3]=float(v.h); }
