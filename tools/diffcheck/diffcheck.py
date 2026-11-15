#!/usr/bin/env python3
"""Runs a Metal kernel on the Apple GPU and mslc's SPIR-V for it on lavapipe, feeds both
identical seeded inputs, and reports any output difference.

  diffcheck.py file.metal [--entry k] [--grid 64] [--local 8] [--seed 1] [--cases 3]

Exit status: 0 every compared case matched, 1 a mismatch, a failed negative control, a
zero-output run or a reflection disagreement, 2 a harness error, 3 nothing could be
compared (skipped, with the reason), 77 Metal or lavapipe is not available here.
See tools/diffcheck/README.md.
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile

import checks
import compare
import directives
import hostenv
import hosts
import inputs

OK, MISMATCH, ERROR, SKIPPED = 0, 1, 2, 3


def run_mslc(mslc, source, work, includes):
    spv, refl = os.path.join(work, "mslc.spv"), os.path.join(work, "mslc.json")
    cmd = [mslc, "--stage", "kernel", "-o", spv, "--reflect", refl, source] + ["-I" + i for i in includes]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=hosts.TIMEOUT)
    if r.returncode != 0:
        return None, None, (r.stderr.strip().splitlines() or ["mslc failed"])[-1]
    val = subprocess.run([shutil.which("spirv-val") or "spirv-val", "--target-env", "vulkan1.3", spv],
                         capture_output=True, text=True)
    if val.returncode != 0:
        return None, None, "mslc output fails spirv-val: " + (val.stdout + val.stderr).strip().splitlines()[0]
    return spv, json.load(open(refl)), None


def check_entry(opts, source, spv, reflection, entry, params, work):
    """Compare one kernel; returns a result dict."""
    result = {"entry": entry, "status": None, "cases": [], "reason": None}
    text = open(source, encoding="utf-8", errors="replace").read()
    local = params["local"]
    groups = params["grid"] // local
    if groups * local != params["grid"] or groups < 1:
        result.update(status="skipped", reason="grid %d is not a multiple of local size %d" % (params["grid"], local))
        return result
    bindings = reflection["bindings"]
    unsupported = sorted({b["kind"] for b in bindings if b["kind"] != "Buffer"})
    if unsupported:
        result.update(status="skipped", reason="unsupported binding kind: " + ", ".join(unsupported))
        return result
    mbuf = sorted([b for b in bindings], key=lambda b: b["member"])

    std = params.get("std")
    try:
        lines = hosts.apple_source_lines(source, work, opts.includes, std, opts.apple_source)
        apple = hosts.apple_reflection(opts.metal, lines, entry, work)
    except hosts.HostError as e:
        result.update(status="skipped", reason=str(e))
        return result
    if apple["unsupported"]:
        result.update(status="skipped", reason="unsupported argument: " + "; ".join(apple["unsupported"]))
        return result
    findings = checks.cross_check(mbuf, apple)
    if findings:
        result.update(status="reflection-mismatch", reason="; ".join(findings))
        return result
    layouts = {b["index"]: b for b in apple["buffers"]}
    if any(l["stride"] == 0 or not l["leaves"] for l in layouts.values()):
        result.update(status="skipped", reason="unsupported argument: buffer element has no scalar layout")
        return result
    if not any(l["access"] != "read" for l in layouts.values()):
        result.update(status="skipped", reason="no writable buffer to compare")
        return result
    if local > apple["max_threads"]:
        result.update(status="skipped", reason="local size %d exceeds Apple's limit %d" % (local, apple["max_threads"]))
        return result
    set_index = bindings[0]["descriptor"]["set"] if bindings else 0
    elements = params.get("elems") or max(64, 4 * params["grid"])
    ulp = compare.ulp_bound_for_source(text)
    excluded = {n: r for n, r in params["exclude"].items()}

    profiles = [(inputs.PROFILES[c % 3], False) for c in range(params["cases"])]
    if opts.sentinel:
        profiles.append(("sentinel", True))
    nonzero = False
    result["ulp_bound"] = ulp
    for case, (profile, sentinel) in enumerate(profiles):
        rng = random.Random(params["seed"] * 1000 + case)
        data = {i: inputs.fill_buffer(l, elements, rng, "wide" if sentinel else profile, sentinel, opts.poison_padding)
                for i, l in sorted(layouts.items())}
        outs = {}
        for backend, runner in (("apple", hosts.run_metal), ("mslc", hosts.run_vulkan)):
            manifest = os.path.join(work, "%s-%d.txt" % (backend, case))
            rows = []
            for b in mbuf:
                idx = b["metal_index"]
                inp = os.path.join(work, "in-%d-%d.bin" % (case, idx))
                if backend == "apple":
                    open(inp, "wb").write(data[idx])
                out = os.path.join(work, "%s-out-%d-%d.bin" % (backend, case, idx))
                key = idx if backend == "apple" else b["member"]
                rows.append("buffer %d %d %s %s" % (key, len(data[idx]), inp, out))
            if backend == "apple":
                text_m = ["mode run"] + lines + ["entry " + entry, "local %d 1 1" % local, "groups %d 1 1" % groups] + rows
                binary = opts.metal
            else:
                text_m = ["spv " + spv, "entry " + entry, "set %d" % set_index, "local %d 1 1" % local,
                          "groups %d 1 1" % groups] + rows
                binary = opts.vk
            open(manifest, "w").write("\n".join(text_m) + "\n")
            runner(binary, manifest)
            outs[backend] = {b["metal_index"]: bytearray(open(os.path.join(work, "%s-out-%d-%d.bin" % (backend, case, b["metal_index"])), "rb").read())
                             for b in mbuf}
        if opts.corrupt_mslc:
            name, _, at = opts.corrupt_mslc.partition(":")
            for i, l in layouts.items():
                if l["name"] == name:
                    outs["mslc"][i][int(at)] ^= 0xff
        case_diffs = []
        for i, layout in sorted(layouts.items()):
            if layout["name"] in excluded:
                continue
            for d in compare.compare(layout, outs["apple"][i], outs["mslc"][i], ulp):
                case_diffs.append(d.to_json())
        nonzero = nonzero or checks.written_nonzero(layouts, data, outs["apple"]) or checks.written_nonzero(layouts, data, outs["mslc"])
        # Negative control: a copy of the mslc result with one leaf changed must differ from
        # Apple's, or the comparison above could not have told a miscompile from a match.
        control = checks.perturb(layouts, outs["mslc"])
        control_ok = False
        if control is not None:
            copy, name, _ = control
            index = next(i for i, l in layouts.items() if l["name"] == name)
            control_ok = bool(compare.compare(layouts[index], outs["apple"][index], copy[index], 0))
            if layouts[index]["name"] in excluded:
                control_ok = True
        result["cases"].append({"case": case, "profile": profile, "diffs": case_diffs[:16],
                                "diff_count": len(case_diffs), "negative_control": control_ok})
    if any(not c["negative_control"] for c in result["cases"]):
        result.update(status="control-failed", reason="the perturbed copy compared equal to Apple's output")
    elif any(c["diff_count"] for c in result["cases"]):
        first = next(c for c in result["cases"] if c["diff_count"])
        result.update(status="mismatched", reason="first difference: %s" % json.dumps(first["diffs"][0]))
    elif not nonzero and not params["writes_zero"]:
        result.update(status="zero-output", reason="no output leaf was written to a non-zero value on either backend "
                      "(declare `// DIFFCHECK: writes-zero` if that is right)")
    else:
        result["status"] = "matched"
    if excluded:
        result["excluded"] = excluded
    return result


def check_file(opts, path):
    """Results for every kernel in `path` (or the one named by --entry)."""
    text = open(path, encoding="utf-8", errors="replace").read()
    d = directives.parse(text)
    work = tempfile.mkdtemp(prefix="diffcheck-", dir=os.environ.get("TMPDIR"))
    try:
        spv, refl, error = run_mslc(opts.mslc, path, work, opts.includes)
        if error:
            return [{"entry": opts.entry or "*", "status": "skipped", "reason": error, "cases": []}]
        entries = [e for e in refl["entry_points"] if e["stage"] == "compute"]
        if opts.entry:
            entries = [e for e in entries if e["name"] == opts.entry]
            if not entries:
                return [{"entry": opts.entry, "status": "skipped", "reason": "no such kernel", "cases": []}]
        results = []
        for e in entries:
            run = d["run"]
            params = {
                "grid": opts.grid or run.get("grid", 64), "local": opts.local or run.get("local", 8),
                "seed": opts.seed if opts.seed is not None else run.get("seed", 1),
                "cases": opts.cases or run.get("cases", 3), "elems": opts.elems or run.get("elems"),
                "std": opts.std, "exclude": d["exclude"], "writes_zero": d["writes_zero"],
            }
            sub = os.path.join(work, e["name"])
            os.makedirs(sub)
            results.append(check_entry(opts, path, spv, e, e["name"], params, sub))
        return results
    finally:
        if not opts.keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print("kept " + work, file=sys.stderr)


def parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("file")
    p.add_argument("--entry", help="kernel to check (default: every kernel in the file)")
    p.add_argument("--grid", type=int, help="total threads in x (default 64)")
    p.add_argument("--local", type=int, help="threads per threadgroup in x (default 8)")
    p.add_argument("--seed", type=int)
    p.add_argument("--cases", type=int, help="number of seeded cases, cycling the moderate, wide and edge profiles")
    p.add_argument("--elems", type=int, help="elements per buffer (default 4 x grid)")
    p.add_argument("--sentinel", action="store_true", help="add a case whose buffers are all 0x7f bytes")
    p.add_argument("--poison-padding", action="store_true", help="fill struct padding with 0xA5")
    p.add_argument("--std", help="Metal language version for Apple's compiler (2.4, 3.0, 3.1, 3.2)")
    p.add_argument("--apple-source", action="store_true",
                   help="compile with newLibraryWithSource (fp contraction on) instead of xcrun metal -ffp-contract=off")
    p.add_argument("-I", dest="includes", action="append", default=[])
    p.add_argument("--mslc", default=os.environ.get("MSLC", "mslc"))
    p.add_argument("--metalhost", default=os.environ.get("DIFFCHECK_METALHOST"))
    p.add_argument("--vkhost", default=os.environ.get("DIFFCHECK_VKHOST"))
    p.add_argument("--report", help="write the JSON report here")
    p.add_argument("--keep", action="store_true", help="keep the scratch directory")
    p.add_argument("--corrupt-mslc", metavar="BUFFER:BYTE",
                   help="self-test hook: invert one byte of mslc's output before comparing")
    return p


def main(argv=None):
    opts = parser().parse_args(argv)
    try:
        opts.metal, opts.vk = hosts.metalhost(opts.metalhost), hosts.vkhost(opts.vkhost)
        if hostenv.find_lavapipe_icd() is None:
            raise hosts.Unavailable("no lavapipe ICD")
        results = check_file(opts, opts.file)
    except hosts.Unavailable as e:
        print("SKIPPED: %s" % e)
        return hostenv.SKIP
    except hosts.HostError as e:
        print("diffcheck: %s" % e, file=sys.stderr)
        return ERROR
    report = {"file": opts.file, "results": results}
    if opts.report:
        json.dump(report, open(opts.report, "w"), indent=1)
    for r in results:
        print("%-14s %s  %s" % (r["status"], r["entry"], r.get("reason") or ""))
    statuses = {r["status"] for r in results}
    if statuses <= {"matched"}:
        return OK
    if statuses <= {"skipped"}:
        return SKIPPED
    return MISMATCH


if __name__ == "__main__":
    sys.exit(main())
