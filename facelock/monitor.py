"""Background loop: locks the screen if the enrolled face hasn't been seen for too long.

Deliberately does nothing on the unlock side — that's handled entirely by
Howdy's own PAM integration, installed separately. This also means the
camera is only ever held open by one process at a time: this monitor
releases it as soon as the session is locked.
"""

from __future__ import annotations

import logging
import signal
import time

import numpy as np

from facelock import config as cfg
from facelock.camera import Camera
from facelock.face_engine import FaceEngine
from facelock.platform import get_backend

logger = logging.getLogger(__name__)


class _Stop(Exception):
    pass


def _raise_stop(signum, frame):
    raise _Stop()


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not cfg.KNOWN_FACE_PATH.exists():
        raise SystemExit(
            f"No enrolled face found at {cfg.KNOWN_FACE_PATH}. Run `facelock-enroll` first."
        )

    config = cfg.Config.load()
    known_embeddings = np.load(cfg.KNOWN_FACE_PATH)
    engine = FaceEngine(config)
    backend = get_backend()
    camera = Camera(config.camera_index)

    signal.signal(signal.SIGTERM, _raise_stop)
    signal.signal(signal.SIGINT, _raise_stop)

    last_seen_known = time.monotonic()
    logger.info(
        "Monitor started (timeout=%ss, interval=%ss)",
        config.unknown_face_timeout_seconds,
        config.check_interval_seconds,
    )

    try:
        while True:
            if backend.is_locked():
                camera.release()
                # Reset so we don't immediately re-lock the instant it's unlocked.
                last_seen_known = time.monotonic()
                time.sleep(config.check_interval_seconds)
                continue

            frame = camera.read()
            seen_known = False
            if frame is not None:
                face = engine.best_face(frame)
                if face is not None:
                    embedding = engine.embed(frame, face)
                    seen_known, _score = engine.matches_any(embedding, known_embeddings)

            now = time.monotonic()
            if seen_known:
                last_seen_known = now
            elif now - last_seen_known >= config.unknown_face_timeout_seconds:
                logger.info(
                    "Known face not seen for %.0fs, locking session", now - last_seen_known
                )
                backend.lock()
                last_seen_known = now  # avoid spamming lock-session every tick

            time.sleep(config.check_interval_seconds)
    except _Stop:
        logger.info("Monitor stopping")
    finally:
        camera.release()
