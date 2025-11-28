#!/usr/bin/env python3
"""
Cron Watchdog - Monitors and restores cron jobs if deleted.

This module provides a watchdog service that ensures the NextDNS blocker
cron jobs remain installed and running. If someone deletes the cron jobs,
the watchdog will automatically restore them.
"""

import os
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Import shared utilities
from common import (
    LOG_DIR,
    AUDIT_LOG_FILE,
    SECURE_FILE_MODE,
    ensure_log_dir,
    audit_log as _base_audit_log,
    write_secure_file,
    read_secure_file,
)


# =============================================================================
# CONFIGURATION & CONSTANTS
# =============================================================================

INSTALL_DIR = Path(__file__).parent.absolute()
DISABLED_FILE = LOG_DIR / ".watchdog_disabled"


def audit_log(action: str, detail: str = "") -> None:
    """Wrapper for audit_log with WD prefix."""
    _base_audit_log(action, detail, prefix="WD")

# Cron job definitions
CRON_SYNC = f"*/2 * * * * cd {INSTALL_DIR} && ./blocker.bin sync >> {LOG_DIR}/cron.log 2>&1"
CRON_WATCHDOG = f"* * * * * cd {INSTALL_DIR} && ./watchdog.bin check >> {LOG_DIR}/wd.log 2>&1"

# Subprocess timeout in seconds
SUBPROCESS_TIMEOUT = 60


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class WatchdogError(Exception):
    """Base exception for Watchdog errors."""
    pass


class CronError(WatchdogError):
    """Raised when cron operations fail."""
    pass


# =============================================================================
# DISABLED STATE MANAGEMENT
# =============================================================================

def is_disabled() -> bool:
    """
    Check if watchdog is temporarily or permanently disabled.

    Returns:
        True if disabled, False otherwise
    """
    content = read_secure_file(DISABLED_FILE)
    if not content:
        return False

    try:
        if content == "permanent":
            return True

        disabled_until = datetime.fromisoformat(content)
        if datetime.now() < disabled_until:
            return True

        # Expired, clean up
        _remove_disabled_file()
        return False
    except ValueError:
        return False


def get_disabled_remaining() -> str:
    """
    Get remaining disabled time as a human-readable string.

    Returns:
        String like "5 min", "permanently", or empty string if not disabled
    """
    content = read_secure_file(DISABLED_FILE)
    if not content:
        return ""

    try:
        if content == "permanent":
            return "permanently"

        disabled_until = datetime.fromisoformat(content)
        remaining = disabled_until - datetime.now()

        if remaining.total_seconds() <= 0:
            _remove_disabled_file()
            return ""

        mins = int(remaining.total_seconds() // 60)
        return f"{mins} min" if mins > 0 else "< 1 min"
    except ValueError:
        return ""


def _remove_disabled_file() -> None:
    """Remove the disabled file safely."""
    try:
        DISABLED_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def set_disabled(minutes: Optional[int] = None) -> None:
    """
    Disable the watchdog temporarily or permanently.

    Args:
        minutes: Number of minutes to disable, or None for permanent
    """
    if minutes:
        disabled_until = datetime.now().replace(microsecond=0) + timedelta(minutes=minutes)
        write_secure_file(DISABLED_FILE, disabled_until.isoformat())
        audit_log("WD_DISABLED", f"{minutes} minutes until {disabled_until.isoformat()}")
    else:
        write_secure_file(DISABLED_FILE, "permanent")
        audit_log("WD_DISABLED", "permanent")


def clear_disabled() -> bool:
    """
    Re-enable the watchdog by removing disabled state.

    Returns:
        True if was disabled and now enabled, False if wasn't disabled
    """
    if DISABLED_FILE.exists():
        _remove_disabled_file()
        audit_log("WD_ENABLED", "Manual enable")
        return True
    return False


# =============================================================================
# CRON MANAGEMENT
# =============================================================================

def get_crontab() -> str:
    """
    Get the current user's crontab contents.

    Returns:
        Crontab contents as string, or empty string if no crontab
    """
    try:
        result = subprocess.run(
            ['crontab', '-l'],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT
        )
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        return ""


def set_crontab(content: str) -> bool:
    """
    Set the user's crontab contents.

    Args:
        content: New crontab contents

    Returns:
        True if successful, False otherwise
    """
    try:
        process = subprocess.Popen(
            ['crontab', '-'],
            stdin=subprocess.PIPE,
            text=True
        )
        process.communicate(input=content, timeout=SUBPROCESS_TIMEOUT)
        return process.returncode == 0
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        return False


def has_sync_cron(crontab: str) -> bool:
    """Check if sync cron job is present."""
    return "blocker.bin sync" in crontab


def has_watchdog_cron(crontab: str) -> bool:
    """Check if watchdog cron job is present."""
    return "watchdog.bin check" in crontab


def filter_our_cron_jobs(crontab: str) -> list:
    """
    Remove our cron jobs from crontab, keeping other entries.

    Args:
        crontab: Current crontab contents

    Returns:
        List of crontab lines without our jobs
    """
    return [
        line for line in crontab.split('\n')
        if 'blocker.bin' not in line
        and 'watchdog.bin' not in line
        and line.strip()
    ]


# =============================================================================
# CLI COMMAND HANDLERS
# =============================================================================

def cmd_check() -> int:
    """
    Check and restore cron jobs if missing.

    Returns:
        Exit code (0 for success)
    """
    if is_disabled():
        remaining = get_disabled_remaining()
        print(f"  watchdog disabled ({remaining})")
        return 0

    crontab = get_crontab()
    restored = False

    # Check and restore sync cron
    if not has_sync_cron(crontab):
        audit_log("CRON_DELETED", "Sync cron missing")
        new_crontab = crontab.strip()
        new_crontab = (new_crontab + "\n" if new_crontab else "") + CRON_SYNC + "\n"
        if set_crontab(new_crontab):
            print("  sync cron restored")
            restored = True

    # Check and restore watchdog cron
    if not has_watchdog_cron(crontab):
        audit_log("WD_CRON_DELETED", "Watchdog cron missing")
        # Re-fetch crontab in case sync was just added
        crontab = get_crontab()
        new_crontab = crontab.strip()
        new_crontab = (new_crontab + "\n" if new_crontab else "") + CRON_WATCHDOG + "\n"
        if set_crontab(new_crontab):
            print("  watchdog cron restored")
            restored = True

    # Run sync if cron was restored
    if restored:
        try:
            subprocess.run(
                [str(INSTALL_DIR / 'blocker.bin'), 'sync'],
                timeout=SUBPROCESS_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            audit_log("SYNC_TIMEOUT", "Sync took >60s after restore")
        except (OSError, subprocess.SubprocessError):
            pass  # Best effort

    return 0


def cmd_install() -> int:
    """
    Install sync and watchdog cron jobs.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    crontab = get_crontab()
    lines = filter_our_cron_jobs(crontab)
    lines.extend([CRON_SYNC, CRON_WATCHDOG])

    if set_crontab('\n'.join(lines) + '\n'):
        audit_log("CRON_INSTALLED", "Manual install")
        print("\n  cron installed")
        print("    sync       every 2 min")
        print("    watchdog   every 1 min\n")
        return 0
    else:
        print("  error: cron install failed")
        return 1


def cmd_uninstall() -> int:
    """
    Remove cron jobs.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    crontab = get_crontab()
    lines = filter_our_cron_jobs(crontab)
    new_content = '\n'.join(lines) + '\n' if lines else ''

    if set_crontab(new_content):
        audit_log("CRON_UNINSTALLED", "Manual uninstall")
        print("\n  Cron jobs removed\n")
        return 0
    else:
        print("  error: failed to remove cron jobs")
        return 1


def cmd_status() -> int:
    """
    Display current cron job status.

    Returns:
        Exit code (0 for success)
    """
    crontab = get_crontab()
    has_sync = has_sync_cron(crontab)
    has_wd = has_watchdog_cron(crontab)
    disabled_remaining = get_disabled_remaining()

    print("\n  cron")
    print("  ----")
    print(f"    sync       {'ok' if has_sync else 'missing'}")
    print(f"    watchdog   {'ok' if has_wd else 'missing'}")

    if disabled_remaining:
        print(f"\n  watchdog: DISABLED ({disabled_remaining})")
    else:
        status = 'active' if (has_sync and has_wd) else 'compromised'
        print(f"\n  status: {status}")
    print()

    return 0


def cmd_disable(minutes: Optional[int] = None) -> int:
    """
    Disable watchdog temporarily or permanently.

    Args:
        minutes: Number of minutes to disable, or None for permanent

    Returns:
        Exit code (0 for success)
    """
    set_disabled(minutes)

    if minutes:
        disabled_until = datetime.now().replace(microsecond=0) + timedelta(minutes=minutes)
        print(f"\n  Watchdog disabled for {minutes} minutes")
        print(f"  Re-enables at: {disabled_until.strftime('%H:%M')}")
    else:
        print("\n  Watchdog disabled permanently")
        print("  Use 'enable' to re-enable")
    print()

    return 0


def cmd_enable() -> int:
    """
    Re-enable watchdog.

    Returns:
        Exit code (0 for success)
    """
    if clear_disabled():
        print("\n  Watchdog enabled\n")
    else:
        print("\n  Watchdog is already enabled\n")
    return 0


def print_usage() -> None:
    """Print CLI usage information."""
    print("\nUsage:")
    print("  check              - Check and restore cron jobs if missing")
    print("  install            - Install cron jobs")
    print("  uninstall          - Remove cron jobs")
    print("  status             - Show cron status")
    print("  disable [minutes]  - Disable watchdog (permanent if no time)")
    print("  enable             - Re-enable watchdog")
    print()


def main() -> int:
    """
    Main entry point for the watchdog CLI.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    if len(sys.argv) < 2:
        print_usage()
        return 1

    action = sys.argv[1].lower()

    if action == "check":
        return cmd_check()
    elif action == "install":
        return cmd_install()
    elif action == "uninstall":
        return cmd_uninstall()
    elif action == "status":
        return cmd_status()
    elif action == "disable":
        if len(sys.argv) > 2:
            try:
                minutes = int(sys.argv[2])
                if minutes <= 0:
                    print("\n  Error: disable duration must be a positive number\n")
                    return 1
            except ValueError:
                print(f"\n  Error: '{sys.argv[2]}' is not a valid number\n")
                return 1
        else:
            minutes = None
        return cmd_disable(minutes)
    elif action == "enable":
        return cmd_enable()
    else:
        print_usage()
        return 1


if __name__ == "__main__":
    sys.exit(main())
