"""FaceLock Modern Graphical Setup & Biometric Control Center.

Modern, soothing design system:
- Glare-free serene slate & obsidian surfaces with calming azure and mint accents.
- Smooth camera HUD viewport with unobtrusive face guidance reticle.
- 7-Step guided biometric enrollment stepper with reassuring prompts.
- Real-time biometric meters with smooth rounded progress tracks.
- Auto-lock daemon service controls and fine-grained security configuration.
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


def apply_window_glass_effect(window: tk.Tk | tk.Toplevel, title: str = "FaceLock") -> None:
    """Apply Linux/Ubuntu window compositor glass translucency and dark styling hints."""
    try:
        window.update_idletasks()
    except Exception:
        pass

    try:
        window.wm_attributes("-alpha", 0.98)
    except Exception:
        pass


def _detect_font_family() -> str:
    try:
        import tkinter.font as tkfont

        root = tk._default_root
        should_destroy = False
        if root is None:
            root = tk.Tk()
            root.withdraw()
            should_destroy = True
        fams = set(tkfont.families(root))
        if should_destroy:
            root.destroy()

        preferred_list = (
            "Ubuntu",
            "Ubuntu Sans",
            "Cantarell",
            "Inter",
            "DejaVu Sans",
            "Liberation Sans",
            "Noto Sans",
        )

        for preferred in preferred_list:
            if preferred in fams:
                return preferred
    except Exception:
        pass
    return "Helvetica"




FONT_FAMILY = _detect_font_family()
FONT_TITLE = (FONT_FAMILY, 13, "bold")
FONT_SUBTITLE = (FONT_FAMILY, 9)
FONT_SECTION = (FONT_FAMILY, 10, "bold")
FONT_BODY = (FONT_FAMILY, 9)
FONT_BODY_BOLD = (FONT_FAMILY, 9, "bold")
FONT_METRIC = (FONT_FAMILY, 11, "bold")
FONT_CHIP = (FONT_FAMILY, 8, "bold")
FONT_CAPTION = (FONT_FAMILY, 8)
FONT_SMALL = (FONT_FAMILY, 7)

# =============================================================================
# Glassmorphism Design System: Frosted Obsidian Glass & Luminous Neon
# =============================================================================
BG_APP = "#070B12"               # Deep space midnight canvas
BG_SURFACE = "#0F1626"           # Frosted glass card surface
BG_SURFACE_ALT = "#162034"       # Elevated glass card / input wells
BG_SURFACE_HOVER = "#212F4C"     # Glass refraction hover sheen
BORDER_COLOR = "#1C2A42"         # Translucent glass boundary rim
BORDER_ACTIVE = "#38BDF8"        # Luminous azure focus / active neon rim
BORDER_GLASS_LIGHT = "#2B3D5E"   # Top-edge specular glass reflection
BORDER_GLASS_ACCENT = "#818CF8"  # Electric indigo glass accent

# Luminous Glass Accents
COLOR_SKY = "#38BDF8"            # Electric azure neon
COLOR_SKY_HOVER = "#7DD3FC"      # Luminous hover cyan
COLOR_SKY_DIM = "#0284C7"        # Dim azure glass accent
COLOR_CYAN = COLOR_SKY           # Alias for compatibility
COLOR_CYAN_HOVER = COLOR_SKY_HOVER
COLOR_CYAN_DIM = COLOR_SKY_DIM   # Alias for compatibility
COLOR_CYAN_BORDER = BORDER_ACTIVE

COLOR_EMERALD = "#34D399"        # Luminous mint / emerald
COLOR_EMERALD_BG = "#064E3B"     # Frosted deep emerald tint
COLOR_EMERALD_BORDER = "#059669" # Emerald glass rim
COLOR_EMERALD_TEXT = "#A7F3D0"   # Light mint text

COLOR_AMBER = "#FBBF24"          # Glowing warm amber
COLOR_AMBER_BG = "#451A03"       # Frosted amber tint
COLOR_AMBER_BORDER = "#D97706"   # Amber glass rim
COLOR_AMBER_TEXT = "#FDE68A"

COLOR_ROSE = "#FB7185"           # Glowing coral / rose
COLOR_ROSE_BG = "#4C0519"        # Frosted rose tint
COLOR_ROSE_BORDER = "#E11D48"    # Rose glass rim
COLOR_ROSE_TEXT = "#FECDD3"

TEXT_MAIN = "#F8FAFC"            # Crisp luminous off-white
TEXT_MUTED = "#94A3B8"           # Soothing slate-400
TEXT_SUBTLE = "#64748B"          # Dim slate-500

# Frosted Glass OpenCV Overlay Colors (BGR)
BGR_SKY = (248, 189, 56)         # #38BDF8 in BGR
BGR_MINT = (153, 211, 52)        # #34D399 in BGR
BGR_CORAL = (133, 113, 251)      # #FB7185 in BGR
BGR_AMBER = (36, 191, 251)       # #FBBF24 in BGR
BGR_BG_PILL = (24, 16, 11)       # Dark glass tint in BGR (#0B1018)
BGR_BG_MINT = (59, 78, 6)        # Deep emerald tint in BGR (#064E3B)
BGR_BG_ROSE = (25, 5, 76)        # Deep rose tint in BGR (#4C0519)


def draw_hud_pill(
    frame: np.ndarray,
    text: str,
    x: int,
    y: int,
    fg: tuple[int, int, int] = BGR_SKY,
    bg: tuple[int, int, int] = BGR_BG_PILL,
    font_scale: float = 0.52,
) -> None:
    """Draw a frosted glass HUD badge with optical background blur and specular rim."""
    font = cv2.FONT_HERSHEY_DUPLEX
    thickness = 1
    (tw, th), bl = cv2.getTextSize(text, font, font_scale, thickness)
    pad_x, pad_y = 12, 6
    fh, fw = frame.shape[:2]

    x1 = max(0, x)
    y1 = max(0, y - th - pad_y)
    x2 = min(fw, x1 + tw + pad_x * 2)
    y2 = min(fh, y + pad_y + 2)

    if x2 - x1 > 8 and y2 - y1 > 8:
        sub = frame[y1:y2, x1:x2]
        # 1. Optical Gaussian blur to simulate real frosted glass background
        ksize = 15
        blurred = cv2.GaussianBlur(sub, (ksize, ksize), 0)
        # 2. Tint with dark glass tone
        tint = np.full_like(sub, bg)
        glass = cv2.addWeighted(blurred, 0.45, tint, 0.55, 0)
        # 3. Alpha blend onto original frame
        cv2.addWeighted(glass, 0.88, sub, 0.12, 0, sub)
        # 4. Specular 1px luminous glass border
        cv2.rectangle(frame, (x1, y1), (x2, y2), fg, 1, cv2.LINE_AA)
        # 5. Top-edge specular refraction line
        if x2 - x1 > 8:
            cv2.line(frame, (x1 + 2, y1), (x2 - 2, y1), (255, 255, 255), 1, cv2.LINE_AA)

    tx = min(fw - tw - 4, x1 + pad_x)
    ty = min(fh - 4, max(th + 2, y))
    cv2.putText(frame, text, (tx, ty), font, font_scale, fg, thickness, cv2.LINE_AA)


class ModernButton(tk.Button):
    """Custom glass-styled button with luminous hover feedback, specular rim, and disabled states."""

    def __init__(
        self,
        parent,
        text: str,
        command=None,
        bg_color=COLOR_CYAN,
        fg_color="#070B12",
        hover_color="#7DD3FC",
        hover_fg=None,
        border_color=BORDER_COLOR,
        hover_border=BORDER_ACTIVE,
        disabled_bg=BG_SURFACE_ALT,
        disabled_fg="#64748B",
        font=FONT_BODY_BOLD,
        state=tk.NORMAL,
        padx: int = 14,
        pady: int = 8,
        **kwargs,
    ):
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.hover_color = hover_color
        self.hover_fg = hover_fg if hover_fg is not None else fg_color
        self.border_color = border_color
        self.hover_border = hover_border
        self.disabled_bg = disabled_bg
        self.disabled_fg = disabled_fg
        self._is_hovered = False

        initial_bg = self.disabled_bg if state == tk.DISABLED else bg_color
        initial_fg = self.disabled_fg if state == tk.DISABLED else fg_color

        super().__init__(
            parent,
            text=text,
            command=command,
            bg=initial_bg,
            fg=initial_fg,
            disabledforeground=self.disabled_fg,
            activebackground=hover_color,
            activeforeground=self.hover_fg,
            font=font,
            relief=tk.FLAT,
            overrelief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.border_color,
            highlightcolor=self.hover_border,
            cursor="hand2" if state == tk.NORMAL else "arrow",
            padx=padx,
            pady=pady,
            state=state,
            **kwargs,
        )

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, event=None):
        self._is_hovered = True
        if str(self["state"]) != tk.DISABLED:
            self.configure(
                bg=self.hover_color,
                fg=self.hover_fg,
                highlightbackground=self.hover_border,
                cursor="hand2",
            )

    def _on_leave(self, event=None):
        self._is_hovered = False
        if str(self["state"]) != tk.DISABLED:
            self.configure(
                bg=self.bg_color,
                fg=self.fg_color,
                highlightbackground=self.border_color,
            )

    def set_text(self, text: str):
        self.configure(text=text)

    def set_colors(
        self,
        bg_color: str,
        fg_color: str,
        hover_color: str,
        hover_fg: str | None = None,
        border_color: str | None = None,
        hover_border: str | None = None,
    ):
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.hover_color = hover_color
        self.hover_fg = hover_fg if hover_fg is not None else fg_color
        if border_color is not None:
            self.border_color = border_color
        if hover_border is not None:
            self.hover_border = hover_border

        self.configure(
            activebackground=hover_color,
            activeforeground=self.hover_fg,
        )
        if str(self["state"]) != tk.DISABLED:
            if self._is_hovered:
                self.configure(bg=self.hover_color, fg=self.hover_fg, highlightbackground=self.hover_border)
            else:
                self.configure(bg=self.bg_color, fg=self.fg_color, highlightbackground=self.border_color)

    def set_state(self, state):
        self.configure(state=state)
        if state == tk.DISABLED:
            self.configure(
                bg=self.disabled_bg,
                disabledforeground=self.disabled_fg,
                highlightbackground=self.border_color,
                cursor="arrow",
            )
        else:
            self.configure(cursor="hand2")
            if self._is_hovered:
                self.configure(bg=self.hover_color, fg=self.hover_fg, highlightbackground=self.hover_border)
            else:
                self.configure(bg=self.bg_color, fg=self.fg_color, highlightbackground=self.border_color)


class MetricMeter(tk.Frame):
    """Visual glass progress/score bar with label, glowing track, and value readout."""

    def __init__(self, parent, title: str, max_val: float = 1.0, unit: str = "%"):
        super().__init__(parent, bg=BG_SURFACE)
        self.max_val = max_val
        self.unit = unit

        header = tk.Frame(self, bg=BG_SURFACE)
        header.pack(fill=tk.X, pady=(0, 4))

        self.title_lbl = tk.Label(header, text=title, font=FONT_BODY, fg=TEXT_MUTED, bg=BG_SURFACE)
        self.title_lbl.pack(side=tk.LEFT)

        self.val_lbl = tk.Label(header, text="--", font=FONT_BODY_BOLD, fg=COLOR_CYAN, bg=BG_SURFACE)
        self.val_lbl.pack(side=tk.RIGHT)

        self.canvas_w = 320
        self.canvas_h = 8
        self.canvas = tk.Canvas(
            self,
            width=self.canvas_w,
            height=self.canvas_h,
            bg=BG_SURFACE,
            highlightthickness=0,
        )
        self.canvas.pack(fill=tk.X)
        self._last_val = 0.0
        self._last_color = COLOR_CYAN
        self._draw_track()
        self.canvas.bind("<Configure>", self._on_canvas_resize)

    def _draw_track(self):
        self.canvas.delete("track")
        y = self.canvas_h // 2
        r = self.canvas_h // 2
        self.canvas.create_line(
            r, y, max(r, self.canvas_w - r), y,
            width=self.canvas_h,
            capstyle=tk.ROUND,
            fill=BG_SURFACE_ALT,
            tags="track",
        )

    def _on_canvas_resize(self, event):
        if event.width > 20:
            self.canvas_w = event.width
            self._draw_track()
            self._redraw_bar()

    def _redraw_bar(self):
        ratio = max(0.0, min(1.0, self._last_val / self.max_val if self.max_val > 0 else 0.0))
        y = self.canvas_h // 2
        r = self.canvas_h // 2
        fill_w = int(ratio * self.canvas_w)
        self.canvas.delete("bar")
        self.canvas.delete("bead")
        if fill_w >= r:
            self.canvas.create_line(
                r, y, max(r, fill_w - r), y,
                width=self.canvas_h - 1,
                capstyle=tk.ROUND,
                fill=self._last_color,
                tags="bar",
            )
            # Specular glowing glass bead reflection at leading edge
            tip_x = max(r, fill_w - r)
            if tip_x > r + 3:
                self.canvas.create_oval(
                    tip_x - 2, y - 2, tip_x + 2, y + 2,
                    fill="#FFFFFF",
                    outline="",
                    tags="bead",
                )

    def set_value(self, val: float, display_text: str | None = None, color: str = COLOR_CYAN):
        self._last_val = val
        self._last_color = color
        self._redraw_bar()

        ratio = max(0.0, min(1.0, val / self.max_val if self.max_val > 0 else 0.0))
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


class SettingsDialog(tk.Toplevel):
    """Modern, soothing FaceLock Security & Auto-Lock Configuration Dialog."""

    def __init__(self, parent: tk.Tk | tk.Toplevel, config: cfg.Config, on_save_callback=None):
        super().__init__(parent)
        self.config = config
        self.on_save_callback = on_save_callback

        self.title("FaceLock — Configuration & Security Settings")
        self.configure(bg=BG_APP)
        self.transient(parent)
        apply_window_glass_effect(self, "FaceLock Settings")

        if LOGO_PATH.exists():
            try:
                self.icon_img = tk.PhotoImage(file=str(LOGO_PATH), master=self)
                self.iconphoto(True, self.icon_img)
            except Exception:
                pass

        dialog_w, dialog_h = 640, 720
        center_window_on_monitor(self, dialog_w, dialog_h)

        self._build_ui()
        self.grab_set()

    def _build_ui(self):
        # Specular glass border container
        border_frame = tk.Frame(self, bg=BORDER_GLASS_LIGHT, padx=1, pady=1)
        border_frame.pack(fill=tk.BOTH, expand=True)

        main_box = tk.Frame(border_frame, bg=BG_APP)
        main_box.pack(fill=tk.BOTH, expand=True)

        # Header bar
        header_bar = tk.Frame(main_box, bg=BG_SURFACE, height=62, highlightthickness=1, highlightbackground=BORDER_GLASS_LIGHT)
        header_bar.pack(fill=tk.X, side=tk.TOP)
        header_bar.pack_propagate(False)

        h_inner = tk.Frame(header_bar, bg=BG_SURFACE, padx=16, pady=8)
        h_inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            h_inner,
            text="⚙️  Security & Auto-Lock Preferences",
            font=FONT_TITLE,
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
        ).pack(anchor="w")

        tk.Label(
            h_inner,
            text="Tune user inactivity triggers, verification windows, and biometric sensitivity.",
            font=FONT_SUBTITLE,
            fg=TEXT_MUTED,
            bg=BG_SURFACE,
        ).pack(anchor="w")

        # Bottom Action Bar (Fixed at bottom)
        bottom_bar = tk.Frame(main_box, bg=BG_SURFACE, height=60, highlightthickness=1, highlightbackground=BORDER_GLASS_LIGHT)
        bottom_bar.pack(fill=tk.X, side=tk.BOTTOM)
        bottom_bar.pack_propagate(False)

        b_inner = tk.Frame(bottom_bar, bg=BG_SURFACE, padx=16, pady=10)
        b_inner.pack(fill=tk.BOTH, expand=True)

        self.btn_save = ModernButton(
            b_inner,
            text="💾  Save & Apply",
            bg_color=COLOR_CYAN,
            fg_color="#070B12",
            hover_color=COLOR_SKY_HOVER,
            hover_fg="#070B12",
            border_color=COLOR_CYAN_DIM,
            hover_border=COLOR_CYAN_HOVER,
            padx=16,
            pady=6,
            command=self._save,
        )
        self.btn_save.pack(side=tk.RIGHT, padx=(8, 0))

        self.btn_cancel = ModernButton(
            b_inner,
            text="Cancel",
            bg_color=BG_SURFACE_ALT,
            fg_color=TEXT_MAIN,
            hover_color=BG_SURFACE_HOVER,
            hover_fg="#FFFFFF",
            border_color=BORDER_COLOR,
            hover_border=BORDER_ACTIVE,
            padx=14,
            pady=6,
            command=self.destroy,
        )
        self.btn_cancel.pack(side=tk.RIGHT)

        # Scrollable Content Area
        canvas = tk.Canvas(main_box, bg=BG_APP, highlightthickness=0)
        scrollbar = tk.Scrollbar(main_box, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=BG_APP, padx=16, pady=12)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(event):
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")
            elif hasattr(event, "delta") and event.delta:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", _on_mousewheel)
        canvas.bind_all("<Button-5>", _on_mousewheel)

        def _cleanup():
            try:
                canvas.unbind_all("<MouseWheel>")
                canvas.unbind_all("<Button-4>")
                canvas.unbind_all("<Button-5>")
            except Exception:
                pass
            self.destroy()

        self.protocol("WM_DELETE_WINDOW", _cleanup)
        self.btn_cancel.configure(command=_cleanup)

        # SECTION 1: Auto-Lock & Inactivity Triggers Card
        card_idle = tk.LabelFrame(
            scrollable_frame,
            text=" Inactivity & Auto-Lock Timing ",
            font=FONT_SECTION,
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
            padx=14,
            pady=12,
            highlightthickness=1,
            highlightbackground=BORDER_GLASS_LIGHT,
        )
        card_idle.pack(fill=tk.X, pady=(0, 14))

        # Checkbox: Smart Idle Detection
        self.var_idle_enabled = tk.BooleanVar(value=getattr(self.config, "idle_detection_enabled", True))
        chk_idle = tk.Checkbutton(
            card_idle,
            text="Enable Smart Input Inactivity Detection",
            variable=self.var_idle_enabled,
            font=FONT_BODY_BOLD,
            fg=TEXT_MAIN,
            bg=BG_SURFACE,
            selectcolor=BG_SURFACE_ALT,
            activebackground=BG_SURFACE,
            activeforeground=COLOR_CYAN,
        )
        chk_idle.pack(anchor="w")

        tk.Label(
            card_idle,
            text="Monitors keyboard, mouse, touch pad and touch screen. Optical camera wakes only after zero activity.",
            font=FONT_SUBTITLE,
            fg=TEXT_MUTED,
            bg=BG_SURFACE,
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 10))

        # 1. Idle timeout
        self.var_idle_timeout = tk.StringVar(value=str(int(getattr(self.config, "idle_timeout_seconds", 120.0))))
        self._build_numeric_row(
            parent=card_idle,
            label_text="User Inactivity Trigger:",
            text_var=self.var_idle_timeout,
            unit="sec",
            presets=[("1m", 60), ("2m", 120), ("5m", 300), ("10m", 600)],
            hint="Seconds of zero input before camera wakes up to check face.",
        )

        # 2. Face check window
        self.var_face_window = tk.StringVar(value=str(int(getattr(self.config, "face_check_window_seconds", 30.0))))
        self._build_numeric_row(
            parent=card_idle,
            label_text="Face Verification Window:",
            text_var=self.var_face_window,
            unit="sec",
            presets=[("15s", 15), ("30s", 30), ("45s", 45), ("60s", 60)],
            hint="Seconds camera searches for enrolled face before locking screen.",
        )

        # 3. Check polling interval
        self.var_check_interval = tk.StringVar(value=str(getattr(self.config, "check_interval_seconds", 2.0)))
        self._build_numeric_row(
            parent=card_idle,
            label_text="Camera Polling Interval:",
            text_var=self.var_check_interval,
            unit="sec",
            presets=[("1.0s", 1.0), ("2.0s", 2.0), ("3.0s", 3.0)],
            hint="Interval between biometric evaluations while camera is active.",
        )

        # 4. Fallback unknown face timeout
        self.var_unknown_timeout = tk.StringVar(value=str(int(getattr(self.config, "unknown_face_timeout_seconds", 60.0))))
        self._build_numeric_row(
            parent=card_idle,
            label_text="Continuous Fallback Timeout:",
            text_var=self.var_unknown_timeout,
            unit="sec",
            presets=[("30s", 30), ("60s", 60), ("120s", 120)],
            hint="Lock duration used when smart inactivity detection is disabled.",
        )

        # SECTION 2: Biometric Validation & Match Thresholds Card
        card_bio = tk.LabelFrame(
            scrollable_frame,
            text=" Biometric Sensitivity & Security Thresholds ",
            font=FONT_SECTION,
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
            padx=14,
            pady=12,
            highlightthickness=1,
            highlightbackground=BORDER_GLASS_LIGHT,
        )
        card_bio.pack(fill=tk.X, pady=(0, 14))

        # Match Threshold Scale
        min_match_val = float(getattr(self.config, "min_match_percent", 92.0))
        self.var_min_match = tk.DoubleVar(value=min_match_val)

        match_row = tk.Frame(card_bio, bg=BG_SURFACE)
        match_row.pack(fill=tk.X, pady=(0, 2))

        tk.Label(
            match_row,
            text="Validation Match Threshold:",
            font=FONT_BODY_BOLD,
            fg=TEXT_MAIN,
            bg=BG_SURFACE,
        ).pack(side=tk.LEFT)

        self.lbl_match_readout = tk.Label(
            match_row,
            text=f"{self.var_min_match.get():.0f}% (High Security)",
            font=FONT_BODY_BOLD,
            fg=COLOR_EMERALD,
            bg=BG_SURFACE,
        )
        self.lbl_match_readout.pack(side=tk.RIGHT)

        def _on_scale(v):
            val = float(v)
            if val >= 92.0:
                tag = "High Security"
                col = COLOR_EMERALD
            elif val >= 80.0:
                tag = "Balanced"
                col = COLOR_CYAN
            else:
                tag = "Permissive"
                col = COLOR_AMBER
            self.lbl_match_readout.configure(text=f"{val:.0f}% ({tag})", fg=col)

        scale_slider = tk.Scale(
            card_bio,
            from_=50.0,
            to=99.0,
            resolution=1.0,
            orient=tk.HORIZONTAL,
            variable=self.var_min_match,
            command=_on_scale,
            bg=BG_SURFACE,
            fg=COLOR_CYAN,
            troughcolor=BG_SURFACE_ALT,
            highlightthickness=0,
            activebackground=COLOR_CYAN,
            font=FONT_CAPTION,
            showvalue=False,
        )
        scale_slider.pack(fill=tk.X, pady=(2, 2))

        tk.Label(
            card_bio,
            text="Faces matching above this confidence threshold are accepted as valid (default 92%).",
            font=FONT_SUBTITLE,
            fg=TEXT_MUTED,
            bg=BG_SURFACE,
        ).pack(anchor="w", pady=(0, 8))

        # Security check guards
        guards_frame = tk.Frame(card_bio, bg=BG_SURFACE)
        guards_frame.pack(fill=tk.X, pady=(4, 0))

        self.var_blink = tk.BooleanVar(value=getattr(self.config, "blink_detection_enabled", True))
        self.var_liveness = tk.BooleanVar(value=getattr(self.config, "liveness_enabled", True))
        self.var_texture = tk.BooleanVar(value=getattr(self.config, "texture_anti_spoof_enabled", True))
        self.var_structural = tk.BooleanVar(value=getattr(self.config, "structural_match_enabled", True))

        row_g1 = tk.Frame(guards_frame, bg=BG_SURFACE)
        row_g1.pack(fill=tk.X, pady=2)
        tk.Checkbutton(
            row_g1,
            text="Photometric Eye Blink Detection",
            variable=self.var_blink,
            font=FONT_BODY,
            fg=TEXT_MAIN,
            bg=BG_SURFACE,
            selectcolor=BG_SURFACE_ALT,
            activebackground=BG_SURFACE,
            activeforeground=COLOR_CYAN,
        ).pack(side=tk.LEFT)

        tk.Checkbutton(
            row_g1,
            text="Micro-Movement Liveness Verification",
            variable=self.var_liveness,
            font=FONT_BODY,
            fg=TEXT_MAIN,
            bg=BG_SURFACE,
            selectcolor=BG_SURFACE_ALT,
            activebackground=BG_SURFACE,
            activeforeground=COLOR_CYAN,
        ).pack(side=tk.RIGHT)

        row_g2 = tk.Frame(guards_frame, bg=BG_SURFACE)
        row_g2.pack(fill=tk.X, pady=2)
        tk.Checkbutton(
            row_g2,
            text="Texture Anti-Spoofing (Anti-Replay)",
            variable=self.var_texture,
            font=FONT_BODY,
            fg=TEXT_MAIN,
            bg=BG_SURFACE,
            selectcolor=BG_SURFACE_ALT,
            activebackground=BG_SURFACE,
            activeforeground=COLOR_CYAN,
        ).pack(side=tk.LEFT)

        tk.Checkbutton(
            row_g2,
            text="Cranial Bone Structural Validation",
            variable=self.var_structural,
            font=FONT_BODY,
            fg=TEXT_MAIN,
            bg=BG_SURFACE,
            selectcolor=BG_SURFACE_ALT,
            activebackground=BG_SURFACE,
            activeforeground=COLOR_CYAN,
        ).pack(side=tk.RIGHT)

        # SECTION 3: Hardware & Device Options
        card_dev = tk.LabelFrame(
            scrollable_frame,
            text=" Optical Camera Hardware ",
            font=FONT_SECTION,
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
            padx=14,
            pady=12,
            highlightthickness=1,
            highlightbackground=BORDER_GLASS_LIGHT,
        )
        card_dev.pack(fill=tk.X, pady=(0, 10))

        self.var_cam_idx = tk.StringVar(value=str(getattr(self.config, "camera_index", 0)))
        self._build_numeric_row(
            parent=card_dev,
            label_text="Camera Device Index:",
            text_var=self.var_cam_idx,
            unit="",
            presets=[("Cam 0", 0), ("Cam 1", 1), ("Cam 2", 2)],
            hint="V4L2 video index (0 for /dev/video0, 1 for /dev/video1).",
        )

    def _build_numeric_row(
        self, parent, label_text: str, text_var: tk.StringVar, unit: str, presets: list[tuple[str, any]], hint: str
    ):
        row = tk.Frame(parent, bg=BG_SURFACE)
        row.pack(fill=tk.X, pady=(4, 1))

        tk.Label(row, text=label_text, font=FONT_BODY_BOLD, fg=TEXT_MAIN, bg=BG_SURFACE).pack(side=tk.LEFT)

        for p_lbl, p_val in presets:
            btn = ModernButton(
                row,
                text=p_lbl,
                font=FONT_CHIP,
                bg_color=BG_SURFACE_ALT,
                fg_color=COLOR_CYAN,
                hover_color=BG_SURFACE_HOVER,
                hover_fg=COLOR_SKY_HOVER,
                border_color=BORDER_COLOR,
                hover_border=BORDER_ACTIVE,
                padx=6,
                pady=2,
                command=lambda v=p_val, tv=text_var: tv.set(str(v)),
            )
            btn.pack(side=tk.RIGHT, padx=2)

        entry_box = tk.Frame(row, bg=BG_SURFACE)
        entry_box.pack(side=tk.RIGHT, padx=(0, 8))

        entry = tk.Entry(
            entry_box,
            textvariable=text_var,
            font=FONT_BODY,
            bg=BG_SURFACE_ALT,
            fg=TEXT_MAIN,
            insertbackground=COLOR_CYAN,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            highlightcolor=BORDER_ACTIVE,
            width=6,
            justify=tk.CENTER,
        )
        entry.pack(side=tk.LEFT)

        if unit:
            tk.Label(entry_box, text=f" {unit}", font=FONT_SUBTITLE, fg=TEXT_MUTED, bg=BG_SURFACE).pack(side=tk.LEFT)

        hint_lbl = tk.Label(parent, text=hint, font=FONT_SUBTITLE, fg=TEXT_SUBTLE, bg=BG_SURFACE)
        hint_lbl.pack(anchor="w", pady=(0, 6))

    def _save(self):
        try:
            idle_timeout = float(self.var_idle_timeout.get().strip())
            if idle_timeout < 5.0:
                raise ValueError("Inactivity trigger timeout must be at least 5 seconds.")

            face_window = float(self.var_face_window.get().strip())
            if face_window < 2.0:
                raise ValueError("Face verification window must be at least 2 seconds.")

            check_interval = float(self.var_check_interval.get().strip())
            if check_interval < 0.2 or check_interval > 30.0:
                raise ValueError("Camera polling interval must be between 0.2 and 30 seconds.")

            unknown_timeout = float(self.var_unknown_timeout.get().strip())
            if unknown_timeout < 5.0:
                raise ValueError("Fallback unknown face timeout must be at least 5 seconds.")

            min_match = float(self.var_min_match.get())
            if min_match < 50.0 or min_match > 100.0:
                raise ValueError("Minimum match threshold must be between 50% and 100%.")

            cam_idx = int(self.var_cam_idx.get().strip())
            if cam_idx < 0:
                raise ValueError("Camera index must be a non-negative integer (e.g. 0, 1).")

        except ValueError as e:
            messagebox.showerror("Invalid Configuration", str(e), parent=self)
            return

        self.config.idle_detection_enabled = bool(self.var_idle_enabled.get())
        self.config.idle_timeout_seconds = idle_timeout
        self.config.face_check_window_seconds = face_window
        self.config.check_interval_seconds = check_interval
        self.config.unknown_face_timeout_seconds = unknown_timeout
        self.config.min_match_percent = min_match
        self.config.camera_index = cam_idx
        self.config.blink_detection_enabled = bool(self.var_blink.get())
        self.config.liveness_enabled = bool(self.var_liveness.get())
        self.config.texture_anti_spoof_enabled = bool(self.var_texture.get())
        self.config.structural_match_enabled = bool(self.var_structural.get())

        try:
            self.config.save()
        except Exception as e:
            messagebox.showerror("Error Saving Configuration", f"Failed to write config.yaml: {e}", parent=self)
            return

        if self.on_save_callback:
            self.on_save_callback(self.config)

        self.destroy()


class SplashScreen:
    """Displays an ultra-modern splash screen with branded banner and percentage bar."""

    def __init__(self, on_complete):
        self.on_complete = on_complete
        self.root = tk.Tk(className="facelock")
        self.root.title("FaceLock Loading")
        self.root.overrideredirect(True)
        self.root.configure(bg=BG_APP)
        apply_window_glass_effect(self.root, "FaceLock Loading")

        if LOGO_PATH.exists():
            try:
                self.logo_img = tk.PhotoImage(file=str(LOGO_PATH))
                self.root.iconphoto(True, self.logo_img)
            except Exception as e:
                logger.debug("Failed to set splash icon: %s", e)

        width, height = 605, 430
        center_window_on_monitor(self.root, width, height)

        # Glass modal container with glowing specular glass border
        border_frame = tk.Frame(self.root, bg=BORDER_GLASS_LIGHT, padx=1, pady=1)
        border_frame.pack(fill=tk.BOTH, expand=True)

        main_card = tk.Frame(border_frame, bg=BG_SURFACE)
        main_card.pack(fill=tk.BOTH, expand=True)

        self.banner_img = None
        if SPLASH_BANNER_PATH.exists():
            try:
                self.banner_img = tk.PhotoImage(file=str(SPLASH_BANNER_PATH))
                banner_lbl = tk.Label(main_card, image=self.banner_img, bg=BG_SURFACE, borderwidth=0)
                banner_lbl.pack(fill=tk.X)
            except Exception as e:
                logger.warning("Could not load splash banner: %s", e)

        info_box = tk.Frame(main_card, bg=BG_SURFACE, padx=24, pady=14)
        info_box.pack(fill=tk.BOTH, expand=True)

        top_row = tk.Frame(info_box, bg=BG_SURFACE)
        top_row.pack(fill=tk.X)

        tk.Label(
            top_row,
            text="FACELOCK BIOMETRICS",
            font=FONT_TITLE,
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
        ).pack(side=tk.LEFT)

        self.percent_lbl = tk.Label(
            top_row,
            text="0%",
            font=FONT_TITLE,
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
        )
        self.percent_lbl.pack(side=tk.RIGHT)

        self.status_lbl = tk.Label(
            info_box,
            text="Initializing biometric subsystem...",
            font=FONT_BODY,
            fg=TEXT_MUTED,
            bg=BG_SURFACE,
        )
        self.status_lbl.pack(anchor="w", pady=(2, 10))

        # Progress bar with rounded pill track
        self.canvas_w = 570
        self.canvas_h = 8
        self.progress_canvas = tk.Canvas(
            info_box,
            width=self.canvas_w,
            height=self.canvas_h,
            bg=BG_SURFACE,
            highlightthickness=0,
        )
        self.progress_canvas.pack(fill=tk.X)
        self._draw_track()

        threading.Thread(target=self._run_init_steps, daemon=True).start()

    def _draw_track(self):
        self.progress_canvas.delete("track")
        y = self.canvas_h // 2
        r = self.canvas_h // 2
        self.progress_canvas.create_line(
            r, y, max(r, self.canvas_w - r), y,
            width=self.canvas_h,
            capstyle=tk.ROUND,
            fill=BG_SURFACE_ALT,
            tags="track",
        )

    def set_progress(self, percent: int, text: str):
        self.status_lbl.configure(text=text)
        self.percent_lbl.configure(text=f"{percent}%")
        fill_w = int((percent / 100.0) * self.canvas_w)
        y = self.canvas_h // 2
        r = self.canvas_h // 2
        self.progress_canvas.delete("bar")
        self.progress_canvas.delete("bead")
        if fill_w >= r:
            self.progress_canvas.create_line(
                r, y, max(r, fill_w - r), y,
                width=self.canvas_h - 1,
                capstyle=tk.ROUND,
                fill=COLOR_CYAN,
                tags="bar",
            )
            tip_x = max(r, fill_w - r)
            if tip_x > r + 3:
                self.progress_canvas.create_oval(
                    tip_x - 2, y - 2, tip_x + 2, y + 2,
                    fill="#FFFFFF",
                    outline="",
                    tags="bead",
                )
        self.root.update_idletasks()

    def _run_init_steps(self):
        steps = [
            (20, "Loading configuration and paths..."),
            (45, "Testing optical camera device..."),
            (70, "Verifying YuNet detection neural net..."),
            (90, "Verifying SFace recognition neural net..."),
            (100, "Starting FaceLock ..."),
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
    """Modern, soothing FaceLock Setup Studio and Biometric Manager."""

    POSE_PROMPTS = [
        ("Look Straight", "Look directly into the camera in your natural resting posture", "CENTER", 0.0),
        ("Tilt Chin Up", "Gently tilt your chin upward slightly and hold steady", "UP", 10.0),
        ("Tilt Head Down", "Gently tilt your head downward slightly and hold steady", "DOWN", -10.0),
        ("Turn Left", "Turn your head gently to your left and hold steady", "LEFT", -15.0),
        ("Turn Right", "Turn your head gently to your right and hold steady", "RIGHT", 15.0),
        ("Blink to Verify", "Blink your eyes naturally to confirm live presence", "BLINK", 0.0),
        ("Smile to Verify", "Smile gently to confirm dynamic facial muscle movement", "SMILE", 0.0),
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
        self.root.title("FaceLock — Biometric Face Setup")
        self.root.configure(bg=BG_APP)
        self.root.minsize(1120, 740)
        center_window_on_monitor(self.root, 1280, 860)
        apply_window_glass_effect(self.root, "FaceLock — Biometric Face Setup")

        if LOGO_PATH.exists():
            try:
                self.logo_img = tk.PhotoImage(file=str(LOGO_PATH), master=self.root)
                self.root.iconphoto(True, self.logo_img)
                raw_logo = cv2.imread(str(LOGO_PATH), cv2.IMREAD_UNCHANGED)
                if raw_logo is not None:
                    logo_scaled = cv2.resize(raw_logo, (42, 42), interpolation=cv2.INTER_AREA)
                    ok, ppm = cv2.imencode(".ppm", logo_scaled)
                    if ok:
                        self.header_logo_img = tk.PhotoImage(data=ppm.tobytes(), master=self.root)
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
        # 1. Navigation Top Header (Frosted Glass Header)
        top_bar = tk.Frame(self.root, bg=BG_SURFACE, height=68, highlightthickness=1, highlightbackground=BORDER_GLASS_LIGHT)
        top_bar.pack(fill=tk.X, side=tk.TOP)
        top_bar.pack_propagate(False)

        top_inner = tk.Frame(top_bar, bg=BG_SURFACE)
        top_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=6)

        # Brand Logo & Title
        brand_frame = tk.Frame(top_inner, bg=BG_SURFACE)
        brand_frame.pack(side=tk.LEFT)

        if hasattr(self, "header_logo_img"):
            try:
                tk.Label(brand_frame, image=self.header_logo_img, bg=BG_SURFACE).pack(side=tk.LEFT, padx=(0, 12))
            except Exception:
                pass
        elif hasattr(self, "logo_img"):
            try:
                tk.Label(brand_frame, image=self.logo_img, bg=BG_SURFACE).pack(side=tk.LEFT, padx=(0, 12))
            except Exception:
                pass

        title_col = tk.Frame(brand_frame, bg=BG_SURFACE)
        title_col.pack(side=tk.LEFT)

        tk.Label(
            title_col,
            text="FACELOCK",
            font=FONT_TITLE,
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
        ).pack(anchor="w")

        tk.Label(
            title_col,
            text="Intelligent Biometric Face Recognition & Auto-Lock",
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
        self.cam_badge_lbl = tk.Label(cam_badge, text=f"📹 Cam {self.config.camera_index}", font=FONT_BODY_BOLD, fg=TEXT_MUTED, bg=BG_SURFACE_ALT)
        self.cam_badge_lbl.pack()

        # Calibrate Button
        self.btn_top_calib = ModernButton(
            right_pills,
            text="🎯  Calibrate",
            bg_color=BG_SURFACE_ALT,
            fg_color=COLOR_CYAN,
            hover_color=BG_SURFACE_HOVER,
            hover_fg="#7DD3FC",
            border_color=BORDER_COLOR,
            hover_border=BORDER_ACTIVE,
            padx=10,
            pady=4,
            command=self._launch_calibration,
        )
        self.btn_top_calib.pack(side=tk.LEFT, padx=6)

        # Settings Button
        self.btn_top_settings = ModernButton(
            right_pills,
            text="⚙️  Settings",
            bg_color=BG_SURFACE_ALT,
            fg_color=COLOR_CYAN,
            hover_color=BG_SURFACE_HOVER,
            hover_fg="#7DD3FC",
            border_color=BORDER_COLOR,
            hover_border=BORDER_ACTIVE,
            padx=10,
            pady=4,
            command=self._open_settings_dialog,
        )
        self.btn_top_settings.pack(side=tk.LEFT, padx=6)

        # Service Status Badge & Control
        self.service_badge = tk.Frame(
            right_pills, bg=BG_SURFACE_ALT, padx=10, pady=4, highlightthickness=1, highlightbackground=BORDER_COLOR
        )
        self.service_badge.pack(side=tk.LEFT, padx=4)
        self.service_status_lbl = tk.Label(
            self.service_badge,
            text="● DAEMON: CHECKING",
            font=FONT_BODY_BOLD,
            fg=TEXT_MUTED,
            bg=BG_SURFACE_ALT,
        )
        self.service_status_lbl.pack()

        self.btn_toggle_daemon = ModernButton(
            right_pills,
            text="⏹  Stop Daemon",
            bg_color="#4C0519",
            fg_color="#FECDD3",
            hover_color="#881337",
            hover_fg="#FFFFFF",
            border_color=COLOR_ROSE_BORDER,
            hover_border=COLOR_ROSE,
            padx=10,
            pady=4,
            command=self._toggle_daemon,
        )
        self.btn_toggle_daemon.pack(side=tk.LEFT, padx=4)

        # Profile Status Badge with glass border
        self.profile_badge = tk.Frame(
            right_pills,
            bg=COLOR_EMERALD_BG if self.known_embeddings is not None else COLOR_ROSE_BG,
            padx=12,
            pady=4,
            highlightthickness=1,
            highlightbackground=COLOR_EMERALD_BORDER if self.known_embeddings is not None else COLOR_ROSE_BORDER,
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

        # Left Column: Video Viewport Card (Frosted Glass Panel)
        left_card = tk.Frame(main_area, bg=BG_SURFACE, highlightthickness=1, highlightbackground=BORDER_GLASS_LIGHT)
        left_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 12))

        viewport_bar = tk.Frame(left_card, bg=BG_SURFACE, padx=14, pady=10)
        viewport_bar.pack(fill=tk.X)

        tk.Label(
            viewport_bar,
            text="CAMERA SENSOR FEED",
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

        self.canvas = tk.Canvas(left_card, bg="#04070F", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        # Right Column: Setup & Biometrics Control Studio (Frosted Glass)
        right_card = tk.Frame(main_area, bg=BG_SURFACE, width=420, highlightthickness=1, highlightbackground=BORDER_GLASS_LIGHT)
        right_card.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))
        right_card.pack_propagate(False)

        right_content = tk.Frame(right_card, bg=BG_SURFACE, padx=16, pady=16)
        right_content.pack(fill=tk.BOTH, expand=True)

        # Stepper Row (dynamic visual glass capsules)
        tk.Label(right_content, text="BIOMETRIC ANGLE ENROLLMENT", font=FONT_SECTION, fg=COLOR_CYAN, bg=BG_SURFACE).pack(anchor="w")

        self.stepper_frame = tk.Frame(right_content, bg=BG_SURFACE, pady=8)
        self.stepper_frame.pack(fill=tk.X)
        self.step_pills: list[tk.Label] = []
        for i in range(len(self.POSE_PROMPTS)):
            pill = tk.Label(
                self.stepper_frame,
                text=str(i + 1),
                width=3,
                font=FONT_CHIP,
                bg=BG_SURFACE_ALT,
                fg=TEXT_MUTED,
                pady=4,
                highlightthickness=1,
                highlightbackground=BORDER_COLOR,
            )
            pill.pack(side=tk.LEFT, expand=True, padx=2)
            self.step_pills.append(pill)

        # Active Guidance Card (Elevated Glass Well)
        self.guide_card = tk.Frame(
            right_content, bg=BG_SURFACE_ALT, padx=14, pady=12, highlightthickness=1, highlightbackground=BORDER_GLASS_LIGHT
        )
        self.guide_card.pack(fill=tk.X, pady=(4, 14))

        self.step_tag_lbl = tk.Label(
            self.guide_card,
            text=f"STEP 1 OF {len(self.POSE_PROMPTS)} • TARGET: CENTER",
            font=FONT_CHIP,
            fg=COLOR_CYAN,
            bg=BG_SURFACE_ALT,
        )
        self.step_tag_lbl.pack(anchor="w")

        self.step_title_lbl = tk.Label(
            self.guide_card,
            text="Look Straight",
            font=FONT_METRIC,
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
            wraplength=350,
            justify=tk.LEFT,
        )
        self.step_desc_lbl.pack(anchor="w")

        # Telemetry Gauges (Glass Card)
        telemetry_box = tk.LabelFrame(
            right_content,
            text=" Live Biometric Telemetry ",
            font=FONT_SECTION,
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
            padx=12,
            pady=10,
            highlightthickness=1,
            highlightbackground=BORDER_GLASS_LIGHT,
        )
        telemetry_box.pack(fill=tk.X, pady=(0, 14))

        self.meter_conf = MetricMeter(telemetry_box, "Face Detection Confidence", max_val=1.0, unit="%")
        self.meter_conf.pack(fill=tk.X, pady=(0, 6))

        self.meter_liveness = MetricMeter(telemetry_box, "Micro-Movement Variance", max_val=1.5, unit="°")
        self.meter_liveness.pack(fill=tk.X, pady=(0, 6))

        self.meter_match = MetricMeter(telemetry_box, "Profile Match Confidence", max_val=100.0, unit="%")
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
            highlightbackground=BORDER_GLASS_LIGHT,
        )
        self.profiles_box.pack(fill=tk.X, pady=(0, 12))

        self.profiles_list_frame = tk.Frame(self.profiles_box, bg=BG_SURFACE)
        self.profiles_list_frame.pack(fill=tk.X)

        # Service & Daemon Control Card (Elevated Glass)
        service_box = tk.Frame(
            right_content, bg=BG_SURFACE_ALT, padx=12, pady=10, highlightthickness=1, highlightbackground=BORDER_GLASS_LIGHT
        )
        service_box.pack(fill=tk.X, pady=(0, 14))

        s_top = tk.Frame(service_box, bg=BG_SURFACE_ALT)
        s_top.pack(fill=tk.X)
        tk.Label(s_top, text="Auto-Lock Daemon Service", font=FONT_BODY_BOLD, fg=TEXT_MAIN, bg=BG_SURFACE_ALT).pack(side=tk.LEFT)

        self.btn_daemon_toggle = ModernButton(
            s_top,
            text="Restart Daemon",
            font=FONT_CAPTION,
            bg_color=BG_SURFACE_ALT,
            fg_color=TEXT_MAIN,
            hover_color=BG_SURFACE_HOVER,
            hover_fg="#FFFFFF",
            border_color=BORDER_COLOR,
            hover_border=BORDER_ACTIVE,
            padx=8,
            pady=3,
            command=self._restart_daemon,
        )
        self.btn_daemon_toggle.pack(side=tk.RIGHT)

        self.daemon_desc_lbl = tk.Label(
            service_box,
            text=self._get_daemon_desc_text(),
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
            font=FONT_CHIP,
            fg=COLOR_CYAN,
            bg=BG_SURFACE,
        ).pack(side=tk.LEFT)
        tk.Label(
            name_hdr,
            text="(Optional • blank for unknown_1/2)",
            font=FONT_SMALL,
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
            highlightcolor=BORDER_ACTIVE,
        )
        self.name_entry.pack(fill=tk.X, ipady=4, pady=(3, 0))

        self.btn_enroll = ModernButton(
            btn_area,
            text="▶  Start Face Enrollment",
            bg_color=COLOR_CYAN,
            fg_color="#070B12",
            hover_color="#7DD3FC",
            hover_fg="#070B12",
            border_color=COLOR_CYAN_DIM,
            hover_border=COLOR_CYAN_HOVER,
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
            hover_color=BG_SURFACE_HOVER,
            hover_fg="#FFFFFF",
            border_color=BORDER_COLOR,
            hover_border=BORDER_ACTIVE,
            command=self._toggle_testing,
        )
        self.btn_test.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self.btn_save = ModernButton(
            row2,
            text="💾  Save Profile",
            bg_color=COLOR_EMERALD,
            fg_color="#070B12",
            hover_color="#6EE7B7",
            hover_fg="#070B12",
            border_color=COLOR_EMERALD_BORDER,
            hover_border=COLOR_EMERALD,
            disabled_bg=BG_SURFACE_ALT,
            disabled_fg="#64748B",
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
            self.profile_badge.configure(bg=COLOR_ROSE_BG, highlightbackground=COLOR_ROSE_BORDER)
            self.profile_status_lbl.configure(
                text=f"✕ NO PROFILE (0/{profiles.MAX_PROFILES})",
                fg=COLOR_ROSE,
                bg=COLOR_ROSE_BG,
            )
        else:
            self.profile_badge.configure(bg=COLOR_EMERALD_BG, highlightbackground=COLOR_EMERALD_BORDER)
            self.profile_status_lbl.configure(
                text=f"✓ ENROLLED ({count}/{profiles.MAX_PROFILES})",
                fg=COLOR_EMERALD,
                bg=COLOR_EMERALD_BG,
            )
            for name, arr in profile_dict.items():
                row = tk.Frame(self.profiles_list_frame, bg=BG_SURFACE_ALT, padx=8, pady=4, highlightthickness=1, highlightbackground=BORDER_COLOR)
                row.pack(fill=tk.X, pady=2)

                tk.Label(
                    row,
                    text=f"👤 {name} ({len(arr)} frames)",
                    font=FONT_BODY_BOLD,
                    fg=COLOR_CYAN,
                    bg=BG_SURFACE_ALT,
                ).pack(side=tk.LEFT)

                del_btn = ModernButton(
                    row,
                    text="🗑 Delete",
                    font=FONT_CHIP,
                    bg_color="#4C0519",
                    fg_color="#FECDD3",
                    hover_color="#881337",
                    hover_fg="#FFFFFF",
                    border_color=COLOR_ROSE_BORDER,
                    hover_border=COLOR_ROSE,
                    padx=6,
                    pady=2,
                    command=lambda n=name: self._delete_profile(n),
                )
                del_btn.pack(side=tk.RIGHT)

            self.profile_badge.configure(bg=COLOR_EMERALD_BG)
            self.profile_status_lbl.configure(
                text=f"✓ ENROLLED ({count}/{profiles.MAX_PROFILES})",
                fg=COLOR_EMERALD,
                bg=COLOR_EMERALD_BG,
            )

    def _delete_profile(self, name: str):
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

    _delete_profile_action = _delete_profile

    def _toggle_enrollment(self):
        if self.is_enrolling:
            self.is_enrolling = False
            self.btn_enroll.set_text("▶  Resume Enrollment")
            self.btn_enroll.set_colors(
                COLOR_CYAN, "#070B12", COLOR_CYAN_HOVER, "#070B12", border_color=COLOR_CYAN_DIM, hover_border=COLOR_CYAN_HOVER
            )
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
            self.btn_enroll.set_colors(
                COLOR_AMBER, "#070B12", COLOR_AMBER_TEXT, "#070B12", border_color=COLOR_AMBER_BORDER, hover_border=COLOR_AMBER
            )
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
            self.btn_enroll.set_colors(
                COLOR_CYAN, "#070B12", "#7DD3FC", "#070B12", border_color=COLOR_CYAN_DIM, hover_border=COLOR_CYAN_HOVER
            )
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
                pill.configure(
                    text="✓",
                    bg=COLOR_EMERALD_BG,
                    fg=COLOR_EMERALD_TEXT,
                    highlightbackground=COLOR_EMERALD_BORDER,
                )
            elif i == count:
                pill.configure(
                    text=str(i + 1),
                    bg=COLOR_CYAN,
                    fg="#070B12",
                    highlightbackground=COLOR_CYAN_HOVER,
                )
            else:
                pill.configure(
                    text=str(i + 1),
                    bg=BG_SURFACE_ALT,
                    fg=TEXT_MUTED,
                    highlightbackground=BORDER_COLOR,
                )

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
            self.btn_enroll.set_colors(
                COLOR_CYAN, "#070B12", "#7DD3FC", "#070B12", border_color=COLOR_CYAN_DIM, hover_border=COLOR_CYAN_HOVER
            )
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

    def _get_daemon_desc_text(self) -> str:
        if getattr(self.config, "idle_detection_enabled", True):
            return (
                f"Idle: {int(self.config.idle_timeout_seconds)}s | "
                f"Window: {int(self.config.face_check_window_seconds)}s | "
                f"Match: {self.config.min_match_percent:.0f}%"
            )
        return (
            f"Continuous: {int(self.config.unknown_face_timeout_seconds)}s | "
            f"Interval: {self.config.check_interval_seconds}s | "
            f"Match: {self.config.min_match_percent:.0f}%"
        )

    def _open_settings_dialog(self):
        SettingsDialog(self.root, self.config, on_save_callback=self._on_settings_saved)

    def _on_settings_saved(self, new_config: cfg.Config):
        self.config = new_config
        self.daemon_desc_lbl.configure(text=self._get_daemon_desc_text())
        if hasattr(self, "cam_badge_lbl"):
            self.cam_badge_lbl.configure(text=f"📹 Cam {self.config.camera_index}")
        self.liveness_tracker = LivenessTracker(
            window_size=self.config.liveness_window_size,
            min_pose_variance=self.config.liveness_min_pose_variance,
            blink_enabled=self.config.blink_detection_enabled,
            blink_close_ratio=self.config.blink_close_ratio,
            blink_min_duration=self.config.blink_min_duration,
            blink_min_frames=self.config.blink_min_frames,
        )
        self._restart_daemon()
        messagebox.showinfo(
            "Settings Saved",
            "Configuration successfully saved to config.yaml!\n\n"
            f"• User Inactivity Trigger: {int(self.config.idle_timeout_seconds)}s\n"
            f"• Face Verification Window: {int(self.config.face_check_window_seconds)}s\n"
            f"• Min Match Threshold: {self.config.min_match_percent:.0f}%\n\n"
            "The background auto-lock daemon has been reloaded.",
            parent=self.root,
        )

    def _update_daemon_status(self):
        def check():
            active = False
            try:
                res = subprocess.run(
                    ["systemctl", "--user", "is-active", "facelock-monitor"],
                    capture_output=True,
                    text=True,
                    timeout=3.0,
                )
                if res.stdout.strip() == "active":
                    active = True
                else:
                    pids_check = subprocess.run(
                        ["pgrep", "-f", "facelock.monitor"],
                        capture_output=True,
                        text=True,
                        timeout=2.0,
                    )
                    if pids_check.returncode == 0 and pids_check.stdout.strip():
                        active = True
            except Exception:
                active = False

            def apply():
                self.daemon_active = active
                if active:
                    self.service_badge.configure(bg=COLOR_EMERALD_BG, highlightbackground=COLOR_EMERALD_BORDER)
                    self.service_status_lbl.configure(
                        text="● DAEMON: ACTIVE", fg=COLOR_EMERALD, bg=COLOR_EMERALD_BG
                    )
                    self.btn_toggle_daemon.set_text("⏹  Stop Daemon")
                    self.btn_toggle_daemon.set_colors(
                        "#4C0519",
                        "#FECDD3",
                        "#881337",
                        "#FFFFFF",
                        border_color=COLOR_ROSE_BORDER,
                        hover_border=COLOR_ROSE,
                    )
                else:
                    self.service_badge.configure(bg=BG_SURFACE_ALT, highlightbackground=BORDER_COLOR)
                    self.service_status_lbl.configure(
                        text="○ DAEMON: STOPPED", fg=TEXT_MUTED, bg=BG_SURFACE_ALT
                    )
                    self.btn_toggle_daemon.set_text("▶  Start Daemon")
                    self.btn_toggle_daemon.set_colors(
                        COLOR_EMERALD_BG,
                        COLOR_EMERALD_TEXT,
                        "#047857",
                        "#A7F3D0",
                        border_color=COLOR_EMERALD_BORDER,
                        hover_border=COLOR_EMERALD,
                    )

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
        def do_restart():
            try:
                res = subprocess.run(["systemctl", "--user", "restart", "facelock-monitor"], check=False, timeout=5.0)
                if res.returncode != 0:
                    pids_check = subprocess.run(
                        ["pgrep", "-f", "facelock.monitor"],
                        capture_output=True,
                        text=True,
                        timeout=2.0,
                    )
                    if pids_check.returncode == 0:
                        subprocess.run(["pkill", "-f", "facelock.monitor"], check=False, timeout=3.0)
                        time.sleep(0.3)
                        subprocess.Popen([sys.executable, "-m", "facelock.monitor"])
                time.sleep(0.5)
            except Exception as e:
                logger.debug("Restart daemon error: %s", e)
            finally:
                self.root.after(0, self._update_daemon_status)

        threading.Thread(target=do_restart, daemon=True).start()


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
                    color = BGR_MINT if direction_matched else BGR_SKY
                elif self.is_testing:
                    color = BGR_MINT if (is_live and live_tex) else BGR_CORAL
                else:
                    color = BGR_SKY if (is_live and live_tex) else BGR_CORAL

                # Sleek glass corner reticle with subtle boundary
                cr = int(min(bw, bh) * 0.18)
                t = 2

                # Subtle glass boundary box (dim translucent tone)
                dim_color = (int(color[0] * 0.30), int(color[1] * 0.30), int(color[2] * 0.30))
                cv2.rectangle(frame, (x, y_box), (x + bw, y_box + bh), dim_color, 1, cv2.LINE_AA)

                # Glowing corner brackets
                cv2.line(frame, (x, y_box), (x + cr, y_box), color, t, cv2.LINE_AA)
                cv2.line(frame, (x, y_box), (x, y_box + cr), color, t, cv2.LINE_AA)
                cv2.line(frame, (x + bw, y_box), (x + bw - cr, y_box), color, t, cv2.LINE_AA)
                cv2.line(frame, (x + bw, y_box), (x + bw, y_box + cr), color, t, cv2.LINE_AA)
                cv2.line(frame, (x, y_box + bh), (x + cr, y_box + bh), color, t, cv2.LINE_AA)
                cv2.line(frame, (x, y_box + bh), (x, y_box + bh - cr), color, t, cv2.LINE_AA)
                cv2.line(frame, (x + bw, y_box + bh), (x + bw - cr, y_box + bh), color, t, cv2.LINE_AA)
                cv2.line(frame, (x + bw, y_box + bh), (x + bw, y_box + bh - cr), color, t, cv2.LINE_AA)

                # Subtle biometric landmark accents (glowing outer ring with white center)
                for i in range(5):
                    lx, ly = int(landmarks[i * 2]), int(landmarks[i * 2 + 1])
                    if i < 2 and blink_state.is_blinking:
                        cv2.circle(frame, (lx, ly), 6, BGR_MINT, 1, cv2.LINE_AA)
                        cv2.circle(frame, (lx, ly), 3, BGR_MINT, -1, cv2.LINE_AA)
                        cv2.circle(frame, (lx, ly), 1, (255, 255, 255), -1, cv2.LINE_AA)
                    else:
                        cv2.circle(frame, (lx, ly), 4, color, 1, cv2.LINE_AA)
                        cv2.circle(frame, (lx, ly), 2, (255, 255, 255), -1, cv2.LINE_AA)

                # Pose HUD pill in top-left of video
                if pose is not None:
                    p, y, r = pose
                    blinks_info = f" • Blinks: {blink_state.blink_count}" if blink_state.blink_count > 0 else ""
                    hud_pose = f"Pose: [{current_dir}]{blinks_info}"
                    draw_hud_pill(
                        frame,
                        hud_pose,
                        x=x,
                        y=max(22, y_box - 10),
                        fg=BGR_SKY,
                        bg=BGR_BG_PILL,
                    )

                # Visual blink flash badge
                if blink_state.is_blinking:
                    draw_hud_pill(
                        frame,
                        "Eye Blink Detected",
                        x=x,
                        y=max(46, y_box - 34),
                        fg=BGR_MINT,
                        bg=BGR_BG_MINT,
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
                        status_text = f"Step {count}/{self.config.enroll_frame_count} Captured! Preparing..."
                        status_fg = BGR_SKY
                        status_bg = BGR_BG_PILL
                    elif target_dir == "BLINK":
                        if blink_state.is_blinking:
                            status_text = "✓ Blink Verified"
                            status_fg = BGR_MINT
                            status_bg = BGR_BG_MINT
                        else:
                            status_text = "Action: Blink eyes naturally"
                            status_fg = BGR_SKY
                            status_bg = BGR_BG_PILL
                    elif target_dir == "SMILE":
                        if direction_matched:
                            if getattr(self.smile_detector, "teeth_detected", False):
                                status_text = "✓ Teeth & Smile Verified 😊"
                            else:
                                status_text = "✓ Smile Verified 😊"
                            status_fg = BGR_MINT
                            status_bg = BGR_BG_MINT
                        else:
                            status_text = "Action: Smile gently 😊"
                            status_fg = BGR_SKY
                            status_bg = BGR_BG_PILL
                    elif direction_matched:
                        status_text = f"Holding {target_dir} ({self.pose_hold_count}/{self.target_hold_needed})"
                        status_fg = BGR_MINT
                        status_bg = BGR_BG_MINT
                    else:
                        status_text = f"Action: {prompt_title} (Current: {current_dir})"
                        status_fg = BGR_AMBER
                        status_bg = BGR_BG_PILL

                    draw_hud_pill(
                        frame,
                        status_text,
                        x=max(16, x),
                        y=min(h - 16, y_box + bh + 32),
                        fg=status_fg,
                        bg=status_bg,
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

                    match_pct = best_match_res.match_percent if best_match_res else 0.0
                    self.meter_match.set_value(
                        match_pct, f"{match_pct:.1f}%", COLOR_EMERALD if matched else COLOR_ROSE
                    )

                    has_blinked = (self.test_challenge_blinks > 0) or (
                        (time.monotonic() - blink_state.last_blink_time) < 5.0
                    )

                    struct_pct = int(best_match_res.structure_score * 100) if best_match_res else 0
                    struct_tag = f" • Bone: {struct_pct}%" if struct_pct > 0 else ""

                    min_pct = getattr(self.config, "min_match_percent", 92.0)
                    if matched and is_live:
                        if has_blinked:
                            status_msg = f"✓ Verified: {matched_name} ({match_pct:.1f}% >= {min_pct:.0f}%{struct_tag})"
                            status_fg = BGR_MINT
                            status_bg = BGR_BG_MINT
                        else:
                            status_msg = f"Match: {matched_name} ({match_pct:.1f}%) • Blink to verify"
                            status_fg = BGR_SKY
                            status_bg = BGR_BG_PILL
                    else:
                        status_msg = f"Unknown Face ({match_pct:.1f}% < {min_pct:.0f}%)"
                        status_fg = BGR_CORAL
                        status_bg = BGR_BG_ROSE

                    draw_hud_pill(
                        frame,
                        status_msg,
                        x=max(16, x),
                        y=min(h - 16, y_box + bh + 32),
                        fg=status_fg,
                        bg=status_bg,
                    )

                    # Show cranial bone invariance badge if verified
                    if best_match_res and best_match_res.cranial_verified:
                        draw_hud_pill(
                            frame,
                            f"Cranial Invariant Match: {struct_pct}%",
                            x=max(16, x),
                            y=min(h - 16, y_box + bh + 58),
                            fg=BGR_SKY,
                            bg=BGR_BG_PILL,
                            font_scale=0.46,
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
