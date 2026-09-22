"""Enrollment: guided multi-angle capture recognizing face movements (center, up, down, left, right)."""

from __future__ import annotations

import logging
import time

import numpy as np

from facelock import config as cfg
from facelock.camera import Camera
from facelock.face_engine import FaceEngine
from facelock.liveness import (
    BlinkDetector,
    SmileDetector,
    analyze_facial_pose,
    check_texture_liveness,
    estimate_head_pose,
)

logger = logging.getLogger(__name__)

# Directional enrollment steps (7 ergonomic steps)
ENROLL_STEPS = [
    ("CENTER", "Look directly at the camera (Straight)"),
    ("UP", "Tilt your head UP"),
    ("DOWN", "Tilt your head DOWN"),
    ("LEFT", "Turn your head to the LEFT"),
    ("RIGHT", "Turn your head to the RIGHT"),
    ("BLINK", "Blink your eyes to complete live biometric enrollment"),
    ("SMILE", "Smile (or show teeth) to complete facial muscle dynamic verification"),
]


def enroll(config: cfg.Config | None = None) -> None:
    from facelock import profiles

    config = config or cfg.Config.load()
    cfg.ensure_dirs()
    engine = FaceEngine(config)

    current_count = profiles.get_profile_count()
    if current_count >= profiles.MAX_PROFILES:
        names_str = ", ".join(f"'{n}'" for n in profiles.get_profile_names())
        print(f"\n❌ Error: Maximum profile limit reached ({profiles.MAX_PROFILES} faces).")
        print(f"Existing face profiles with names: {names_str}")
        print("Please delete an existing profile first using `make gui`.\n")
        return

    default_name = profiles.next_unknown_name()
    try:
        prompt_name = input(f"Enter profile name [default: {default_name}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        prompt_name = ""
    target_name = prompt_name if prompt_name else default_name

    existing_names = [n.lower() for n in profiles.get_profile_names()]
    if target_name.lower() in existing_names:
        print(f"\n❌ Error: A face profile already exists with name '{target_name}'.")
        print("Please choose a different name.\n")
        return

    total_frames = config.enroll_frame_count
    steps = ENROLL_STEPS[:total_frames]

    print("\n=======================================================")
    print(f" FaceLock Biometric Enrollment: Profile '{target_name}'")
    print(f" Camera Index {config.camera_index} • {total_frames} Movement Steps")
    print("=======================================================\n")

    embeddings: list[np.ndarray] = []

    blink_detector = BlinkDetector(
        close_threshold_ratio=config.blink_close_ratio,
        min_blink_duration=config.blink_min_duration,
        min_closed_frames=config.blink_min_frames,
    )
    smile_detector = SmileDetector(expansion_threshold=1.05, min_absolute_ratio=0.85)

    with Camera(config.camera_index) as camera:
        if camera._cap is None:
            raise SystemExit(f"Could not open camera index {config.camera_index}")

        for step_idx, (target_dir, step_instruction) in enumerate(steps, start=1):
            print(f"[{step_idx}/{total_frames}] 👉 {step_instruction}...")

            hold_count = 0
            required_holds = 3  # consecutive frames in target pose
            target_captured = False

            while not target_captured:
                frame = camera.read()
                if frame is None:
                    raise SystemExit("Camera stopped returning frames during enrollment")

                face = engine.best_face(frame)
                if face is None:
                    hold_count = 0
                    time.sleep(0.05)
                    continue

                if config.liveness_enabled and config.texture_anti_spoof_enabled:
                    is_tex_live, _ = check_texture_liveness(
                        frame, face[:4], min_laplacian_var=config.min_laplacian_var
                    )
                    if not is_tex_live:
                        hold_count = 0
                        time.sleep(0.05)
                        continue

                landmarks = face[4:14]
                pose = estimate_head_pose(landmarks, frame.shape[:2], mirrored=False)
                _, _, current_dir = analyze_facial_pose(
                    landmarks,
                    mirrored=False,
                    pose=pose,
                    neutral_v_ratio=config.neutral_v_ratio,
                    neutral_h_offset=config.neutral_h_offset,
                )

                # Check if user has achieved the required direction or action
                direction_matched = False
                if target_dir == "BLINK":
                    blink_state = blink_detector.update(frame, landmarks)
                    if blink_state.is_blinking:
                        direction_matched = True
                        hold_count = required_holds  # instant capture on confirmed blink!
                        print("  👁 Eye blink detected! Live human confirmed.")
                    elif current_dir == "CENTER":
                        hold_count += 1
                        if hold_count >= 15:  # fallback after ~0.75s steady hold
                            direction_matched = True
                elif target_dir == "SMILE":
                    is_smiling, smile_ratio = smile_detector.update(landmarks, frame=frame)
                    if is_smiling:
                        direction_matched = True
                        hold_count = required_holds  # instant capture on confirmed smile!
                        if getattr(smile_detector, "teeth_detected", False):
                            print(f"  😊 Smile verified (teeth visible, {int(smile_ratio*100)}% width ratio)! Live dynamic confirmed.")
                        else:
                            print(f"  😊 Smile verified ({int(smile_ratio*100)}% width ratio)! Live dynamic confirmed.")
                    elif current_dir == "CENTER":
                        hold_count += 1
                        if hold_count >= 20:  # fallback after ~1.0s steady hold
                            direction_matched = True
                elif target_dir == "CENTER" and current_dir == "CENTER":
                    direction_matched = True
                    smile_detector.record_baseline(landmarks)
                elif target_dir == "RIGHT" and ("RIGHT" in current_dir):
                    direction_matched = True
                elif target_dir == "LEFT" and ("LEFT" in current_dir):
                    direction_matched = True
                elif target_dir == "UP" and ("UP" in current_dir):
                    direction_matched = True
                elif target_dir == "DOWN" and ("DOWN" in current_dir):
                    direction_matched = True
                elif target_dir in current_dir:
                    direction_matched = True

                if direction_matched:
                    hold_count += 1
                    if hold_count >= required_holds:
                        # Capture embedding!
                        embedding = engine.embed(frame, face)
                        embeddings.append(embedding.reshape(-1))
                        target_captured = True
                        print(f"  ✓ Target pose verified! Captured {len(embeddings)}/{total_frames}\n")
                        time.sleep(0.5)  # brief pause before next instruction
                else:
                    hold_count = 0

                time.sleep(0.05)

    try:
        saved_name = profiles.save_profile(target_name, embeddings, engine=engine)
        print("=======================================================")
        print(f" Success: Saved face profile '{saved_name}' ({len(embeddings)} frames)")
        print(f" Enrolled profiles: {profiles.get_profile_count()}/{profiles.MAX_PROFILES}")
        print("=======================================================\n")
    except profiles.FaceAlreadyExistsError as e:
        print(f"\n❌ Biometric Conflict: {e}\n")
    except Exception as e:
        print(f"\n❌ Failed to save profile: {e}\n")
