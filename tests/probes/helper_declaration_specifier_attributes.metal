// EXPECT: valid
static inline __attribute__((always_inline)) float twice(float x) {
    return x * 2.0f;
}
__attribute__((noinline, unknown_attribute(nested(1)))) static inline float add(float x) {
    return twice(x) + 1.0f;
}
kernel void attributed_helper(device float* out [[buffer(0)]]) {
    out[0] = add(out[0]);
}
