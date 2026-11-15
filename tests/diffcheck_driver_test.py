#!/usr/bin/env python3
"""End-to-end test of tools/diffcheck/diffcheck.py: the real Apple compiler and GPU against
mslc's SPIR-V on lavapipe. Exits 77 (ctest SKIP) when either side is unavailable.

usage: diffcheck_driver_test.py <mslc> <metalhost> <vkhost>
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

mslc, metalhost, vkhost = sys.argv[1:4]
DRIVER = os.path.join(HERE, "..", "tools", "diffcheck", "diffcheck.py")


def kernel(name):
    return os.path.join(HERE, "diffcheck", name)


def run(name, *extra):
    report = tempfile.mktemp(suffix=".json")
    r = subprocess.run([sys.executable, DRIVER, kernel(name), "--mslc", mslc, "--metalhost", metalhost,
                        "--vkhost", vkhost, "--report", report, *extra], capture_output=True, text=True)
    data = json.load(open(report)) if os.path.exists(report) else None
    return r.returncode, r.stdout, data


rc, out, data = run("fma_kernel.metal")
if rc == 77:
    print(out)
    sys.exit(77)
assert rc == 0 and data["results"][0]["status"] == "matched", (rc, out)
assert all(c["negative_control"] for c in data["results"][0]["cases"])
assert [c["profile"] for c in data["results"][0]["cases"]] == ["moderate", "wide", "edge"]

rc, out, data = run("struct_kernel.metal", "--sentinel", "--poison-padding")
assert rc == 0, out
assert data["results"][0]["cases"][-1]["profile"] == "sentinel"

# A difference between the backends is reported with the buffer, byte offset and both values.
rc, out, data = run("fma_kernel.metal", "--corrupt-mslc", "o:8")
assert rc == 1 and data["results"][0]["status"] == "mismatched", (rc, out)
diff = data["results"][0]["cases"][0]["diffs"][0]
assert (diff["buffer"], diff["offset"]) == ("o", 8) and diff["apple_hex"] != diff["mslc_hex"], diff

# Zero output on both backends fails unless the file declares it.
rc, out, data = run("zero_kernel.metal")
assert rc == 1 and data["results"][0]["status"] == "zero-output", (rc, out)
rc, out, data = run("zero_declared_kernel.metal")
assert rc == 0, out

# A texture argument is not compared; it is skipped with the reason, not passed.
rc, out, data = run("texture_kernel.metal")
assert rc == 3 and "unsupported binding kind: Texture" in data["results"][0]["reason"], (rc, out)

# A kernel that does not exist is skipped, not matched.
rc, out, data = run("fma_kernel.metal", "--entry", "nope")
assert rc == 3, (rc, out)
# An index buffer drawn from its declared range is read in bounds on both sides.
rc, out, data = run("range_kernel.metal")
assert rc == 0 and data["results"][0]["status"] == "matched", (rc, out)

# Corpus mode: a table with a summary; skips do not fail the run, a mismatch does.
with tempfile.TemporaryDirectory() as d:
    listing = os.path.join(d, "list.txt")
    open(listing, "w").write("# comment\n%s\n%s std=3.1\n%s\n%s\n%s\n" % (
        kernel("fma_kernel.metal"), kernel("struct_kernel.metal"), kernel("texture_kernel.metal"),
        os.path.join(d, "missing.metal"), kernel("zero_declared_kernel.metal")))
    open(os.path.join(d, "missing.metal"), "w").write("kernel void k() { nope(); }\n")
    report = os.path.join(d, "r.json")
    base = [sys.executable, DRIVER, "--corpus", listing, "--mslc", mslc, "--metalhost", metalhost,
            "--vkhost", vkhost, "--report", report]
    r = subprocess.run(base, capture_output=True, text=True)
    assert r.returncode == 0, r
    assert "5 kernels: 3 compared, 3 matched, 2 skipped" in r.stdout, r.stdout
    reasons = {os.path.basename(x["file"]): x["reason"] for x in json.load(open(report))["results"] if x["status"] == "skipped"}
    assert "unsupported binding kind: Texture" in reasons["texture_kernel.metal"], reasons
    assert "nope" in reasons["missing.metal"] or "mslc" in reasons["missing.metal"], reasons
    open(listing, "a").write("%s\n" % kernel("zero_kernel.metal"))
    r = subprocess.run(base, capture_output=True, text=True)
    assert r.returncode == 1 and "1 zero-output" in r.stdout, r
print("PASS")
