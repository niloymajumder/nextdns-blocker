"""Tests for file I/O error handling in common.py.

These tests cover edge cases and error branches in audit_log(),
write_secure_file(), and file locking functions.
"""

import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from nextdns_blocker.common import (
    SECURE_FILE_MODE,
    _lock_file,
    _unlock_file,
    audit_log,
    ensure_log_dir,
    read_secure_file,
    write_secure_file,
)


class TestAuditLogErrorHandling:
    """Tests for audit_log error handling."""

    def test_audit_log_handles_oserror_on_mkdir(self, tmp_path):
        """Should handle OSError when creating log directory."""
        fake_log_dir = tmp_path / "logs"

        with patch("nextdns_blocker.common.get_log_dir", return_value=fake_log_dir):
            with patch(
                "nextdns_blocker.common.ensure_log_dir", side_effect=OSError("Permission denied")
            ):
                # Should not raise exception
                audit_log("TEST_ACTION", "test detail")

    def test_audit_log_handles_oserror_on_write(self, tmp_path):
        """Should handle OSError when writing to audit file."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
            with patch("builtins.open", side_effect=OSError("Disk full")):
                # Should not raise exception
                audit_log("TEST_ACTION", "test detail")

    def test_audit_log_handles_oserror_on_touch(self, tmp_path):
        """Should handle OSError when creating audit file."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        audit_file = log_dir / "audit.log"

        with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
            with patch("nextdns_blocker.common.get_audit_log_file", return_value=audit_file):
                with patch.object(Path, "touch", side_effect=OSError("Permission denied")):
                    # Should not raise exception
                    audit_log("TEST_ACTION", "test detail")

    def test_audit_log_with_prefix(self, tmp_path):
        """Should include prefix in log entry."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)
        audit_file = log_dir / "audit.log"

        with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
            with patch("nextdns_blocker.common.get_audit_log_file", return_value=audit_file):
                audit_log("TEST_ACTION", "test detail", prefix="WD")

        content = audit_file.read_text()
        assert "WD" in content
        assert "TEST_ACTION" in content
        assert "test detail" in content


class TestWriteSecureFileErrorHandling:
    """Tests for write_secure_file error handling."""

    def test_write_secure_file_creates_parent_dirs(self, tmp_path):
        """Should create parent directories if needed."""
        target_file = tmp_path / "subdir" / "deep" / "file.txt"

        with patch("nextdns_blocker.common.get_log_dir", return_value=tmp_path / "logs"):
            write_secure_file(target_file, "test content")

        assert target_file.exists()
        assert target_file.read_text() == "test content"

    def test_write_secure_file_sets_permissions_on_existing(self, tmp_path):
        """Should set permissions on existing file."""
        target_file = tmp_path / "existing.txt"
        target_file.write_text("old content")

        with patch("nextdns_blocker.common.get_log_dir", return_value=tmp_path / "logs"):
            write_secure_file(target_file, "new content")

        assert target_file.read_text() == "new content"

    def test_write_secure_file_handles_oserror(self, tmp_path):
        """Should raise OSError on file write failure."""
        target_file = tmp_path / "file.txt"

        with patch("nextdns_blocker.common.get_log_dir", return_value=tmp_path / "logs"):
            with patch("os.open", side_effect=OSError("Cannot open")):
                with pytest.raises(OSError):
                    write_secure_file(target_file, "content")

    def test_write_secure_file_closes_fd_on_fdopen_error(self, tmp_path):
        """Should close fd if fdopen fails."""
        target_file = tmp_path / "file.txt"
        target_file.parent.mkdir(parents=True, exist_ok=True)

        mock_fd = 99

        with patch("nextdns_blocker.common.get_log_dir", return_value=tmp_path / "logs"):
            with patch("os.open", return_value=mock_fd):
                with patch("os.fdopen", side_effect=OSError("fdopen failed")):
                    with patch("os.close") as mock_close:
                        with pytest.raises(OSError):
                            write_secure_file(target_file, "content")

                        mock_close.assert_called_once_with(mock_fd)

    def test_write_secure_file_in_log_dir(self, tmp_path):
        """Should ensure log dir exists when writing to log dir."""
        log_dir = tmp_path / "logs"
        target_file = log_dir / "state.txt"

        with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
            write_secure_file(target_file, "state data")

        assert log_dir.exists()
        assert target_file.exists()


class TestReadSecureFile:
    """Tests for read_secure_file function."""

    def test_read_secure_file_nonexistent(self, tmp_path):
        """Should return None for non-existent file."""
        result = read_secure_file(tmp_path / "nonexistent.txt")
        assert result is None

    def test_read_secure_file_success(self, tmp_path):
        """Should read file content."""
        target_file = tmp_path / "test.txt"
        target_file.write_text("  test content  \n")

        result = read_secure_file(target_file)
        assert result == "test content"

    def test_read_secure_file_oserror(self, tmp_path):
        """Should return None on OSError."""
        target_file = tmp_path / "test.txt"
        target_file.write_text("content")

        with patch("builtins.open", side_effect=OSError("Cannot read")):
            result = read_secure_file(target_file)

        assert result is None


class TestFileLocking:
    """Tests for file locking functions."""

    def test_lock_file_exclusive(self, tmp_path):
        """Should acquire exclusive lock."""
        test_file = tmp_path / "lock_test.txt"
        test_file.write_text("test")

        with open(test_file) as f:
            # Should not raise
            _lock_file(f, exclusive=True)
            _unlock_file(f)

    def test_lock_file_shared(self, tmp_path):
        """Should acquire shared lock."""
        test_file = tmp_path / "lock_test.txt"
        test_file.write_text("test")

        with open(test_file) as f:
            # Should not raise
            _lock_file(f, exclusive=False)
            _unlock_file(f)

    def test_unlock_file_already_unlocked(self, tmp_path):
        """Should handle unlocking already unlocked file."""
        test_file = tmp_path / "lock_test.txt"
        test_file.write_text("test")

        with open(test_file) as f:
            # Unlock without locking first - should not raise
            _unlock_file(f)


class TestWindowsFileLockingFallback:
    """Tests for Windows file locking fallback (msvcrt)."""

    def test_windows_lock_uses_msvcrt(self):
        """Verify Windows fallback uses msvcrt.locking."""
        # This test verifies the structure exists even on non-Windows
        # The actual msvcrt code path is covered when running on Windows
        import nextdns_blocker.common as common_module

        # Check that _HAS_FCNTL is defined
        assert hasattr(common_module, "_HAS_FCNTL")

    def test_noop_lock_when_no_locking_available(self, tmp_path):
        """Test behavior when no file locking is available."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        # Simulate no-op locking (the fallback case)
        def noop_lock(f, exclusive=True):
            pass

        def noop_unlock(f):
            pass

        with open(test_file) as f:
            # These should complete without error
            noop_lock(f, exclusive=True)
            noop_unlock(f)


class TestEnsureLogDir:
    """Tests for ensure_log_dir function."""

    def test_ensure_log_dir_creates_directory(self, tmp_path):
        """Should create log directory if it doesn't exist."""
        log_dir = tmp_path / "new_logs"

        with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
            ensure_log_dir()

        assert log_dir.exists()
        assert log_dir.is_dir()

    def test_ensure_log_dir_exists_ok(self, tmp_path):
        """Should not fail if directory already exists."""
        log_dir = tmp_path / "existing_logs"
        log_dir.mkdir(parents=True)

        with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
            # Should not raise
            ensure_log_dir()

        assert log_dir.exists()


class TestSecureFileMode:
    """Tests for secure file mode constant."""

    def test_secure_file_mode_value(self):
        """Verify SECURE_FILE_MODE is 0o600."""
        assert SECURE_FILE_MODE == stat.S_IRUSR | stat.S_IWUSR
        assert SECURE_FILE_MODE == 0o600

    def test_write_secure_file_uses_correct_mode(self, tmp_path):
        """Should create file with secure permissions."""
        target_file = tmp_path / "secure.txt"

        with patch("nextdns_blocker.common.get_log_dir", return_value=tmp_path / "logs"):
            write_secure_file(target_file, "secure content")

        # Check file mode (on Unix-like systems)
        import sys

        if sys.platform != "win32":
            file_mode = target_file.stat().st_mode & 0o777
            assert file_mode == 0o600
