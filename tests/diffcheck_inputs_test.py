#!/usr/bin/env python3
"""Unit tests for tools/diffcheck/inputs.py and directives.py. No GPU needed."""

import os
import random
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "diffcheck"))
import directives  # noqa: E402
import inputs  # noqa: E402

LAYOUT = {"name": "b", "stride": 16, "leaves": [
    {"off": 0, "scalar": "float"}, {"off": 4, "scalar": "uint"},
    {"off": 8, "scalar": "bool"}, {"off": 10, "scalar": "half"}]}


def make(profile, seed=1, **kw):
    return inputs.fill_buffer(LAYOUT, 400, random.Random(seed), profile, **kw)


class Fill(unittest.TestCase):
    def test_same_seed_same_bytes(self):
        self.assertEqual(make("edge"), make("edge"))
        self.assertNotEqual(make("edge", 1), make("edge", 2))

    def test_bool_is_only_zero_or_one(self):
        for profile in inputs.PROFILES:
            data = make(profile)
            self.assertLessEqual({data[i * 16 + 8] for i in range(400)}, {0, 1}, profile)
            self.assertEqual({data[i * 16 + 9] for i in range(400)}, {0})

    def test_edge_profile_reaches_nan_inf_and_int_min(self):
        data = make("edge")
        floats = [struct.unpack_from("<I", data, i * 16)[0] for i in range(400)]
        self.assertIn(0x7fc00000, floats)
        self.assertIn(0x7f800000, floats)
        self.assertIn(0x80000000, [struct.unpack_from("<I", data, i * 16 + 4)[0] for i in range(400)])

    def test_wide_and_moderate_floats_are_finite(self):
        for profile in ("moderate", "wide"):
            data = make(profile)
            for i in range(400):
                f = struct.unpack_from("<f", data, i * 16)[0]
                self.assertEqual(f, f)
                self.assertNotIn(abs(f), (float("inf"),))

    def test_padding_zero_or_poisoned(self):
        self.assertEqual(make("moderate")[12], 0)
        self.assertEqual(make("moderate", poison_padding=True)[12], inputs.POISON)

    def test_sentinel_fills_every_byte(self):
        data = make("edge", sentinel=True)
        self.assertEqual(set(data), {0x7f})
        self.assertEqual(len(data), 400 * 16)


class Bounds(unittest.TestCase):
    def test_integer_leaves_stay_in_range_and_floats_are_untouched(self):
        for profile in inputs.PROFILES:
            data = make(profile, bounds=(0, 3))
            self.assertLessEqual({struct.unpack_from("<I", data, i * 16 + 4)[0] for i in range(400)}, {0, 1, 2, 3}, profile)
        floats = {struct.unpack_from("<I", make("wide", bounds=(0, 3)), i * 16)[0] for i in range(400)}
        self.assertGreater(len(floats), 100)


class Directives(unittest.TestCase):
    def test_parse(self):
        d = directives.parse("// RUN: grid=64 seed=2\n// DIFFCHECK: writes-zero\n// DIFFCHECK-RANGE: which 0 3\n"
                             "// DIFFCHECK-EXCLUDE: scratch reads uninitialised memory\nkernel void k() {}\n")
        self.assertEqual(d, {"run": {"grid": 64, "seed": 2}, "writes_zero": True,
                             "exclude": {"scratch": "reads uninitialised memory"},
                             "range": {"which": (0, 3)}})

    def test_exclusion_without_a_reason_is_an_error(self):
        with self.assertRaises(ValueError):
            directives.parse("// DIFFCHECK-EXCLUDE: scratch\n")

    def test_empty_range_is_an_error(self):
        with self.assertRaises(ValueError):
            directives.parse("// DIFFCHECK-RANGE: which 5 2\n")

    def test_unknown_run_key_is_an_error(self):
        with self.assertRaises(ValueError):
            directives.parse("// RUN: gird=64\n")


if __name__ == "__main__":
    unittest.main()
