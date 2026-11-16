"""Textures and samplers as both modes feed them: the same seeded texels on both sides, bound by
Apple's index and by the set and binding of mslc's reflection.

A texture is 2D, RGBA32Float, shader-read; a sampler is nearest, normalised, no mips, with an
address mode picked by its Metal index (0 clamp to edge, 1 repeat, 2 mirrored repeat). Probes should sample at a texel centre (an edge or a filter is where the backends may
legitimately differ). Anything else is reported by `unsupported` and the file is skipped.
"""

import hostenv
import inputs

TEXTURE_SIZE = 4
READABLE = {"Sample", "Read"}


def texture_data(rng, profile):
    return bytearray(b"".join(inputs.leaf_bits(rng, "float", profile).to_bytes(4, "little")
                              for _ in range(4 * TEXTURE_SIZE * TEXTURE_SIZE)))


def cross_check(bindings, apple, label=""):
    """Findings where mslc's texture and sampler bindings differ from Apple's by index or name."""
    findings = []
    for kind, key in (("Texture", "textures"), ("Sampler", "samplers")):
        # An embedded sampler has no Metal index (and is skipped by `unsupported` before this runs).
        mine = sorted((b["metal_index"], b["name"]) for b in bindings if b["kind"] == kind and "metal_index" in b)
        theirs = sorted((t["index"], t["name"]) for t in apple[key])
        if mine != theirs:
            findings.append("%s%s bindings differ: mslc %s, Apple %s" % (label, kind.lower(), mine, theirs))
    return findings


def threadgroup_cross_check(threadgroups, apple):
    """Findings where mslc's ThreadgroupMemory bindings differ from Apple's threadgroup arguments by
    index, name or element size."""
    mine = sorted((b["metal_index"], b["name"], b["element_size"]) for b in threadgroups)
    theirs = sorted((t["index"], t["name"], t["size"]) for t in apple["threadgroups"])
    return [] if mine == theirs else ["threadgroup arguments differ: mslc %s, Apple %s" % (mine, theirs)]


def threadgroup_lines(threadgroups, local, backend):
    """Manifest lines giving every threadgroup argument room for one element per thread of the group:
    Apple's setThreadgroupMemoryLength takes the bytes (a multiple of 16, so rounded up), and mslc's reflection says the Vulkan side is
    the element count in the argument's spec constant (bytes / element_size)."""
    if backend == "apple":
        return ["threadgroup %d %d" % (b["metal_index"], -(-local * b["element_size"] // 16) * 16) for b in threadgroups]
    return ["spec %d %d" % (b["spec_id"], local) for b in threadgroups]


def unsupported(entry, apple):
    """Reasons this entry point's textures and samplers cannot be fed (empty: they can)."""
    reasons = ["texture %s access %s" % (b["name"], b.get("texture_access")) for b in entry["bindings"]
               if b["kind"] == "Texture" and b.get("texture_access") not in READABLE]
    reasons += ["texture %s is not a 2D float texture" % t["name"] for t in apple["textures"]
                if t["type"] != "2d" or t["data"] != "float"]
    reasons += ["texture %s is written (Apple access %s)" % (t["name"], t["access"]) for t in apple["textures"]
                if t["access"] != "read"]
    embedded = entry["embedded_samplers"] or [b for b in entry["bindings"] if "embedded_sampler" in b]
    return reasons + (["embedded samplers"] if embedded else [])


def seed(bindings, rng, profile, base):
    """Writes one texture file per Texture binding to `base`+name and returns the manifest
    tuples ([(index, set, binding, file, access)], [(index, set, binding)]), in binding order;
    `access` is mslc's texture_access: a `Read` texture is a storage image in SPIR-V, the rest are sampled."""
    textures, samplers = [], []
    for b in bindings:
        if b["kind"] == "Texture":
            path = "%stex%d.bin" % (base, b["metal_index"])
            hostenv.write_bytes(path, texture_data(rng, profile))
            textures.append((b["metal_index"], b["descriptor"]["set"], b["descriptor"]["binding"], path, b["texture_access"]))
        elif b["kind"] == "Sampler":
            samplers.append((b["metal_index"], b["descriptor"]["set"], b["descriptor"]["binding"]))
    return textures, samplers


def lines(textures, samplers):
    """The manifest lines both hosts read."""
    return (["%s %d %d %d %d %d %s" % ("storagetexture" if a == "Read" else "texture", i, s, b, TEXTURE_SIZE, TEXTURE_SIZE, f)
             for i, s, b, f, a in textures]
            + ["sampler %d %d %d" % s for s in samplers])
