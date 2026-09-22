#!/usr/bin/env python3
"""Desktop Entry and Icon Theme Installer CLI for FaceLock."""

from __future__ import annotations

from pathlib import Path
import sys

# Ensure facelock can be imported even if running uninstalled
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from facelock.desktop import main

if __name__ == "__main__":
    sys.exit(main())
