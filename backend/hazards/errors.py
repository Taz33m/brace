"""The one exception type the hazards package raises on purpose."""
from __future__ import annotations


class HazardError(RuntimeError):
    """A hazard source could not be reached, or returned something unusable.

    Every network-backed function in this package either raises this (with a
    message that names the source) or returns an "unknown" value. Nothing hangs:
    all requests carry timeouts.
    """
