"""PAM (Pluggable Authentication Modules) integration manager for FaceLock.

Installs and manages the FaceLock biometric unlock hook in /etc/pam.d/gdm-password
and /etc/pam.d/sudo to allow native face unlocking.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

PAM_GDM_PATH = Path("/etc/pam.d/gdm-password")
PAM_SUDO_PATH = Path("/etc/pam.d/sudo")
AUTH_BIN_PATH = Path("/usr/local/bin/facelock-auth")

PAM_MARKER_START = "# >>> FaceLock Biometric Unlock >>>"
PAM_MARKER_END = "# <<< FaceLock Biometric Unlock <<<"
PAM_RULE = f"""{PAM_MARKER_START}
auth    sufficient      pam_exec.so quiet stdout {AUTH_BIN_PATH}
{PAM_MARKER_END}
"""


def is_pam_enabled(pam_file: Path = PAM_GDM_PATH) -> bool:
    """Check if FaceLock is hooked into the specified PAM service."""
    if not pam_file.exists():
        return False
    try:
        content = pam_file.read_text(encoding="utf-8")
        return (str(AUTH_BIN_PATH) in content) or (PAM_MARKER_START in content)
    except Exception:
        return False


def get_status() -> dict[str, bool]:
    """Return enabled status for GDM and sudo PAM services."""
    return {
        "gdm-password": is_pam_enabled(PAM_GDM_PATH),
        "sudo": is_pam_enabled(PAM_SUDO_PATH),
    }


def enable_pam(
    enable_gdm: bool = True,
    enable_sudo: bool = False,
) -> tuple[bool, str]:
    """Install FaceLock PAM hook into target services."""
    if os.geteuid() != 0:
        return False, "Root privileges required. Please run with `sudo`."

    ensure_auth_wrapper()

    targets = []
    if enable_gdm and PAM_GDM_PATH.exists():
        targets.append(PAM_GDM_PATH)
    if enable_sudo and PAM_SUDO_PATH.exists():
        targets.append(PAM_SUDO_PATH)

    if not targets:
        return False, "No eligible PAM service files found in /etc/pam.d/."

    modified: list[str] = []
    for pam_file in targets:
        if is_pam_enabled(pam_file):
            continue

        backup_file = pam_file.with_suffix(".facelock.bak")
        if not backup_file.exists():
            shutil.copy2(pam_file, backup_file)

        content = pam_file.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        inserted = False

        # Insert before @include common-auth or pam_unix
        new_lines = []
        for line in lines:
            if not inserted and (
                "@include common-auth" in line
                or "pam_unix.so" in line
                or "pam_gnome_keyring.so" in line
            ):
                new_lines.append(PAM_RULE)
                inserted = True
            new_lines.append(line)

        if not inserted:
            new_lines.insert(0, PAM_RULE)

        pam_file.write_text("".join(new_lines), encoding="utf-8")
        modified.append(pam_file.name)

    if modified:
        return True, f"Successfully enabled FaceLock unlock in: {', '.join(modified)}."
    return True, "FaceLock unlock is already enabled in selected PAM services."


def disable_pam() -> tuple[bool, str]:
    """Remove FaceLock PAM hooks and restore backups if available."""
    if os.geteuid() != 0:
        return False, "Root privileges required. Please run with `sudo`."

    targets = [PAM_GDM_PATH, PAM_SUDO_PATH]
    restored: list[str] = []

    for pam_file in targets:
        if not pam_file.exists() or not is_pam_enabled(pam_file):
            continue

        backup_file = pam_file.with_suffix(".facelock.bak")
        if backup_file.exists():
            shutil.copy2(backup_file, pam_file)
            restored.append(f"{pam_file.name} (restored from backup)")
        else:
            # Strip FaceLock block manually
            content = pam_file.read_text(encoding="utf-8")
            lines = content.splitlines(keepends=True)
            new_lines = []
            skipping = False
            for line in lines:
                if PAM_MARKER_START in line:
                    skipping = True
                    continue
                if PAM_MARKER_END in line:
                    skipping = False
                    continue
                if not skipping and str(AUTH_BIN_PATH) not in line:
                    new_lines.append(line)
            pam_file.write_text("".join(new_lines), encoding="utf-8")
            restored.append(pam_file.name)

    if restored:
        return True, f"Disabled FaceLock in: {', '.join(restored)}."
    return True, "FaceLock was not active in any PAM service."


def ensure_auth_wrapper() -> Path:
    """Create or update /usr/local/bin/facelock-auth dispatcher executable."""
    AUTH_BIN_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Detect python environment
    current_python = sys.executable
    script_content = f"""#!/usr/bin/env bash
# FaceLock PAM Authenticator Dispatcher

if [[ -x /opt/facelock/venv/bin/python ]]; then
    exec /opt/facelock/venv/bin/python -m facelock.auth "$@"
elif [[ -x /opt/facelock/bin/python ]]; then
    exec /opt/facelock/bin/python -m facelock.auth "$@"
elif [[ -x "{current_python}" ]]; then
    exec "{current_python}" -m facelock.auth "$@"
else
    exec python3 -m facelock.auth "$@"
fi
"""
    if os.geteuid() == 0:
        AUTH_BIN_PATH.write_text(script_content, encoding="utf-8")
        AUTH_BIN_PATH.chmod(0o755)

    return AUTH_BIN_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description="FaceLock PAM Auto-Unlock Configuration Manager")
    parser.add_argument("action", choices=["status", "enable", "disable"], default="status", nargs="?")
    parser.add_argument("--sudo", action="store_true", help="Also enable face authentication for sudo")
    args = parser.parse_args()

    if args.action == "status":
        status = get_status()
        print("\n" + "=" * 50)
        print(" 🔐 FACELOCK PAM AUTO-UNLOCK STATUS")
        print("=" * 50)
        print(f" • Lock Screen (GDM): {'✅ ENABLED' if status['gdm-password'] else '❌ DISABLED'}")
        print(f" • Sudo Terminal Auth: {'✅ ENABLED' if status['sudo'] else '❌ DISABLED'}")
        print(f" • Authenticator Hook: {AUTH_BIN_PATH}")
        print("=" * 50)
        if not status["gdm-password"]:
            print("\nTo enable face auto-unlock at the lock screen (Super+L):")
            print("  sudo facelock-pam enable   (or: sudo make pam-enable)\n")
        else:
            print("\nFace auto-unlock is active! Wake your lock screen to unlock with your face.\n")
        return

    if args.action == "enable":
        ok, msg = enable_pam(enable_gdm=True, enable_sudo=args.sudo)
        print(f"\n{msg}\n")
        if not ok:
            sys.exit(1)
        return

    if args.action == "disable":
        ok, msg = disable_pam()
        print(f"\n{msg}\n")
        if not ok:
            sys.exit(1)
        return


if __name__ == "__main__":
    main()
