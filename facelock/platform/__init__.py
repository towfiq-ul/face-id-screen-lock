import sys

from facelock.platform.base import Backend


def get_backend() -> Backend:
    """Return platform-specific backend."""
    if sys.platform == "darwin":
        from facelock.platform.macos import MacOSBackend

        return MacOSBackend()

    from facelock.platform.linux import LinuxBackend

    return LinuxBackend()
