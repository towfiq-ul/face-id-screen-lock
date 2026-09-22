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


def _verify_frame(
    frame: np.ndarray,
    engine: FaceEngine,
    known_embeddings: np.ndarray,
    config: cfg.Config,
    liveness_tracker: LivenessTracker,
) -> bool:
    """Detect and authenticate face with anti-spoof checks."""
    face = engine.best_face(frame)
    if face is None:
        liveness_tracker.reset()
        return False

    embedding = engine.embed(frame, face)
    landmarks = face[4:14]
    seen_known, _score = engine.matches_any(
        embedding, known_embeddings, landmarks=landmarks
    )
    if not seen_known:
        return False

    if config.liveness_enabled:
        if config.texture_anti_spoof_enabled:
            is_tex_live, tex_score = check_texture_liveness(
                frame, face[:4], min_laplacian_var=config.min_laplacian_var
            )
            if not is_tex_live:
                logger.warning("Anti-spoof: face texture check failed (score=%.1f)", tex_score)
                return False

        if config.cranial_liveness_enabled:
            is_cranial_3d, err = check_3d_cranial_consistency(
                landmarks, frame.shape, mirrored=False
            )
            if not is_cranial_3d:
                logger.warning("Anti-spoof: 3D cranial structure invalid (err=%.2f)", err)
                return False

        if config.blink_detection_enabled:
            liveness_tracker.update_eyes(frame, landmarks)
        pose = estimate_head_pose(landmarks, frame.shape)
        if pose is not None:
            liveness_tracker.add_pose(*pose)
        is_live, reason = liveness_tracker.evaluate()
        if not is_live:
            logger.warning("Anti-spoof: %s", reason)
            return False

    return True


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

    idle_enabled = config.idle_detection_enabled
    idle_timeout = config.idle_timeout_seconds        # default 120s (2 min)
    check_window = config.face_check_window_seconds   # default 30s
    checking_started_time: float | None = None
    snooze_until: float = 0.0
    last_seen_known = time.monotonic()

    logger.info(
        "Monitor started (idle_check=%s, idle_timeout=%.0fs, check_window=%.0fs, interval=%.1fs)",
        idle_enabled,
        idle_timeout,
        check_window,
        config.check_interval_seconds,
    )

    try:
        while True:
            now = time.monotonic()

            if backend.is_locked():
                camera.release()
                liveness_tracker.reset()
                checking_started_time = None
                snooze_until = 0.0
                last_seen_known = now
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

            # Query input idle time across mouse, keyboard, touchpad, touchscreen
            idle_sec = backend.get_idle_seconds() if idle_enabled else None

            # -------------------------------------------------------------
            # Mode 1: Smart Idle-Triggered Camera Check
            # -------------------------------------------------------------
            if idle_sec is not None:
                # 1. User active (< 120s idle): keep camera completely OFF
                if idle_sec < idle_timeout:
                    if checking_started_time is not None:
                        logger.info(
                            "User interaction detected (idle=%.1fs). Aborting check and turning off camera.",
                            idle_sec,
                        )
                    camera.release()
                    liveness_tracker.reset()
                    checking_started_time = None
                    snooze_until = 0.0
                    last_seen_known = now
                    sleep_time = min(config.check_interval_seconds, max(0.5, idle_timeout - idle_sec))
                    time.sleep(sleep_time)
                    continue

                # 2. User idle >= 120s, but recently verified (snooze period active)
                if now < snooze_until:
                    camera.release()
                    time.sleep(config.check_interval_seconds)
                    continue

                # 3. User idle >= 120s: Turn on camera and verify footage
                if checking_started_time is None:
                    checking_started_time = now
                    logger.info(
                        "No user interaction for %.0fs (>= %.0fs). Turning on camera to verify presence...",
                        idle_sec,
                        idle_timeout,
                    )

                frame = camera.read()
                seen_known = False
                if frame is not None:
                    seen_known = _verify_frame(
                        frame, engine, known_embeddings, config, liveness_tracker
                    )

                if seen_known:
                    # Matching face verified: Take NO action, release camera, snooze next check
                    logger.info(
                        "Authorized face verified in front of screen. Keeping session unlocked (idle=%.0fs).",
                        idle_sec,
                    )
                    camera.release()
                    liveness_tracker.reset()
                    checking_started_time = None
                    snooze_until = now + check_window
                    time.sleep(config.check_interval_seconds)
                    continue

                # No matching face on this tick: check if 30s window has expired
                elapsed_checking = now - checking_started_time
                if elapsed_checking >= check_window:
                    logger.info(
                        "No authorized face detected after %.0fs check window (idle %.0fs). Executing screen lock.",
                        elapsed_checking,
                        idle_sec,
                    )
                    camera.release()
                    backend.lock()
                    checking_started_time = None
                    snooze_until = 0.0
                    time.sleep(config.check_interval_seconds)
                    continue
                else:
                    time.sleep(config.check_interval_seconds)
                    continue

            # -------------------------------------------------------------
            # Mode 2: Fallback Continuous Checking (if idle is unsupported)
            # -------------------------------------------------------------
            frame = camera.read()
            seen_known = False
            if frame is not None:
                seen_known = _verify_frame(
                    frame, engine, known_embeddings, config, liveness_tracker
                )

            if seen_known:
                last_seen_known = now
            elif now - last_seen_known >= config.unknown_face_timeout_seconds:
                logger.info(
                    "Known face not seen for %.0fs, locking session", now - last_seen_known
                )
                camera.release()
                backend.lock()
                last_seen_known = now

            time.sleep(config.check_interval_seconds)
    except _Stop:
        logger.info("Monitor stopping")
    finally:
        camera.release()
