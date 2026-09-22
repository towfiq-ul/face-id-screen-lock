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


def gui_main() -> None:
    from facelock.gui import launch_gui

    launch_gui()


def calibrate_main() -> None:
    from facelock.calibrate import main

    main()


def test_main() -> None:
    from facelock.test_face import main

    main()


def remove_main() -> None:
    from facelock.profiles import cli_main

    cli_main()


def auth_main() -> None:
    from facelock.auth import main

    main()


def pam_main() -> None:
    from facelock.pam import main

    main()

