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
from facelock.gui import (
    BGR_AMBER,
    BGR_BG_MINT,
    BGR_BG_PILL,
    BGR_BG_ROSE,
    BGR_CORAL,
    BGR_MINT,
    BGR_SKY,
    BG_APP,
    BG_SURFACE,
    BG_SURFACE_ALT,
    BG_SURFACE_HOVER,
    BORDER_ACTIVE,
    BORDER_COLOR,
    BORDER_GLASS_LIGHT,
    COLOR_AMBER,
    COLOR_CYAN,
    COLOR_CYAN_DIM,
    COLOR_CYAN_HOVER,
    COLOR_EMERALD,
    COLOR_EMERALD_BG,
    COLOR_EMERALD_BORDER,
    COLOR_ROSE,
    COLOR_ROSE_BG,
    COLOR_SKY,
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_CAPTION,
    FONT_CHIP,
    FONT_SECTION,
    FONT_SUBTITLE,
    FONT_TITLE,
    ModernButton,
    TEXT_MAIN,
    TEXT_MUTED,
    TEXT_SUBTLE,
    apply_window_glass_effect,
    center_window_on_monitor,
    draw_hud_pill,
)
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
        self.root.configure(bg=BG_APP)
        self.root.minsize(1120, 760)
        center_window_on_monitor(self.root, 1260, 840)
        apply_window_glass_effect(self.root, "FaceLock Calibration")

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
        # Top Header (Frosted Glass Header)
        top_bar = tk.Frame(self.root, bg=BG_SURFACE, height=60, highlightthickness=1, highlightbackground=BORDER_GLASS_LIGHT)
        top_bar.pack(fill=tk.X, side=tk.TOP)
        top_bar.pack_propagate(False)

        top_inner = tk.Frame(top_bar, bg=BG_SURFACE)
        top_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        tk.Label(
            top_inner,
            text="🎯  Biometric Calibration & Camera Diagnostic",
            font=FONT_TITLE,
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
        ).pack(side=tk.LEFT)

        self.status_pill = tk.Label(
            top_inner,
            text="LIVE TELEMETRY ACTIVE",
            font=FONT_CHIP,
            fg=COLOR_EMERALD,
            bg=COLOR_EMERALD_BG,
            padx=12,
            pady=4,
            highlightthickness=1,
            highlightbackground=COLOR_EMERALD_BORDER,
        )
        self.status_pill.pack(side=tk.RIGHT)

        # Main Layout: Left Video, Right Diagnostic Control Deck
        main_content = tk.Frame(self.root, bg=BG_APP)
        main_content.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

        # Video Panel (Frosted Glass Card)
        video_wrap = tk.Frame(main_content, bg=BG_SURFACE, highlightthickness=1, highlightbackground=BORDER_GLASS_LIGHT)
        video_wrap.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 15))

        self.video_lbl = tk.Label(video_wrap, bg="#04070F")
        self.video_lbl.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Right Control Panel (Frosted Glass Card)
        right_panel = tk.Frame(main_content, bg=BG_SURFACE, width=360, highlightthickness=1, highlightbackground=BORDER_GLASS_LIGHT)
        right_panel.pack(side=tk.RIGHT, fill=tk.Y)
        right_panel.pack_propagate(False)

        inner_right = tk.Frame(right_panel, bg=BG_SURFACE)
        inner_right.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        tk.Label(
            inner_right,
            text="REAL-TIME TELEMETRY",
            font=FONT_SECTION,
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
        ).pack(anchor="w", pady=(0, 10))

        # Telemetry labels card
        telem_card = tk.Frame(inner_right, bg=BG_SURFACE_ALT, padx=12, pady=10, highlightthickness=1, highlightbackground=BORDER_COLOR)
        telem_card.pack(fill=tk.X, pady=(0, 15))

        self.lbl_v_ratio = tk.Label(telem_card, text="Vertical Ratio (v): --", font=FONT_BODY, fg=COLOR_CYAN, bg=BG_SURFACE_ALT)
        self.lbl_v_ratio.pack(anchor="w", pady=2)

        self.lbl_h_offset = tk.Label(telem_card, text="Horizontal Offset (h): --", font=FONT_BODY, fg=COLOR_CYAN, bg=BG_SURFACE_ALT)
        self.lbl_h_offset.pack(anchor="w", pady=2)

        self.lbl_pose = tk.Label(telem_card, text="Pose Direction: --", font=FONT_BODY_BOLD, fg=TEXT_MAIN, bg=BG_SURFACE_ALT)
        self.lbl_pose.pack(anchor="w", pady=2)

        self.lbl_openness = tk.Label(telem_card, text="Eye Openness: --", font=FONT_BODY, fg=COLOR_EMERALD, bg=BG_SURFACE_ALT)
        self.lbl_openness.pack(anchor="w", pady=2)

        self.lbl_noise_floor = tk.Label(telem_card, text="Noise Floor: Calibrating...", font=FONT_CAPTION, fg=TEXT_MUTED, bg=BG_SURFACE_ALT)
        self.lbl_noise_floor.pack(anchor="w", pady=2)

        # Action Buttons
        tk.Label(
            inner_right,
            text="CALIBRATION & DATA ACTIONS",
            font=FONT_SECTION,
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
        ).pack(anchor="w", pady=(10, 8))

        self.btn_train = ModernButton(
            inner_right,
            text="🎯  Start Guided Calibration (3 Steps)",
            font=FONT_BODY_BOLD,
            bg_color=COLOR_CYAN,
            fg_color="#070B12",
            hover_color=COLOR_CYAN_HOVER,
            hover_fg="#070B12",
            border_color=COLOR_CYAN_DIM,
            hover_border=COLOR_CYAN_HOVER,
            padx=12,
            pady=10,
            command=self._start_calibration,
        )
        self.btn_train.pack(fill=tk.X, pady=6)

        self.btn_record = ModernButton(
            inner_right,
            text="📸  Record 5s Diagnostic Footage",
            font=FONT_BODY_BOLD,
            bg_color=BG_SURFACE_ALT,
            fg_color=TEXT_MAIN,
            hover_color=BG_SURFACE_HOVER,
            hover_fg="#FFFFFF",
            border_color=BORDER_COLOR,
            hover_border=BORDER_ACTIVE,
            padx=12,
            pady=10,
            command=self._start_recording,
        )
        self.btn_record.pack(fill=tk.X, pady=6)

        self.btn_apply_defaults = ModernButton(
            inner_right,
            text="↺  Reset to Recommended Defaults",
            font=FONT_BODY,
            bg_color=BG_SURFACE,
            fg_color=TEXT_MUTED,
            hover_color=BG_SURFACE_ALT,
            hover_fg=TEXT_MAIN,
            border_color=BORDER_COLOR,
            hover_border=BORDER_ACTIVE,
            padx=12,
            pady=8,
            command=self._reset_defaults,
        )
        self.btn_apply_defaults.pack(fill=tk.X, pady=4)

        # Instruction / Progress Box
        self.guide_box = tk.Frame(inner_right, bg=BG_SURFACE_ALT, highlightthickness=1, highlightbackground=BORDER_GLASS_LIGHT, padx=12, pady=12)
        self.guide_box.pack(fill=tk.BOTH, expand=True, pady=(15, 0))

        self.guide_title = tk.Label(
            self.guide_box,
            text="System Ready",
            font=FONT_BODY_BOLD,
            fg=COLOR_CYAN,
            bg=BG_SURFACE_ALT,
        )
        self.guide_title.pack(anchor="w")

        self.guide_desc = tk.Label(
            self.guide_box,
            text="Click 'Start Guided Calibration' to automatically fit thresholds to your webcam and facial geometry.",
            font=FONT_BODY,
            fg=TEXT_MUTED,
            bg=BG_SURFACE_ALT,
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
        self.status_pill.configure(text="CALIBRATION STEP 1/3", bg="#0369A1", fg="#F8FAFC")
        self.guide_title.configure(text="STEP 1: LOOK STRAIGHT", fg=COLOR_SKY)
        self.guide_desc.configure(
            text="Look naturally at your screen in your normal posture. The system is measuring your skull's resting neutral gaze..."
        )

    def _start_recording(self):
        self.mode = "RECORDING"
        self.recording_frames.clear()
        self.recording_telemetry.clear()
        self.recording_end_time = time.monotonic() + 5.0
        self.status_pill.configure(text="● RECORDING FOOTAGE", bg=COLOR_ROSE_BG, fg=COLOR_ROSE)
        self.guide_title.configure(text="Recording Diagnostic Footage...", fg=COLOR_ROSE)
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

                # Sleek, soothing corner reticle
                x, y_box, bw, bh = box
                color = BGR_MINT if direction == "CENTER" else BGR_SKY
                cr = int(min(bw, bh) * 0.18)
                t = 2
                cv2.line(frame, (x, y_box), (x + cr, y_box), color, t, cv2.LINE_AA)
                cv2.line(frame, (x, y_box), (x, y_box + cr), color, t, cv2.LINE_AA)
                cv2.line(frame, (x + bw, y_box), (x + bw - cr, y_box), color, t, cv2.LINE_AA)
                cv2.line(frame, (x + bw, y_box), (x + bw, y_box + cr), color, t, cv2.LINE_AA)
                cv2.line(frame, (x, y_box + bh), (x + cr, y_box + bh), color, t, cv2.LINE_AA)
                cv2.line(frame, (x, y_box + bh), (x, y_box + bh - cr), color, t, cv2.LINE_AA)
                cv2.line(frame, (x + bw, y_box + bh), (x + bw - cr, y_box + bh), color, t, cv2.LINE_AA)
                cv2.line(frame, (x + bw, y_box + bh), (x + bw, y_box + bh - cr), color, t, cv2.LINE_AA)

                # Subtle biometric landmark accents (clean, gentle dots)
                for i in range(5):
                    cv2.circle(frame, (int(landmarks[i * 2]), int(landmarks[i * 2 + 1])), 2, color, -1, cv2.LINE_AA)

                # Live metrics HUD pill
                hud_text = f"[{direction}]  v:{v_rat:.2f}  h:{h_off:+.2f}  eye:{openness:.1f}"
                draw_hud_pill(
                    frame,
                    hud_text,
                    x=x,
                    y=max(22, y_box - 10),
                    fg=color,
                    bg=BGR_BG_PILL,
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
                            self.status_pill.configure(text="CALIBRATION STEP 2/3", bg="#0369A1", fg="#F8FAFC")
                            self.guide_title.configure(text="STEP 2: KEEP EYES OPEN", fg=COLOR_SKY)
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
                            self.status_pill.configure(text="CALIBRATION STEP 3/3", bg="#0369A1", fg="#F8FAFC")
                            self.guide_title.configure(text="STEP 3: BLINK NATURALLY", fg=COLOR_SKY)
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
                    draw_hud_pill(
                        frame,
                        "● RECORDING 5s",
                        x=24,
                        y=34,
                        fg=BGR_CORAL,
                        bg=BGR_BG_ROSE,
                    )

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
        self.status_pill.configure(text="CALIBRATION COMPLETE ✓", bg=COLOR_EMERALD_BG, fg=COLOR_EMERALD)

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

        self.guide_title.configure(text="Calibration Model Trained ✓", fg=COLOR_EMERALD)
        self.guide_desc.configure(
            text=f"Trained: Neutral v={new_neutral_v:.2f}, h={new_neutral_h:+.2f}. Blink close ratio={calibrated_close_ratio:.2f}."
        )

        messagebox.showinfo("Calibration Successful", summary_msg)

    def _finish_recording(self):
        self.mode = "MONITOR"
        self.status_pill.configure(text="RECORDING SAVED ✓", bg=COLOR_EMERALD_BG, fg=COLOR_EMERALD)

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

        self.guide_title.configure(text="Diagnostic Footage Saved", fg=COLOR_SKY)
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
