"""Graphics mode: a vertex and a fragment function drawn into offscreen targets on both
backends, the targets read back and compared per pixel.

One fixed draw: a triangle list (DEFAULT_GEOMETRY or // DIFFCHECK-GEOMETRY, in pixel
coordinates) with `instances` instances into float or integer colour targets chosen from the
fragment's output types, plus a depth target when the fragment writes depth or the file says
`// DIFFCHECK: depth`. Everything stays inside the target: lavapipe returns NaN for
noperspective varyings on a guard-band-clipped triangle, and Apple clips differently.

Vertex data: the field named by // DIFFCHECK-POSITION carries the geometry (w = 1); every other
stage_in field, [[buffer]] argument and texture is seeded like a kernel's buffers. One tightly
packed vertex buffer per attribute; the Metal vertex descriptor and the Vulkan one use the
same bytes. A runtime sampler is nearest, clamp-to-edge, normalised coordinates, no mips.
Textures are 4x4 RGBA32Float.

Both hosts get one manifest body (graphics_manifest); Apple's gets the source lines, Vulkan's
the SPIR-V. Attachments are compared with compare.compare as if they were buffers named
color0, color1, ... and depth.
"""

import os
import random
import struct

import checks
import compare
import hostenv
import hosts
import inputs
import spirvio

# (host format name, scalar of the attachment) per fragment output scalar.
COLOR_FORMATS = {"float": "rgba32float", "int": "rgba32sint", "uint": "rgba32uint", "half": "rgba16float"}
# Clear values no plausible shader output equals, so "a pixel changed" means "a pixel was drawn".
CLEAR = {"float": (-1.5, -2.5, -3.5, -4.5), "half": (-1.5, -2.5, -3.5, -4.5),
         "int": (-12345, 54321, -777, 31), "uint": (123456, 654321, 77777, 4242)}
DEPTH_CLEAR = 0.375
DEPTH_INDEX = 100
# Interpolated floats: barycentric interpolation is not specified to the bit. Absolute epsilon
# because a ULP bound is useless near zero; measured on the probes, then rounded up.
INTERP_ULP, INTERP_EPS = 32, 1e-5
DEPTH_EPS = 1e-6
SLOT_TOP = 30  # attribute at location n is vertex buffer slot 30 - n, away from [[buffer(n)]] arguments
MAX_COLOR = 8
TEXTURE_SIZE = 4
DEFAULT_SIZE, DEFAULT_ELEMS = 32, 64
# Pixel coordinates of 32x32. Three shapes; no edge passes through a pixel centre (checked by
# hand: the slopes 1/2, 13/18 and 3/26 never meet k + 0.5), so top-left fill rules cannot
# make the backends disagree about a covered pixel.
DEFAULT_GEOMETRY = [(2, 3, .5), (22, 3, .5), (22, 13, .5), (2, 3, .5), (22, 13, .5), (2, 13, .5),
                    (3, 16, .5), (21, 16, .5), (21, 29, .5), (3, 16, .5), (21, 29, .5), (3, 29, .5),
                    (24, 2, .5), (30, 2, .5), (27, 28, .5)]


class GraphicsError(Exception):
    """The file cannot be drawn as asked; reported as an error, not a skip."""


def ndc(point, width, height):
    x, y, z = point
    return 2 * x / width - 1, 1 - 2 * y / height, z


def check_geometry(points, width, height):
    if not points or len(points) % 3:
        raise GraphicsError("DIFFCHECK-GEOMETRY needs a multiple of 3 points, got %d" % len(points))
    for x, y, z in points:
        if not (0 < x < width and 0 < y < height and 0 <= z <= 1):
            raise GraphicsError("geometry point %g,%g,%g is not strictly inside the %dx%d target "
                                "(clipped geometry differs between the backends)" % (x, y, z, width, height))


def format_name(scalar, comps):
    return scalar if comps == 1 else "%s%d" % (scalar, comps)


def attachment_layout(name, scalar, comps):
    size = compare.SCALARS[scalar][0]
    return {"name": name, "stride": 4 * size, "access": "readwrite",
            "leaves": [{"off": i * size, "scalar": scalar} for i in range(comps)]}


def clear_image(scalar, pixels):
    fmt = "<f" if scalar == "float" else "<e" if scalar == "half" else "<i" if scalar == "int" else "<I"
    return bytearray(b"".join(struct.pack(fmt, v) for v in CLEAR[scalar]) * pixels)


def vertex_data(attributes, points, position, width, height, rng, profile):
    """{location: bytes}: one tightly packed array per attribute, `len(points)` vertices."""
    data = {}
    for location, a in sorted(attributes.items()):
        size = compare.SCALARS[a["scalar"]][0]
        out = bytearray()
        for p in points:
            if a["name"] == position:
                x, y, z = ndc(p, width, height)
                out += b"".join(struct.pack("<f", v) for v in (x, y, z, 1.0)[:a["comps"]])
            else:
                for _ in range(a["comps"]):
                    out += inputs.leaf_bits(rng, a["scalar"], profile).to_bytes(size, "little")
        data[location] = out
    return data


def texture_data(rng, profile):
    return bytearray(b"".join(inputs.leaf_bits(rng, "float", profile).to_bytes(4, "little")
                              for _ in range(4 * TEXTURE_SIZE * TEXTURE_SIZE)))


def tolerance(source_ulp, interpolated, scalar):
    """(ulp, eps) for one attachment: exact for integers and flat floats."""
    if compare.SCALARS[scalar][1] != "float" or not interpolated:
        return source_ulp, 0.0
    return max(source_ulp, INTERP_ULP), INTERP_EPS
