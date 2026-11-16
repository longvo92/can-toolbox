"""Numba compilation settings shared by the log kernels.

Kernels release the GIL so the GUI stays responsive while a worker thread
scans a log. The on-disk cache is used from a source checkout only: a frozen
executable has no source files for Numba to key its cache on.
"""

from __future__ import annotations

import sys

from numba import njit as _njit

_CACHE = not getattr(sys, "frozen", False)


def njit(function):
    return _njit(cache=_CACHE, nogil=True)(function)
