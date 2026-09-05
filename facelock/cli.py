"""Entry points registered in pyproject.toml."""

from __future__ import annotations

import logging


def enroll_main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from facelock.enroll import enroll

    enroll()


def monitor_main() -> None:
    from facelock.monitor import run

    run()
