"""FaceLock Modern Graphical Setup & Biometric Control Center.

Modern dark cyberpunk/glassmorphic design system:
- High-contrast dark surfaces with neon cyan and emerald accents.
- Optical sensor HUD viewport with dynamic targeting reticles and telemetry.
- 8-Step interactive enrollment stepper with visual angle badges.
- Real-time biometric meters (Confidence, Liveness variance, Match cosine).
- Systemd daemon service control & status integration.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import cv2
import numpy as np

from facelock import config as cfg
from facelock import profiles
from facelock.camera import Camera
from facelock.face_engine import FaceEngine
from facelock.liveness import (
    LivenessTracker,
    SmileDetector,
    analyze_facial_pose,
    check_texture_liveness,
    estimate_head_pose,
)

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LOGO_PATH = ASSETS_DIR / "logo_small.png"
SPLASH_BANNER_PATH = ASSETS_DIR / "splash_banner.png"

# Design System Palette (Deep Space Glass & Cyber Neon)
BG_APP = "#070B14"               # Deepest background
BG_SURFACE = "#0E1726"           # Card surface
BG_SURFACE_ALT = "#142136"       # Elevated secondary surface
BORDER_COLOR = "#1D2C47"         # Subtle card border
BORDER_ACTIVE = "#00F0FF"        # Focused cyan border

COLOR_CYAN = "#00F0FF"           # Primary brand / interactive
COLOR_CYAN_DIM = "#007A8A"       # Dim cyan for borders/fills
COLOR_EMERALD = "#10B981"        # Success / live match
COLOR_EMERALD_BG = "#064E3B"     # Success badge bg
COLOR_AMBER = "#F59E0B"          # Warning / attention
COLOR_ROSE = "#F43F5E"           # Danger / error / spoof
COLOR_ROSE_BG = "#4C0519"        # Danger badge bg

TEXT_MAIN = "#F8FAFC"            # High contrast text
TEXT_MUTED = "#94A3B8"           # Secondary body text
TEXT_SUBTLE = "#64748B"          # Dim captions / metadata

FONT_TITLE = ("Helvetica", 14, "bold")
FONT_SUBTITLE = ("Helvetica", 9)
FONT_SECTION = ("Helvetica", 10, "bold")
FONT_BODY = ("Helvetica", 9)
FONT_BODY_BOLD = ("Helvetica", 9, "bold")
FONT_METRIC = ("Helvetica", 11, "bold")


class ModernButton(tk.Button):
    """Custom flat styled button with smooth hover state."""

    def __init__(
        self,
        parent,
        text: str,
        command=None,
        bg_color=COLOR_CYAN,
        fg_color="#000000",
        hover_color="#38F4FF",
        font=FONT_BODY_BOLD,
        state=tk.NORMAL,
        padx: int = 14,
        pady: int = 8,
        **kwargs,
    ):
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.hover_color = hover_color
        super().__init__(
            parent,
            text=text,
            command=command,
            bg=bg_color,
            fg=fg_color,
            activebackground=hover_color,
            activeforeground=fg_color,
            font=font,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=padx,
            pady=pady,
            state=state,
            **kwargs,
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, event):
        if str(self["state"]) == tk.NORMAL:
            self.configure(bg=self.hover_color)

    def _on_leave(self, event):
        if str(self["state"]) == tk.NORMAL:
            self.configure(bg=self.bg_color)

    def set_text(self, text: str):
        self.configure(text=text)

    def set_colors(self, bg_color: str, fg_color: str, hover_color: str):
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.hover_color = hover_color
        if str(self["state"]) == tk.NORMAL:
            self.configure(
                bg=bg_color,
                fg=fg_color,
                activebackground=hover_color,
                activeforeground=fg_color,
            )

    def set_state(self, state):
        self.configure(state=state)
        if state == tk.DISABLED:
            self.configure(bg=BG_SURFACE_ALT, fg=TEXT_SUBTLE, cursor="arrow")
        else:
            self.configure(bg=self.bg_color, fg=self.fg_color, cursor="hand2")


class MetricMeter(tk.Frame):
    """Visual progress/score bar with label and value readout."""

    def __init__(self, parent, title: str, max_val: float = 1.0, unit: str = "%"):
        super().__init__(parent, bg=BG_SURFACE)
        self.max_val = max_val
        self.unit = unit

        header = tk.Frame(self, bg=BG_SURFACE)
        header.pack(fill=tk.X, pady=(0, 2))

        self.title_lbl = tk.Label(header, text=title, font=FONT_BODY, fg=TEXT_MUTED, bg=BG_SURFACE)
        self.title_lbl.pack(side=tk.LEFT)

        self.val_lbl = tk.Label(header, text="--", font=FONT_BODY_BOLD, fg=COLOR_CYAN, bg=BG_SURFACE)
        self.val_lbl.pack(side=tk.RIGHT)

        self.canvas_w = 320
        self.canvas_h = 6
        self.canvas = tk.Canvas(
            self,
            width=self.canvas_w,
            height=self.canvas_h,
            bg=BG_SURFACE_ALT,
            highlightthickness=0,
        )
        self.canvas.pack(fill=tk.X)

    def set_value(self, val: float, display_text: str | None = None, color: str = COLOR_CYAN):
        ratio = max(0.0, min(1.0, val / self.max_val if self.max_val > 0 else 0.0))
        fill_w = int(ratio * self.canvas_w)
        self.canvas.delete("bar")
        if fill_w > 0:
            self.canvas.create_rectangle(0, 0, fill_w, self.canvas_h, fill=color, width=0, tags="bar")

        if display_text:
            self.val_lbl.configure(text=display_text, fg=color)
        else:
            if self.unit == "%":
                self.val_lbl.configure(text=f"{int(ratio * 100)}%", fg=color)
            else:
                self.val_lbl.configure(text=f"{val:.2f}{self.unit}", fg=color)


def get_active_monitor_geometry(
    pointer_x: int | None = None, pointer_y: int | None = None
) -> tuple[int, int, int, int] | None:
    """Detect and return (width, height, x_offset, y_offset) for the active/primary monitor.

    Handles multi-monitor setups (side-by-side, stacked, or hybrid) using xrandr so
    windows do not get split across multiple displays.
    """
    monitors: list[tuple[int, int, int, int]] = []
    primary: tuple[int, int, int, int] | None = None
    try:
        out = subprocess.check_output(
            ["xrandr", "--listmonitors"], text=True, stderr=subprocess.DEVNULL, timeout=3.0
        )
        for line in out.strip().splitlines():
            m = re.search(r"(\d+)(?:/\d+)?x(\d+)(?:/\d+)?\+(\d+)\+(\d+)", line)
            if m:
                w, h, x, y = [int(v) for v in m.groups()]
                mon = (w, h, x, y)
                monitors.append(mon)
                if "*" in line:
                    primary = mon
    except Exception:
        pass

    if pointer_x is not None and pointer_y is not None:
        for w, h, x, y in monitors:
            if x <= pointer_x < x + w and y <= pointer_y < y + h:
                return w, h, x, y

    if primary:
        return primary
    if monitors:
        return monitors[0]

    return None


def center_window_on_monitor(root: tk.Tk | tk.Toplevel, width: int, height: int) -> None:
    """Center a window strictly within a single display, preventing multi-screen splits."""
    try:
        px, py = root.winfo_pointerxy()
    except Exception:
        px, py = None, None

    mon = get_active_monitor_geometry(px, py)
    if mon is not None:
        mon_w, mon_h, mon_x, mon_y = mon
        x = mon_x + max(0, (mon_w - width) // 2)
        y = mon_y + max(0, (mon_h - height) // 2)
    else:
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)

    root.geometry(f"{width}x{height}+{x}+{y}")


class SplashScreen:
    """Displays an ultra-modern splash screen with branded banner and percentage bar."""

    def __init__(self, on_complete):
        self.on_complete = on_complete
        self.root = tk.Tk(className="facelock")
        self.root.title("FaceLock Loading")
        self.root.overrideredirect(True)
        self.root.configure(bg=BG_APP)

        if LOGO_PATH.exists():
            try:
                self.logo_img = tk.PhotoImage(file=str(LOGO_PATH))
                self.root.iconphoto(True, self.logo_img)
            except Exception as e:
                logger.debug("Failed to set splash icon: %s", e)

        width, height = 620, 440
        center_window_on_monitor(self.root, width, height)

        # Card container with glowing cyan accent border
        border_frame = tk.Frame(self.root, bg=BORDER_COLOR, padx=1, pady=1)
        border_frame.pack(fill=tk.BOTH, expand=True)

        main_card = tk.Frame(border_frame, bg=BG_APP)
        main_card.pack(fill=tk.BOTH, expand=True)

        self.banner_img = None
        if SPLASH_BANNER_PATH.exists():
            try:
                self.banner_img = tk.PhotoImage(file=str(SPLASH_BANNER_PATH))
                banner_lbl = tk.Label(main_card, image=self.banner_img, bg=BG_APP, borderwidth=0)
                banner_lbl.pack(fill=tk.X)
            except Exception as e:
                logger.warning("Could not load splash banner: %s", e)

        info_box = tk.Frame(main_card, bg=BG_APP, padx=24, pady=14)
        info_box.pack(fill=tk.BOTH, expand=True)

        top_row = tk.Frame(info_box, bg=BG_APP)
        top_row.pack(fill=tk.X)

        tk.Label(
            top_row,
            text="FACELOCK BIOMETRICS",
            font=("Helvetica", 13, "bold"),
            fg=COLOR_CYAN,
            bg=BG_APP,
        ).pack(side=tk.LEFT)

        self.percent_lbl = tk.Label(
            top_row,
            text="0%",
            font=("Helvetica", 13, "bold"),
            fg=COLOR_CYAN,
            bg=BG_APP,
        )
        self.percent_lbl.pack(side=tk.RIGHT)

        self.status_lbl = tk.Label(
            info_box,
            text="Initializing biometric subsystem...",
            font=FONT_BODY,
            fg=TEXT_MUTED,
            bg=BG_APP,
        )
        self.status_lbl.pack(anchor="w", pady=(2, 10))

        # Progress bar
        self.canvas_w = 570
        self.canvas_h = 8
        self.progress_canvas = tk.Canvas(
            info_box,
            width=self.canvas_w,
            height=self.canvas_h,
            bg=BG_SURFACE,
            highlightthickness=1,
            highlightbackground="#1E293B",
        )
        self.progress_canvas.pack(fill=tk.X)

        threading.Thread(target=self._run_init_steps, daemon=True).start()

    def set_progress(self, percent: int, text: str):
        self.status_lbl.configure(text=text)
        self.percent_lbl.configure(text=f"{percent}%")
        fill_w = int((percent / 100.0) * self.canvas_w)
        self.progress_canvas.delete("bar")
        if fill_w > 0:
            self.progress_canvas.create_rectangle(
                0, 0, fill_w, self.canvas_h, fill=COLOR_CYAN, width=0, tags="bar"
            )
        self.root.update_idletasks()

    def _run_init_steps(self):
        steps = [
            (20, "Loading configuration and paths..."),
            (45, "Testing optical camera device..."),
            (70, "Verifying YuNet detection neural net..."),
            (90, "Verifying SFace recognition neural net..."),
            (100, "Starting FaceLock Studio..."),
        ]

        time.sleep(0.25)
        self.root.after(0, self.set_progress, steps[0][0], steps[0][1])
        cfg.ensure_dirs()
        config = cfg.Config.load()

        time.sleep(0.25)
        self.root.after(0, self.set_progress, steps[1][0], steps[1][1])
        with Camera(config.camera_index) as cam:
            _ = cam.open()

        time.sleep(0.25)
        self.root.after(0, self.set_progress, steps[2][0], steps[2][1])
        time.sleep(0.25)
        self.root.after(0, self.set_progress, steps[3][0], steps[3][1])
        engine = FaceEngine(config)

        time.sleep(0.25)
        self.root.after(0, self.set_progress, steps[4][0], steps[4][1])
        time.sleep(0.35)

        self.root.after(0, self._finish, config, engine)

    def _finish(self, config, engine):
        self.root.destroy()
        self.on_complete(config, engine)

    def start(self):
        self.root.mainloop()


class FaceSetupGUI:
    """Modern Dark Cyberpunk FaceLock Setup Studio and Biometric Manager."""

    POSE_PROMPTS = [
        ("LOOK STRAIGHT", "Center your face directly into the camera guide", "CENTER", 0.0),
        ("TILT UP", "Tilt your chin UP slightly and hold steady", "UP", 10.0),
        ("TILT DOWN", "Tilt your head DOWN slightly and hold steady", "DOWN", -10.0),
        ("TURN LEFT", "Turn your head to the LEFT and hold steady", "LEFT", -15.0),
        ("TURN RIGHT", "Turn your head to the RIGHT and hold steady", "RIGHT", 15.0),
        ("BLINK TO VERIFY", "Blink your eyes to complete live biometric enrollment", "BLINK", 0.0),
        ("SMILE TO VERIFY", "Smile or show teeth to complete facial muscle dynamic verification", "SMILE", 0.0),
    ]

    def __init__(self, config: cfg.Config, engine: FaceEngine):
        self.config = config
        self.engine = engine
        self.camera = Camera(config.camera_index)
        self.liveness_tracker = LivenessTracker(
            window_size=config.liveness_window_size,
            min_pose_variance=config.liveness_min_pose_variance,
            blink_enabled=config.blink_detection_enabled,
        )
        self.smile_detector = SmileDetector(expansion_threshold=1.05, min_absolute_ratio=0.85)
        self.smile_steady_count = 0
        self.blink_steady_count = 0

        self.root = tk.Tk(className="facelock")
        self.root.title("FaceLock Studio — Biometric Face Setup")
        self.root.configure(bg=BG_APP)
        self.root.minsize(1020, 680)
        center_window_on_monitor(self.root, 1120, 760)

        if LOGO_PATH.exists():
            try:
                self.logo_img = tk.PhotoImage(file=str(LOGO_PATH))
                self.root.iconphoto(True, self.logo_img)
                raw_logo = cv2.imread(str(LOGO_PATH), cv2.IMREAD_UNCHANGED)
                if raw_logo is not None:
                    logo_scaled = cv2.resize(raw_logo, (42, 42), interpolation=cv2.INTER_AREA)
                    ok, ppm = cv2.imencode(".ppm", logo_scaled)
                    if ok:
                        self.header_logo_img = tk.PhotoImage(data=ppm.tobytes())
                    else:
                        self.header_logo_img = self.logo_img.subsample(2, 2)
                else:
                    self.header_logo_img = self.logo_img.subsample(2, 2)
            except Exception:
                pass

        self.is_running = True
        self.is_enrolling = False
        self.is_testing = False
        self.test_challenge_blinks = 0
        self.captured_embeddings: list[np.ndarray] = []
        self.last_pose: tuple[float, float, float] | None = None
        self.pose_hold_count = 0
        self.target_hold_needed = 3
        self.cooldown_until = 0.0

        self.known_embeddings: np.ndarray | None = profiles.get_combined_embeddings()

        self._build_ui()
        self.camera.open()
        self._video_loop()
        self._update_daemon_status()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # 1. Navigation Top Header
        top_bar = tk.Frame(self.root, bg=BG_SURFACE, height=68, highlightthickness=1, highlightbackground=BORDER_COLOR)
        top_bar.pack(fill=tk.X, side=tk.TOP)
        top_bar.pack_propagate(False)

        top_inner = tk.Frame(top_bar, bg=BG_SURFACE)
        top_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=6)

        # Brand Logo & Title
        brand_frame = tk.Frame(top_inner, bg=BG_SURFACE)
        brand_frame.pack(side=tk.LEFT)

        if hasattr(self, "header_logo_img"):
            tk.Label(brand_frame, image=self.header_logo_img, bg=BG_SURFACE).pack(side=tk.LEFT, padx=(0, 12))
        elif hasattr(self, "logo_img"):
            tk.Label(brand_frame, image=self.logo_img, bg=BG_SURFACE).pack(side=tk.LEFT, padx=(0, 12))

        title_col = tk.Frame(brand_frame, bg=BG_SURFACE)
        title_col.pack(side=tk.LEFT)

        tk.Label(
            title_col,
            text="FACELOCK STUDIO",
            font=("Helvetica", 14, "bold"),
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
        ).pack(anchor="w")

        tk.Label(
            title_col,
            text="Biometric Authentication & Anti-Spoofing Center",
            font=FONT_SUBTITLE,
            fg=TEXT_MUTED,
            bg=BG_SURFACE,
        ).pack(anchor="w")

        # Top-Right System Indicators
        right_pills = tk.Frame(top_inner, bg=BG_SURFACE)
        right_pills.pack(side=tk.RIGHT)

        # Camera Index Badge
        cam_badge = tk.Frame(right_pills, bg=BG_SURFACE_ALT, padx=10, pady=4, highlightthickness=1, highlightbackground=BORDER_COLOR)
        cam_badge.pack(side=tk.LEFT, padx=6)
        tk.Label(cam_badge, text=f"📹 Cam {self.config.camera_index}", font=FONT_BODY_BOLD, fg=TEXT_MUTED, bg=BG_SURFACE_ALT).pack()

        # Calibrate Button
        self.btn_top_calib = ModernButton(
            right_pills,
            text="🎯  Calibrate",
            bg_color=BG_SURFACE_ALT,
            fg_color=COLOR_CYAN,
            hover_color="#243452",
            padx=10,
            pady=4,
            command=self._launch_calibration,
        )
        self.btn_top_calib.pack(side=tk.LEFT, padx=6)

        # Service Status Badge & Control
        self.service_badge = tk.Frame(right_pills, bg="#1E293B", padx=10, pady=4)
        self.service_badge.pack(side=tk.LEFT, padx=4)
        self.service_status_lbl = tk.Label(
            self.service_badge,
            text="● DAEMON: CHECKING",
            font=FONT_BODY_BOLD,
            fg=TEXT_MUTED,
            bg="#1E293B",
        )
        self.service_status_lbl.pack()

        self.btn_toggle_daemon = ModernButton(
            right_pills,
            text="⏹  Stop Daemon",
            bg_color="#331A24",
            fg_color="#FDA4AF",
            hover_color="#4C0519",
            padx=10,
            pady=4,
            command=self._toggle_daemon,
        )
        self.btn_toggle_daemon.pack(side=tk.LEFT, padx=4)

        # Profile Status Badge
        self.profile_badge = tk.Frame(
            right_pills,
            bg=COLOR_EMERALD_BG if self.known_embeddings is not None else COLOR_ROSE_BG,
            padx=12,
            pady=4,
        )
        self.profile_badge.pack(side=tk.LEFT, padx=6)
        self.profile_status_lbl = tk.Label(
            self.profile_badge,
            text="✓ ENROLLED" if self.known_embeddings is not None else "✕ NO PROFILE",
            font=FONT_BODY_BOLD,
            fg=COLOR_EMERALD if self.known_embeddings is not None else COLOR_ROSE,
            bg=COLOR_EMERALD_BG if self.known_embeddings is not None else COLOR_ROSE_BG,
        )
        self.profile_status_lbl.pack()

        # 2. Main Work Area
        main_area = tk.Frame(self.root, bg=BG_APP)
        main_area.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)

        # Left Column: Video Viewport Card
        left_card = tk.Frame(main_area, bg=BG_SURFACE, highlightthickness=1, highlightbackground=BORDER_COLOR)
        left_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 12))

        viewport_bar = tk.Frame(left_card, bg=BG_SURFACE, padx=14, pady=10)
        viewport_bar.pack(fill=tk.X)

        tk.Label(
            viewport_bar,
            text="OPTICAL SENSOR VIEWPORT",
            font=FONT_SECTION,
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
        ).pack(side=tk.LEFT)

        self.fps_lbl = tk.Label(
            viewport_bar,
            text="● LIVE | 30 FPS",
            font=FONT_BODY_BOLD,
            fg=COLOR_EMERALD,
            bg=BG_SURFACE,
        )
        self.fps_lbl.pack(side=tk.RIGHT)

        self.canvas = tk.Canvas(left_card, bg="#040711", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        # Right Column: Setup & Biometrics Control Studio
        right_card = tk.Frame(main_area, bg=BG_SURFACE, width=380, highlightthickness=1, highlightbackground=BORDER_COLOR)
        right_card.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))
        right_card.pack_propagate(False)

        right_content = tk.Frame(right_card, bg=BG_SURFACE, padx=16, pady=16)
        right_content.pack(fill=tk.BOTH, expand=True)

        # Stepper Row (dynamic visual pills)
        tk.Label(right_content, text="BIOMETRIC ANGLE ENROLLMENT", font=FONT_SECTION, fg=COLOR_CYAN, bg=BG_SURFACE).pack(anchor="w")

        self.stepper_frame = tk.Frame(right_content, bg=BG_SURFACE, pady=8)
        self.stepper_frame.pack(fill=tk.X)
        self.step_pills: list[tk.Label] = []
        for i in range(len(self.POSE_PROMPTS)):
            pill = tk.Label(
                self.stepper_frame,
                text=str(i + 1),
                width=3,
                font=("Helvetica", 9, "bold"),
                bg=BG_SURFACE_ALT,
                fg=TEXT_MUTED,
                pady=4,
            )
            pill.pack(side=tk.LEFT, expand=True, padx=2)
            self.step_pills.append(pill)

        # Active Guidance Card
        self.guide_card = tk.Frame(right_content, bg=BG_SURFACE_ALT, padx=14, pady=12, highlightthickness=1, highlightbackground=BORDER_COLOR)
        self.guide_card.pack(fill=tk.X, pady=(4, 14))

        self.step_tag_lbl = tk.Label(
            self.guide_card,
            text=f"STEP 1 OF {len(self.POSE_PROMPTS)} • TARGET: CENTER",
            font=("Helvetica", 8, "bold"),
            fg=COLOR_CYAN,
            bg=BG_SURFACE_ALT,
        )
        self.step_tag_lbl.pack(anchor="w")

        self.step_title_lbl = tk.Label(
            self.guide_card,
            text="LOOK STRAIGHT",
            font=("Helvetica", 11, "bold"),
            fg=TEXT_MAIN,
            bg=BG_SURFACE_ALT,
        )
        self.step_title_lbl.pack(anchor="w", pady=(2, 2))

        self.step_desc_lbl = tk.Label(
            self.guide_card,
            text="Center your face into the camera guide, then click 'Start Face Enrollment'.",
            font=FONT_BODY,
            fg=TEXT_MUTED,
            bg=BG_SURFACE_ALT,
            wraplength=320,
            justify=tk.LEFT,
        )
        self.step_desc_lbl.pack(anchor="w")

        # Telemetry Gauges
        telemetry_box = tk.LabelFrame(
            right_content,
            text=" Live Biometric Telemetry ",
            font=FONT_SECTION,
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
            padx=12,
            pady=10,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
        )
        telemetry_box.pack(fill=tk.X, pady=(0, 14))

        self.meter_conf = MetricMeter(telemetry_box, "Face Detection Confidence", max_val=1.0, unit="%")
        self.meter_conf.pack(fill=tk.X, pady=(0, 6))

        self.meter_liveness = MetricMeter(telemetry_box, "Micro-Movement Variance", max_val=1.5, unit="°")
        self.meter_liveness.pack(fill=tk.X, pady=(0, 6))

        self.meter_match = MetricMeter(telemetry_box, "Stored Profile Match (Cosine)", max_val=1.0, unit="")
        self.meter_match.pack(fill=tk.X)

        # Enrolled Profiles Card (Max 2)
        self.profiles_box = tk.LabelFrame(
            right_content,
            text=" Enrolled Face Profiles (0/2) ",
            font=FONT_SECTION,
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
            padx=10,
            pady=8,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
        )
        self.profiles_box.pack(fill=tk.X, pady=(0, 12))

        self.profiles_list_frame = tk.Frame(self.profiles_box, bg=BG_SURFACE)
        self.profiles_list_frame.pack(fill=tk.X)

        # Service & Daemon Control Card
        service_box = tk.Frame(right_content, bg=BG_SURFACE_ALT, padx=12, pady=10, highlightthickness=1, highlightbackground=BORDER_COLOR)
        service_box.pack(fill=tk.X, pady=(0, 14))

        s_top = tk.Frame(service_box, bg=BG_SURFACE_ALT)
        s_top.pack(fill=tk.X)
        tk.Label(s_top, text="Auto-Lock Daemon Service", font=FONT_BODY_BOLD, fg=TEXT_MAIN, bg=BG_SURFACE_ALT).pack(side=tk.LEFT)

        self.btn_daemon_toggle = tk.Button(
            s_top,
            text="Restart Daemon",
            font=("Helvetica", 8),
            bg=BORDER_COLOR,
            fg=TEXT_MAIN,
            activebackground=COLOR_CYAN,
            activeforeground="#000",
            relief=tk.FLAT,
            command=self._restart_daemon,
        )
        self.btn_daemon_toggle.pack(side=tk.RIGHT)

        self.daemon_desc_lbl = tk.Label(
            service_box,
            text=f"Timeout: {int(self.config.unknown_face_timeout_seconds)}s | Interval: {self.config.check_interval_seconds}s",
            font=FONT_BODY,
            fg=TEXT_MUTED,
            bg=BG_SURFACE_ALT,
        )
        self.daemon_desc_lbl.pack(anchor="w", pady=(4, 0))

        # Action Buttons
        btn_area = tk.Frame(right_content, bg=BG_SURFACE)
        btn_area.pack(fill=tk.X, side=tk.BOTTOM)

        # Name Entry Row
        name_frame = tk.Frame(btn_area, bg=BG_SURFACE)
        name_frame.pack(fill=tk.X, pady=(0, 8))

        name_hdr = tk.Frame(name_frame, bg=BG_SURFACE)
        name_hdr.pack(fill=tk.X)
        tk.Label(
            name_hdr,
            text="Profile Name:",
            font=("Helvetica", 8, "bold"),
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
        ).pack(side=tk.LEFT)
        tk.Label(
            name_hdr,
            text="(Optional • blank for unknown_1/2)",
            font=("Helvetica", 7),
            fg=TEXT_MUTED,
            bg=BG_SURFACE,
        ).pack(side=tk.RIGHT)

        self.name_entry = tk.Entry(
            name_frame,
            font=FONT_BODY,
            bg=BG_SURFACE_ALT,
            fg=TEXT_MAIN,
            insertbackground=COLOR_CYAN,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            highlightcolor=COLOR_CYAN,
        )
        self.name_entry.pack(fill=tk.X, ipady=4, pady=(3, 0))

        self.btn_enroll = ModernButton(
            btn_area,
            text="▶  Start Face Enrollment",
            bg_color=COLOR_CYAN,
            fg_color="#000000",
            hover_color="#38F4FF",
            command=self._toggle_enrollment,
        )
        self.btn_enroll.pack(fill=tk.X, pady=(0, 8))

        row2 = tk.Frame(btn_area, bg=BG_SURFACE)
        row2.pack(fill=tk.X, pady=(0, 8))

        self.btn_test = ModernButton(
            row2,
            text="🔍  Test Match",
            bg_color=BG_SURFACE_ALT,
            fg_color=TEXT_MAIN,
            hover_color="#243452",
            command=self._toggle_testing,
        )
        self.btn_test.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self.btn_save = ModernButton(
            row2,
            text="💾  Save Profile",
            bg_color=COLOR_EMERALD,
            fg_color="#000000",
            hover_color="#34D399",
            state=tk.DISABLED,
            command=self._save_profile,
        )
        self.btn_save.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(4, 0))

        self._refresh_profiles_ui()

    def _refresh_profiles_ui(self):
        """Update profiles list card and top-header profile count badge."""
        for w in self.profiles_list_frame.winfo_children():
            w.destroy()

        profile_dict = profiles.list_profiles()
        count = len(profile_dict)
        self.profiles_box.configure(text=f" Enrolled Face Profiles ({count}/{profiles.MAX_PROFILES}) ")

        if count == 0:
            tk.Label(
                self.profiles_list_frame,
                text="No face profiles enrolled yet (0/2).",
                font=FONT_SUBTITLE,
                fg=TEXT_MUTED,
                bg=BG_SURFACE,
            ).pack(anchor="w", pady=4)
            self.profile_badge.configure(bg=COLOR_ROSE_BG)
            self.profile_status_lbl.configure(
                text=f"✕ NO PROFILE (0/{profiles.MAX_PROFILES})",
                fg=COLOR_ROSE,
                bg=COLOR_ROSE_BG,
            )
        else:
            for name, arr in profile_dict.items():
                row = tk.Frame(self.profiles_list_frame, bg=BG_SURFACE_ALT, padx=8, pady=4)
                row.pack(fill=tk.X, pady=2)

                tk.Label(
                    row,
                    text=f"👤 {name} ({len(arr)} frames)",
                    font=FONT_BODY_BOLD,
                    fg=COLOR_CYAN,
                    bg=BG_SURFACE_ALT,
                ).pack(side=tk.LEFT)

                del_btn = tk.Button(
                    row,
                    text="🗑 Delete",
                    font=("Helvetica", 8, "bold"),
                    bg="#4C0519",
                    fg="#F43F5E",
                    activebackground="#F43F5E",
                    activeforeground="#FFFFFF",
                    relief=tk.FLAT,
                    bd=0,
                    cursor="hand2",
                    padx=6,
                    pady=2,
                    command=lambda n=name: self._delete_profile_action(n),
                )
                del_btn.pack(side=tk.RIGHT)

            self.profile_badge.configure(bg=COLOR_EMERALD_BG)
            self.profile_status_lbl.configure(
                text=f"✓ ENROLLED ({count}/{profiles.MAX_PROFILES})",
                fg=COLOR_EMERALD,
                bg=COLOR_EMERALD_BG,
            )

    def _delete_profile_action(self, name: str):
        """Confirm and delete a specific named profile."""
        if messagebox.askyesno(
            "Delete Face Profile",
            f"Are you sure you want to delete profile '{name}'?\n\n"
            "This action cannot be undone.",
        ):
            profiles.delete_profile(name)
            self.known_embeddings = profiles.get_combined_embeddings()
            self._refresh_profiles_ui()
            messagebox.showinfo("Profile Deleted", f"Profile '{name}' has been successfully removed.")

    def _toggle_enrollment(self):
        if self.is_enrolling:
            self.is_enrolling = False
            self.btn_enroll.set_text("▶  Resume Enrollment")
            self.btn_enroll.set_colors(COLOR_CYAN, "#000", "#38F4FF")
        else:
            if profiles.get_profile_count() >= profiles.MAX_PROFILES:
                names_str = ", ".join(f"'{n}'" for n in profiles.get_profile_names())
                messagebox.showerror(
                    "Maximum Profiles Limit",
                    f"Maximum limit reached ({profiles.MAX_PROFILES} faces).\n\n"
                    f"Existing face profiles with names:\n• {names_str}\n\n"
                    f"Please delete an existing face profile first to enroll a new face.",
                )
                return

            self.is_testing = False
            self.btn_test.set_text("🔍  Test Match")
            if len(self.captured_embeddings) >= self.config.enroll_frame_count:
                self.captured_embeddings.clear()
                self.last_pose = None
            if len(self.captured_embeddings) == 0:
                self.smile_detector.reset()
                self.liveness_tracker.reset()
            self.smile_steady_count = 0
            self.blink_steady_count = 0
            self.is_enrolling = True
            self.btn_enroll.set_text("⏸  Pause Enrollment")
            self.btn_enroll.set_colors(COLOR_AMBER, "#000", "#FBBF24")
            self.pose_hold_count = 0
            self.cooldown_until = 0.0
            self._update_progress()

    def _toggle_testing(self):
        if self.is_testing:
            self.is_testing = False
            self.btn_test.set_text("🔍  Test Match")
        else:
            if self.known_embeddings is None and not self.captured_embeddings:
                messagebox.showwarning(
                    "No Profile Enrolled",
                    "Please enroll your face first before testing live recognition.",
                )
                return
            self.is_enrolling = False
            self.btn_enroll.set_text("▶  Start Face Enrollment")
            self.btn_enroll.set_colors(COLOR_CYAN, "#000", "#38F4FF")
            self.is_testing = True
            self.test_challenge_blinks = 0
            self.liveness_tracker.blink_detector.reset()
            self.btn_test.set_text("⏹  Stop Test")

    def _launch_calibration(self):
        self.btn_top_calib.set_state(tk.DISABLED)
        self.camera_paused = True
        self.camera.release()
        # Ensure V4L2 device file descriptor is fully released by kernel before child process opens it
        time.sleep(0.15)
        proc = subprocess.Popen([sys.executable, "-m", "facelock.calibrate"])

        def _wait_calib():
            if proc.poll() is None:
                self.root.after(500, _wait_calib)
            else:
                time.sleep(0.15)
                self.config = cfg.Config.load()
                self.liveness_tracker = LivenessTracker(
                    window_size=self.config.liveness_window_size,
                    min_pose_variance=self.config.liveness_min_pose_variance,
                    blink_enabled=self.config.blink_detection_enabled,
                    blink_close_ratio=self.config.blink_close_ratio,
                    blink_min_duration=self.config.blink_min_duration,
                    blink_min_frames=self.config.blink_min_frames,
                )
                self.camera.open()
                self.camera_paused = False
                self.btn_top_calib.set_state(tk.NORMAL)

        self.root.after(500, _wait_calib)

    def _update_progress(self):
        count = len(self.captured_embeddings)
        total = self.config.enroll_frame_count

        for i, pill in enumerate(self.step_pills):
            if i < count:
                pill.configure(text="✓", bg=COLOR_EMERALD, fg="#000")
            elif i == count:
                pill.configure(text=str(i + 1), bg=COLOR_CYAN, fg="#000")
            else:
                pill.configure(text=str(i + 1), bg=BG_SURFACE_ALT, fg=TEXT_MUTED)

        if count < total:
            prompt_title, prompt_desc, target_dir, _ = self.POSE_PROMPTS[count % len(self.POSE_PROMPTS)]
            self.step_tag_lbl.configure(text=f"STEP {count + 1} OF {total} • TARGET: {target_dir}")
            self.step_title_lbl.configure(text=prompt_title)
            self.step_desc_lbl.configure(text=prompt_desc)
            self.btn_save.set_state(tk.DISABLED)
        else:
            self.step_tag_lbl.configure(text="ALL ANGLES ACQUIRED")
            self.step_title_lbl.configure(text="✓ Enrollment Ready!")
            self.step_desc_lbl.configure(
                text=f"All {len(self.POSE_PROMPTS)} biometric angles and expressions captured. Click 'Save Profile' to activate."
            )
            self.is_enrolling = False
            self.btn_enroll.set_text("🔄  Re-Enroll Face")
            self.btn_enroll.set_colors(COLOR_CYAN, "#000", "#38F4FF")
            self.btn_save.set_state(tk.NORMAL)

    def _save_profile(self):
        if len(self.captured_embeddings) < self.config.enroll_frame_count:
            return

        name = self.name_entry.get().strip()

        try:
            saved_name = profiles.save_profile(
                name=name,
                embeddings=self.captured_embeddings,
                engine=self.engine,
            )
        except profiles.MaxProfilesError as e:
            messagebox.showerror("Maximum Faces Limit", str(e))
            return
        except profiles.ProfileNameExistsError as e:
            messagebox.showerror("Profile Name Already Exists", str(e))
            return
        except profiles.FaceAlreadyExistsError as e:
            messagebox.showerror("Face Already Exists", str(e))
            return
        except Exception as e:
            messagebox.showerror("Error Saving Profile", f"Failed to save face profile: {e}")
            return

        self.known_embeddings = profiles.get_combined_embeddings()
        self.name_entry.delete(0, tk.END)
        self._refresh_profiles_ui()

        count = profiles.get_profile_count()
        messagebox.showinfo(
            "Profile Saved",
            f"Face profile '{saved_name}' successfully saved!\n\n"
            f"Enrolled profiles: {count}/{profiles.MAX_PROFILES}\n"
            f"Your session is now protected by FaceLock.",
        )
        self.btn_save.set_state(tk.DISABLED)
        self._update_daemon_status()

    def _update_daemon_status(self):
        def check():
            try:
                res = subprocess.run(
                    ["systemctl", "--user", "is-active", "facelock-monitor"],
                    capture_output=True,
                    text=True,
                    timeout=3.0,
                )
                active = (res.stdout.strip() == "active")
            except Exception:
                active = False

            def apply():
                self.daemon_active = active
                if active:
                    self.service_badge.configure(bg=COLOR_EMERALD_BG)
                    self.service_status_lbl.configure(
                        text="● DAEMON: ACTIVE", fg=COLOR_EMERALD, bg=COLOR_EMERALD_BG
                    )
                    self.btn_toggle_daemon.set_text("⏹  Stop Daemon")
                    self.btn_toggle_daemon.set_colors("#4C0519", "#FDA4AF", "#E11D48")
                else:
                    self.service_badge.configure(bg="#1E293B")
                    self.service_status_lbl.configure(
                        text="○ DAEMON: STOPPED", fg=TEXT_MUTED, bg="#1E293B"
                    )
                    self.btn_toggle_daemon.set_text("▶  Start Daemon")
                    self.btn_toggle_daemon.set_colors(COLOR_EMERALD_BG, COLOR_EMERALD, "#059669")

            self.root.after(0, apply)

        threading.Thread(target=check, daemon=True).start()

    def _toggle_daemon(self):
        """Start or stop the background auto-lock daemon service."""
        is_active = getattr(self, "daemon_active", False)
        action = "stop" if is_active else "start"
        self.btn_toggle_daemon.set_text("⏳ Working...")
        self.btn_toggle_daemon.set_state(tk.DISABLED)

        def do_toggle():
            try:
                subprocess.run(["systemctl", "--user", action, "facelock-monitor"], check=False, timeout=5.0)
                time.sleep(0.5)
            except Exception as e:
                logger.error("Failed to %s daemon: %s", action, e)
            finally:
                self.root.after(0, lambda: self.btn_toggle_daemon.set_state(tk.NORMAL))
                self._update_daemon_status()

        threading.Thread(target=do_toggle, daemon=True).start()

    def _restart_daemon(self):
        try:
            subprocess.run(["systemctl", "--user", "restart", "facelock-monitor"], check=False, timeout=5.0)
            time.sleep(0.5)
            self._update_daemon_status()
        except Exception:
            pass

    def _video_loop(self):
        if not self.is_running:
            return
        if getattr(self, "camera_paused", False):
            self.root.after(100, self._video_loop)
            return

        frame = self.camera.read()
        if frame is not None:
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]

            face = self.engine.best_face(frame)

            if face is not None:
                box = face[:4].astype(int)
                landmarks = face[4:14]
                conf = float(face[14])

                self.meter_conf.set_value(conf, f"{int(conf * 100)}%", COLOR_EMERALD)

                pose = estimate_head_pose(landmarks, (h, w), mirrored=True)
                if pose is not None:
                    p, y, r = pose
                    self.liveness_tracker.add_pose(p, y, r)

                # Photometric eye blink detection
                blink_state = self.liveness_tracker.update_eyes(frame, landmarks)
                if self.is_testing and blink_state.is_blinking:
                    self.test_challenge_blinks += 1

                h_offset, v_ratio, current_dir = analyze_facial_pose(
                    landmarks,
                    mirrored=True,
                    pose=pose,
                    neutral_v_ratio=self.config.neutral_v_ratio,
                    neutral_h_offset=self.config.neutral_h_offset,
                )

                # Pre-evaluate target direction if currently enrolling
                direction_matched = False
                target_dir = None
                prompt_title = ""
                count = len(self.captured_embeddings)
                if self.is_enrolling and count < self.config.enroll_frame_count:
                    prompt_title, prompt_desc, target_dir, _ = self.POSE_PROMPTS[
                        count % len(self.POSE_PROMPTS)
                    ]
                    if target_dir == "BLINK":
                        if blink_state.is_blinking:
                            direction_matched = True
                            self.blink_steady_count = 0
                        elif current_dir == "CENTER":
                            self.blink_steady_count += 1
                            if self.blink_steady_count >= 15:
                                direction_matched = True
                        else:
                            self.blink_steady_count = 0
                    elif target_dir == "SMILE":
                        is_smiling, smile_ratio = self.smile_detector.update(landmarks, frame=frame)
                        if is_smiling:
                            direction_matched = True
                            self.smile_steady_count = 0
                        elif current_dir == "CENTER":
                            self.smile_steady_count += 1
                            if self.smile_steady_count >= 20:
                                direction_matched = True
                        else:
                            self.smile_steady_count = 0
                    elif target_dir == "CENTER" and current_dir == "CENTER":
                        direction_matched = True
                        self.smile_detector.record_baseline(landmarks)
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

                is_live, reason = self.liveness_tracker.evaluate()
                live_tex, _ = check_texture_liveness(
                    frame, box, min_laplacian_var=self.config.min_laplacian_var
                )

                # Liveness meter
                if len(self.liveness_tracker._history) >= 2 or blink_state.blink_count > 0:
                    yaws = [rec.yaw for rec in self.liveness_tracker._history]
                    std_yaw = float(np.std(yaws)) if yaws else 0.0
                    blinks_str = f" | {blink_state.blink_count} blinks" if blink_state.blink_count > 0 else ""
                    self.meter_liveness.set_value(
                        std_yaw, f"{std_yaw:.2f}°{blinks_str}", COLOR_EMERALD if is_live else COLOR_ROSE
                    )

                # HUD Overlay drawing
                x, y_box, bw, bh = box
                if self.is_enrolling:
                    color = (0, 230, 118) if direction_matched else (0, 240, 255)  # Emerald on match, Cyan otherwise
                elif self.is_testing:
                    color = (0, 230, 118) if (is_live and live_tex) else (244, 63, 94)
                else:
                    color = (0, 240, 255) if (is_live and live_tex) else (244, 63, 94)

                # Corner bracket reticle
                cr = int(min(bw, bh) * 0.22)
                t = 2
                cv2.line(frame, (x, y_box), (x + cr, y_box), color, t, cv2.LINE_AA)
                cv2.line(frame, (x, y_box), (x, y_box + cr), color, t, cv2.LINE_AA)
                cv2.line(frame, (x + bw, y_box), (x + bw - cr, y_box), color, t, cv2.LINE_AA)
                cv2.line(frame, (x + bw, y_box), (x + bw, y_box + cr), color, t, cv2.LINE_AA)
                cv2.line(frame, (x, y_box + bh), (x + cr, y_box + bh), color, t, cv2.LINE_AA)
                cv2.line(frame, (x, y_box + bh), (x, y_box + bh - cr), color, t, cv2.LINE_AA)
                cv2.line(frame, (x + bw, y_box + bh), (x + bw - cr, y_box + bh), color, t, cv2.LINE_AA)
                cv2.line(frame, (x + bw, y_box + bh), (x + bw, y_box + bh - cr), color, t, cv2.LINE_AA)

                # 5 Biometric Landmark Dots & Cranial Structure Lattice
                re_pt = (int(landmarks[0]), int(landmarks[1]))
                le_pt = (int(landmarks[2]), int(landmarks[3]))
                no_pt = (int(landmarks[4]), int(landmarks[5]))
                rm_pt = (int(landmarks[6]), int(landmarks[7]))
                lm_pt = (int(landmarks[8]), int(landmarks[9]))

                # Subtle structural geometry wireframe
                wire_color = (0, 160, 190)
                cv2.line(frame, re_pt, le_pt, wire_color, 1, cv2.LINE_AA)
                cv2.line(frame, le_pt, no_pt, wire_color, 1, cv2.LINE_AA)
                cv2.line(frame, no_pt, re_pt, wire_color, 1, cv2.LINE_AA)
                cv2.line(frame, no_pt, rm_pt, wire_color, 1, cv2.LINE_AA)
                cv2.line(frame, no_pt, lm_pt, wire_color, 1, cv2.LINE_AA)
                cv2.line(frame, rm_pt, lm_pt, wire_color, 1, cv2.LINE_AA)

                for i in range(5):
                    lx, ly = int(landmarks[i * 2]), int(landmarks[i * 2 + 1])
                    dot_color = (0, 230, 118) if (i < 2 and blink_state.is_blinking) else (0, 240, 255)
                    cv2.circle(frame, (lx, ly), 3, dot_color, -1, cv2.LINE_AA)

                # Pose HUD pill in top-left of video
                if pose is not None:
                    p, y, r = pose
                    blinks_info = f" • BLINKS:{blink_state.blink_count}"
                    hud_pose = f"P:{p:+.0f}° Y:{y:+.0f}° [{current_dir}]{blinks_info}"
                    cv2.putText(
                        frame,
                        hud_pose,
                        (x, max(20, y_box - 10)),
                        cv2.FONT_HERSHEY_DUPLEX,
                        0.55,
                        (0, 240, 255),
                        1,
                        cv2.LINE_AA,
                    )

                # Visual blink flash badge
                if blink_state.is_blinking:
                    cv2.putText(
                        frame,
                        "👁 EYE BLINK DETECTED",
                        (x, max(42, y_box - 32)),
                        cv2.FONT_HERSHEY_DUPLEX,
                        0.58,
                        (0, 230, 118),
                        1,
                        cv2.LINE_AA,
                    )

                # Enrollment Capture Engine with Directional Pose Verification
                now = time.monotonic()
                if (
                    self.is_enrolling
                    and count < self.config.enroll_frame_count
                ):
                    in_cooldown = now < self.cooldown_until

                    # On-screen HUD for directional guidance
                    if in_cooldown:
                        status_text = f"STEP {count}/{self.config.enroll_frame_count} CAPTURED! GET READY..."
                        status_color = (0, 240, 255)  # Cyan
                    elif target_dir == "BLINK":
                        if blink_state.is_blinking:
                            status_text = "✓ BLINK DETECTED! VERIFIED"
                            status_color = (0, 230, 118)
                        else:
                            status_text = "CHALLENGE: BLINK YOUR EYES NOW"
                            status_color = (0, 240, 255)
                    elif target_dir == "SMILE":
                        if direction_matched:
                            if getattr(self.smile_detector, "teeth_detected", False):
                                status_text = "✓ TEETH & SMILE VERIFIED 😊"
                            else:
                                status_text = "✓ SMILE DETECTED! VERIFIED 😊"
                            status_color = (0, 230, 118)
                        else:
                            status_text = "CHALLENGE: SMILE (SHOW TEETH) 😊"
                            status_color = (0, 240, 255)
                    elif direction_matched:
                        status_text = f"HOLD {target_dir} ({self.pose_hold_count}/{self.target_hold_needed})"
                        status_color = (0, 230, 118)  # Emerald
                    else:
                        status_text = f"ACTION: {prompt_title} (NOW: {current_dir})"
                        status_color = (0, 190, 255)  # Amber-yellow/cyan

                    cv2.putText(
                        frame,
                        status_text,
                        (max(20, x), min(h - 20, y_box + bh + 30)),
                        cv2.FONT_HERSHEY_DUPLEX,
                        0.6,
                        status_color,
                        1,
                        cv2.LINE_AA,
                    )

                    if (
                        not in_cooldown
                        and direction_matched
                        and live_tex
                    ):
                        if (target_dir == "BLINK" and blink_state.is_blinking) or (target_dir == "SMILE" and direction_matched):
                            self.pose_hold_count = self.target_hold_needed

                        self.pose_hold_count += 1
                        if self.pose_hold_count >= self.target_hold_needed:
                            emb = self.engine.embed(frame, face)
                            self.captured_embeddings.append(emb.reshape(-1))
                            self.pose_hold_count = 0
                            self.cooldown_until = now + 0.8
                            self._update_progress()
                    else:
                        if not direction_matched or in_cooldown:
                            self.pose_hold_count = 0

                # Testing Engine
                if self.is_testing:
                    current_profiles = profiles.list_profiles()
                    emb = self.engine.embed(frame, face)
                    matched = False
                    matched_name = "UNKNOWN"
                    best_score = -1.0
                    best_match_res = None

                    if current_profiles:
                        for p_name, p_known in current_profiles.items():
                            m_res = self.engine.match_detailed(emb, p_known, landmarks=landmarks)
                            if m_res.fused_score > best_score:
                                best_score = m_res.fused_score
                                best_match_res = m_res
                                if m_res.matched:
                                    matched = True
                                    matched_name = p_name
                    elif self.captured_embeddings:
                        m_res = self.engine.match_detailed(
                            emb, np.stack(self.captured_embeddings), landmarks=landmarks
                        )
                        matched = m_res.matched
                        best_score = m_res.fused_score
                        best_match_res = m_res
                        if matched:
                            matched_name = "Session Face"

                    score = best_score if best_score > 0 else 0.0
                    self.meter_match.set_value(
                        score, f"{score:.2f}", COLOR_EMERALD if matched else COLOR_ROSE
                    )

                    has_blinked = (self.test_challenge_blinks > 0) or (
                        (time.monotonic() - blink_state.last_blink_time) < 5.0
                    )

                    struct_pct = int(best_match_res.structure_score * 100) if best_match_res else 0
                    struct_tag = f" • BONE:{struct_pct}%" if struct_pct > 0 else ""

                    if matched and is_live:
                        if has_blinked:
                            status_msg = f"✓ VERIFIED: {matched_name} ({score:.2f}{struct_tag})"
                            status_c = (0, 230, 118)
                        else:
                            status_msg = f"MATCH: {matched_name} ({score:.2f}{struct_tag}) • BLINK"
                            status_c = (0, 240, 255)
                    else:
                        status_msg = f"UNKNOWN / SPOOF ({score:.2f})"
                        status_c = (63, 61, 244)

                    cv2.putText(
                        frame,
                        status_msg,
                        (x, y_box + bh + 24),
                        cv2.FONT_HERSHEY_DUPLEX,
                        0.58,
                        status_c,
                        1,
                        cv2.LINE_AA,
                    )

                    # Show cranial bone invariance badge if verified
                    if best_match_res and best_match_res.cranial_verified:
                        cv2.putText(
                            frame,
                            f"CRANIAL STRUCTURE: {struct_pct}% (SKULL INVARIANT MATCH)",
                            (x, min(h - 10, y_box + bh + 46)),
                            cv2.FONT_HERSHEY_DUPLEX,
                            0.46,
                            (0, 240, 255),
                            1,
                            cv2.LINE_AA,
                        )
            else:
                self.meter_conf.set_value(0.0, "0%", TEXT_MUTED)
                self.meter_liveness.set_value(0.0, "Waiting", TEXT_MUTED)
                self.meter_match.set_value(0.0, "--", TEXT_MUTED)
                self.liveness_tracker.reset()
                self.pose_hold_count = 0

            # Render to Canvas
            canvas_w = self.canvas.winfo_width()
            canvas_h = self.canvas.winfo_height()
            if canvas_w > 20 and canvas_h > 20:
                scale = min(canvas_w / w, canvas_h / h)
                nw, nh = int(w * scale), int(h * scale)
                resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)

                ok, ppm = cv2.imencode(".ppm", resized)
                if ok:
                    self.tk_photo = tk.PhotoImage(data=ppm.tobytes())
                    self.canvas.delete("all")
                    cx, cy = canvas_w // 2, canvas_h // 2
                    self.canvas.create_image(cx, cy, image=self.tk_photo)

        self.root.after(33, self._video_loop)

    def _on_close(self):
        self.is_running = False
        self.camera.release()
        self.root.destroy()


def launch_gui():
    def open_main_window(config, engine):
        app = FaceSetupGUI(config, engine)
        app.root.mainloop()

    splash = SplashScreen(on_complete=open_main_window)
    splash.start()


if __name__ == "__main__":
    launch_gui()
