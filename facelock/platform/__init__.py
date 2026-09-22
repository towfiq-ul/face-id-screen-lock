"""Linux platform backend dispatcher for FaceLock."""

from __future__ import annotations

from facelock.platform.base import Backend
from facelock.platform.linux import LinuxBackend


def get_backend() -> Backend:
    """Return platform backend (Linux)."""
    return LinuxBackend()

