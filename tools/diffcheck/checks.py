"""Checks the driver applies around a comparison: reflection cross-check, the negative
control's perturbation, and the "something was actually written" test."""

import compare
import json


def cross_check(mslc_buffers, apple):
    """Findings where mslc's reflection and Apple's disagree about the buffers."""
    findings = []
    by_index = {b["index"]: b for b in apple["buffers"]}
    for b in mslc_buffers:
        a = by_index.get(b["metal_index"])
        if a is None:
            findings.append("mslc binds buffer(%d) %s, Apple's reflection has no buffer at that index" % (b["metal_index"], b["name"]))
        elif a["name"] != b["name"]:
            findings.append("buffer(%d) is %s in mslc and %s in Apple" % (b["metal_index"], b["name"], a["name"]))
    extra = set(by_index) - {b["metal_index"] for b in mslc_buffers}
    for i in sorted(extra):
        findings.append("Apple reflects buffer(%d) %s, mslc does not bind it" % (i, by_index[i]["name"]))
    return findings


def perturb(layouts, outputs):
    """A copy of `outputs` with one leaf made different, for the negative control.
    Returns (copy, buffer, offset), or None when no buffer has a leaf to change."""
    for index, layout in sorted(layouts.items()):
        if layout["access"] == "read" or not layout["leaves"] or not outputs[index]:
            continue
        leaf = layout["leaves"][0]
        size = compare.SCALARS[leaf["scalar"]][0]
        raw = bytes(outputs[index][leaf["off"]:leaf["off"] + size])
        if compare.SCALARS[leaf["scalar"]][1] == "float" and compare.is_nan(raw, leaf["scalar"]):
            new = struct_one(leaf["scalar"])
        else:
            new = bytes([raw[0] ^ 1]) + raw[1:]
        copy = {i: bytearray(o) for i, o in outputs.items()}
        copy[index][leaf["off"]:leaf["off"] + size] = new
        return copy, layout["name"], leaf["off"]
    return None


def struct_one(scalar):
    return bytes.fromhex("0000803f") if scalar == "float" else bytes.fromhex("003c")


def written_nonzero(layouts, before, after):
    """True when some leaf of a writable buffer changed to a non-zero value. Counting only
    changed leaves keeps untouched input elements from making a kernel that writes zeros
    (or nothing) look like it produced output."""
    for index, layout in layouts.items():
        if layout["access"] == "read":
            continue
        for element in range(len(after[index]) // max(layout["stride"], 1)):
            for leaf in layout["leaves"]:
                size = compare.SCALARS[leaf["scalar"]][0]
                at = element * layout["stride"] + leaf["off"]
                new = bytes(after[index][at:at + size])
                if any(new) and new != bytes(before[index][at:at + size]):
                    return True
    return False


def verdict(cases, nonzero, writes_zero):
    """(status, reason) for the cases of one kernel. A control that did not fire outranks a
    match, because a comparison that cannot fail proves nothing."""
    if any(not c["negative_control"] for c in cases):
        return "control-failed", "the perturbed copy compared equal to Apple's output, or nothing could be perturbed"
    first = next((c for c in cases if c["diff_count"]), None)
    if first:
        return "mismatched", "first difference: %s" % json.dumps(first["diffs"][0])
    if not nonzero and not writes_zero:
        return "zero-output", ("no output leaf was written to a non-zero value on either backend "
                               "(declare `// DIFFCHECK: writes-zero` if that is right)")
    return "matched", None
