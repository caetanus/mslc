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
import concurrent.futures
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
import graphics
import hostenv
import hosts
import inputs

OK, MISMATCH, ERROR, SKIPPED = 0, 1, 2, 3


def check_entry(opts, source, spv, reflection, entry, params, work, includes):
    """Compare one kernel; returns a result dict."""
    result = {"entry": entry, "status": None, "cases": [], "reason": None}
    text = hostenv.read_text(source)
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
        lines = hosts.apple_source_lines(source, work, includes, std, opts.apple_contract)
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
    excluded = dict(params["exclude"])
    result["buffers"] = sorted(l["name"] for l in layouts.values())
    compared = {i: l for i, l in layouts.items() if l["name"] not in excluded}

    profiles = [(opts.profiles[c % len(opts.profiles)], False) for c in range(params["cases"])]
    if opts.sentinel:
        profiles.append(("sentinel", True))
    nonzero = False
    result["ulp_bound"] = ulp
    for case, (profile, sentinel) in enumerate(profiles):
        rng = random.Random(params["seed"] * 1000 + case)
        data = {i: inputs.fill_buffer(l, elements, rng, profile, sentinel, opts.poison_padding,
                                  params["range"].get(l["name"]), case)
                for i, l in sorted(layouts.items())}
        outs = {}
        for backend, runner in (("apple", hosts.run_metal), ("mslc", hosts.run_vulkan)):
            manifest = os.path.join(work, "%s-%d.txt" % (backend, case))
            rows = []
            for b in mbuf:
                idx = b["metal_index"]
                inp = os.path.join(work, "in-%d-%d.bin" % (case, idx))
                if backend == "apple":
                    hostenv.write_bytes(inp, data[idx])
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
            hostenv.write_text(manifest, "\n".join(text_m) + "\n")
            runner(binary, manifest)
            outs[backend] = {b["metal_index"]: bytearray(hostenv.read_bytes(os.path.join(work, "%s-out-%d-%d.bin" % (backend, case, b["metal_index"]))))
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
        nonzero = nonzero or checks.written_nonzero(compared, data, outs["apple"]) or checks.written_nonzero(compared, data, outs["mslc"])
        # Negative control: a copy of the mslc result with one leaf of a compared buffer changed
        # must differ from Apple's, or the comparison above could not have told a miscompile from
        # a match. Excluded buffers are not candidates: perturbing one would test nothing.
        control = checks.perturb(compared, outs["mslc"], outs["apple"])
        control_ok = False
        if control is not None:
            copy, name, _ = control
            index = next(i for i, l in layouts.items() if l["name"] == name)
            control_ok = bool(compare.compare(layouts[index], outs["apple"][index], copy[index], 0))
        result["cases"].append({"case": case, "profile": profile, "diffs": case_diffs[:16],
                                "diff_count": len(case_diffs), "negative_control": control_ok})
    result["status"], result["reason"] = checks.verdict(result["cases"], nonzero, params["writes_zero"])
    if excluded:
        result["excluded"] = excluded
    return result


def unknown_directives(opts, d, results):
    """A directive naming no buffer of any compared kernel is a typo that would silently do nothing."""
    known = set().union(*(r.get("buffers", []) for r in results))
    errors = []
    if known:
        named = {"DIFFCHECK-EXCLUDE": d["exclude"], "DIFFCHECK-RANGE": d["range"]}
        if not opts.corpus:
            named["--range"] = opts.ranges
        for directive, table in named.items():
            unknown = sorted(set(table) - known)
            if unknown:
                errors.append({"entry": "*", "status": "error", "cases": [], "reason": "%s names %s, which is not "
                               "a buffer (buffers: %s)" % (directive, ", ".join(unknown), ", ".join(sorted(known)))})
    return errors


def check_graphics_file(opts, path, d, vs, fs, work, includes, std):
    run = d["run"]
    params = {"width": opts.width or run.get("width", graphics.DEFAULT_SIZE), "height": opts.height or run.get("height", graphics.DEFAULT_SIZE),
              "instances": opts.instances or run.get("instances", 1), "seed": opts.seed if opts.seed is not None else run.get("seed", 1),
              "cases": opts.cases or run.get("cases", 2), "elems": opts.elems or run.get("elems"), "std": std or opts.std,
              "exclude": d["exclude"], "range": dict(d["range"], **opts.ranges), "writes_zero": d["writes_zero"],
              "geometry": d["geometry"], "position": d["position"], "depth": d["depth"]}
    sub = os.path.join(work, "graphics")
    os.makedirs(sub)
    results = [graphics.check_pair(opts, path, vs, fs, params, sub, includes)]
    return results + unknown_directives(opts, d, results)


def check_file(opts, path, std=None):
    """Results for every kernel in `path` (or the one named by --entry)."""
    here = os.path.dirname(os.path.abspath(path))
    includes = opts.includes + [here, os.path.dirname(here)]
    text = hostenv.read_text(path)
    d = directives.parse(text)
    work = tempfile.mkdtemp(prefix="diffcheck-", dir=os.environ.get("TMPDIR"))
    try:
        vs, fs = opts.vertex or d["run"].get("vertex"), opts.fragment or d["run"].get("fragment")
        if bool(vs) != bool(fs):
            return [{"entry": "*", "status": "error", "cases": [], "reason": "graphics needs both a vertex and a fragment name"}]
        if vs:
            return check_graphics_file(opts, path, d, vs, fs, work, includes, std)
        spv, refl, error = hosts.run_mslc(opts.mslc, path, work, includes)
        if error:
            status, reason = hosts.mslc_failure(error)
            return [{"entry": opts.entry or "*", "status": status, "reason": reason, "cases": []}]
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
                "std": std or opts.std, "exclude": d["exclude"], "range": dict(d["range"], **opts.ranges), "writes_zero": d["writes_zero"],
            }
            sub = os.path.join(work, e["name"])
            os.makedirs(sub)
            results.append(check_entry(opts, path, spv, e, e["name"], params, sub, includes))
        results += unknown_directives(opts, d, results)
        return results
    finally:
        if not opts.keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print("kept " + work, file=sys.stderr)


def corpus_files(listing, root):
    """(path, std) for each line of a corpus list: `path [std=3.1]`, # comments, relative to root."""
    files = []
    for line in hostenv.read_text(listing).splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        std = next((f[4:] for f in fields[1:] if f.startswith("std=")), None)
        files.append((os.path.join(root, fields[0]), std))
    return files


def check_one(opts, path, std):
    try:
        return [dict(r, file=path) for r in check_file(opts, path, std)]
    except (hosts.HostError, subprocess.TimeoutExpired, OSError, ValueError) as e:
        return [{"file": path, "entry": "*", "status": "error", "reason": str(e), "cases": []}]


def run_files(opts, files):
    """Check every file; a harness failure on one file is that file's result, not the run's."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(opts.jobs, 1)) as pool:
        return [r for rs in pool.map(lambda f: check_one(opts, *f), files) for r in rs]


def summary(results):
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    compared = sum(n for st, n in counts.items() if st not in ("skipped", "error", "invalid"))
    line = "%d kernels: %d compared" % (len(results), compared)
    return line + "".join(", %d %s" % (n, st) for st, n in sorted(counts.items()))


def parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("file", nargs="?")
    p.add_argument("--corpus", metavar="LIST", help="check every file in a list (path [std=3.1] per line)")
    p.add_argument("--root", help="directory the corpus list's paths are relative to (default: the list's own)")
    p.add_argument("--entry", help="kernel to check (default: every kernel in the file)")
    p.add_argument("--grid", type=int, help="total threads in x (default 64)")
    p.add_argument("--local", type=int, help="threads per threadgroup in x (default 8)")
    p.add_argument("--seed", type=int)
    p.add_argument("--cases", type=int, help="number of seeded cases, cycling the moderate, wide and edge profiles")
    p.add_argument("--elems", type=int, help="elements per buffer (default 4 x grid)")
    p.add_argument("--profiles", help="input profiles the cases cycle through (default: all for a kernel, moderate "
                   "for graphics; use moderate for kernels that take loop bounds or indices from buffers)")
    p.add_argument("--vertex", help="vertex function of a graphics pair (or // RUN: vertex=)")
    p.add_argument("--fragment", help="fragment function of a graphics pair (or // RUN: fragment=)")
    p.add_argument("--width", type=int, help="graphics target width in pixels (default 32)")
    p.add_argument("--height", type=int, help="graphics target height in pixels (default 32)")
    p.add_argument("--instances", type=int, help="graphics instance count (default 1)")
    p.add_argument("--sentinel", action="store_true", help="add a case whose buffers are all 0x7f bytes")
    p.add_argument("--poison-padding", action="store_true", help="fill struct padding with 0xA5")
    p.add_argument("--std", help="Metal language version for Apple's compiler (2.4, 3.0, 3.1, 3.2)")
    p.add_argument("--apple-contract", action="store_true",
                   help="let Apple's compiler fuse a * b + c into an fma, as an app's build does (default: off, "
                        "because mslc emits a separate multiply and add)")
    p.add_argument("-I", dest="includes", action="append", default=[])
    p.add_argument("--mslc", default=os.environ.get("MSLC", "mslc"))
    p.add_argument("--metalhost", default=os.environ.get("DIFFCHECK_METALHOST"))
    p.add_argument("--vkhost", default=os.environ.get("DIFFCHECK_VKHOST"))
    p.add_argument("--range", dest="ranges", action="append", default=[], metavar="BUFFER=LO:HI",
                   help="like // DIFFCHECK-RANGE, for a file you do not edit (repeatable)")
    p.add_argument("--timeout", type=int, default=hosts.TIMEOUT, help="seconds a host or compiler may run")
    p.add_argument("--jobs", type=int, default=1, help="files checked in parallel in --corpus mode")
    p.add_argument("--report", help="write the JSON report here")
    p.add_argument("--min-compared", type=int, default=0,
                   help="--corpus fails when fewer kernels than this were compared (guards against mslc "
                        "regressing to rejecting files, which otherwise only shows as skips)")
    p.add_argument("--keep", action="store_true", help="keep the scratch directory")
    p.add_argument("--corrupt-mslc", metavar="BUFFER:BYTE",
                   help="self-test hook: invert one byte of mslc's output before comparing")
    return p


def main(argv=None):
    opts = parser().parse_args(argv)
    hosts.TIMEOUT = opts.timeout
    opts.gfx_profiles = opts.profiles.split(",") if opts.profiles else ["moderate"]
    opts.profiles = (opts.profiles or ",".join(inputs.PROFILES)).split(",")
    if any(x not in inputs.PROFILES for x in opts.profiles):
        print("diffcheck: --profiles takes a list of %s" % ", ".join(inputs.PROFILES), file=sys.stderr)
        return ERROR
    try:
        opts.ranges = {n: (int(lo), int(hi)) for n, _, r in (x.partition("=") for x in opts.ranges)
                       for lo, hi in [r.split(":")]}
    except ValueError:
        print("diffcheck: --range wants BUFFER=LO:HI", file=sys.stderr)
        return ERROR
    for name in ("grid", "local", "cases", "elems", "jobs", "width", "height", "instances"):
        value = getattr(opts, name)
        if value is not None and value < 1:
            print("diffcheck: --%s must be at least 1" % name, file=sys.stderr)
            return ERROR
    if bool(opts.file) == bool(opts.corpus):
        print("diffcheck: give a file or --corpus list", file=sys.stderr)
        return ERROR
    try:
        opts.metal, opts.vk = hosts.metalhost(opts.metalhost), hosts.vkhost(opts.vkhost)
        if hostenv.find_lavapipe_icd() is None:
            raise hosts.Unavailable("no lavapipe ICD")
        if opts.corpus:
            root = opts.root or os.path.dirname(os.path.abspath(opts.corpus))
            results = run_files(opts, corpus_files(opts.corpus, root))
        else:
            results = run_files(opts, [(opts.file, None)])
    except hosts.Unavailable as e:
        print("SKIPPED: %s" % e)
        return hostenv.SKIP
    except hosts.HostError as e:
        print("diffcheck: %s" % e, file=sys.stderr)
        return ERROR
    if opts.report:
        hostenv.write_text(opts.report, json.dumps({"results": results}, indent=1))
    for r in results:
        print("%-17s %s::%s  %s" % (r["status"], r["file"], r["entry"], (r.get("reason") or "")[:160]))
    print(summary(results))
    statuses = {r["status"] for r in results}
    if not results:
        print("diffcheck: nothing to check", file=sys.stderr)
        return ERROR
    compared = sum(1 for r in results if r["status"] not in ("skipped", "error", "invalid"))
    if compared < opts.min_compared:
        print("diffcheck: %d compared, --min-compared wants %d" % (compared, opts.min_compared), file=sys.stderr)
        return MISMATCH
    if "error" in statuses:
        return ERROR
    if statuses <= {"matched"}:
        return OK
    if statuses <= {"skipped"}:
        return SKIPPED
    return OK if statuses <= {"matched", "skipped"} and opts.corpus else MISMATCH


if __name__ == "__main__":
    sys.exit(main())
