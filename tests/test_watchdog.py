"""Tests for watchdog.py - Cron watchdog functionality."""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import watchdog


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_disabled_file(temp_log_dir):
    """Mock the DISABLED_FILE path."""
    disabled_file = temp_log_dir / ".watchdog_disabled"
    with patch.object(watchdog, 'DISABLED_FILE', disabled_file):
        yield disabled_file


@pytest.fixture
def mock_audit_log_file(temp_log_dir):
    """Mock the AUDIT_LOG_FILE path."""
    audit_file = temp_log_dir / "audit.log"
    with patch.object(watchdog, 'AUDIT_LOG_FILE', audit_file):
        yield audit_file


class TestIsDisabled:
    """Tests for is_disabled function."""

    def test_is_disabled_no_file(self, mock_disabled_file):
        """Should return False when no disabled file exists."""
        assert watchdog.is_disabled() is False

    def test_is_disabled_permanent(self, mock_disabled_file):
        """Should return True when permanently disabled."""
        mock_disabled_file.write_text("permanent")
        assert watchdog.is_disabled() is True

    def test_is_disabled_active_timer(self, mock_disabled_file):
        """Should return True when disabled with active timer."""
        future_time = datetime.now() + timedelta(minutes=30)
        mock_disabled_file.write_text(future_time.isoformat())
        assert watchdog.is_disabled() is True

    def test_is_disabled_expired_timer(self, mock_disabled_file):
        """Should return False and clean up when timer expired."""
        past_time = datetime.now() - timedelta(minutes=30)
        mock_disabled_file.write_text(past_time.isoformat())
        assert watchdog.is_disabled() is False
        # File should be cleaned up
        assert not mock_disabled_file.exists()

    def test_is_disabled_invalid_content(self, mock_disabled_file):
        """Should return False for invalid file content."""
        mock_disabled_file.write_text("invalid content")
        assert watchdog.is_disabled() is False


class TestGetDisabledRemaining:
    """Tests for get_disabled_remaining function."""

    def test_get_disabled_remaining_no_file(self, mock_disabled_file):
        """Should return empty string when no file exists."""
        assert watchdog.get_disabled_remaining() == ""

    def test_get_disabled_remaining_permanent(self, mock_disabled_file):
        """Should return 'permanently' when permanently disabled."""
        mock_disabled_file.write_text("permanent")
        assert watchdog.get_disabled_remaining() == "permanently"

    def test_get_disabled_remaining_minutes(self, mock_disabled_file):
        """Should return remaining minutes."""
        future_time = datetime.now() + timedelta(minutes=45)
        mock_disabled_file.write_text(future_time.isoformat())
        result = watchdog.get_disabled_remaining()
        # Should be around 44-45 min
        assert "min" in result
        assert int(result.split()[0]) >= 44

    def test_get_disabled_remaining_less_than_minute(self, mock_disabled_file):
        """Should return '< 1 min' when less than a minute remaining."""
        future_time = datetime.now() + timedelta(seconds=30)
        mock_disabled_file.write_text(future_time.isoformat())
        assert watchdog.get_disabled_remaining() == "< 1 min"

    def test_get_disabled_remaining_expired(self, mock_disabled_file):
        """Should return empty string and clean up when expired."""
        past_time = datetime.now() - timedelta(minutes=5)
        mock_disabled_file.write_text(past_time.isoformat())
        assert watchdog.get_disabled_remaining() == ""
        assert not mock_disabled_file.exists()


class TestSetDisabled:
    """Tests for set_disabled function."""

    def test_set_disabled_temporary(self, mock_disabled_file, mock_audit_log_file):
        """Should set temporary disabled state."""
        watchdog.set_disabled(30)
        content = mock_disabled_file.read_text()
        # Should be a valid ISO datetime
        disabled_until = datetime.fromisoformat(content)
        expected = datetime.now() + timedelta(minutes=30)
        # Allow 1 second tolerance
        assert abs((disabled_until - expected).total_seconds()) < 1

    def test_set_disabled_permanent(self, mock_disabled_file, mock_audit_log_file):
        """Should set permanent disabled state."""
        watchdog.set_disabled(None)
        assert mock_disabled_file.read_text() == "permanent"


class TestClearDisabled:
    """Tests for clear_disabled function."""

    def test_clear_disabled_when_disabled(self, mock_disabled_file, mock_audit_log_file):
        """Should return True and remove file when disabled."""
        mock_disabled_file.write_text("permanent")
        assert watchdog.clear_disabled() is True
        assert not mock_disabled_file.exists()

    def test_clear_disabled_when_not_disabled(self, mock_disabled_file):
        """Should return False when not disabled."""
        assert watchdog.clear_disabled() is False


class TestCronHelpers:
    """Tests for cron helper functions."""

    def test_has_sync_cron_present(self):
        """Should return True when sync cron is present."""
        crontab = "*/2 * * * * cd /path && ./blocker.bin sync"
        assert watchdog.has_sync_cron(crontab) is True

    def test_has_sync_cron_absent(self):
        """Should return False when sync cron is absent."""
        crontab = "0 * * * * some_other_job"
        assert watchdog.has_sync_cron(crontab) is False

    def test_has_watchdog_cron_present(self):
        """Should return True when watchdog cron is present."""
        crontab = "* * * * * cd /path && ./watchdog.bin check"
        assert watchdog.has_watchdog_cron(crontab) is True

    def test_has_watchdog_cron_absent(self):
        """Should return False when watchdog cron is absent."""
        crontab = "0 * * * * some_other_job"
        assert watchdog.has_watchdog_cron(crontab) is False

    def test_filter_our_cron_jobs_removes_blocker(self):
        """Should remove blocker.bin jobs."""
        crontab = """0 * * * * other_job
*/2 * * * * cd /path && ./blocker.bin sync
30 * * * * another_job"""
        result = watchdog.filter_our_cron_jobs(crontab)
        assert len(result) == 2
        assert "blocker.bin" not in "\n".join(result)

    def test_filter_our_cron_jobs_removes_watchdog(self):
        """Should remove watchdog.bin jobs."""
        crontab = """0 * * * * other_job
* * * * * cd /path && ./watchdog.bin check"""
        result = watchdog.filter_our_cron_jobs(crontab)
        assert len(result) == 1
        assert "watchdog.bin" not in "\n".join(result)

    def test_filter_our_cron_jobs_keeps_empty_lines_out(self):
        """Should not include empty lines in result."""
        crontab = """0 * * * * other_job

30 * * * * another_job
"""
        result = watchdog.filter_our_cron_jobs(crontab)
        assert len(result) == 2
        assert "" not in result


class TestGetCrontab:
    """Tests for get_crontab function."""

    def test_get_crontab_success(self):
        """Should return crontab content on success."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "*/5 * * * * some_job\n"

        with patch('subprocess.run', return_value=mock_result):
            result = watchdog.get_crontab()
            assert result == "*/5 * * * * some_job\n"

    def test_get_crontab_no_crontab(self):
        """Should return empty string when no crontab exists."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch('subprocess.run', return_value=mock_result):
            result = watchdog.get_crontab()
            assert result == ""

    def test_get_crontab_error(self):
        """Should return empty string on error."""
        with patch('subprocess.run', side_effect=OSError("error")):
            result = watchdog.get_crontab()
            assert result == ""


class TestSetCrontab:
    """Tests for set_crontab function."""

    def test_set_crontab_success(self):
        """Should return True on success."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = MagicMock()

        with patch('subprocess.Popen', return_value=mock_process):
            result = watchdog.set_crontab("*/5 * * * * job\n")
            assert result is True

    def test_set_crontab_failure(self):
        """Should return False on failure."""
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.communicate = MagicMock()

        with patch('subprocess.Popen', return_value=mock_process):
            result = watchdog.set_crontab("*/5 * * * * job\n")
            assert result is False

    def test_set_crontab_error(self):
        """Should return False on error."""
        with patch('subprocess.Popen', side_effect=OSError("error")):
            result = watchdog.set_crontab("*/5 * * * * job\n")
            assert result is False


class TestCmdCheck:
    """Tests for cmd_check function."""

    def test_cmd_check_disabled(self, mock_disabled_file, capsys):
        """Should skip check when disabled."""
        mock_disabled_file.write_text("permanent")
        result = watchdog.cmd_check()
        assert result == 0
        captured = capsys.readouterr()
        assert "disabled" in captured.out

    def test_cmd_check_all_present(self):
        """Should do nothing when all cron jobs present."""
        crontab = "*/2 * * * * ./blocker.bin sync\n* * * * * ./watchdog.bin check\n"

        with patch.object(watchdog, 'get_crontab', return_value=crontab):
            result = watchdog.cmd_check()
            assert result == 0


class TestCmdStatus:
    """Tests for cmd_status function."""

    def test_cmd_status_all_ok(self, mock_disabled_file, capsys):
        """Should show OK status when all cron jobs present."""
        crontab = "*/2 * * * * ./blocker.bin sync\n* * * * * ./watchdog.bin check\n"

        with patch.object(watchdog, 'get_crontab', return_value=crontab):
            result = watchdog.cmd_status()
            assert result == 0
            captured = capsys.readouterr()
            assert "ok" in captured.out
            assert "active" in captured.out

    def test_cmd_status_missing_crons(self, mock_disabled_file, capsys):
        """Should show missing status when cron jobs absent."""
        with patch.object(watchdog, 'get_crontab', return_value=""):
            result = watchdog.cmd_status()
            assert result == 0
            captured = capsys.readouterr()
            assert "missing" in captured.out
            assert "compromised" in captured.out

    def test_cmd_status_disabled(self, mock_disabled_file, capsys):
        """Should show disabled status when watchdog disabled."""
        mock_disabled_file.write_text("permanent")
        crontab = "*/2 * * * * ./blocker.bin sync\n* * * * * ./watchdog.bin check\n"

        with patch.object(watchdog, 'get_crontab', return_value=crontab):
            result = watchdog.cmd_status()
            assert result == 0
            captured = capsys.readouterr()
            assert "DISABLED" in captured.out


class TestCmdDisable:
    """Tests for cmd_disable function."""

    def test_cmd_disable_temporary(self, mock_disabled_file, mock_audit_log_file, capsys):
        """Should disable for specified minutes."""
        result = watchdog.cmd_disable(30)
        assert result == 0
        captured = capsys.readouterr()
        assert "30 minutes" in captured.out

    def test_cmd_disable_permanent(self, mock_disabled_file, mock_audit_log_file, capsys):
        """Should disable permanently."""
        result = watchdog.cmd_disable(None)
        assert result == 0
        captured = capsys.readouterr()
        assert "permanently" in captured.out


class TestCmdEnable:
    """Tests for cmd_enable function."""

    def test_cmd_enable_when_disabled(self, mock_disabled_file, mock_audit_log_file, capsys):
        """Should enable when currently disabled."""
        mock_disabled_file.write_text("permanent")
        result = watchdog.cmd_enable()
        assert result == 0
        captured = capsys.readouterr()
        assert "enabled" in captured.out

    def test_cmd_enable_when_already_enabled(self, mock_disabled_file, capsys):
        """Should indicate already enabled."""
        result = watchdog.cmd_enable()
        assert result == 0
        captured = capsys.readouterr()
        assert "already enabled" in captured.out


class TestWriteSecureFile:
    """Tests for write_secure_file function."""

    def test_write_secure_file_creates_file(self, temp_log_dir):
        """Should create file with content."""
        test_file = temp_log_dir / "test.txt"
        watchdog.write_secure_file(test_file, "test content")
        assert test_file.read_text() == "test content"

    def test_write_secure_file_secure_permissions(self, temp_log_dir):
        """Should create file with secure permissions."""
        test_file = temp_log_dir / "test.txt"
        watchdog.write_secure_file(test_file, "test content")
        mode = test_file.stat().st_mode & 0o777
        assert mode == 0o600

    def test_write_secure_file_overwrites(self, temp_log_dir):
        """Should overwrite existing file."""
        test_file = temp_log_dir / "test.txt"
        test_file.write_text("old content")
        watchdog.write_secure_file(test_file, "new content")
        assert test_file.read_text() == "new content"


class TestReadSecureFile:
    """Tests for read_secure_file function."""

    def test_read_secure_file_exists(self, temp_log_dir):
        """Should read existing file content."""
        test_file = temp_log_dir / "test.txt"
        test_file.write_text("  test content  ")
        result = watchdog.read_secure_file(test_file)
        assert result == "test content"

    def test_read_secure_file_not_exists(self, temp_log_dir):
        """Should return None for non-existent file."""
        test_file = temp_log_dir / "nonexistent.txt"
        result = watchdog.read_secure_file(test_file)
        assert result is None


class TestCmdInstall:
    """Tests for cmd_install function."""

    def test_cmd_install_success(self, mock_audit_log_file, capsys):
        """Should install cron jobs successfully."""
        with patch.object(watchdog, 'get_crontab', return_value=""):
            with patch.object(watchdog, 'set_crontab', return_value=True):
                result = watchdog.cmd_install()
                assert result == 0
                captured = capsys.readouterr()
                assert "cron installed" in captured.out

    def test_cmd_install_failure(self, capsys):
        """Should return error when cron install fails."""
        with patch.object(watchdog, 'get_crontab', return_value=""):
            with patch.object(watchdog, 'set_crontab', return_value=False):
                result = watchdog.cmd_install()
                assert result == 1
                captured = capsys.readouterr()
                assert "failed" in captured.out

    def test_cmd_install_preserves_existing(self, mock_audit_log_file):
        """Should preserve existing cron jobs."""
        existing_cron = "0 * * * * other_job\n"
        with patch.object(watchdog, 'get_crontab', return_value=existing_cron):
            with patch.object(watchdog, 'set_crontab', return_value=True) as mock_set:
                watchdog.cmd_install()
                # Verify existing job is preserved
                call_arg = mock_set.call_args[0][0]
                assert "other_job" in call_arg


class TestCmdUninstall:
    """Tests for cmd_uninstall function."""

    def test_cmd_uninstall_success(self, mock_audit_log_file, capsys):
        """Should uninstall cron jobs successfully."""
        crontab = "*/2 * * * * ./blocker.bin sync\n* * * * * ./watchdog.bin check\n"
        with patch.object(watchdog, 'get_crontab', return_value=crontab):
            with patch.object(watchdog, 'set_crontab', return_value=True):
                result = watchdog.cmd_uninstall()
                assert result == 0
                captured = capsys.readouterr()
                assert "removed" in captured.out

    def test_cmd_uninstall_failure(self, capsys):
        """Should return error when uninstall fails."""
        with patch.object(watchdog, 'get_crontab', return_value=""):
            with patch.object(watchdog, 'set_crontab', return_value=False):
                result = watchdog.cmd_uninstall()
                assert result == 1

    def test_cmd_uninstall_preserves_other_jobs(self, mock_audit_log_file):
        """Should preserve non-blocker cron jobs."""
        crontab = "0 * * * * other_job\n*/2 * * * * ./blocker.bin sync\n"
        with patch.object(watchdog, 'get_crontab', return_value=crontab):
            with patch.object(watchdog, 'set_crontab', return_value=True) as mock_set:
                watchdog.cmd_uninstall()
                call_arg = mock_set.call_args[0][0]
                assert "other_job" in call_arg
                assert "blocker.bin" not in call_arg


class TestCmdCheckRestoration:
    """Tests for cmd_check cron restoration."""

    def test_cmd_check_restores_missing_sync(self, mock_disabled_file, mock_audit_log_file, capsys):
        """Should restore missing sync cron."""
        # First call returns no sync, second returns with sync added
        crontab_states = ["* * * * * ./watchdog.bin check\n",
                         "* * * * * ./watchdog.bin check\n*/2 * * * * blocker.bin sync\n"]
        call_count = [0]

        def get_crontab_side_effect():
            result = crontab_states[min(call_count[0], len(crontab_states)-1)]
            call_count[0] += 1
            return result

        with patch.object(watchdog, 'get_crontab', side_effect=get_crontab_side_effect):
            with patch.object(watchdog, 'set_crontab', return_value=True):
                with patch('subprocess.run'):
                    result = watchdog.cmd_check()
                    assert result == 0
                    captured = capsys.readouterr()
                    assert "sync cron restored" in captured.out

    def test_cmd_check_restores_missing_watchdog(self, mock_disabled_file, mock_audit_log_file, capsys):
        """Should restore missing watchdog cron."""
        crontab_states = ["*/2 * * * * ./blocker.bin sync\n",
                         "*/2 * * * * ./blocker.bin sync\n"]
        call_count = [0]

        def get_crontab_side_effect():
            result = crontab_states[min(call_count[0], len(crontab_states)-1)]
            call_count[0] += 1
            return result

        with patch.object(watchdog, 'get_crontab', side_effect=get_crontab_side_effect):
            with patch.object(watchdog, 'set_crontab', return_value=True):
                with patch('subprocess.run'):
                    result = watchdog.cmd_check()
                    assert result == 0
                    captured = capsys.readouterr()
                    assert "watchdog cron restored" in captured.out


class TestAuditLogWatchdog:
    """Tests for watchdog audit_log function."""

    def test_audit_log_creates_file(self, temp_log_dir):
        """Should create audit log file."""
        audit_file = temp_log_dir / "audit.log"
        with patch('common.AUDIT_LOG_FILE', audit_file):
            watchdog.audit_log("TEST", "detail")
            assert audit_file.exists()

    def test_audit_log_writes_wd_prefix(self, temp_log_dir):
        """Should write WD prefix in log entries."""
        audit_file = temp_log_dir / "audit.log"
        with patch('common.AUDIT_LOG_FILE', audit_file):
            watchdog.audit_log("ACTION", "detail")
            content = audit_file.read_text()
            assert "WD" in content
            assert "ACTION" in content


class TestMain:
    """Tests for main function."""

    def test_main_no_args(self, capsys):
        """Should print usage when no args provided."""
        with patch.object(sys, 'argv', ['watchdog.py']):
            result = watchdog.main()
            assert result == 1
            captured = capsys.readouterr()
            assert "Usage:" in captured.out

    def test_main_unknown_command(self, capsys):
        """Should print usage for unknown command."""
        with patch.object(sys, 'argv', ['watchdog.py', 'unknown']):
            result = watchdog.main()
            assert result == 1

    def test_main_status_command(self, mock_disabled_file):
        """Should run status command."""
        with patch.object(sys, 'argv', ['watchdog.py', 'status']):
            with patch.object(watchdog, 'get_crontab', return_value=""):
                result = watchdog.main()
                assert result == 0

    def test_main_check_command(self, mock_disabled_file):
        """Should run check command."""
        crontab = "*/2 * * * * ./blocker.bin sync\n* * * * * ./watchdog.bin check\n"
        with patch.object(sys, 'argv', ['watchdog.py', 'check']):
            with patch.object(watchdog, 'get_crontab', return_value=crontab):
                result = watchdog.main()
                assert result == 0

    def test_main_install_command(self, mock_audit_log_file):
        """Should run install command."""
        with patch.object(sys, 'argv', ['watchdog.py', 'install']):
            with patch.object(watchdog, 'get_crontab', return_value=""):
                with patch.object(watchdog, 'set_crontab', return_value=True):
                    result = watchdog.main()
                    assert result == 0

    def test_main_uninstall_command(self, mock_audit_log_file):
        """Should run uninstall command."""
        with patch.object(sys, 'argv', ['watchdog.py', 'uninstall']):
            with patch.object(watchdog, 'get_crontab', return_value=""):
                with patch.object(watchdog, 'set_crontab', return_value=True):
                    result = watchdog.main()
                    assert result == 0

    def test_main_disable_command(self, mock_disabled_file, mock_audit_log_file):
        """Should run disable command."""
        with patch.object(sys, 'argv', ['watchdog.py', 'disable', '30']):
            result = watchdog.main()
            assert result == 0

    def test_main_disable_permanent(self, mock_disabled_file, mock_audit_log_file):
        """Should run disable command without minutes (permanent)."""
        with patch.object(sys, 'argv', ['watchdog.py', 'disable']):
            result = watchdog.main()
            assert result == 0

    def test_main_enable_command(self, mock_disabled_file, mock_audit_log_file):
        """Should run enable command."""
        mock_disabled_file.write_text("permanent")
        with patch.object(sys, 'argv', ['watchdog.py', 'enable']):
            result = watchdog.main()
            assert result == 0

    def test_main_disable_invalid_minutes(self, capsys):
        """Should error on invalid disable minutes."""
        with patch.object(sys, 'argv', ['watchdog.py', 'disable', 'abc']):
            result = watchdog.main()
            assert result == 1
            captured = capsys.readouterr()
            assert "not a valid number" in captured.out

    def test_main_disable_negative_minutes(self, capsys):
        """Should error on negative disable minutes."""
        with patch.object(sys, 'argv', ['watchdog.py', 'disable', '-5']):
            result = watchdog.main()
            assert result == 1
            captured = capsys.readouterr()
            assert "positive number" in captured.out
