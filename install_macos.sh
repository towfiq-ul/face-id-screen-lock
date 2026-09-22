#!/usr/bin/env bash
# Installs FaceLock on macOS (Intel and Apple Silicon):
#   /opt/facelock (or ~/.local/opt/facelock) - virtual environment & installed package
#   /usr/local/bin (or /opt/homebrew/bin)    - symlinked CLI commands
#   ~/Library/LaunchAgents/com.facelock.monitor.plist - background auto-lock daemon
set -euo pipefail

# 1. Visual Banner
cat <<'EOF'
  ███████╗ █████╗  ██████╗███████╗██╗      ██████╗  ██████╗██╗  ██╗
  ██╔════╝██╔══██╗██╔════╝██╔════╝██║     ██╔═══██╗██╔════╝██║ ██╔╝
  █████╗  ███████║██║     █████╗  ██║     ██║   ██║██║     █████═╝ 
  ██╔══╝  ██╔══██║██║     ██╔══╝  ██║     ██║   ██║██║     ██╔═██╗ 
  ██║     ██║  ██║╚██████╗███████╗███████╗╚██████╔╝╚██████╗██║  ██╗
  ╚═╝     ╚═╝  ╚═╝ ╚═════╝╚══════╝╚══════╝ ╚═════╝  ╚═════╝╚═╝  ╚═╝
           ADVANCED BIOMETRIC AUTO-LOCK & ANTI-SPOOFING (macOS)
EOF
echo

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Error: This installer is intended for macOS only." >&2
    exit 1
fi

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

# 2. Determine target user and paths
REAL_USER="${USER:-$(whoami)}"
REAL_HOME="$HOME"

# On macOS, determine best bin directory
if [[ -d "/usr/local/bin" && -w "/usr/local/bin" ]]; then
    BIN_DIR="/usr/local/bin"
elif [[ -d "/opt/homebrew/bin" && -w "/opt/homebrew/bin" ]]; then
    BIN_DIR="/opt/homebrew/bin"
else
    BIN_DIR="$REAL_HOME/.local/bin"
    mkdir -p "$BIN_DIR"
fi

PREFIX="$REAL_HOME/.local/opt/facelock"
PLIST_LABEL="com.facelock.monitor"
PLIST_DST="$REAL_HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
LOG_DIR="$REAL_HOME/Library/Logs/FaceLock"

echo "This will install facelock for user '$REAL_USER':"
echo "  environment -> $PREFIX"
echo "  commands    -> $BIN_DIR/facelock-gui, $BIN_DIR/facelock-monitor, etc."
echo "  launchd     -> $PLIST_DST"
echo

reply="$(ask_prompt "Proceed with installation? [y/N]" "N")"
[[ "$reply" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }

# 3. Check Python 3 and Tkinter
PYTHON_CMD=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" >/dev/null 2>&1; then
        if "$cmd" -c "import venv" >/dev/null 2>&1; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    echo "Error: Python 3 with 'venv' is required. Please install via Homebrew:" >&2
    echo "  brew install python@3.12 python-tk@3.12" >&2
    exit 1
fi

# 4. Source repo detection
SCRIPT_SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
REPO_DIR="$SCRIPT_SOURCE_DIR"

print_progress 20 "Preparing installation environment at $PREFIX..."
mkdir -p "$PREFIX" "$LOG_DIR" "$(dirname "$PLIST_DST")"

print_progress 40 "Creating Python virtual environment..."
"$PYTHON_CMD" -m venv "$PREFIX/venv"

print_progress 55 "Upgrading pip..."
"$PREFIX/venv/bin/pip" install --upgrade pip -q

print_progress 75 "Installing FaceLock and dependencies..."
"$PREFIX/venv/bin/pip" install "$REPO_DIR" -q

print_progress 85 "Symlinking executable commands to $BIN_DIR..."
for script in facelock-enroll facelock-gui facelock-monitor facelock-calibrate facelock-test facelock-remove; do
    ln -sf "$PREFIX/venv/bin/$script" "$BIN_DIR/$script"
done

print_progress 90 "Configuring launchd LaunchAgent..."
sed -e "s|@BIN_DIR@|$BIN_DIR|g" -e "s|@LOG_DIR@|$LOG_DIR|g" \
    "$REPO_DIR/packaging/com.facelock.monitor.plist" > "$PLIST_DST"

print_progress 100 "Installation completed successfully!"
echo

# 5. Profile check & Launch Wizard
FACE_FILE="$REAL_HOME/.local/share/facelock/known_face.npy"
if [[ -f "$FACE_FILE" ]]; then
    echo "==> Existing enrolled face profile detected."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load "$PLIST_DST" 2>/dev/null || true
    echo "==> FaceLock auto-lock monitor daemon loaded in launchd!"
else
    echo
    gui_reply="$(ask_prompt "No enrolled face found. Launch Face Setup GUI now? [Y/n]" "Y")"
    if [[ "$gui_reply" =~ ^[Nn]$ ]]; then
        echo "Run 'facelock-gui' or 'facelock-enroll' anytime to enroll your face."
    else
        echo "Launching FaceLock Setup GUI..."
        "$BIN_DIR/facelock-gui" || "$BIN_DIR/facelock-enroll"
        launchctl unload "$PLIST_DST" 2>/dev/null || true
        launchctl load "$PLIST_DST" 2>/dev/null || true
    fi
fi

# 6. Uninstaller script
cat <<EOF > "$PREFIX/uninstall.sh"
#!/usr/bin/env bash
set -euo pipefail
echo "==> Unloading launchd agent"
launchctl unload "$PLIST_DST" 2>/dev/null || true
rm -f "$PLIST_DST"

echo "==> Removing commands from $BIN_DIR"
for script in facelock-enroll facelock-gui facelock-monitor facelock-calibrate facelock-test facelock-remove; do
    rm -f "$BIN_DIR/\$script"
done

echo "==> Removing $PREFIX"
rm -rf "$PREFIX"

echo "FaceLock uninstalled successfully."
EOF
chmod +x "$PREFIX/uninstall.sh"

echo
echo "=========================================================================="
echo " FaceLock is installed on macOS!"
echo
echo " IMPORTANT PERMISSION NOTICE (macOS):"
echo "   1. Camera Access: When launching the GUI or monitor, approve the"
echo "      camera permission prompt (or check System Settings -> Privacy -> Camera)."
echo "   2. Screen Lock: FaceLock locks the screen automatically when you are away."
echo
echo " Quick commands:"
echo "   facelock-gui      : Open the graphical setup wizard & live camera HUD"
echo "   facelock-test     : Test live face matching with interactive HUD"
echo "   facelock-enroll   : Enroll face via terminal"
echo "   facelock-monitor  : Run background daemon in foreground for testing"
echo "   Uninstall anytime : $PREFIX/uninstall.sh"
echo "=========================================================================="
