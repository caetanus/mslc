// EXPECT: valid
// DISASM-NOT: OpLogicalEqual

#include <metal_stdlib>
using namespace metal;

constant bool A = true;
constant bool B = A == false;
constant bool C = 2 < 3;

kernel void k(device int* out [[buffer(0)]]) {
  out[0] = B ? 1 : 0;
  out[2] = C ? 1 : 0;
}
