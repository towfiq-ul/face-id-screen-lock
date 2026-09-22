"""Camera Diagnostic, Footage Recording, and Biometric Calibration Assistant.

Allows users to:
1. Capture real video footage and annotated snapshots with full landmark telemetry.
2. Calibrate their personal neutral resting gaze (eliminates false UP/DOWN/LEFT/RIGHT).
3. Measure camera sensor noise floor and calibrate eye blink detection (eliminates false blinks).
4. Save the calibrated model parameters to config.yaml.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
import time
import tkinter as tk
from tkinter import messagebox
from typing import Any

import cv2
import numpy as np

from facelock import config as cfg
from facelock.camera import Camera
from facelock.face_engine import FaceEngine
from facelock.liveness import (
    analyze_facial_pose,
    calculate_eye_openness,
    estimate_head_pose,
)

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LOGO_PATH = ASSETS_DIR / "logo_small.png"
CALIBRATION_DIR = cfg.DATA_DIR / "calibration_data"


class CalibrateStudio:
    """Interactive Biometric Calibration & Diagnostic Recorder."""

    def __init__(self, config: cfg.Config | None = None):
        self.config = config or cfg.Config.load()
        self.engine = FaceEngine(self.config)
        self.camera = Camera(self.config.camera_index)

        self.root = tk.Tk(className="facelock")
        self.root.title("FaceLock — Camera Diagnostic & Biometric Calibration")
        self.root.configure(bg="#090D16")
        self.root.minsize(1040, 720)

        if LOGO_PATH.exists():
            try:
                self.logo_img = tk.PhotoImage(file=str(LOGO_PATH))
                self.root.iconphoto(True, self.logo_img)
            except Exception as e:
                logger.debug("Failed to set window icon: %s", e)

        CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)

        self.is_running = True
        self.mode = "MONITOR"  # "MONITOR", "RECORDING", "CALIBRATING"
        self.calib_step = 0    # 1: Straight, 2: Eyes Open, 3: Blink Test
        self.calib_timer = 0.0
        self.calib_data: dict[str, list[float]] = {
            "v_ratios": [],
            "h_offsets": [],
            "openness_steady": [],
            "openness_blinks": [],
        }

        # Recording session storage
        self.recording_frames: list[np.ndarray] = []
        self.recording_telemetry: list[dict[str, Any]] = []
        self.recording_end_time = 0.0

        self._build_ui()
        self.camera.open()
        self._video_loop()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # Top Header
        top_bar = tk.Frame(self.root, bg="#111827", height=60, highlightthickness=1, highlightbackground="#1F2937")
        top_bar.pack(fill=tk.X, side=tk.TOP)
        top_bar.pack_propagate(False)

        top_inner = tk.Frame(top_bar, bg="#111827")
        top_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        tk.Label(
            top_inner,
            text="🎯 BIOMETRIC CALIBRATION & CAMERA DIAGNOSTIC",
            font=("Helvetica", 13, "bold"),
            fg="#00F0FF",
            bg="#111827",
        ).pack(side=tk.LEFT)

        self.status_pill = tk.Label(
            top_inner,
            text="LIVE TELEMETRY ACTIVE",
            font=("Helvetica", 10, "bold"),
            fg="#00E676",
            bg="#064E3B",
            padx=12,
            pady=4,
        )
        self.status_pill.pack(side=tk.RIGHT)

        # Main Layout: Left Video, Right Diagnostic Control Deck
        main_content = tk.Frame(self.root, bg="#090D16")
        main_content.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

        # Video Panel
        video_wrap = tk.Frame(main_content, bg="#0F172A", highlightthickness=1, highlightbackground="#1E293B")
        video_wrap.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 15))

        self.video_lbl = tk.Label(video_wrap, bg="#020617")
        self.video_lbl.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Right Control Panel
        right_panel = tk.Frame(main_content, bg="#0F172A", width=360, highlightthickness=1, highlightbackground="#1E293B")
        right_panel.pack(side=tk.RIGHT, fill=tk.Y)
        right_panel.pack_propagate(False)

        inner_right = tk.Frame(right_panel, bg="#0F172A")
        inner_right.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        tk.Label(
            inner_right,
            text="REAL-TIME TELEMETRY",
            font=("Helvetica", 11, "bold"),
            fg="#F8FAFC",
            bg="#0F172A",
        ).pack(anchor="w", pady=(0, 10))

        # Telemetry labels card
        telem_card = tk.Frame(inner_right, bg="#1E293B", padx=12, pady=10)
        telem_card.pack(fill=tk.X, pady=(0, 15))

        self.lbl_v_ratio = tk.Label(telem_card, text="Vertical Ratio (v): --", font=("Helvetica", 10), fg="#38BDF8", bg="#1E293B")
        self.lbl_v_ratio.pack(anchor="w", pady=2)

        self.lbl_h_offset = tk.Label(telem_card, text="Horizontal Offset (h): --", font=("Helvetica", 10), fg="#38BDF8", bg="#1E293B")
        self.lbl_h_offset.pack(anchor="w", pady=2)

        self.lbl_pose = tk.Label(telem_card, text="Pose Direction: --", font=("Helvetica", 10, "bold"), fg="#00F0FF", bg="#1E293B")
        self.lbl_pose.pack(anchor="w", pady=2)

        self.lbl_openness = tk.Label(telem_card, text="Eye Openness: --", font=("Helvetica", 10), fg="#34D399", bg="#1E293B")
        self.lbl_openness.pack(anchor="w", pady=2)

        self.lbl_noise_floor = tk.Label(telem_card, text="Noise Floor: Calibrating...", font=("Helvetica", 9), fg="#94A3B8", bg="#1E293B")
        self.lbl_noise_floor.pack(anchor="w", pady=2)

        # Action Buttons
        tk.Label(
            inner_right,
            text="CALIBRATION & DATA ACTIONS",
            font=("Helvetica", 11, "bold"),
            fg="#F8FAFC",
            bg="#0F172A",
        ).pack(anchor="w", pady=(10, 8))

        self.btn_train = tk.Button(
            inner_right,
            text="🎯  Start Guided Calibration (3 Steps)",
            font=("Helvetica", 10, "bold"),
            bg="#00F0FF",
            fg="#000000",
            activebackground="#38F4FF",
            padx=12,
            pady=10,
            relief=tk.FLAT,
            command=self._start_calibration,
        )
        self.btn_train.pack(fill=tk.X, pady=6)

        self.btn_record = tk.Button(
            inner_right,
            text="📸  Record 5s Diagnostic Footage",
            font=("Helvetica", 10, "bold"),
            bg="#1E293B",
            fg="#F8FAFC",
            activebackground="#334155",
            padx=12,
            pady=10,
            relief=tk.FLAT,
            command=self._start_recording,
        )
        self.btn_record.pack(fill=tk.X, pady=6)

        self.btn_apply_defaults = tk.Button(
            inner_right,
            text="↺  Reset to Recommended Defaults",
            font=("Helvetica", 9),
            bg="#0F172A",
            fg="#94A3B8",
            relief=tk.FLAT,
            command=self._reset_defaults,
        )
        self.btn_apply_defaults.pack(fill=tk.X, pady=4)

        # Instruction / Progress Box
        self.guide_box = tk.Frame(inner_right, bg="#111827", highlightthickness=1, highlightbackground="#374151", padx=12, pady=12)
        self.guide_box.pack(fill=tk.BOTH, expand=True, pady=(15, 0))

        self.guide_title = tk.Label(
            self.guide_box,
            text="System Ready",
            font=("Helvetica", 11, "bold"),
            fg="#00F0FF",
            bg="#111827",
        )
        self.guide_title.pack(anchor="w")

        self.guide_desc = tk.Label(
            self.guide_box,
            text="Click 'Start Guided Calibration' to automatically fit thresholds to your webcam and facial geometry.",
            font=("Helvetica", 9),
            fg="#94A3B8",
            bg="#111827",
            wraplength=300,
            justify=tk.LEFT,
        )
        self.guide_desc.pack(anchor="w", pady=(6, 0))

    def _start_calibration(self):
        self.mode = "CALIBRATING"
        self.calib_step = 1
        self.calib_timer = time.monotonic()
        self.calib_data = {
            "v_ratios": [],
            "h_offsets": [],
            "openness_steady": [],
            "openness_blinks": [],
        }
        self.status_pill.configure(text="CALIBRATION STEP 1/3", bg="#0284C7", fg="#FFFFFF")
        self.guide_title.configure(text="STEP 1: LOOK STRAIGHT", fg="#00F0FF")
        self.guide_desc.configure(
            text="Look naturally at your screen in your normal posture. The system is measuring your skull's resting neutral gaze..."
        )

    def _start_recording(self):
        self.mode = "RECORDING"
        self.recording_frames.clear()
        self.recording_telemetry.clear()
        self.recording_end_time = time.monotonic() + 5.0
        self.status_pill.configure(text="● RECORDING FOOTAGE", bg="#BE123C", fg="#FFFFFF")
        self.guide_title.configure(text="Recording Diagnostic Footage...", fg="#F43F5E")
        self.guide_desc.configure(text="Capturing 5 seconds of real frames and raw landmarks. Move, blink, or turn naturally.")

    def _reset_defaults(self):
        self.config.neutral_v_ratio = 0.52
        self.config.neutral_h_offset = 0.0
        self.config.blink_close_ratio = 0.62
        self.config.blink_min_duration = 0.10
        self.config.save()
        messagebox.showinfo("Defaults Restored", "Calibration parameters reset to recommended standard defaults.")

    def _video_loop(self):
        if not self.is_running:
            return

        frame = self.camera.read()
        now = time.monotonic()

        if frame is not None:
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]

            face = self.engine.best_face(frame)
            if face is not None:
                box = face[:4].astype(int)
                landmarks = face[4:14]

                # 1. Pose analysis with roll compensation and neutral offsets
                pose = estimate_head_pose(landmarks, (h, w), mirrored=True)
                h_off, v_rat, direction = analyze_facial_pose(
                    landmarks,
                    mirrored=True,
                    pose=pose,
                    neutral_v_ratio=self.config.neutral_v_ratio,
                    neutral_h_offset=self.config.neutral_h_offset,
                )

                # 2. Eye openness
                openness = calculate_eye_openness(frame, landmarks)

                # Update live telemetry text
                self.lbl_v_ratio.configure(text=f"Vertical Ratio (v): {v_rat:.3f} (neutral: {self.config.neutral_v_ratio:.2f})")
                self.lbl_h_offset.configure(text=f"Horizontal Offset (h): {h_off:+.3f} (neutral: {self.config.neutral_h_offset:+.2f})")
                self.lbl_pose.configure(text=f"Pose Direction: [{direction}]")
                self.lbl_openness.configure(text=f"Eye Openness: {openness:.1f}")

                # Draw Visual Overlay
                x, y, bw, bh = box
                color = (0, 230, 118) if direction == "CENTER" else (0, 240, 255)
                cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)

                # Draw cranial wireframe
                re_pt = (int(landmarks[0]), int(landmarks[1]))
                le_pt = (int(landmarks[2]), int(landmarks[3]))
                no_pt = (int(landmarks[4]), int(landmarks[5]))
                rm_pt = (int(landmarks[6]), int(landmarks[7]))
                lm_pt = (int(landmarks[8]), int(landmarks[9]))

                wf_col = (0, 180, 220)
                cv2.line(frame, re_pt, le_pt, wf_col, 1, cv2.LINE_AA)
                cv2.line(frame, le_pt, no_pt, wf_col, 1, cv2.LINE_AA)
                cv2.line(frame, no_pt, re_pt, wf_col, 1, cv2.LINE_AA)
                cv2.line(frame, no_pt, rm_pt, wf_col, 1, cv2.LINE_AA)
                cv2.line(frame, no_pt, lm_pt, wf_col, 1, cv2.LINE_AA)
                cv2.line(frame, rm_pt, lm_pt, wf_col, 1, cv2.LINE_AA)

                for i in range(5):
                    cv2.circle(frame, (int(landmarks[i*2]), int(landmarks[i*2+1])), 3, (0, 240, 255), -1)

                cv2.putText(
                    frame,
                    f"[{direction}] v:{v_rat:.2f} h:{h_off:+.2f} eye:{openness:.1f}",
                    (x, max(22, y - 8)),
                    cv2.FONT_HERSHEY_DUPLEX,
                    0.52,
                    color,
                    1,
                    cv2.LINE_AA,
                )

                # Handle Calibration State Machine
                if self.mode == "CALIBRATING":
                    elapsed = now - self.calib_timer
                    if self.calib_step == 1:
                        # Step 1: straight gaze sampling
                        self.calib_data["v_ratios"].append(v_rat)
                        self.calib_data["h_offsets"].append(h_off)
                        countdown = max(0.0, 3.0 - elapsed)
                        self.guide_desc.configure(text=f"Look straight at screen... ({countdown:.1f}s remaining)")
                        if elapsed >= 3.0:
                            # Advance to Step 2
                            self.calib_step = 2
                            self.calib_timer = now
                            self.status_pill.configure(text="CALIBRATION STEP 2/3", bg="#0284C7")
                            self.guide_title.configure(text="STEP 2: KEEP EYES OPEN")
                            self.guide_desc.configure(text="Keep eyes open naturally without blinking. Measuring camera sensor noise floor...")

                    elif self.calib_step == 2:
                        # Step 2: measuring open eyes noise floor
                        self.calib_data["openness_steady"].append(openness)
                        countdown = max(0.0, 3.0 - elapsed)
                        self.guide_desc.configure(text=f"Hold eyes open... ({countdown:.1f}s remaining)")
                        if elapsed >= 3.0:
                            # Advance to Step 3
                            self.calib_step = 3
                            self.calib_timer = now
                            self.status_pill.configure(text="CALIBRATION STEP 3/3", bg="#0284C7")
                            self.guide_title.configure(text="STEP 3: BLINK NATURALLY")
                            self.guide_desc.configure(text="Blink your eyes 2 or 3 times naturally now...")

                    elif self.calib_step == 3:
                        # Step 3: blink dynamics
                        self.calib_data["openness_blinks"].append(openness)
                        countdown = max(0.0, 3.5 - elapsed)
                        self.guide_desc.configure(text=f"Blink naturally... ({countdown:.1f}s remaining)")
                        if elapsed >= 3.5:
                            # Finish & Train
                            self._finish_calibration()

                # Handle Recording Mode
                elif self.mode == "RECORDING":
                    self.recording_frames.append(frame.copy())
                    self.recording_telemetry.append({
                        "timestamp": now,
                        "v_ratio": v_rat,
                        "h_offset": h_off,
                        "direction": direction,
                        "openness": openness,
                        "landmarks": landmarks.tolist(),
                        "box": box.tolist(),
                    })
                    cv2.circle(frame, (30, 30), 10, (0, 0, 255), -1)
                    cv2.putText(frame, "REC", (50, 36), cv2.FONT_HERSHEY_DUPLEX, 0.6, (0, 0, 255), 1)

                    if now >= self.recording_end_time:
                        self._finish_recording()

            # Render to Tkinter
            resized = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_LINEAR)
            ok, ppm = cv2.imencode(".ppm", resized)
            if ok:
                self._tk_img = tk.PhotoImage(data=ppm.tobytes())
                self.video_lbl.configure(image=self._tk_img)

        self.root.after(20, self._video_loop)

    def _finish_calibration(self):
        self.mode = "MONITOR"
        self.status_pill.configure(text="CALIBRATION COMPLETE ✓", bg="#064E3B", fg="#00E676")

        # 1. Compute empirical neutral v_ratio and h_offset
        v_list = self.calib_data["v_ratios"]
        h_list = self.calib_data["h_offsets"]
        steady_open = self.calib_data["openness_steady"]
        blink_open = self.calib_data["openness_blinks"]

        new_neutral_v = float(np.median(v_list)) if v_list else 0.52
        new_neutral_h = float(np.median(h_list)) if h_list else 0.0

        # 2. Compute noise floor
        mu_open = float(np.mean(steady_open)) if steady_open else 11.0
        min_open_observed = float(np.min(steady_open)) if steady_open else mu_open * 0.8

        # Set close threshold safely below the natural open noise floor
        # Ensure that normal open sensor noise NEVER dips below close_ratio!
        noise_floor_ratio = min_open_observed / (mu_open + 1e-6)
        calibrated_close_ratio = max(0.50, min(0.65, noise_floor_ratio - 0.12))

        # Save to config
        self.config.neutral_v_ratio = round(new_neutral_v, 3)
        self.config.neutral_h_offset = round(new_neutral_h, 3)
        self.config.blink_close_ratio = round(calibrated_close_ratio, 2)
        self.config.save()

        summary_msg = (
            f"Personal Calibration Applied!\n\n"
            f"• Neutral Straight Look (v_ratio): {new_neutral_v:.3f}\n"
            f"• Neutral Horizontal Offset: {new_neutral_h:+.3f}\n"
            f"• Open Eye Noise Floor: {min_open_observed:.1f} (Mean: {mu_open:.1f})\n"
            f"• Calibrated Blink Trigger Ratio: {calibrated_close_ratio:.2f}\n\n"
            f"Saved to {cfg.CONFIG_PATH}"
        )

        self.guide_title.configure(text="Calibration Model Trained ✓", fg="#00E676")
        self.guide_desc.configure(
            text=f"Trained: Neutral v={new_neutral_v:.2f}, h={new_neutral_h:+.2f}. Blink close ratio={calibrated_close_ratio:.2f}."
        )

        messagebox.showinfo("Calibration Successful", summary_msg)

    def _finish_recording(self):
        self.mode = "MONITOR"
        self.status_pill.configure(text="RECORDING SAVED ✓", bg="#064E3B", fg="#00E676")

        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_folder = CALIBRATION_DIR / f"session_{timestamp_str}"
        session_folder.mkdir(parents=True, exist_ok=True)

        # Save sample snapshots
        snap_count = min(10, len(self.recording_frames))
        indices = np.linspace(0, len(self.recording_frames) - 1, snap_count, dtype=int)
        for idx in indices:
            cv2.imwrite(str(session_folder / f"frame_{idx:03d}.png"), self.recording_frames[idx])

        # Save telemetry JSON
        telemetry_file = session_folder / "telemetry.json"
        with telemetry_file.open("w", encoding="utf-8") as f:
            json.dump(self.recording_telemetry, f, indent=2)

        self.guide_title.configure(text="Diagnostic Footage Saved", fg="#00F0FF")
        self.guide_desc.configure(
            text=f"Saved {len(self.recording_frames)} frames and telemetry to:\n{session_folder}"
        )

        messagebox.showinfo(
            "Diagnostic Footage Saved",
            f"Successfully recorded {len(self.recording_frames)} frames!\n\nSaved snapshots and telemetry data to:\n{session_folder}",
        )

    def _on_close(self):
        self.is_running = False
        self.camera.release()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    studio = CalibrateStudio()
    studio.run()


if __name__ == "__main__":
    main()
