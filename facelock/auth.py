"""FaceLock PAM Biometric Authenticator for screen unlock and sudo.

Invoked by PAM via pam_exec.so (e.g. in /etc/pam.d/gdm-password or /etc/pam.d/sudo).
Exits with code 0 on verified biometric match, or code 1 on timeout/mismatch.
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import logging.handlers
import os
import pwd
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import yaml

from facelock import config as cfg
from facelock.camera import Camera
from facelock.face_engine import FaceEngine
from facelock.liveness import check_texture_liveness

logger = logging.getLogger("facelock.auth")


def setup_auth_logging(verbose: bool = False, data_dir: Path | None = None) -> None:
    """Configure robust logging to syslog and local auth.log (and stderr only when verbose)."""
    handlers: list[logging.Handler] = []
    if verbose:
        handlers.append(logging.StreamHandler(sys.stderr))
    try:
        syslog_h = logging.handlers.SysLogHandler(address="/dev/log")
        syslog_h.setFormatter(logging.Formatter("facelock-auth: %(message)s"))
        handlers.append(syslog_h)
    except Exception:
        pass

    target_log = Path("/var/log/facelock-auth.log")
    try:
        file_h = logging.FileHandler(str(target_log), mode="a", encoding="utf-8")
        file_h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        handlers.append(file_h)
    except (PermissionError, OSError):
        if data_dir is not None:
            try:
                data_dir.mkdir(parents=True, exist_ok=True)
                local_log = data_dir / "auth.log"
                file_h = logging.FileHandler(str(local_log), mode="a", encoding="utf-8")
                file_h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
                handlers.append(file_h)
            except Exception:
                pass

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="[facelock-auth] %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def resolve_user_context(target_user: str | None = None) -> tuple[str, Path, Path]:
    """Resolve username, home directory, and data directory for the target user."""
    user = (
        target_user
        or os.environ.get("PAM_USER")
        or os.environ.get("SUDO_USER")
        or os.environ.get("USER")
        or getpass.getuser()
    )

    try:
        pw = pwd.getpwnam(user)
        home = Path(pw.pw_dir)
    except (KeyError, AttributeError):
        home = Path.home()

    data_dir = home / ".local" / "share" / "facelock"
    config_dir = home / ".config" / "facelock"
    return user, data_dir, config_dir


def load_user_profiles(data_dir: Path) -> dict[str, np.ndarray]:
    """Load face profiles for a given user data directory."""
    profiles: dict[str, np.ndarray] = {}
    meta_path = data_dir / "profiles.json"
    faces_dir = data_dir / "faces"

    if meta_path.exists():
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data.get("profiles", []):
                    raw_filename = item.get("filename", "")
                    clean_filename = Path(raw_filename).name  # Prevent directory traversal
                    fpath = faces_dir / clean_filename
                    if fpath.exists():
                        profiles[item.get("name", "user")] = np.load(fpath, allow_pickle=False)
        except Exception as e:
            logger.warning("Error reading profiles from %s: %s", meta_path, e)

    # Fallback to known_face.npy if no profiles.json
    if not profiles:
        legacy_path = data_dir / "known_face.npy"
        if legacy_path.exists():
            try:
                profiles["user"] = np.load(legacy_path, allow_pickle=False)
            except Exception:
                pass

    return profiles


def authenticate(
    target_user: str | None = None,
    timeout_seconds: float = 3.5,
    verbose: bool = False,
) -> bool:
    """Attempt biometric authentication against enrolled profiles for target_user.

    Returns:
        True if verified (exit 0), False if failed or timed out (exit 1).
    """
    # Instantly output prompt to GDM so it replaces any default message without delay
    print("Scanning face...", flush=True)

    user, data_dir, config_dir = resolve_user_context(target_user)
    setup_auth_logging(verbose=verbose, data_dir=data_dir)

    user_profiles = load_user_profiles(data_dir)

    if not user_profiles:
        logger.warning("No face profile enrolled for '%s' in %s", user, data_dir)
        if verbose:
            print(f"[FaceLock] No face profile enrolled for '{user}'.", file=sys.stderr)
        return False

    # Load configuration
    config_file = config_dir / "config.yaml"
    if config_file.exists():
        try:
            with config_file.open("r", encoding="utf-8") as f:
                raw_cfg = yaml.safe_load(f) or {}
            config = cfg.Config(**{k: v for k, v in raw_cfg.items() if hasattr(cfg.Config, k)})
        except Exception:
            config = cfg.Config()
    else:
        config = cfg.Config()

    engine = FaceEngine(config)

    cam = Camera(config.camera_index)
    if not cam.open():
        logger.error("Could not open camera %s for user '%s'", config.camera_index, user)
        if verbose:
            print(f"[FaceLock] Could not open camera {config.camera_index}.", file=sys.stderr)
        return False

    start_time = time.monotonic()
    matched_name: str | None = None
    best_score = 0.0
    frames_seen = 0
    faces_seen = 0
    low_light_frames = 0
    highest_match_score = 0.0
    last_rejection_reason = "No face detected"

    try:
        while (time.monotonic() - start_time) < timeout_seconds:
            frame = cam.read()
            if frame is None:
                time.sleep(0.04)
                continue

            frames_seen += 1
            if frame.ndim == 3:
                mean_lum = float(np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)))
            else:
                mean_lum = float(np.mean(frame))

            if mean_lum < 50.0:
                low_light_frames += 1

            face = engine.best_face(frame)
            if face is None:
                last_rejection_reason = f"No face detected (lum={mean_lum:.1f})"
                time.sleep(0.03)
                continue

            faces_seen += 1

            # Anti-spoof texture verification
            if config.texture_anti_spoof_enabled:
                live_tex, tex_score = check_texture_liveness(
                    frame, face[:4], min_laplacian_var=config.min_laplacian_var
                )
                if not live_tex:
                    last_rejection_reason = f"Texture anti-spoof rejected (score={tex_score:.1f}, lum={mean_lum:.1f})"
                    time.sleep(0.03)
                    continue

            emb = engine.embed(frame, face)
            landmarks = face[4:14]

            # Compare against enrolled profiles
            for name, known_vecs in user_profiles.items():
                res = engine.match_detailed(emb, known_vecs, landmarks=landmarks)
                if res.fused_score > highest_match_score:
                    highest_match_score = res.fused_score

                if res.matched:
                    matched_name = name
                    best_score = res.fused_score
                    break

            if matched_name is not None:
                break

            last_rejection_reason = f"Score {highest_match_score:.2f} < threshold {config.match_threshold}"
            time.sleep(0.02)

    finally:
        cam.release()

    elapsed = time.monotonic() - start_time

    if matched_name is not None:
        logger.info(
            "✓ Verified '%s' as enrolled profile '%s' (score=%.2f in %.2fs, frames=%d, low_light=%d)",
            user,
            matched_name,
            best_score,
            elapsed,
            frames_seen,
            low_light_frames,
        )
        print(f"✓ Face verified. Welcome, {matched_name}!", flush=True)
        time.sleep(0.35)
        return True

    logger.warning(
        "Biometric verification failed for user '%s': %s (elapsed=%.2fs, frames=%d)",
        user,
        last_rejection_reason,
        elapsed,
        frames_seen,
    )
    print("Face not recognized. Please enter password.", flush=True)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="FaceLock Biometric PAM Authenticator")
    parser.add_argument("--user", "-u", default=None, help="Target username")
    parser.add_argument("--timeout", "-t", type=float, default=3.5, help="Max wait seconds")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print debug info")
    args = parser.parse_args()

    success = authenticate(
        target_user=args.user,
        timeout_seconds=args.timeout,
        verbose=args.verbose,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
