# diffcheck: Apple's compiler against mslc, by execution

`spirv-val` proves a module is valid, not that it does what the Metal source says.
diffcheck compiles a kernel with Apple's compiler and runs it on the Apple GPU, runs
mslc's SPIR-V for the same source on lavapipe, feeds both the same seeded bytes, and
reports any output difference.

## One command

```sh
python3 tools/diffcheck/diffcheck.py file.metal [--entry k] [--grid 64] [--local 8] \
    [--seed 1] [--cases 3] [--sentinel] [--poison-padding] [--report out.json]
python3 tools/diffcheck/diffcheck.py --corpus list.txt [--root dir] [--jobs 4] [--report out.json]
```

Needs: macOS with a Metal device, `mslc` (`MSLC=path` or `--mslc`), `spirv-val`, a Vulkan
loader and Mesa's lavapipe (`brew install mesa vulkan-loader`; the ICD is found under
`$HOMEBREW_PREFIX/share/vulkan/icd.d` or taken from `VK_ICD_FILENAMES`, and only a
lavapipe manifest is accepted), `cc` and `clang++`. The two hosts are built on demand into
`$TMPDIR/diffcheck-hosts`. Nothing else outside this repository is needed.

A corpus list has one path per line, `#` comments, and an optional `std=3.1`. Paths are
relative to `--root` (default: the list's directory), so third-party shaders stay out of
the repository: the harness takes any path.

Exit status: `0` every compared case matched; `1` a mismatch, a failed negative control, a
zero-output run or a reflection disagreement; `2` a harness error; `3` nothing could be
compared (skipped, with the reason); `77` Metal or lavapipe is not available here.
In `--corpus` mode skips do not fail the run.

## What it does for a kernel

1. mslc compiles the file (`--stage kernel`) and `spirv-val --target-env vulkan1.3` must pass.
2. Apple compiles it with `newLibraryWithSource` and `MTLMathModeSafe` (`xcrun metal` for a
   file with a quoted `#include`, which an in-memory source cannot resolve). Apple's
   pipeline reflection gives every buffer's index, name, access and element layout, flattened
   to scalar leaves; mslc's reflection JSON has no types. The two reflections are
   cross-checked (buffer index and name); a disagreement is itself a finding.
3. Per case, every buffer is filled from one seeded generator and both backends get the same
   bytes. Cases cycle three profiles: `moderate` (small values), `wide` (random bits, finite
   floats) and `edge` (0, 1, -1, INT_MIN/MAX, UINT_MAX, +-0, +-inf, NaN, denormals, +-1e-38,
   +-1e38). bool leaves are only ever 0 or 1. `--sentinel` adds a case whose buffers are all
   0x7f bytes (a finite float), so a store outside the expected bytes shows. `--poison-padding`
   fills struct padding with 0xA5.
4. All buffers are read back and compared leaf by leaf, writable and read-only alike.
5. Negative control, every case: one leaf of mslc's result is changed and must then compare
   unequal to Apple's, so a comparison that cannot fail is detected. A run in which no leaf of
   a writable buffer was written to a non-zero value fails (`zero-output`) unless the file says
   `// DIFFCHECK: writes-zero`.

Grid and local size are in x only. `--grid` is the total thread count and must be a multiple
of `--local`. Buffers get `--elems` elements (default four per thread). The Vulkan side sets
the local size through spec constants 0, 1 and 2, which is what indium does.

## Comparison rules (`compare.py`)

| Type | Rule |
| --- | --- |
| integers, bool | bit-exact |
| float, half | bit-exact, unless the source calls an inexact builtin: then within the loosest bound of `ULP_BOUNDS` among the builtins it calls |
| NaN | two NaNs match (payloads differ legitimately); a NaN against a number never matches and never passes a ULP bound |
| infinities | the same infinity |
| +0 and -0 | different, except under a ULP bound |
| struct padding | not compared (only leaves are) |

## Exclusions, all explicit

- `// DIFFCHECK-EXCLUDE: <buffer> <reason>` skips one buffer's comparison; the reason is
  required and printed in the report. Use it for reads of uninitialised memory, out-of-bounds
  accesses, races, and the Apple quirks listed in the handover (bool-index dynamic stores write
  lanes j and j+2, vector long/ulong to bool, `half(1e-8)`, fast math).
- `// DIFFCHECK-RANGE: <buffer> <lo> <hi>` bounds the integer leaves of an index buffer.
- `// RUN: grid=64 local=8 seed=1 cases=3 elems=256` sets the run parameters for the file
  (command-line flags win).
- Fused multiply-add: Metal contracts `a * b + c` into an fma even in safe math mode, mslc emits
  a separate multiply and add, and the results differ by a ULP or more under cancellation. That
  is a permitted difference, so the Apple side compiles with `#pragma clang fp contract(off)`.
  `--apple-contract` restores what an app's build does.
- Not supported yet, skipped with the reason: textures, samplers, threadgroup memory, argument
  buffers, atomics, graphics stages.

## Reading a mismatch: what is not an mslc bug

Triage of the first corpus sweeps (1,295 probe kernels at grid 1, 1,086 compared, 986 matched):

- Inputs that are UB for the kernel. A float input converted to an array index, a `uchar` lane
  index, a loop bound or a store index drawn from the full 32-bit range reads or writes out of
  bounds or never terminates. Use `// DIFFCHECK-RANGE`, `--range`, or `--profiles moderate`
  (probes are single-thread designs: run them with `--grid 1 --local 1`).
- Uninitialised reads (a struct local with no initialiser, a threadgroup array read before any
  write): Apple returns garbage, mslc zero. Exclude the buffer with a reason.
- lavapipe folds `float(half(x))` to `x` and `float(int(x))` to `trunc(x)`, so a half or a
  negative fraction held in a register differs from Apple (`-0.0` against `0.0`). The SPIR-V has
  the OpFConvert and OpConvertFToS; storing the half to a buffer first (as a real kernel does)
  matches. Compare through a buffer store, or exclude.
- `newLibraryWithSource` pre-includes `<metal_stdlib>`, so a source that tests a macro before its
  include sees it defined; the offline compiler does not. A quoted `#include` takes the offline
  route and matches.
- Lavapipe rejects some valid modules (an empty struct: `vkCreateComputePipelines` -13).
- Apple may re-associate `(x + 1) - 1` (`out[i]++; --out[i].y`): a last-bits difference on
  cancellation, reported as a mismatch until a ULP bound or exclusion is given.

## Tests and CI

`-DMSLC_DIFFCHECK=ON` registers `diffcheck/*` tests; the default build and `ctest` are
unchanged. The pure-Python tests (`compare`, `inputs`, `checks`) run anywhere; the tests that
need a Metal device or lavapipe exit 77, which ctest reports as skipped. The Apple half needs
a macOS runner, and lavapipe needs Mesa installed, so this is a local and opt-in check; CI jobs
that have both can enable the option.

A probe in `tests/probes/` opts in with a `// RUN:` line; with the option on it becomes the
ctest test `diffcheck/probe/<name>` and kills a mutant the disassembly regexes cannot.
