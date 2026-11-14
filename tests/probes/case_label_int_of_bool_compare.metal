// EXPECT: valid
// DISASM: OpSwitch

#include <metal_stdlib>
using namespace metal;

kernel void k(device int* out [[buffer(0)]]) {
  switch (out[1]) {
    case int(true == true): out[0] = 1; break;
    default: out[0] = 2; break;
  }
}
