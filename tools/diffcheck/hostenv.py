"""Locating the pieces diffcheck needs outside the repo."""

import glob
import os
import shutil

SKIP = 77  # ctest SKIP_RETURN_CODE


def find_lavapipe_icd():
    """The lavapipe ICD manifest, or None. VK_ICD_FILENAMES wins when it names a file."""
    explicit = os.environ.get("VK_ICD_FILENAMES", "")
    for path in explicit.split(os.pathsep):
        if path and os.path.isfile(path) and "lvp" in os.path.basename(path):
            return path
    roots = [os.path.join(os.environ.get("HOMEBREW_PREFIX", "/opt/homebrew"), "share/vulkan/icd.d"),
             "/usr/local/share/vulkan/icd.d", "/usr/share/vulkan/icd.d", "/etc/vulkan/icd.d"]
    for root in roots:
        found = sorted(glob.glob(os.path.join(root, "lvp_icd*.json")))
        if found:
            return found[0]
    return None


def vulkan_env():
    """os.environ with the loader pointed at lavapipe only (never a hardware ICD)."""
    icd = find_lavapipe_icd()
    if icd is None:
        return None
    env = dict(os.environ)
    env["VK_ICD_FILENAMES"] = icd
    return env


def have_tool(name):
    return shutil.which(name) is not None
