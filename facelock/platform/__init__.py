from facelock.platform.linux import LinuxBackend


def get_backend():
    """Only Linux is implemented today. Windows/macOS backends will slot in here later."""
    return LinuxBackend()
