# Known issues

## lavapipe cannot execute any mslc module on this machine (RESOLVED, stale)

**Status:** resolved/stale as of 2026-10-13; kept for history, not current guidance.
Originally found 2026-10-10 while verifying #181.

This entry claimed every mslc-produced compute module failed at
`vkCreateComputePipelines` with `VK_ERROR_FEATURE_NOT_PRESENT`, or segfaulted
inside the driver. That is no longer true on this machine: fragment and
compute/kernel lavapipe readbacks have since run cleanly and produced correct,
mutation-sensitive numeric results for #184 (point_size), #220 (texture3d),
#221 (texture2d_array), and #173 (half fwidth), across several sessions
between 2026-10-10 and 2026-10-13. Whatever the original environment fault
was (driver update, ICD reinstall, or a transient local misconfiguration on
this shared machine, never isolated), it no longer reproduces. Left here
rather than deleted so a future reader who hits a *new* lavapipe failure has
the original evidence and knows this specific failure mode was already seen
and later resolved, not to be treated as still-current advice to skip
readbacks on this host.

Original evidence (2026-10-10):

- The device was found, reported Vulkan API 1.4.354, exposed `dynamicRendering`,
  `maintenance4` and `VK_KHR_synchronization2`, and created instance, device,
  queue, buffer, memory and descriptor set without complaint.
- `spirv-val --target-env vulkan1.3` accepted the same modules.
- It reproduced with `tests/compute_buffer_clear.metal` and with a four-line
  kernel that only stores a literal, so it was not a specific feature mslc
  emitted.
- `lldb` put the fault in `libvulkan_lvp.dylib`'s worker thread
  (`___lldb_unnamed_symbol14182 + 356`), with no mslc or harness frame below it.
- It was unaffected by `spirv-opt --freeze-spec-const`, so
  `OpExecutionModeId ... LocalSizeId` spec constants were not the cause.

**Do** attempt a lavapipe readback on this machine; it works as of 2026-10-13.
If a *new* failure reproduces, record fresh evidence rather than reviving this
entry, since the original cause was never identified.

## half `fwidth` lowers via widen-to-float32, Apple parity unmeasured (#173)

`fwidth` on a `half`/`half2`/`half3`/`half4` argument lowers by converting the
operand to `float32`, emitting `OpFwidth` (core SPIR-V requires 32-bit float
components), and converting the result back to `half`. This is proven
internally correct by a lavapipe readback (exact affine-input derivative,
tolerance 0, two compiler mutants both caught), but **Apple's own half-fwidth
rounding policy is unmeasured on this machine** (no Apple toolchain is
reachable here). Apple is known to emit a native `air.fwidth.v2f16` for half,
which may compute the difference/sum in half precision directly rather than
widening to float32 first; the two approaches are not guaranteed to produce
bit-identical results. The project owner was asked directly and chose to land
this lowering with the gap stated rather than wait for hardware access to
measure it. If Apple hardware/toolchain access becomes available, measure
`air.fwidth.v2f16`'s actual output against mslc's widen-compute-narrow output
and update or remove this entry.

## mslc emits Vulkan-valid modules that this lavapipe rejects

`PhysicalStorageBuffer64` addressing with a binding-0 address block is correct
for indium and is validated by `spirv-val`, but a driver may not implement it.
Where a read-back is required for such a module, confirm the driver supports
the addressing model before treating a failure as an mslc defect.

## atomic_compare_exchange_weak_explicit accepts a narrower set than Apple (#249)

mslc lowers the weak form only for the shapes below and refuses the rest with a
diagnostic, so these are documented under-acceptances (valid Metal that mslc
rejects), not miscompiles. `atomic_compare_exchange_strong_explicit` does not
exist in Apple's toolchain and is rejected on purpose.

Expected side (`&expected`): only the address of a plain local scalar of the
atomic's own type (`uint` for `atomic_uint`, `int` for `atomic_int`) is taken.
Not supported: `&e[1]` (array element), `&e.y` (a struct member; a vector
element is an error in Apple too), a `thread` pointer local passed as the
expected argument, a builtin parameter, `&*&e`, and a `memory_order(0)` style
order spelled as anything but `memory_order_relaxed`.

Atomic side: only a device `atomic_uint`/`atomic_int` buffer pointer or element
(`&c[i]`, or the pointer itself), or `&local` of a scalar threadgroup atomic.
Not supported: atomic pointers received as helper parameters, atomics held in
struct members, a `device atomic_uint&` reference, pointer arithmetic on the
atomic pointer, threadgroup atomic arrays, `atomic<uint>`, and an alias
declared with `using A = atomic_uint` (a `typedef` alias is supported).

## An anonymous enum's enumerator converts to a named enum (#261)

`typedef enum { TA, TB } Anon; constant Mode km = TB;` (and the same through an
argument, a brace leaf, a conditional or a return) compiles. Apple rejects it:
"cannot initialize a variable of type 'const constant Mode' with an rvalue of
type 'Anon'". `requireEnumValue` lets `"<anonymous>"` through at every target,
because mslc cannot tell an untagged enumerator from the target enum's own one;
closing it needs anonymous-enum identity tracking, which does not exist.
Pinned by `tests/probes/enum_element_argument_and_brace_accepted.metal`.

A file-scope enum constant initialised with a conditional
(`constant Mode km = c ? MA : MB;`) is also refused as "not a value that can be
worked out", where Apple accepts it; the folder has no conditional.

## A float cast to an enum in a file-scope constant is refused when it does not fit (#261)

`constant Mode km = (Mode)1e30f;` (also `(Mode)2147483648.0f`, `(Mode)-2.7f`, NaN
and infinities) is refused: the truncated value is outside the enum's range,
which C++ leaves undefined. mslc takes the range as 0 up to INT_MAX (it records
an int underlying type unless an enumerator is past INT_MAX); Apple's enum
without a negative enumerator is unsigned, so the refusal is slightly wider than
Apple's range for values in [2^31, 2^32) and for enums with negative
enumerators. Apple accepts the out-of-range casts and folds them through LLVM's
undefined-behaviour rules to host- and pass-dependent values (`(Mode)9e18f` is
-1, `(Mode)-2.7f` is 0), not a language rule mslc could match. Truncations that
fit (`1.5f`, `-0.5f`, `1e-40f`) fold as Apple does. Pinned by the
`file_scope_constant_enum_cast_float_*` probes.
