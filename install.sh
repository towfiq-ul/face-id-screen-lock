#!/usr/bin/env bash
# Installs FaceLock system-wide, following standard Linux (FHS) paths:
#   /opt/facelock              - self-contained venv + installed package
#   /usr/local/bin/facelock-*  - symlinks onto PATH (facelock-gui, facelock-enroll, facelock-monitor)
#   ~<user>/.config/systemd/user/facelock-monitor.service - per-user service unit
#
# Supports both:
#   1. One-line curl install over the internet:
#      curl -fsSL https://raw.githubusercontent.com/towfiq-ul/face-id-screen-lock/develop/install.sh | bash
#   2. Local execution from within cloned repo:
#      sudo ./install.sh
set -euo pipefail

# 1. Visual Banner
cat <<'EOF'
  ███████╗ █████╗  ██████╗███████╗██╗      ██████╗  ██████╗██╗  ██╗
  ██╔════╝██╔══██╗██╔════╝██╔════╝██║     ██╔═══██╗██╔════╝██║ ██╔╝
  █████╗  ███████║██║     █████╗  ██║     ██║   ██║██║     █████═╝ 
  ██╔══╝  ██╔══██║██║     ██╔══╝  ██║     ██║   ██║██║     ██╔═██╗ 
  ██║     ██║  ██║╚██████╗███████╗███████╗╚██████╔╝╚██████╗██║  ██╗
  ╚═╝     ╚═╝  ╚═╝ ╚═════╝╚══════╝╚══════╝ ╚═════╝  ╚═════╝╚═╝  ╚═╝
           ADVANCED BIOMETRIC AUTO-LOCK & ANTI-SPOOFING
EOF
echo

print_progress() {
    local pct="$1"
    local msg="$2"
    local filled=$((pct / 5))
    local empty=$((20 - filled))
    local bar=""
    for ((i=0; i<filled; i++)); do bar+="#"; done
    for ((i=0; i<empty; i++)); do bar+="-"; done
    printf "\r[%3d%%] [%-20s] %s\n" "$pct" "$bar" "$msg"
}

ask_prompt() {
    local query="$1"
    local default_ans="${2:-N}"
    local reply=""
    if [[ -e /dev/tty ]]; then
        read -rp "$query " reply </dev/tty || reply="$default_ans"
    else
        reply="$default_ans"
    fi
    echo "$reply"
}

# 2. Determine target desktop user and privileges
if [[ -n "${SUDO_USER:-}" ]]; then
    REAL_USER="$SUDO_USER"
elif [[ $EUID -eq 0 ]]; then
    REAL_USER="$(logname 2>/dev/null || who | awk '{print $1}' | head -n1 || echo "root")"
else
    REAL_USER="$(whoami)"
fi

REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
REAL_UID="$(id -u "$REAL_USER")"

if [[ $EUID -ne 0 ]]; then
    if ! command -v sudo >/dev/null 2>&1; then
        echo "Error: 'sudo' command is required to install system files to /opt and /usr/local/bin." >&2
        exit 1
    fi
    # Request sudo credentials upfront
    sudo -v || exit 1
    SUDO="sudo"
else
    SUDO=""
fi

PREFIX=/opt/facelock
BIN_DIR=/usr/local/bin
UNIT_NAME=facelock-monitor.service
UNIT_DST="$REAL_HOME/.config/systemd/user/$UNIT_NAME"

echo "This will install facelock for user '$REAL_USER':"
echo "  code + venv -> $PREFIX"
echo "  commands    -> $BIN_DIR/facelock-enroll, $BIN_DIR/facelock-gui, $BIN_DIR/facelock-monitor"
echo "  service     -> $UNIT_DST"

reply="$(ask_prompt "Proceed with installation? [y/N]" "N")"
[[ "$reply" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }

# 3. Source repository resolution (local repo vs internet curl)
SCRIPT_SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
CLEANUP_REPO=false
TMP_DIR=""

if [[ -n "$SCRIPT_SOURCE_DIR" && -f "$SCRIPT_SOURCE_DIR/pyproject.toml" ]]; then
    REPO_DIR="$SCRIPT_SOURCE_DIR"
else
    TMP_DIR="$(mktemp -d /tmp/facelock-install-XXXXXX)"
    CLEANUP_REPO=true
    REPO_URL="${FACELOCK_REPO_URL:-https://github.com/towfiq-ul/face-id-screen-lock.git}"
    BRANCH="${FACELOCK_BRANCH:-develop}"

    print_progress 5 "Downloading FaceLock source code from repository..."
    if command -v git >/dev/null 2>&1; then
        git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$TMP_DIR" -q 2>/dev/null || \
        git clone --depth 1 "$REPO_URL" "$TMP_DIR" -q
    else
        curl -fsSL "https://github.com/towfiq-ul/face-id-screen-lock/archive/refs/heads/${BRANCH}.tar.gz" | tar -xz -C "$TMP_DIR" --strip-components=1
    fi
    REPO_DIR="$TMP_DIR"
fi

cleanup() {
    if [[ "$CLEANUP_REPO" = true && -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then
        if [[ -n "${SUDO:-}" ]] && command -v sudo >/dev/null 2>&1; then
            $SUDO rm -rf "$TMP_DIR" 2>/dev/null || rm -rf "$TMP_DIR" 2>/dev/null || true
        else
            rm -rf "$TMP_DIR" 2>/dev/null || true
        fi
    fi
}
trap cleanup EXIT

# 4. Check system dependencies
if ! python3 -m venv --help >/dev/null 2>&1; then
    echo "python3's venv module isn't available. Install it first, e.g.:" >&2
    echo "  sudo apt install python3-venv" >&2
    exit 1
fi

print_progress 15 "Preparing installation directory at $PREFIX..."
$SUDO mkdir -p "$PREFIX"

print_progress 30 "Creating isolated Python virtual environment..."
$SUDO python3 -m venv "$PREFIX/venv"

print_progress 45 "Upgrading pip package manager..."
$SUDO "$PREFIX/venv/bin/pip" install --upgrade pip -q

print_progress 65 "Installing FaceLock and AI models into $PREFIX/venv..."
$SUDO "$PREFIX/venv/bin/pip" install "$REPO_DIR" -q
$SUDO chmod -R a+rX "$PREFIX"

print_progress 80 "Linking executable commands to $BIN_DIR..."
$SUDO ln -sf "$PREFIX/venv/bin/facelock-enroll" "$BIN_DIR/facelock-enroll"
$SUDO ln -sf "$PREFIX/venv/bin/facelock-gui" "$BIN_DIR/facelock-gui"
$SUDO ln -sf "$PREFIX/venv/bin/facelock-monitor" "$BIN_DIR/facelock-monitor"
$SUDO ln -sf "$PREFIX/venv/bin/facelock-calibrate" "$BIN_DIR/facelock-calibrate"
$SUDO ln -sf "$PREFIX/venv/bin/facelock-test" "$BIN_DIR/facelock-test"
$SUDO ln -sf "$PREFIX/venv/bin/facelock-remove" "$BIN_DIR/facelock-remove"
$SUDO ln -sf "$PREFIX/venv/bin/facelock-pam" "$BIN_DIR/facelock-pam"
$SUDO ln -sf "$PREFIX/venv/bin/facelock-auth" "$BIN_DIR/facelock-auth"

print_progress 85 "Installing desktop launcher and application icons..."
if [[ -f "$REPO_DIR/packaging/install_desktop.py" ]]; then
    $SUDO "$PREFIX/venv/bin/python" "$REPO_DIR/packaging/install_desktop.py" --install --system --repo-dir "$REPO_DIR" || true
else
    $SUDO mkdir -p /usr/share/applications /usr/share/pixmaps
    [[ -f "$REPO_DIR/packaging/facelock.desktop" ]] && $SUDO install -m 644 "$REPO_DIR/packaging/facelock.desktop" /usr/share/applications/facelock.desktop
    [[ -f "$REPO_DIR/facelock/assets/logo.png" ]] && $SUDO install -m 644 "$REPO_DIR/facelock/assets/logo.png" /usr/share/pixmaps/facelock.png
    command -v update-desktop-database >/dev/null 2>&1 && $SUDO update-desktop-database /usr/share/applications 2>/dev/null || true
fi

print_progress 90 "Configuring systemd --user service for $REAL_USER..."
if [[ $EUID -eq 0 ]]; then
    sudo -u "$REAL_USER" mkdir -p "$(dirname "$UNIT_DST")"
else
    mkdir -p "$(dirname "$UNIT_DST")"
fi

if [[ -f "$REPO_DIR/packaging/$UNIT_NAME" ]]; then
    sed "s|@VENV_BIN@|$BIN_DIR|" "$REPO_DIR/packaging/$UNIT_NAME" | if [[ $EUID -eq 0 ]]; then sudo -u "$REAL_USER" tee "$UNIT_DST" >/dev/null; else tee "$UNIT_DST" >/dev/null; fi
else
    cat <<SERVICE_EOF | if [[ $EUID -eq 0 ]]; then sudo -u "$REAL_USER" tee "$UNIT_DST" >/dev/null; else tee "$UNIT_DST" >/dev/null; fi
[Unit]
Description=Facelock webcam auto-lock monitor
After=graphical-session.target

[Service]
ExecStart=$BIN_DIR/facelock-monitor
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
SERVICE_EOF
fi

if [[ $EUID -eq 0 ]]; then
    sudo -u "$REAL_USER" XDG_RUNTIME_DIR="/run/user/$REAL_UID" systemctl --user daemon-reload
else
    XDG_RUNTIME_DIR="/run/user/$REAL_UID" systemctl --user daemon-reload
fi

print_progress 100 "Installation completed successfully!"
echo

# 5. PAM Biometric Auto-Unlock Setup
echo
echo "==> Configuring Biometric Auto-Unlock for Lock Screen (Super+L)..."
pam_reply="$(ask_prompt "Enable Face Auto-Unlock on lock screen (Super+L) via PAM? [Y/n]" "Y")"
if [[ ! "$pam_reply" =~ ^[Nn]$ ]]; then
    $SUDO "$PREFIX/venv/bin/python" -m facelock.pam enable || true
    echo "==> Biometric auto-unlock enabled for lock screen!"
else
    echo "==> Skipped PAM unlock. You can enable it anytime via 'sudo facelock-pam enable'."
fi

# 6. Profile check & Launch Wizard
FACE_FILE="$REAL_HOME/.local/share/facelock/known_face.npy"
if [[ -f "$FACE_FILE" ]]; then
    echo "==> Existing enrolled face profile detected."
    if [[ $EUID -eq 0 ]]; then
        sudo -u "$REAL_USER" XDG_RUNTIME_DIR="/run/user/$REAL_UID" systemctl --user enable --now "$UNIT_NAME"
    else
        XDG_RUNTIME_DIR="/run/user/$REAL_UID" systemctl --user enable --now "$UNIT_NAME"
    fi
    echo "==> FaceLock auto-lock monitor is active!"
else
    echo
    gui_reply="$(ask_prompt "No enrolled face found. Launch Face Setup GUI now? [Y/n]" "Y")"
    if [[ "$gui_reply" =~ ^[Nn]$ ]]; then
        if [[ $EUID -eq 0 ]]; then
            sudo -u "$REAL_USER" XDG_RUNTIME_DIR="/run/user/$REAL_UID" systemctl --user enable "$UNIT_NAME"
        else
            XDG_RUNTIME_DIR="/run/user/$REAL_UID" systemctl --user enable "$UNIT_NAME"
        fi
        echo "Service enabled. Run 'facelock-gui' or 'facelock-enroll' as $REAL_USER anytime to set up your face."
    else
        echo "Launching FaceLock Setup GUI..."
        DISP="${DISPLAY:-:0}"
        XAUTH="${XAUTHORITY:-$REAL_HOME/.Xauthority}"
        if [[ $EUID -eq 0 ]]; then
            sudo -u "$REAL_USER" -H DISPLAY="$DISP" XAUTHORITY="$XAUTH" "$BIN_DIR/facelock-gui" 2>/dev/null || \
            sudo -u "$REAL_USER" -H "$BIN_DIR/facelock-enroll"
            sudo -u "$REAL_USER" XDG_RUNTIME_DIR="/run/user/$REAL_UID" systemctl --user enable --now "$UNIT_NAME" 2>/dev/null || true
        else
            DISPLAY="$DISP" "$BIN_DIR/facelock-gui" 2>/dev/null || "$BIN_DIR/facelock-enroll"
            XDG_RUNTIME_DIR="/run/user/$REAL_UID" systemctl --user enable --now "$UNIT_NAME" 2>/dev/null || true
        fi
    fi
fi

echo "==> Generating uninstaller at $PREFIX/uninstall.sh"
$SUDO tee "$PREFIX/uninstall.sh" >/dev/null <<EOF
#!/usr/bin/env bash
# Generated by install.sh — reverses exactly what was installed.
set -euo pipefail

if [[ \$EUID -ne 0 ]]; then
    echo "Run this with sudo: sudo $PREFIX/uninstall.sh" >&2
    exit 1
fi

echo "==> Disabling FaceLock PAM integration"
"$PREFIX/venv/bin/python" -m facelock.pam disable 2>/dev/null || true

echo "==> Stopping and removing systemd --user service for $REAL_USER"
sudo -u "$REAL_USER" XDG_RUNTIME_DIR="/run/user/$REAL_UID" systemctl --user disable --now "$UNIT_NAME" 2>/dev/null || true
rm -f "$UNIT_DST"
sudo -u "$REAL_USER" XDG_RUNTIME_DIR="/run/user/$REAL_UID" systemctl --user daemon-reload 2>/dev/null || true

echo "==> Removing commands from $BIN_DIR"
rm -f "$BIN_DIR/facelock-enroll" "$BIN_DIR/facelock-gui" "$BIN_DIR/facelock-monitor" "$BIN_DIR/facelock-calibrate" "$BIN_DIR/facelock-test" "$BIN_DIR/facelock-remove" "$BIN_DIR/facelock-pam" "$BIN_DIR/facelock-auth"

echo "==> Removing desktop entry and application icons"
rm -f /usr/share/applications/facelock.desktop
rm -f /usr/share/pixmaps/facelock.png
for s in 16 24 32 48 64 128 256 512; do
    rm -f "/usr/share/icons/hicolor/\${s}x\${s}/apps/facelock.png"
done
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true

echo "==> Removing $PREFIX"
rm -rf "$PREFIX"

echo "Note: your enrolled face and config were preserved at:"
echo "  $REAL_HOME/.local/share/facelock/"
echo "  $REAL_HOME/.config/facelock/"
echo "Remove those manually if you desire a completely clean uninstall."
EOF
$SUDO chmod +x "$PREFIX/uninstall.sh"

echo
echo "=========================================================================="
echo " FaceLock is installed! Quick commands:"
echo "   facelock-gui      : Open the graphical setup wizard & live camera HUD"
echo "   facelock-test     : Test live face matching with interactive HUD"
echo "   facelock-pam      : Check or configure lock-screen auto-unlock (Super+L)"
echo "   facelock-enroll   : Enroll face via terminal"
echo "   facelock-monitor  : Run background daemon in foreground for testing"
echo "   Uninstall anytime : sudo $PREFIX/uninstall.sh"
echo "=========================================================================="
