#!/usr/bin/env python3
"""Common utilities shared between nextdns_blocker and watchdog modules."""

import fcntl
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Optional


# =============================================================================
# SHARED CONSTANTS
# =============================================================================

LOG_DIR = Path(os.path.expanduser("~/.local/share/nextdns-audit/logs"))
AUDIT_LOG_FILE = LOG_DIR / "audit.log"


def ensure_log_dir() -> None:
    """Ensure log directory exists. Called lazily when needed."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

# Secure file permissions (owner read/write only)
SECURE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0o600


# =============================================================================
# SHARED UTILITY FUNCTIONS
# =============================================================================

def audit_log(action: str, detail: str = "", prefix: str = "") -> None:
    """
    Log an action to the audit log file with secure permissions and file locking.

    Args:
        action: The action being logged (e.g., 'BLOCK', 'UNBLOCK', 'PAUSE')
        detail: Additional details about the action
        prefix: Optional prefix for the log entry (e.g., 'WD' for watchdog)
    """
    try:
        # Ensure log directory exists
        ensure_log_dir()

        # Create file with secure permissions if it doesn't exist
        if not AUDIT_LOG_FILE.exists():
            AUDIT_LOG_FILE.touch(mode=SECURE_FILE_MODE)

        # Build log entry
        parts = [datetime.now().isoformat()]
        if prefix:
            parts.append(prefix)
        parts.extend([action, detail])
        log_entry = " | ".join(parts) + "\n"

        # Write with exclusive lock to prevent corruption from concurrent writes
        with open(AUDIT_LOG_FILE, 'a') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(log_entry)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    except OSError:
        pass  # Fail silently for audit logging


def write_secure_file(path: Path, content: str) -> None:
    """
    Write content to a file with secure permissions (0o600).

    Args:
        path: Path to the file
        content: Content to write
    """
    # Ensure log directory exists if writing to LOG_DIR
    if path.parent == LOG_DIR:
        ensure_log_dir()
    else:
        # Create parent directories if needed for other paths
        path.parent.mkdir(parents=True, exist_ok=True)

    # Set secure permissions before writing if file exists
    if path.exists():
        os.chmod(path, SECURE_FILE_MODE)

    # Write with exclusive lock
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, SECURE_FILE_MODE)
    fd_owned = False
    try:
        f = os.fdopen(fd, 'w')
        fd_owned = True  # os.fdopen now owns the fd, don't close manually
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(content)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        f.close()
    except Exception:
        if not fd_owned:
            os.close(fd)
        raise


def read_secure_file(path: Path) -> Optional[str]:
    """
    Read content from a file with shared lock.

    Args:
        path: Path to the file

    Returns:
        File content or None if file doesn't exist or read fails
    """
    if not path.exists():
        return None

    try:
        with open(path, 'r') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return f.read().strip()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        return None
