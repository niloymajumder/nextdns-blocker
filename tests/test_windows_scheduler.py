"""Tests for Windows Task Scheduler functions in watchdog.py.

These tests mock the Windows-specific functions to achieve coverage
on non-Windows platforms.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nextdns_blocker import watchdog
from nextdns_blocker.watchdog import (
    WINDOWS_TASK_SYNC_NAME,
    WINDOWS_TASK_WATCHDOG_NAME,
    _build_task_command,
    _escape_windows_path,
    _run_schtasks,
    has_windows_task,
)


class TestEscapeWindowsPath:
    """Tests for _escape_windows_path function."""

    def test_simple_path(self):
        """Should return path unchanged if no special chars."""
        result = _escape_windows_path(r"C:\Program Files\app.exe")
        # _escape_windows_path does NOT add quotes - that's done by _build_task_command
        assert result == r"C:\Program Files\app.exe"

    def test_path_with_spaces(self):
        """Should preserve spaces (quoting done by caller)."""
        result = _escape_windows_path(r"C:\My Documents\file.txt")
        assert result == r"C:\My Documents\file.txt"

    def test_path_with_quotes(self):
        """Should escape internal quotes by doubling them."""
        result = _escape_windows_path(r'C:\test"file.txt')
        assert result == r'C:\test""file.txt'

    def test_path_with_percent(self):
        """Should escape percent signs by doubling them."""
        result = _escape_windows_path(r"C:\test%file.txt")
        assert result == r"C:\test%%file.txt"

    def test_path_with_both_special_chars(self):
        """Should escape both quotes and percent signs."""
        result = _escape_windows_path(r'C:\test%"file.txt')
        assert result == r'C:\test%%""file.txt'


class TestBuildTaskCommand:
    """Tests for _build_task_command function."""

    def test_build_sync_command(self):
        """Should build correct sync command."""
        exe = r"C:\Program Files\nextdns-blocker.exe"
        log = r"C:\logs\sync.log"
        result = _build_task_command(exe, "sync", log)
        assert "sync" in result
        assert ">" in result or ">>" in result

    def test_build_watchdog_command(self):
        """Should build correct watchdog command."""
        exe = r"C:\app\nextdns-blocker.exe"
        log = r"C:\logs\wd.log"
        result = _build_task_command(exe, "watchdog check", log)
        assert "watchdog check" in result


class TestRunSchtasks:
    """Tests for _run_schtasks function."""

    def test_run_schtasks_success(self):
        """Should run schtasks with correct arguments."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Success"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = _run_schtasks(["/query", "/tn", "TestTask"])

        assert result.returncode == 0
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "schtasks" in args
        assert "/query" in args

    def test_run_schtasks_failure(self):
        """Should handle schtasks failure."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Task not found"

        with patch("subprocess.run", return_value=mock_result):
            result = _run_schtasks(["/query", "/tn", "NonExistent"])

        assert result.returncode == 1

    def test_run_schtasks_exception(self):
        """Should propagate OSError from schtasks."""
        # _run_schtasks doesn't handle exceptions - callers like has_windows_task do
        with patch("nextdns_blocker.watchdog.subprocess.run", side_effect=OSError("Not found")):
            with pytest.raises(OSError):
                _run_schtasks(["/query"])


class TestHasWindowsTask:
    """Tests for has_windows_task function."""

    def test_has_windows_task_exists(self):
        """Should return True when task exists."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("nextdns_blocker.watchdog.subprocess.run", return_value=mock_result):
            assert has_windows_task("ExistingTask") is True

    def test_has_windows_task_not_exists(self):
        """Should return False when task doesn't exist."""
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("nextdns_blocker.watchdog.subprocess.run", return_value=mock_result):
            assert has_windows_task("NonExistentTask") is False

    def test_has_windows_task_exception(self):
        """Should return False on exception."""
        with patch("nextdns_blocker.watchdog.subprocess.run", side_effect=OSError("error")):
            assert has_windows_task("AnyTask") is False


class TestInstallWindowsTasks:
    """Tests for _install_windows_tasks function."""

    @pytest.fixture
    def runner(self):
        """Create Click CLI test runner."""
        return CliRunner()

    def test_install_windows_tasks_success(self, runner, tmp_path):
        """Should install both tasks successfully."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("nextdns_blocker.watchdog.is_macos", return_value=False):
            with patch("nextdns_blocker.watchdog.is_windows", return_value=True):
                with patch("nextdns_blocker.watchdog.get_log_dir", return_value=log_dir):
                    with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
                        with patch(
                            "nextdns_blocker.watchdog.get_executable_path",
                            return_value=r"C:\app\nextdns-blocker.exe",
                        ):
                            with patch(
                                "nextdns_blocker.watchdog._run_schtasks", return_value=mock_result
                            ):
                                result = runner.invoke(watchdog.watchdog_cli, ["install"])

        assert result.exit_code == 0
        assert "Task Scheduler" in result.output or "installed" in result.output.lower()

    def test_install_windows_tasks_sync_fails(self, runner, tmp_path):
        """Should exit with error when sync task creation fails."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        call_count = [0]

        def mock_schtasks(args):
            call_count[0] += 1
            result = MagicMock()
            if "/delete" in args:
                result.returncode = 0
            elif "/create" in args and WINDOWS_TASK_SYNC_NAME in args:
                result.returncode = 1
                result.stderr = "Access denied"
            else:
                result.returncode = 0
            result.stdout = ""
            return result

        with patch("nextdns_blocker.watchdog.is_macos", return_value=False):
            with patch("nextdns_blocker.watchdog.is_windows", return_value=True):
                with patch("nextdns_blocker.watchdog.get_log_dir", return_value=log_dir):
                    with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
                        with patch(
                            "nextdns_blocker.watchdog.get_executable_path",
                            return_value=r"C:\app\nextdns-blocker.exe",
                        ):
                            with patch(
                                "nextdns_blocker.watchdog._run_schtasks", side_effect=mock_schtasks
                            ):
                                result = runner.invoke(watchdog.watchdog_cli, ["install"])

        assert result.exit_code == 1
        assert "failed" in result.output.lower() or "error" in result.output.lower()

    def test_install_windows_tasks_watchdog_fails_rollback(self, runner, tmp_path):
        """Should rollback sync task when watchdog task creation fails."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        calls = []

        def mock_schtasks(args):
            calls.append(args)
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            if "/delete" in args:
                result.returncode = 0
            elif "/create" in args:
                if WINDOWS_TASK_WATCHDOG_NAME in args:
                    result.returncode = 1
                    result.stderr = "Failed to create watchdog"
                else:
                    result.returncode = 0
            else:
                result.returncode = 0
            return result

        with patch("nextdns_blocker.watchdog.is_macos", return_value=False):
            with patch("nextdns_blocker.watchdog.is_windows", return_value=True):
                with patch("nextdns_blocker.watchdog.get_log_dir", return_value=log_dir):
                    with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
                        with patch(
                            "nextdns_blocker.watchdog.get_executable_path",
                            return_value=r"C:\app\nextdns-blocker.exe",
                        ):
                            with patch(
                                "nextdns_blocker.watchdog._run_schtasks", side_effect=mock_schtasks
                            ):
                                result = runner.invoke(watchdog.watchdog_cli, ["install"])

        assert result.exit_code == 1
        # Verify rollback was attempted (delete sync task after watchdog fails)
        delete_calls = [c for c in calls if "/delete" in c and WINDOWS_TASK_SYNC_NAME in c]
        assert len(delete_calls) >= 1


class TestUninstallWindowsTasks:
    """Tests for _uninstall_windows_tasks function."""

    @pytest.fixture
    def runner(self):
        """Create Click CLI test runner."""
        return CliRunner()

    def test_uninstall_windows_tasks_success(self, runner, tmp_path):
        """Should uninstall both tasks successfully."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("nextdns_blocker.watchdog.is_macos", return_value=False):
            with patch("nextdns_blocker.watchdog.is_windows", return_value=True):
                with patch("nextdns_blocker.watchdog.get_log_dir", return_value=log_dir):
                    with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
                        with patch(
                            "nextdns_blocker.watchdog._run_schtasks", return_value=mock_result
                        ):
                            result = runner.invoke(watchdog.watchdog_cli, ["uninstall"])

        assert result.exit_code == 0
        assert "removed" in result.output.lower()

    def test_uninstall_windows_tasks_sync_fails(self, runner, tmp_path):
        """Should show warning when sync task removal fails."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        def mock_schtasks(args):
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            if WINDOWS_TASK_SYNC_NAME in args:
                result.returncode = 1
            else:
                result.returncode = 0
            return result

        with patch("nextdns_blocker.watchdog.is_macos", return_value=False):
            with patch("nextdns_blocker.watchdog.is_windows", return_value=True):
                with patch("nextdns_blocker.watchdog.get_log_dir", return_value=log_dir):
                    with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
                        with patch(
                            "nextdns_blocker.watchdog._run_schtasks", side_effect=mock_schtasks
                        ):
                            result = runner.invoke(watchdog.watchdog_cli, ["uninstall"])

        assert result.exit_code == 0
        assert "warning" in result.output.lower()

    def test_uninstall_windows_tasks_both_fail(self, runner, tmp_path):
        """Should show warning when both task removals fail."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("nextdns_blocker.watchdog.is_macos", return_value=False):
            with patch("nextdns_blocker.watchdog.is_windows", return_value=True):
                with patch("nextdns_blocker.watchdog.get_log_dir", return_value=log_dir):
                    with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
                        with patch(
                            "nextdns_blocker.watchdog._run_schtasks", return_value=mock_result
                        ):
                            result = runner.invoke(watchdog.watchdog_cli, ["uninstall"])

        assert result.exit_code == 0
        assert "warning" in result.output.lower()
        assert "both" in result.output.lower()

    def test_uninstall_windows_tasks_watchdog_fails(self, runner, tmp_path):
        """Should show warning when watchdog task removal fails."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        def mock_schtasks(args):
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            if WINDOWS_TASK_WATCHDOG_NAME in args:
                result.returncode = 1
            else:
                result.returncode = 0
            return result

        with patch("nextdns_blocker.watchdog.is_macos", return_value=False):
            with patch("nextdns_blocker.watchdog.is_windows", return_value=True):
                with patch("nextdns_blocker.watchdog.get_log_dir", return_value=log_dir):
                    with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
                        with patch(
                            "nextdns_blocker.watchdog._run_schtasks", side_effect=mock_schtasks
                        ):
                            result = runner.invoke(watchdog.watchdog_cli, ["uninstall"])

        assert result.exit_code == 0
        assert "warning" in result.output.lower()


class TestStatusWindowsTasks:
    """Tests for _status_windows_tasks function."""

    @pytest.fixture
    def runner(self):
        """Create Click CLI test runner."""
        return CliRunner()

    def test_status_windows_both_ok(self, runner, tmp_path):
        """Should show OK status when both tasks exist."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        with patch("nextdns_blocker.watchdog.is_macos", return_value=False):
            with patch("nextdns_blocker.watchdog.is_windows", return_value=True):
                with patch("nextdns_blocker.watchdog.get_log_dir", return_value=log_dir):
                    with patch("nextdns_blocker.watchdog.has_windows_task", return_value=True):
                        result = runner.invoke(watchdog.watchdog_cli, ["status"])

        assert result.exit_code == 0
        assert "ok" in result.output.lower()
        assert "active" in result.output.lower()

    def test_status_windows_missing_tasks(self, runner, tmp_path):
        """Should show missing status when tasks don't exist."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        with patch("nextdns_blocker.watchdog.is_macos", return_value=False):
            with patch("nextdns_blocker.watchdog.is_windows", return_value=True):
                with patch("nextdns_blocker.watchdog.get_log_dir", return_value=log_dir):
                    with patch("nextdns_blocker.watchdog.has_windows_task", return_value=False):
                        result = runner.invoke(watchdog.watchdog_cli, ["status"])

        assert result.exit_code == 0
        assert "missing" in result.output.lower()
        assert "compromised" in result.output.lower()

    def test_status_windows_disabled(self, runner, tmp_path):
        """Should show disabled status when watchdog is disabled."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)
        disabled_file = log_dir / ".watchdog_disabled"
        disabled_file.write_text("permanent")

        with patch("nextdns_blocker.watchdog.is_macos", return_value=False):
            with patch("nextdns_blocker.watchdog.is_windows", return_value=True):
                with patch("nextdns_blocker.watchdog.get_log_dir", return_value=log_dir):
                    with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
                        with patch("nextdns_blocker.watchdog.has_windows_task", return_value=True):
                            result = runner.invoke(watchdog.watchdog_cli, ["status"])

        assert result.exit_code == 0
        assert "disabled" in result.output.lower()


class TestCheckWindowsTasks:
    """Tests for _check_windows_tasks function."""

    @pytest.fixture
    def runner(self):
        """Create Click CLI test runner."""
        return CliRunner()

    def test_check_windows_restores_sync_task(self, runner, tmp_path):
        """Should restore missing sync task."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        has_task_calls = []

        def mock_has_task(name):
            has_task_calls.append(name)
            # First call for sync returns False (missing), second for watchdog returns True
            if name == WINDOWS_TASK_SYNC_NAME:
                return False
            return True

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("nextdns_blocker.watchdog.is_macos", return_value=False):
            with patch("nextdns_blocker.watchdog.is_windows", return_value=True):
                with patch("nextdns_blocker.watchdog.get_log_dir", return_value=log_dir):
                    with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
                        with patch(
                            "nextdns_blocker.watchdog.has_windows_task", side_effect=mock_has_task
                        ):
                            with patch(
                                "nextdns_blocker.watchdog.get_executable_path",
                                return_value=r"C:\app\nextdns-blocker.exe",
                            ):
                                with patch(
                                    "nextdns_blocker.watchdog._run_schtasks",
                                    return_value=mock_result,
                                ):
                                    with patch("subprocess.run") as mock_sync:
                                        mock_sync.return_value = MagicMock(returncode=0)
                                        result = runner.invoke(watchdog.watchdog_cli, ["check"])

        assert result.exit_code == 0
        assert "sync task restored" in result.output.lower()

    def test_check_windows_restores_watchdog_task(self, runner, tmp_path):
        """Should restore missing watchdog task."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        def mock_has_task(name):
            if name == WINDOWS_TASK_WATCHDOG_NAME:
                return False
            return True

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("nextdns_blocker.watchdog.is_macos", return_value=False):
            with patch("nextdns_blocker.watchdog.is_windows", return_value=True):
                with patch("nextdns_blocker.watchdog.get_log_dir", return_value=log_dir):
                    with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
                        with patch(
                            "nextdns_blocker.watchdog.has_windows_task", side_effect=mock_has_task
                        ):
                            with patch(
                                "nextdns_blocker.watchdog.get_executable_path",
                                return_value=r"C:\app\nextdns-blocker.exe",
                            ):
                                with patch(
                                    "nextdns_blocker.watchdog._run_schtasks",
                                    return_value=mock_result,
                                ):
                                    with patch("subprocess.run") as mock_sync:
                                        mock_sync.return_value = MagicMock(returncode=0)
                                        result = runner.invoke(watchdog.watchdog_cli, ["check"])

        assert result.exit_code == 0
        assert "watchdog task restored" in result.output.lower()

    def test_check_windows_restore_sync_fails(self, runner, tmp_path):
        """Should show warning when sync task restoration fails."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        mock_fail = MagicMock()
        mock_fail.returncode = 1
        mock_fail.stdout = ""
        mock_fail.stderr = "Failed"

        with patch("nextdns_blocker.watchdog.is_macos", return_value=False):
            with patch("nextdns_blocker.watchdog.is_windows", return_value=True):
                with patch("nextdns_blocker.watchdog.get_log_dir", return_value=log_dir):
                    with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
                        with patch("nextdns_blocker.watchdog.has_windows_task", return_value=False):
                            with patch(
                                "nextdns_blocker.watchdog.get_executable_path",
                                return_value=r"C:\app\nextdns-blocker.exe",
                            ):
                                with patch(
                                    "nextdns_blocker.watchdog._run_schtasks", return_value=mock_fail
                                ):
                                    result = runner.invoke(watchdog.watchdog_cli, ["check"])

        assert result.exit_code == 0
        assert "warning" in result.output.lower() or "failed" in result.output.lower()

    def test_check_windows_all_present(self, runner, tmp_path):
        """Should do nothing when all tasks are present."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        with patch("nextdns_blocker.watchdog.is_macos", return_value=False):
            with patch("nextdns_blocker.watchdog.is_windows", return_value=True):
                with patch("nextdns_blocker.watchdog.get_log_dir", return_value=log_dir):
                    with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
                        with patch("nextdns_blocker.watchdog.has_windows_task", return_value=True):
                            result = runner.invoke(watchdog.watchdog_cli, ["check"])

        assert result.exit_code == 0
        # Should not mention restoration
        assert "restored" not in result.output.lower()
