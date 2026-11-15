"""Comment directives a .metal file may carry for diffcheck.

  // RUN: grid=64 local=8 seed=1 cases=3 elems=256   run parameters for this file
  // DIFFCHECK: writes-zero                          every output is legitimately all zero
  // DIFFCHECK-RANGE: <buffer> <lo> <hi>             integer leaves of that buffer are drawn from lo..hi,
                                                     for a buffer the kernel uses as an index
  // DIFFCHECK-EXCLUDE: <buffer> <reason>            skip a buffer's comparison; the reason
                                                     is required and is printed in the report
"""

import re

RUN_KEYS = {"grid", "local", "seed", "cases", "elems"}


def parse(source):
    result = {"run": {}, "writes_zero": False, "exclude": {}, "range": {}}
    for line in source.splitlines():
        m = re.match(r"\s*//\s*RUN:\s*(.*)$", line)
        if m:
            for pair in m.group(1).split():
                key, _, value = pair.partition("=")
                if key not in RUN_KEYS or not value.isdigit() or int(value) < 1:
                    raise ValueError("bad RUN parameter %r (a positive number; keys: %s)" % (pair, ", ".join(sorted(RUN_KEYS))))
                result["run"][key] = int(value)
            continue
        m = re.match(r"\s*//\s*DIFFCHECK:\s*writes-zero\s*$", line)
        if m:
            result["writes_zero"] = True
            continue
        m = re.match(r"\s*//\s*DIFFCHECK-RANGE:\s*(\S+)\s+(-?\d+)\s+(-?\d+)\s*$", line)
        if m:
            lo, hi = int(m.group(2)), int(m.group(3))
            if lo > hi:
                raise ValueError("DIFFCHECK-RANGE %s: %d > %d" % (m.group(1), lo, hi))
            result["range"][m.group(1)] = (lo, hi)
            continue
        m = re.match(r"\s*//\s*DIFFCHECK-EXCLUDE:\s*(\S+)\s*(.*)$", line)
        if m:
            if not m.group(2).strip():
                raise ValueError("DIFFCHECK-EXCLUDE %s needs a reason" % m.group(1))
            result["exclude"][m.group(1)] = m.group(2).strip()
    return result
