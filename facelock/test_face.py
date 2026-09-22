"""Interactive verification test comparing enrolled face embeddings against live camera feed.

Supports both interactive GUI HUD window and console telemetry mode.
"""

from __future__ import annotations

import argparse
import os
import time

import cv2
import numpy as np

from facelock import config as cfg
from facelock import profiles
from facelock.camera import Camera
from facelock.face_engine import FaceEngine
from facelock.liveness import (
    LivenessTracker,
    analyze_facial_pose,
    check_texture_liveness,
    estimate_head_pose,
)


def run_test(
    config: cfg.Config | None = None,
    show_window: bool = True,
    duration_seconds: float | None = None,
    max_frames: int | None = None,
) -> None:
    config = config or cfg.Config.load()
    current_profiles = profiles.list_profiles()

    if not current_profiles:
        print("\n❌ No face profiles found.")
        print("Please enroll your face first using `make gui` or `make enroll`.\n")
        return

    engine = FaceEngine(config)
    liveness_tracker = LivenessTracker(
        window_size=config.liveness_window_size,
        min_pose_variance=config.liveness_min_pose_variance,
        blink_enabled=config.blink_detection_enabled,
        blink_close_ratio=config.blink_close_ratio,
        blink_min_duration=config.blink_min_duration,
        blink_min_frames=config.blink_min_frames,
    )

    print("\n" + "=" * 65)
    print(" 🔍 FACELOCK BIOMETRIC VERIFICATION & ANTI-SPOOF TEST STUDIO")
    print("=" * 65)
    profiles_summary = ", ".join(f"'{name}' ({len(vecs)} vectors)" for name, vecs in current_profiles.items())
    print(f" • Profiles ({len(current_profiles)}/{profiles.MAX_PROFILES}): {profiles_summary}")
    print(f" • Camera Device: Index {config.camera_index}")
    print(f" • SFace Cosine Match Threshold: {config.match_threshold}")
    print(f" • Structural Cranial Match: {'Enabled' if config.structural_match_enabled else 'Disabled'}")
    print(f" • Blink & Texture Anti-Spoof: {'Enabled' if config.liveness_enabled else 'Disabled'}")
    if show_window:
        print(" • Press 'q' or ESC in the preview window to exit.")
    else:
        print(" • Press Ctrl+C in terminal to stop.")
    print("=" * 65 + "\n")

    cam = Camera(config.camera_index)
    cam.open()
    if cam._cap is None:
        print(f"❌ Could not open camera at index {config.camera_index}")
        return

    total_frames = 0
    faces_detected = 0
    matches_count = 0
    blinks_observed = 0
    scores_sum = 0.0
    start_time = time.time()

    window_name = "FaceLock Biometric Test - Live vs Saved Profile"
    can_display = show_window and ("DISPLAY" in os.environ or "WAYLAND_DISPLAY" in os.environ)

    try:
        while True:
            frame = cam.read()
            if frame is None:
                time.sleep(0.03)
                continue

            total_frames += 1
            now = time.monotonic()
            h, w = frame.shape[:2]
            display_frame = cv2.flip(frame, 1)

            face = engine.best_face(display_frame)
            matched = False
            score = 0.0
            bone_pct = 0
            current_dir = "NO FACE"
            status_text = "SCANNING FOR FACE..."
            status_color = (148, 163, 184)  # slate gray

            if face is not None:
                faces_detected += 1
                box = face[:4].astype(int)
                landmarks = face[4:14]

                # Extract biometric embedding (deep + cranial bone structure)
                emb = engine.embed(display_frame, face)
                matched_name = "UNKNOWN"
                best_score = -1.0
                best_match_res = None

                for p_name, p_known in current_profiles.items():
                    m_res = engine.match_detailed(emb, p_known, landmarks=landmarks)
                    if m_res.fused_score > best_score:
                        best_score = m_res.fused_score
                        best_match_res = m_res
                        if m_res.matched:
                            matched = True
                            matched_name = p_name

                score = best_score if best_score > 0 else 0.0
                scores_sum += score

                # Pose estimation & classification
                pose = estimate_head_pose(landmarks, (h, w), mirrored=True)
                if pose is not None:
                    p, y, r = pose
                    liveness_tracker.add_pose(p, y, r)

                _, _, current_dir = analyze_facial_pose(
                    landmarks,
                    mirrored=True,
                    pose=pose,
                    neutral_v_ratio=config.neutral_v_ratio,
                    neutral_h_offset=config.neutral_h_offset,
                )

                # Eye blink update
                blink_state = liveness_tracker.update_eyes(display_frame, landmarks)
                if blink_state.is_blinking:
                    blinks_observed = blink_state.blink_count

                is_live, live_reason = liveness_tracker.evaluate()
                live_tex, tex_score = check_texture_liveness(
                    display_frame, box, min_laplacian_var=config.min_laplacian_var
                )

                bone_pct = int(best_match_res.structure_score * 100) if best_match_res else 0

                # Status decision
                has_blinked = (blink_state.blink_count > 0) or (
                    (time.monotonic() - blink_state.last_blink_time) < 6.0
                )

                if matched and is_live and live_tex:
                    matches_count += 1
                    if has_blinked:
                        status_text = f"✓ VERIFIED: {matched_name} ({score:.2f} • BONE:{bone_pct}%)"
                        status_color = (0, 230, 118)  # Emerald
                    else:
                        status_text = f"MATCH: {matched_name} ({score:.2f} • BONE:{bone_pct}%) - BLINK"
                        status_color = (0, 240, 255)  # Cyan
                elif matched and not live_tex:
                    status_text = f"TEXTURE REJECTED ({tex_score:.1f} < {config.min_laplacian_var})"
                    status_color = (63, 61, 244)  # Red
                else:
                    status_text = f"UNKNOWN FACE ({score:.2f} < {config.match_threshold})"
                    status_color = (63, 61, 244)  # Red

                # HUD drawing on display frame
                x, y_box, bw, bh = box
                cr = int(min(bw, bh) * 0.22)
                cv2.line(display_frame, (x, y_box), (x + cr, y_box), status_color, 2, cv2.LINE_AA)
                cv2.line(display_frame, (x, y_box), (x, y_box + cr), status_color, 2, cv2.LINE_AA)
                cv2.line(display_frame, (x + bw, y_box), (x + bw - cr, y_box), status_color, 2, cv2.LINE_AA)
                cv2.line(display_frame, (x + bw, y_box), (x + bw, y_box + cr), status_color, 2, cv2.LINE_AA)
                cv2.line(display_frame, (x, y_box + bh), (x + cr, y_box + bh), status_color, 2, cv2.LINE_AA)
                cv2.line(display_frame, (x, y_box + bh), (x, y_box + bh - cr), status_color, 2, cv2.LINE_AA)
                cv2.line(display_frame, (x + bw, y_box + bh), (x + bw - cr, y_box + bh), status_color, 2, cv2.LINE_AA)
                cv2.line(display_frame, (x + bw, y_box + bh), (x + bw, y_box + bh - cr), status_color, 2, cv2.LINE_AA)

                # Draw cranial structural geometry wireframe
                re_pt = (int(landmarks[0]), int(landmarks[1]))
                le_pt = (int(landmarks[2]), int(landmarks[3]))
                no_pt = (int(landmarks[4]), int(landmarks[5]))
                rm_pt = (int(landmarks[6]), int(landmarks[7]))
                lm_pt = (int(landmarks[8]), int(landmarks[9]))
                wire_color = (0, 160, 190)
                cv2.line(display_frame, re_pt, le_pt, wire_color, 1, cv2.LINE_AA)
                cv2.line(display_frame, le_pt, no_pt, wire_color, 1, cv2.LINE_AA)
                cv2.line(display_frame, no_pt, re_pt, wire_color, 1, cv2.LINE_AA)
                cv2.line(display_frame, no_pt, rm_pt, wire_color, 1, cv2.LINE_AA)
                cv2.line(display_frame, no_pt, lm_pt, wire_color, 1, cv2.LINE_AA)
                cv2.line(display_frame, rm_pt, lm_pt, wire_color, 1, cv2.LINE_AA)

                for i in range(5):
                    lx, ly = int(landmarks[i * 2]), int(landmarks[i * 2 + 1])
                    cv2.circle(display_frame, (lx, ly), 3, (0, 240, 255), -1, cv2.LINE_AA)

                if pose is not None:
                    p, y, r = pose
                    hud_pose = f"P:{p:+.0f}° Y:{y:+.0f}° [{current_dir}] • BLINKS:{blink_state.blink_count}"
                    cv2.putText(
                        display_frame,
                        hud_pose,
                        (x, max(24, y_box - 10)),
                        cv2.FONT_HERSHEY_DUPLEX,
                        0.55,
                        (0, 240, 255),
                        1,
                        cv2.LINE_AA,
                    )

                cv2.putText(
                    display_frame,
                    status_text,
                    (max(16, x), min(h - 16, y_box + bh + 26)),
                    cv2.FONT_HERSHEY_DUPLEX,
                    0.6,
                    status_color,
                    1,
                    cv2.LINE_AA,
                )

                if display_frame.ndim == 3:
                    mean_lum = float(np.mean(cv2.cvtColor(display_frame, cv2.COLOR_BGR2GRAY)))
                else:
                    mean_lum = float(np.mean(display_frame))
                is_low_light = mean_lum < 50.0

                # Terminal log update
                verdict_badge = f"✅ MATCH: {matched_name}" if matched else "❌ NO MATCH"
                light_tag = f" | Lum: {mean_lum:.0f} (🌙)" if is_low_light else f" | Lum: {mean_lum:.0f}"
                print(
                    f"\r[{verdict_badge}] Score: {score:.3f} (Thresh: {config.match_threshold}) | "
                    f"Bone: {bone_pct}% | Pose: {current_dir:<7} | Blinks: {blink_state.blink_count} | "
                    f"Live: {'YES' if is_live and live_tex else 'NO':<3}{light_tag}",
                    end="",
                    flush=True,
                )
            else:
                if display_frame.ndim == 3:
                    mean_lum = float(np.mean(cv2.cvtColor(display_frame, cv2.COLOR_BGR2GRAY)))
                else:
                    mean_lum = float(np.mean(display_frame))
                low_str = " (🌙 LOW LIGHT)" if mean_lum < 50.0 else ""
                print(f"\r[🔍 SCANNING] Searching for face in sensor feed...{low_str}       ", end="", flush=True)

            if can_display:
                # Add header bar
                cv2.rectangle(display_frame, (0, 0), (w, 36), (14, 23, 38), -1)
                cv2.putText(
                    display_frame,
                    "FACELOCK BIOMETRIC VERIFICATION (Press 'q' to quit)",
                    (14, 24),
                    cv2.FONT_HERSHEY_DUPLEX,
                    0.55,
                    (0, 240, 255),
                    1,
                    cv2.LINE_AA,
                )
                cv2.imshow(window_name, display_frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), ord("Q"), 27):  # 'q' or ESC
                    break

            if duration_seconds is not None and (time.time() - start_time) >= duration_seconds:
                break
            if max_frames is not None and total_frames >= max_frames:
                break

    except KeyboardInterrupt:
        pass
    finally:
        cam.release()
        if can_display:
            cv2.destroyAllWindows()

    elapsed = time.time() - start_time
    print("\n\n" + "=" * 65)
    print(" 📊 BIOMETRIC TEST BENCHMARK SUMMARY")
    print("=" * 65)
    print(f" • Total Frames Processed: {total_frames} ({total_frames / max(0.1, elapsed):.1f} FPS)")
    print(f" • Face Detections:        {faces_detected} ({faces_detected / max(1, total_frames) * 100:.1f}%)")
    if faces_detected > 0:
        match_pct = (matches_count / faces_detected) * 100
        avg_score = scores_sum / faces_detected
        print(f" • Enrolled Profile Match: {matches_count}/{faces_detected} ({match_pct:.1f}%)")
        print(f" • Average Cosine Score:   {avg_score:.3f}")
        print(f" • Blinks Registered:      {blinks_observed}")
        if matches_count > 0:
            print(" • Result:                 ✅ BIOMETRIC AUTHENTICATION SUCCEEDED")
        else:
            print(" • Result:                 ❌ BIOMETRIC AUTHENTICATION FAILED")
    else:
        print(" • Result:                 ⚠️ NO FACE DETECTED DURING TEST")
    print("=" * 65 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test live face against saved FaceLock biometric profile")
    parser.add_argument("--no-gui", action="store_true", help="Run in terminal mode without opening an OpenCV window")
    parser.add_argument("--duration", type=float, default=None, help="Stop test after N seconds")
    parser.add_argument("--frames", type=int, default=None, help="Stop test after N frames")
    args = parser.parse_args()

    run_test(
        show_window=not args.no_gui,
        duration_seconds=args.duration,
        max_frames=args.frames,
    )


if __name__ == "__main__":
    main()
