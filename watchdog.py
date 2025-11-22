#!/usr/bin/env python3
"""Cron watchdog"""

import os, sys, subprocess
from datetime import datetime

LOG_DIR = os.path.expanduser("~/.local/share/nextdns-audit/logs")
os.makedirs(LOG_DIR, exist_ok=True)
INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))

CRON_SYNC = f"*/2 * * * * cd {INSTALL_DIR} && ./blocker.bin sync >> {LOG_DIR}/cron.log 2>&1"
CRON_WATCHDOG = f"* * * * * cd {INSTALL_DIR} && ./watchdog.bin check >> {LOG_DIR}/wd.log 2>&1"


def audit_log(action: str, detail: str = ""):
    with open(os.path.join(LOG_DIR, 'audit.log'), 'a') as f:
        f.write(f"{datetime.now().isoformat()} | WD | {action} | {detail}\n")


def get_crontab() -> str:
    try:
        result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def set_crontab(content: str) -> bool:
    try:
        process = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, text=True)
        process.communicate(input=content)
        return process.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def check():
    crontab = get_crontab()
    restored = False

    if "blocker.bin sync" not in crontab:
        audit_log("CRON_DELETED", "Sync cron missing")
        new_crontab = crontab.strip()
        new_crontab = (new_crontab + "\n" if new_crontab else "") + CRON_SYNC + "\n"
        if set_crontab(new_crontab):
            print("  sync cron restored")
            restored = True

    if "watchdog.bin check" not in crontab:
        audit_log("WD_CRON_DELETED", "Watchdog cron missing")
        crontab = get_crontab()
        new_crontab = crontab.strip()
        new_crontab = (new_crontab + "\n" if new_crontab else "") + CRON_WATCHDOG + "\n"
        if set_crontab(new_crontab): restored = True

    if restored:
        try:
            subprocess.run([f'{INSTALL_DIR}/blocker.bin', 'sync'], timeout=60)
        except subprocess.TimeoutExpired:
            audit_log("SYNC_TIMEOUT", "Sync took >60s after restore")


def install():
    crontab = get_crontab()
    lines = [line for line in crontab.split('\n') if 'blocker.bin' not in line and 'watchdog.bin' not in line and line.strip()]
    lines.extend([CRON_SYNC, CRON_WATCHDOG])
    if set_crontab('\n'.join(lines) + '\n'):
        print("\n  cron installed")
        print("    sync       every 2 min")
        print("    watchdog   every 1 min\n")
    else:
        print("  error: cron install failed"); sys.exit(1)


def status():
    crontab = get_crontab()
    has_sync = "blocker.bin sync" in crontab
    has_watchdog = "watchdog.bin check" in crontab
    print("\n  cron")
    print("  ----")
    print(f"    sync       {'ok' if has_sync else 'missing'}")
    print(f"    watchdog   {'ok' if has_watchdog else 'missing'}")
    print(f"\n  status: {'active' if has_sync and has_watchdog else 'compromised'}\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: [check|install|status]")
        sys.exit(1)
    action = sys.argv[1].lower()
    if action == "check": check()
    elif action == "install": install()
    elif action == "status": status()
    else: print("Usage: [check|install|status]"); sys.exit(1)


if __name__ == "__main__":
    main()
