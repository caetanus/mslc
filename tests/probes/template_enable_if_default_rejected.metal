// EXPECT: error the default argument of the template parameter "E" of "f" is not lowered
// Refs #341 (slice 3 evaluates it): the default is what drops the template for a non-float T, so
// ignoring it could pick the template where Apple does not; the call is refused instead.
#include <metal_stdlib>
using namespace metal;
template <typename T, typename E = typename enable_if<is_floating_point<T>::value>::type> float f(T x) { return 1.0f; }
kernel void k(device float* out [[buffer(0)]]) { out[0] = f(1.0f); }
