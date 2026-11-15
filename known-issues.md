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

## An ignored nested scalar initializer element is emitted, then discarded (open)

**Status:** open, found 2026-11-15 while fixing #164. Nothing regressed: master
rejected every excess form.

`float x{{a, b}}` keeps `a` and Apple never evaluates `b`, but it does type-check
it. mslc type-checks it by emitting it and lifting the instructions out, so:

- An element mslc cannot lower as a value is rejected where Apple accepts it:
  `i++`/`i--`, `i += 1`, an assignment such as `out[1] = 5.0f` ("cannot be used
  as a value"), a void call `g()`, a bare buffer name `in`, `discard_fragment()`.
  `int x{{in[1], i++}}` leaves `i` unchanged in Apple. Pinned by
  `tests/probes/brace_local_scalar_nested_excess_increment_not_lowered.metal`.
- The lift leaves unused OpConstant and OpType declarations, a GLSL.std450
  import, and one unused OpVariable in the call case. A half operation in an
  ignored element adds OpCapability Float16 to a module that does not otherwise
  need it. A helper called only from an ignored element is still emitted as an
  uncalled OpFunction.

## Compound assignment reads its target before the right operand runs (found 2026-11-15, #232)

**Status:** open, pre-existing on master. For `n += (n = 10, 5);` Apple's AIR stores
15 (the right operand runs first, then `n` is read), while mslc loads `n` before the
right operand runs and stores the old `n` plus 5. Master does the same with
`n += g(n)` where `g(thread int &r) { r = 10; return 5; }`. The ordering lives in
`emitAssignment`'s compound-assignment path; the comma operator only opens another way
to reach it. Valid SPIR-V, wrong value, so a fix needs a produced-value read-back.

## Forms Apple accepts that the comma operator and void casts still reject (#232)

**Status:** open, all loud rejections, none a miscompile.

- `c ? f() : g();` with void helpers: `isVoidValued` treats only void casts, commas ending
  in one and conditionals of them as void, not calls.
- `return f();` with `f` void in a void function.
- A comma in a constant context: an array size `[(1, 2)]`, `case (1, 2):`,
  `constant int N = (1, 2);`.
- A comma whose right operand writes, used as a value: `x = (a, b = 3)` and `x = (a, n++)`.
- `(n = 1, s).b` on a struct: rejected with the misleading ".b swizzles a value that is
  not a vector", because `structOf` has no Comma case. Making `structOf` throw is wrong
  (it is called speculatively on any expression), so it needs a real case that returns the
  right operand's struct and lowers the member of a value.
- `(n, t) = 3;` is now rejected as "assigning to a comma expression is not lowered yet"
  (probe `comma_assignment_target_rejected`).

## An overloaded helper's Linkage name depends on the overload set this unit sees (#266)

A helper name with one signature in a unit keeps its plain Linkage name (`scaled`), as
before. A name that has two or more signatures in the unit exports each as
`name(parameter types)`, built from the canonical signature (`mixed(float3)`,
`mixed(float,thread const int&)`). The choice is made per unit, so two units of one link
have to see the same overloads of a name: a library that defines `f(float)` alone exports
`f`, and a caller whose own headers also declare `f(float3)` imports `f(float)`, which
does not meet it. Importing one overload of an overloaded name (declared here, defined in
another unit) is refused for the same reason. Apple's own AIR symbols are Itanium-mangled
for every function, which mslc does not follow.

## Overload sets, using declarations and argument-dependent lookup: what is not followed (#266)

- A using declaration names the overloads declared above it, and a later one is not found
  through it (Apple). mslc refuses a new overload declared after a using declaration of its
  name instead of modelling the cut-off.
- Argument-dependent lookup adds the same-named functions of the namespace of each struct
  argument, found from the argument's struct when it is a name, a member, an element or a call
  result. An enum argument, or a struct the emitter cannot name before evaluating, adds nothing.
  The passes that run before emission (the import scan, file-scope sampler ownership) read a
  call's names from the source and do not see what lookup adds: a function declared and defined
  elsewhere that only argument-dependent lookup reaches is refused, and a file-scope sampler
  named by a function only it reaches is not counted against its entry point.
- A helper no entry point reaches is not checked for a call to an overloaded name (arity, no
  matching function, declared above); resolution happens where the call is emitted.
- Beside other overloads, an element or member of a local that a mutable reference parameter could
  bind is refused unless it is a local name or an element of a local array of scalars (a vector
  component cannot be bound, and Apple errors on it after choosing the reference). A device or
  constant lvalue is classified (it never binds a thread reference).
- An import of an overloaded name is refused, but the plain Linkage name of a function with one
  signature does not tell `f(E)` from `f(int)`: an import of one links to an export of the other.

## String literals, char pointers and pointer-to-bool are rejected on purpose (#156)

Apple's compiler accepts `const constant char *p = "abc"`, `constant char *p = "x"`,
`bool b = "x"`, `if ("x")`, `sizeof("abc")`, `"abc"[1]`, `"a" "b"`, `u8"abc"`, `R"(abc)"`, `L"x"` as a `bool`, in `sizeof` or as a `wchar_t` pointer
(only `const constant char *s = L"x"` is rejected there), `static_assert(1, "msg")`,
and accepts a kernel buffer pointer in a bool context (`bool b = p`, `if (p)`, `!p`; measured
with `xcrun -sdk macosx metal`). mslc rejects all of them, deliberately. The decision is a
rejection with a clear diagnostic ("a string literal is not lowered; mslc has no string type,
so char pointers, char arrays and bool-from-pointer are not lowered"; "a prefixed string
literal ..."; "the buffer ... is used as a value (a comparison, a conversion to bool or a copy); mslc does not lower pointer values yet"), not an accident.

Why: no corpus shader uses a string literal; a char pointer to one has no SPIR-V
representation without a constant char array plus a pointer into it; a pointer in a bool
context would need a null test, and the Logical and PhysicalStorageBuffer addressing mslc
emits give a pointer no meaningful null.

What accepting them would need: a constant char array lowering (a Private or UniformConstant
variable with an initializer), a pointer type for `const constant char *` as a value, array
decay and indexing of a literal, adjacent literal concatenation and `sizeof` folding in the
parser, prefix and raw-string lexing, and an explicit pointer-to-bool rule for buffer
pointers (a constant true, or an address compare against zero in PhysicalStorageBuffer64).
Related and separate: a helper function taking a `constant char *` parameter is refused by
the helper pointer-parameter limit, not by this one.

Also recorded under this entry, all measured against Apple and all pre-existing:

- `static_assert(1, "msg")` inside a function is rejected with the string-literal wording above,
  because mslc has no `static_assert` and reads it as a call with a string argument.
- Raw strings Apple accepts (`R"d(a;b)" c)d"` and a multi-line `R"(...)"`) still fail in the lexer
  with "newline in a string literal at offset N", so the prefixed-literal message never fires
  for them; it fires only for a single-line prefixed literal that the lexer keeps whole.
- Character literals (`'a'`, `u8'a'`, `L'a'`) are not lexed at all ("unexpected character"),
  although Apple accepts them.
- A prefix separated by a space (`L "x"`) is an identifier and a literal, and keeps the
  "expected ; after a declaration" error (Apple rejects it too).
- The buffer-as-value message ("the buffer ... is used as a value") covers every use of a
  kernel buffer pointer as a value: a comparison, a conversion to bool, a copy. Apple accepts
  comparisons and bool tests and rejects `float x = p`; mslc rejects all, with one wording.

## Brace elision: forms Apple accepts that mslc refuses (#161)

Refusals, not miscompiles; each fails with a diagnostic.

- A designator over a struct member with a bare value, `Outer o{.p = 1.0f, .c = 3.0f}`: Apple elides
  under the designator (p.a = 1, p.b = 0); mslc reports "a struct converts to another form of itself only".
- A member with a user constructor, `struct OC { Ctor k; float c; }; OC o{1.0f, 2.0f};`: Apple calls
  `Ctor(float)`; mslc rejects brace initialisation involving declared constructors.
- A member struct with an array member reached by elision is rejected as not lowered (arrays: #131).
