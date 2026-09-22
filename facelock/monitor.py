"""Background loop: locks the screen if the enrolled face hasn't been seen for too long.

Releases the camera as soon as the session is locked so that the PAM unlock
authenticator has unobstructed access to the camera hardware.
"""

from __future__ import annotations

import logging
import signal
import time

from facelock import config as cfg
from facelock.camera import Camera
from facelock.face_engine import FaceEngine
from facelock.liveness import (
    LivenessTracker,
    check_3d_cranial_consistency,
    check_texture_liveness,
    estimate_head_pose,
)
from facelock.platform import get_backend

logger = logging.getLogger(__name__)


class _Stop(Exception):
    pass


def _raise_stop(signum, frame):
    raise _Stop()


def _get_meta_mtime() -> float:
    from facelock import profiles

    try:
        return profiles.PROFILES_META_PATH.stat().st_mtime
    except OSError:
        return 0.0


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from facelock import profiles

    known_embeddings = profiles.get_combined_embeddings()
    if known_embeddings is None:
        raise SystemExit(
            "No enrolled face profiles found. Run `facelock-gui` or `facelock-enroll` first."
        )

    last_meta_mtime = _get_meta_mtime()
    config = cfg.Config.load()
    engine = FaceEngine(config)
    backend = get_backend()
    camera = Camera(config.camera_index)
    liveness_tracker = LivenessTracker(
        window_size=config.liveness_window_size,
        min_pose_variance=config.liveness_min_pose_variance,
        blink_enabled=config.blink_detection_enabled,
        blink_close_ratio=config.blink_close_ratio,
        blink_min_duration=config.blink_min_duration,
        blink_min_frames=config.blink_min_frames,
    )

    signal.signal(signal.SIGTERM, _raise_stop)
    signal.signal(signal.SIGINT, _raise_stop)

    last_seen_known = time.monotonic()
    logger.info(
        "Monitor started (timeout=%ss, interval=%ss, liveness=%s)",
        config.unknown_face_timeout_seconds,
        config.check_interval_seconds,
        config.liveness_enabled,
    )

    try:
        while True:
            if backend.is_locked():
                camera.release()
                liveness_tracker.reset()
                # Reset so we don't immediately re-lock the instant it's unlocked.
                last_seen_known = time.monotonic()
                time.sleep(config.check_interval_seconds)
                continue
            # Check for profile updates on disk
            current_mtime = _get_meta_mtime()
            if current_mtime != last_meta_mtime:
                updated_embeddings = profiles.get_combined_embeddings()
                if updated_embeddings is not None:
                    known_embeddings = updated_embeddings
                    logger.info("Face profiles reloaded dynamically from disk")
                last_meta_mtime = current_mtime

            frame = camera.read()
            seen_known = False
            if frame is not None:
                face = engine.best_face(frame)
                if face is not None:
                    embedding = engine.embed(frame, face)
                    landmarks = face[4:14]
                    seen_known, _score = engine.matches_any(
                        embedding, known_embeddings, landmarks=landmarks
                    )

                    if seen_known and config.liveness_enabled:
                        if config.texture_anti_spoof_enabled:
                            is_tex_live, tex_score = check_texture_liveness(
                                frame, face[:4], min_laplacian_var=config.min_laplacian_var
                            )
                            if not is_tex_live:
                                logger.warning("Anti-spoof: face texture check failed (score=%.1f)", tex_score)
                                seen_known = False

                        if seen_known and config.cranial_liveness_enabled:
                            is_cranial_3d, err = check_3d_cranial_consistency(landmarks, frame.shape, mirrored=False)
                            if not is_cranial_3d:
                                logger.warning("Anti-spoof: 3D cranial structure invalid (err=%.2f)", err)
                                seen_known = False

                        if seen_known:
                            if config.blink_detection_enabled:
                                liveness_tracker.update_eyes(frame, landmarks)
                            pose = estimate_head_pose(landmarks, frame.shape)
                            if pose is not None:
                                liveness_tracker.add_pose(*pose)
                            is_live, reason = liveness_tracker.evaluate()
                            if not is_live:
                                logger.warning("Anti-spoof: %s", reason)
                                seen_known = False
                else:
                    liveness_tracker.reset()

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
