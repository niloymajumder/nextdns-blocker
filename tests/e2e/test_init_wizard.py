"""E2E tests for init wizard functionality."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import responses
from click.testing import CliRunner

from nextdns_blocker.init import (
    NEXTDNS_API_URL,
    _build_task_command,
    _escape_windows_path,
    create_env_file,
    create_sample_domains,
    detect_existing_config,
    handle_domains_migration,
    validate_api_credentials,
    validate_timezone,
)


class TestValidateApiCredentials:
    """Tests for API credential validation."""

    @responses.activate
    def test_valid_credentials(self) -> None:
        """Test validation with valid credentials."""
        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"data": []},
            status=200,
        )

        success, message = validate_api_credentials("valid-key", "abc123")

        assert success is True
        assert message == "Credentials valid"

    @responses.activate
    def test_invalid_api_key(self) -> None:
        """Test validation with invalid API key."""
        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"error": "Unauthorized"},
            status=401,
        )

        success, message = validate_api_credentials("invalid-key", "abc123")

        assert success is False
        assert message == "Invalid API key"

    @responses.activate
    def test_profile_not_found(self) -> None:
        """Test validation with non-existent profile."""
        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/invalid/denylist",
            json={"error": "Not found"},
            status=404,
        )

        success, message = validate_api_credentials("valid-key", "invalid")

        assert success is False
        assert message == "Profile ID not found"

    @responses.activate
    def test_api_error_status(self) -> None:
        """Test validation with server error."""
        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"error": "Server error"},
            status=500,
        )

        success, message = validate_api_credentials("key", "abc123")

        assert success is False
        assert "API error: 500" in message

    @responses.activate
    def test_connection_timeout(self) -> None:
        """Test validation handles timeout."""
        import requests

        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            body=requests.exceptions.Timeout(),
        )

        success, message = validate_api_credentials("key", "abc123")

        assert success is False
        assert message == "Connection timeout"

    @responses.activate
    def test_connection_error(self) -> None:
        """Test validation handles connection error."""
        import requests

        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            body=requests.exceptions.ConnectionError(),
        )

        success, message = validate_api_credentials("key", "abc123")

        assert success is False
        assert message == "Connection failed"

    @responses.activate
    def test_request_exception(self) -> None:
        """Test validation handles generic request exception."""
        import requests

        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            body=requests.exceptions.RequestException("Network issue"),
        )

        success, message = validate_api_credentials("key", "abc123")

        assert success is False
        assert "Request error" in message


class TestValidateTimezone:
    """Tests for timezone validation."""

    def test_valid_timezone(self) -> None:
        """Test with valid timezone."""
        success, message = validate_timezone("America/Mexico_City")

        assert success is True
        assert message == "Valid timezone"

    def test_valid_utc(self) -> None:
        """Test with UTC timezone."""
        success, message = validate_timezone("UTC")

        assert success is True

    def test_invalid_timezone(self) -> None:
        """Test with invalid timezone."""
        success, message = validate_timezone("Invalid/Timezone")

        assert success is False
        assert "Invalid timezone" in message


class TestCreateEnvFile:
    """Tests for .env file creation."""

    def test_creates_env_file(self, tmp_path: Path) -> None:
        """Test basic .env file creation."""
        config_dir = tmp_path / "config"

        env_file = create_env_file(
            config_dir,
            api_key="test-key",
            profile_id="profile123",
            timezone="UTC",
        )

        assert env_file.exists()
        content = env_file.read_text()
        assert "NEXTDNS_API_KEY=test-key" in content
        assert "NEXTDNS_PROFILE_ID=profile123" in content
        assert "TIMEZONE=UTC" in content

    def test_creates_env_file_with_url(self, tmp_path: Path) -> None:
        """Test .env file creation with domains URL."""
        config_dir = tmp_path / "config"

        env_file = create_env_file(
            config_dir,
            api_key="test-key",
            profile_id="profile123",
            timezone="UTC",
            domains_url="https://example.com/domains.json",
        )

        content = env_file.read_text()
        assert "DOMAINS_URL=https://example.com/domains.json" in content

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Test that parent directories are created."""
        config_dir = tmp_path / "nested" / "path" / "config"

        env_file = create_env_file(
            config_dir,
            api_key="key",
            profile_id="profile",
            timezone="UTC",
        )

        assert env_file.exists()
        assert config_dir.exists()


class TestCreateSampleDomains:
    """Tests for sample domains.json creation."""

    def test_creates_sample_file(self, tmp_path: Path) -> None:
        """Test sample domains.json creation."""
        config_dir = tmp_path / "config"

        domains_file = create_sample_domains(config_dir)

        assert domains_file.exists()
        content = json.loads(domains_file.read_text())
        assert "domains" in content
        assert "allowlist" in content
        assert len(content["domains"]) > 0

    def test_sample_has_valid_structure(self, tmp_path: Path) -> None:
        """Test sample domains.json has valid structure."""
        config_dir = tmp_path / "config"

        domains_file = create_sample_domains(config_dir)
        content = json.loads(domains_file.read_text())

        # Check first domain has required fields
        domain_entry = content["domains"][0]
        assert "domain" in domain_entry
        assert "schedule" in domain_entry


class TestDetectExistingConfig:
    """Tests for existing configuration detection."""

    def test_no_existing_config(self, tmp_path: Path) -> None:
        """Test detection when no config exists."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        result = detect_existing_config(config_dir)

        assert result["has_local"] is False
        assert result["has_url"] is False
        assert result["url"] is None

    def test_local_domains_file_exists(self, tmp_path: Path) -> None:
        """Test detection with local domains.json."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "domains.json").write_text('{"domains": []}')

        result = detect_existing_config(config_dir)

        assert result["has_local"] is True
        assert result["has_url"] is False

    def test_url_in_env_file(self, tmp_path: Path) -> None:
        """Test detection with DOMAINS_URL in .env."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / ".env").write_text("DOMAINS_URL=https://example.com/domains.json\n")

        result = detect_existing_config(config_dir)

        assert result["has_local"] is False
        assert result["has_url"] is True
        assert result["url"] == "https://example.com/domains.json"

    def test_url_with_quotes(self, tmp_path: Path) -> None:
        """Test detection with quoted URL."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / ".env").write_text('DOMAINS_URL="https://example.com/domains.json"\n')

        result = detect_existing_config(config_dir)

        assert result["has_url"] is True
        assert result["url"] == "https://example.com/domains.json"

    def test_url_with_single_quotes(self, tmp_path: Path) -> None:
        """Test detection with single-quoted URL."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / ".env").write_text("DOMAINS_URL='https://example.com/domains.json'\n")

        result = detect_existing_config(config_dir)

        assert result["has_url"] is True
        assert result["url"] == "https://example.com/domains.json"

    def test_commented_url_ignored(self, tmp_path: Path) -> None:
        """Test that commented DOMAINS_URL is ignored."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / ".env").write_text("# DOMAINS_URL=https://example.com/domains.json\n")

        result = detect_existing_config(config_dir)

        assert result["has_url"] is False
        assert result["url"] is None

    def test_both_local_and_url(self, tmp_path: Path) -> None:
        """Test detection with both local file and URL."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "domains.json").write_text('{"domains": []}')
        (config_dir / ".env").write_text("DOMAINS_URL=https://example.com/domains.json\n")

        result = detect_existing_config(config_dir)

        assert result["has_local"] is True
        assert result["has_url"] is True


class TestHandleDomainsMigration:
    """Tests for domains migration handling."""

    def test_url_choice_deletes_local(self, tmp_path: Path) -> None:
        """Test 'url' choice deletes local file."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        local_file = config_dir / "domains.json"
        local_file.write_text('{"domains": []}')

        url, should_create = handle_domains_migration(
            config_dir, "url", "https://example.com/d.json"
        )

        assert url == "https://example.com/d.json"
        assert should_create is False
        assert not local_file.exists()

    def test_local_choice_no_url(self, tmp_path: Path) -> None:
        """Test 'local' choice returns no URL."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        url, should_create = handle_domains_migration(config_dir, "local", None)

        assert url is None
        assert should_create is True  # Should create if doesn't exist

    def test_local_choice_with_existing_file(self, tmp_path: Path) -> None:
        """Test 'local' choice with existing file."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "domains.json").write_text('{"domains": []}')

        url, should_create = handle_domains_migration(config_dir, "local", None)

        assert url is None
        assert should_create is False  # Don't create, it exists

    def test_keep_url_choice(self, tmp_path: Path) -> None:
        """Test 'keep_url' choice keeps URL."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        url, should_create = handle_domains_migration(
            config_dir, "keep_url", "https://example.com/d.json"
        )

        assert url == "https://example.com/d.json"
        assert should_create is False

    def test_both_choice(self, tmp_path: Path) -> None:
        """Test 'both' choice keeps URL."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        url, should_create = handle_domains_migration(
            config_dir, "both", "https://example.com/d.json"
        )

        assert url == "https://example.com/d.json"
        assert should_create is False

    def test_none_choice(self, tmp_path: Path) -> None:
        """Test 'none' choice for no existing config."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        url, should_create = handle_domains_migration(config_dir, "none", None)

        assert url is None
        assert should_create is False


class TestWindowsPathHelpers:
    """Tests for Windows path helper functions."""

    def test_escape_windows_path_percent(self) -> None:
        """Test percent sign escaping."""
        result = _escape_windows_path("C:\\Users\\%USERNAME%\\file.txt")

        assert result == "C:\\Users\\%%USERNAME%%\\file.txt"

    def test_escape_windows_path_quotes(self) -> None:
        """Test quote escaping."""
        result = _escape_windows_path('C:\\path with "quotes"\\file.txt')

        assert result == 'C:\\path with ""quotes""\\file.txt'

    def test_build_task_command(self) -> None:
        """Test task command building."""
        result = _build_task_command(
            exe="C:\\Program Files\\app.exe",
            args="sync",
            log_file="C:\\Logs\\app.log",
        )

        assert "cmd /c" in result
        assert "sync" in result
        assert ">>" in result


class TestInstallScheduling:
    """Tests for scheduling installation."""

    @patch("nextdns_blocker.init.is_macos", return_value=True)
    @patch("nextdns_blocker.init.is_windows", return_value=False)
    @patch("nextdns_blocker.init._install_launchd")
    def test_install_uses_launchd_on_macos(
        self,
        mock_install: MagicMock,
        mock_is_windows: MagicMock,
        mock_is_macos: MagicMock,
    ) -> None:
        """Test scheduling installation uses launchd on macOS."""
        from nextdns_blocker.init import install_scheduling

        mock_install.return_value = (True, "launchd")

        success, sched_type = install_scheduling()

        mock_install.assert_called_once()

    @patch("nextdns_blocker.init.is_macos", return_value=False)
    @patch("nextdns_blocker.init.is_windows", return_value=True)
    @patch("nextdns_blocker.init._install_windows_task")
    def test_install_uses_task_scheduler_on_windows(
        self,
        mock_install: MagicMock,
        mock_is_windows: MagicMock,
        mock_is_macos: MagicMock,
    ) -> None:
        """Test scheduling installation uses Task Scheduler on Windows."""
        from nextdns_blocker.init import install_scheduling

        mock_install.return_value = (True, "Task Scheduler")

        success, sched_type = install_scheduling()

        mock_install.assert_called_once()

    @patch("nextdns_blocker.init.is_macos", return_value=False)
    @patch("nextdns_blocker.init.is_windows", return_value=False)
    @patch("nextdns_blocker.init._install_cron")
    def test_install_uses_cron_on_linux(
        self,
        mock_install: MagicMock,
        mock_is_windows: MagicMock,
        mock_is_macos: MagicMock,
    ) -> None:
        """Test scheduling installation uses cron on Linux."""
        from nextdns_blocker.init import install_scheduling

        mock_install.return_value = (True, "cron")

        success, sched_type = install_scheduling()

        mock_install.assert_called_once()


class TestInstallLaunchd:
    """Tests for launchd installation."""

    @patch("nextdns_blocker.init.get_log_dir")
    @patch("nextdns_blocker.init.get_executable_args")
    @patch("subprocess.run")
    def test_install_launchd_success(
        self,
        mock_run: MagicMock,
        mock_exe_args: MagicMock,
        mock_log_dir: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test successful launchd installation."""
        from nextdns_blocker.init import _install_launchd

        mock_log_dir.return_value = tmp_path / "logs"
        mock_exe_args.return_value = ["/usr/local/bin/nextdns-blocker"]
        mock_run.return_value = MagicMock(returncode=0)

        with patch.object(Path, "home", return_value=tmp_path):
            # Create LaunchAgents directory
            launch_agents = tmp_path / "Library" / "LaunchAgents"
            launch_agents.mkdir(parents=True)

            success, message = _install_launchd()

        assert success is True
        assert message == "launchd"

    @patch("nextdns_blocker.init.get_log_dir")
    @patch("nextdns_blocker.init.get_executable_args")
    @patch("subprocess.run")
    def test_install_launchd_load_failure(
        self,
        mock_run: MagicMock,
        mock_exe_args: MagicMock,
        mock_log_dir: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test launchd installation with load failure."""
        from nextdns_blocker.init import _install_launchd

        mock_log_dir.return_value = tmp_path / "logs"
        mock_exe_args.return_value = ["/usr/local/bin/nextdns-blocker"]
        # First two calls (unload) succeed, third call (load) fails
        mock_run.side_effect = [
            MagicMock(returncode=0),  # unload sync
            MagicMock(returncode=0),  # unload watchdog
            MagicMock(returncode=1),  # load sync fails
            MagicMock(returncode=0),  # load watchdog
        ]

        with patch.object(Path, "home", return_value=tmp_path):
            launch_agents = tmp_path / "Library" / "LaunchAgents"
            launch_agents.mkdir(parents=True)

            success, message = _install_launchd()

        assert success is False
        assert "Failed to load" in message


class TestInstallCron:
    """Tests for cron installation."""

    @patch("nextdns_blocker.init.get_log_dir")
    @patch("nextdns_blocker.init.get_executable_path")
    @patch("subprocess.run")
    def test_install_cron_success(
        self,
        mock_run: MagicMock,
        mock_exe_path: MagicMock,
        mock_log_dir: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test successful cron installation."""
        from nextdns_blocker.init import _install_cron

        mock_log_dir.return_value = tmp_path / "logs"
        mock_exe_path.return_value = "/usr/local/bin/nextdns-blocker"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=""),  # crontab -l
            MagicMock(returncode=0),  # crontab -
        ]

        success, message = _install_cron()

        assert success is True
        assert message == "cron"

    @patch("nextdns_blocker.init.get_log_dir")
    @patch("nextdns_blocker.init.get_executable_path")
    @patch("subprocess.run")
    def test_install_cron_removes_existing_entries(
        self,
        mock_run: MagicMock,
        mock_exe_path: MagicMock,
        mock_log_dir: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test cron installation removes existing nextdns-blocker entries."""
        from nextdns_blocker.init import _install_cron

        mock_log_dir.return_value = tmp_path / "logs"
        mock_exe_path.return_value = "/usr/local/bin/nextdns-blocker"
        mock_run.side_effect = [
            MagicMock(
                returncode=0,
                stdout="*/2 * * * * old-nextdns-blocker sync\nother-job",
            ),
            MagicMock(returncode=0),
        ]

        success, message = _install_cron()

        assert success is True
        # Verify crontab - was called with new content
        call_args = mock_run.call_args_list[1]
        assert "crontab" in call_args[0][0]


class TestInstallWindowsTask:
    """Tests for Windows Task Scheduler installation."""

    @patch("nextdns_blocker.init.get_log_dir")
    @patch("nextdns_blocker.init.get_executable_path")
    @patch("subprocess.run")
    def test_install_windows_task_success(
        self,
        mock_run: MagicMock,
        mock_exe_path: MagicMock,
        mock_log_dir: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test successful Windows task installation."""
        from nextdns_blocker.init import _install_windows_task

        mock_log_dir.return_value = tmp_path / "logs"
        mock_exe_path.return_value = "C:\\Program Files\\nextdns-blocker.exe"
        mock_run.return_value = MagicMock(returncode=0)

        success, message = _install_windows_task()

        assert success is True
        assert message == "Task Scheduler"

    @patch("nextdns_blocker.init.get_log_dir")
    @patch("nextdns_blocker.init.get_executable_path")
    @patch("subprocess.run")
    def test_install_windows_task_failure(
        self,
        mock_run: MagicMock,
        mock_exe_path: MagicMock,
        mock_log_dir: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test Windows task installation failure."""
        from nextdns_blocker.init import _install_windows_task

        mock_log_dir.return_value = tmp_path / "logs"
        mock_exe_path.return_value = "C:\\Program Files\\nextdns-blocker.exe"
        mock_run.side_effect = [
            MagicMock(returncode=0),  # delete sync
            MagicMock(returncode=0),  # delete watchdog
            MagicMock(returncode=1, stderr="Access denied"),  # create sync fails
            MagicMock(returncode=0),  # create watchdog
        ]

        success, message = _install_windows_task()

        assert success is False
        assert "Failed to create" in message


class TestRunInitialSync:
    """Tests for initial sync execution."""

    @patch("nextdns_blocker.init.get_executable_args")
    @patch("subprocess.run")
    def test_run_initial_sync_success(
        self,
        mock_run: MagicMock,
        mock_exe_args: MagicMock,
    ) -> None:
        """Test successful initial sync."""
        from nextdns_blocker.init import run_initial_sync

        mock_exe_args.return_value = ["/usr/local/bin/nextdns-blocker"]
        mock_run.return_value = MagicMock(returncode=0)

        result = run_initial_sync()

        assert result is True

    @patch("nextdns_blocker.init.get_executable_args")
    @patch("subprocess.run")
    def test_run_initial_sync_failure(
        self,
        mock_run: MagicMock,
        mock_exe_args: MagicMock,
    ) -> None:
        """Test failed initial sync."""
        from nextdns_blocker.init import run_initial_sync

        mock_exe_args.return_value = ["/usr/local/bin/nextdns-blocker"]
        mock_run.return_value = MagicMock(returncode=1)

        result = run_initial_sync()

        assert result is False

    @patch("nextdns_blocker.init.get_executable_args")
    @patch("subprocess.run")
    def test_run_initial_sync_exception(
        self,
        mock_run: MagicMock,
        mock_exe_args: MagicMock,
    ) -> None:
        """Test initial sync with exception."""
        from nextdns_blocker.init import run_initial_sync

        mock_exe_args.return_value = ["/usr/local/bin/nextdns-blocker"]
        mock_run.side_effect = Exception("Network error")

        result = run_initial_sync()

        assert result is False


class TestNonInteractiveInit:
    """Tests for non-interactive init flow."""

    @responses.activate
    def test_non_interactive_missing_api_key(
        self,
        runner: CliRunner,
        e2e_config_dir: Path,
        e2e_log_dir: Path,
    ) -> None:
        """Test non-interactive init fails without API key."""
        from nextdns_blocker.init import run_non_interactive

        # Ensure env vars are not set
        with patch.dict(os.environ, {}, clear=True):
            result = run_non_interactive(e2e_config_dir)

        assert result is False

    @responses.activate
    def test_non_interactive_missing_profile_id(
        self,
        runner: CliRunner,
        e2e_config_dir: Path,
        e2e_log_dir: Path,
    ) -> None:
        """Test non-interactive init fails without profile ID."""
        from nextdns_blocker.init import run_non_interactive

        with patch.dict(os.environ, {"NEXTDNS_API_KEY": "test-key"}, clear=True):
            result = run_non_interactive(e2e_config_dir)

        assert result is False

    @responses.activate
    def test_non_interactive_invalid_timezone(
        self,
        runner: CliRunner,
        e2e_config_dir: Path,
    ) -> None:
        """Test non-interactive init fails with invalid timezone."""
        from nextdns_blocker.init import run_non_interactive

        env = {
            "NEXTDNS_API_KEY": "test-key",
            "NEXTDNS_PROFILE_ID": "abc123",
            "TIMEZONE": "Invalid/TZ",
        }
        with patch.dict(os.environ, env, clear=True):
            result = run_non_interactive(e2e_config_dir)

        assert result is False

    @responses.activate
    def test_non_interactive_invalid_credentials(
        self,
        runner: CliRunner,
        e2e_config_dir: Path,
    ) -> None:
        """Test non-interactive init fails with invalid credentials."""
        from nextdns_blocker.init import run_non_interactive

        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"error": "Unauthorized"},
            status=401,
        )

        env = {
            "NEXTDNS_API_KEY": "invalid-key",
            "NEXTDNS_PROFILE_ID": "abc123",
            "TIMEZONE": "UTC",
        }
        with patch.dict(os.environ, env, clear=True):
            result = run_non_interactive(e2e_config_dir)

        assert result is False

    @responses.activate
    @patch("nextdns_blocker.init.install_scheduling")
    @patch("nextdns_blocker.init.run_initial_sync")
    def test_non_interactive_success(
        self,
        mock_sync: MagicMock,
        mock_scheduling: MagicMock,
        runner: CliRunner,
        e2e_config_dir: Path,
    ) -> None:
        """Test successful non-interactive init."""
        from nextdns_blocker.init import run_non_interactive

        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"data": []},
            status=200,
        )
        mock_scheduling.return_value = (True, "launchd")
        mock_sync.return_value = True

        env = {
            "NEXTDNS_API_KEY": "valid-key",
            "NEXTDNS_PROFILE_ID": "abc123",
            "TIMEZONE": "UTC",
        }
        with patch.dict(os.environ, env, clear=True):
            result = run_non_interactive(e2e_config_dir)

        assert result is True
        assert (e2e_config_dir / ".env").exists()

    @responses.activate
    @patch("nextdns_blocker.init.install_scheduling")
    @patch("nextdns_blocker.init.run_initial_sync")
    def test_non_interactive_with_domains_url(
        self,
        mock_sync: MagicMock,
        mock_scheduling: MagicMock,
        e2e_config_dir: Path,
    ) -> None:
        """Test non-interactive init with domains URL."""
        from nextdns_blocker.init import run_non_interactive

        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"data": []},
            status=200,
        )
        mock_scheduling.return_value = (True, "launchd")
        mock_sync.return_value = True

        env = {
            "NEXTDNS_API_KEY": "valid-key",
            "NEXTDNS_PROFILE_ID": "abc123",
            "TIMEZONE": "UTC",
        }
        with patch.dict(os.environ, env, clear=True):
            result = run_non_interactive(
                e2e_config_dir,
                domains_url="https://example.com/domains.json",
            )

        assert result is True
        content = (e2e_config_dir / ".env").read_text()
        assert "DOMAINS_URL=https://example.com/domains.json" in content

    @responses.activate
    @patch("nextdns_blocker.init.install_scheduling")
    @patch("nextdns_blocker.init.run_initial_sync")
    def test_non_interactive_scheduling_failure_continues(
        self,
        mock_sync: MagicMock,
        mock_scheduling: MagicMock,
        e2e_config_dir: Path,
    ) -> None:
        """Test non-interactive init continues even if scheduling fails."""
        from nextdns_blocker.init import run_non_interactive

        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"data": []},
            status=200,
        )
        mock_scheduling.return_value = (False, "Scheduling failed")
        mock_sync.return_value = True

        env = {
            "NEXTDNS_API_KEY": "valid-key",
            "NEXTDNS_PROFILE_ID": "abc123",
        }
        with patch.dict(os.environ, env, clear=True):
            result = run_non_interactive(e2e_config_dir)

        # Should still succeed, scheduling failure is a warning
        assert result is True

    @responses.activate
    @patch("nextdns_blocker.init.install_scheduling")
    @patch("nextdns_blocker.init.run_initial_sync")
    def test_non_interactive_sync_failure_continues(
        self,
        mock_sync: MagicMock,
        mock_scheduling: MagicMock,
        e2e_config_dir: Path,
    ) -> None:
        """Test non-interactive init continues even if sync fails."""
        from nextdns_blocker.init import run_non_interactive

        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"data": []},
            status=200,
        )
        mock_scheduling.return_value = (True, "launchd")
        mock_sync.return_value = False  # Sync fails

        env = {
            "NEXTDNS_API_KEY": "valid-key",
            "NEXTDNS_PROFILE_ID": "abc123",
        }
        with patch.dict(os.environ, env, clear=True):
            result = run_non_interactive(e2e_config_dir)

        # Should still succeed, sync failure is a warning
        assert result is True


class TestCreateEnvFileErrors:
    """Tests for error handling in create_env_file."""

    def test_create_env_file_oserror(self, tmp_path: Path) -> None:
        """Test create_env_file handles OSError during write."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Make the directory read-only to trigger OSError
        with patch("os.fdopen", side_effect=OSError("Permission denied")):
            with pytest.raises(OSError):
                create_env_file(
                    config_dir,
                    api_key="test-key",
                    profile_id="profile123",
                    timezone="UTC",
                )


class TestDetectExistingConfigErrors:
    """Tests for error handling in detect_existing_config."""

    def test_detect_existing_config_oserror(self, tmp_path: Path) -> None:
        """Test detect_existing_config handles OSError when reading .env."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        env_file = config_dir / ".env"
        env_file.write_text("DOMAINS_URL=https://example.com/d.json")

        # Mock read_text to raise OSError
        with patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
            result = detect_existing_config(config_dir)

        # Should handle gracefully and return no URL detected
        assert result["has_url"] is False


class TestHandleDomainsMigrationErrors:
    """Tests for error handling in handle_domains_migration."""

    def test_handle_migration_delete_oserror(self, tmp_path: Path) -> None:
        """Test handle_domains_migration handles OSError when deleting local file."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        local_file = config_dir / "domains.json"
        local_file.write_text('{"domains": []}')

        # Mock unlink to raise OSError
        with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
            url, should_create = handle_domains_migration(
                config_dir, "url", "https://example.com/d.json"
            )

        # Should continue despite delete failure
        assert url == "https://example.com/d.json"
        assert should_create is False


class TestInstallLaunchdErrors:
    """Tests for error handling in launchd installation."""

    @patch("nextdns_blocker.init.get_log_dir")
    @patch("nextdns_blocker.init.get_executable_args")
    def test_install_launchd_exception(
        self,
        mock_exe_args: MagicMock,
        mock_log_dir: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test launchd installation handles exceptions."""
        from nextdns_blocker.init import _install_launchd

        mock_log_dir.return_value = tmp_path / "logs"
        mock_exe_args.side_effect = Exception("Unexpected error")

        with patch.object(Path, "home", return_value=tmp_path):
            success, message = _install_launchd()

        assert success is False
        assert "launchd error" in message


class TestInstallCronErrors:
    """Tests for error handling in cron installation."""

    @patch("nextdns_blocker.init.get_log_dir")
    @patch("nextdns_blocker.init.get_executable_path")
    @patch("subprocess.run")
    def test_install_cron_set_failure(
        self,
        mock_run: MagicMock,
        mock_exe_path: MagicMock,
        mock_log_dir: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test cron installation handles crontab set failure."""
        from nextdns_blocker.init import _install_cron

        mock_log_dir.return_value = tmp_path / "logs"
        mock_exe_path.return_value = "/usr/local/bin/nextdns-blocker"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=""),  # crontab -l
            MagicMock(returncode=1),  # crontab - fails
        ]

        success, message = _install_cron()

        assert success is False
        assert "Failed to set crontab" in message

    @patch("nextdns_blocker.init.get_log_dir")
    @patch("nextdns_blocker.init.get_executable_path")
    def test_install_cron_exception(
        self,
        mock_exe_path: MagicMock,
        mock_log_dir: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test cron installation handles exceptions."""
        from nextdns_blocker.init import _install_cron

        mock_log_dir.return_value = tmp_path / "logs"
        mock_exe_path.side_effect = Exception("Unexpected error")

        success, message = _install_cron()

        assert success is False
        assert "cron error" in message


class TestInstallWindowsTaskErrors:
    """Tests for error handling in Windows task installation."""

    @patch("nextdns_blocker.init.get_log_dir")
    @patch("nextdns_blocker.init.get_executable_path")
    @patch("subprocess.run")
    def test_install_windows_watchdog_failure(
        self,
        mock_run: MagicMock,
        mock_exe_path: MagicMock,
        mock_log_dir: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test Windows task installation handles watchdog creation failure."""
        from nextdns_blocker.init import _install_windows_task

        mock_log_dir.return_value = tmp_path / "logs"
        mock_exe_path.return_value = "C:\\Program Files\\nextdns-blocker.exe"
        mock_run.side_effect = [
            MagicMock(returncode=0),  # delete sync
            MagicMock(returncode=0),  # delete watchdog
            MagicMock(returncode=0),  # create sync succeeds
            MagicMock(returncode=1, stderr="Access denied"),  # create watchdog fails
        ]

        success, message = _install_windows_task()

        assert success is False
        assert "Failed to create" in message

    @patch("nextdns_blocker.init.get_log_dir")
    @patch("nextdns_blocker.init.get_executable_path")
    def test_install_windows_exception(
        self,
        mock_exe_path: MagicMock,
        mock_log_dir: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test Windows task installation handles exceptions."""
        from nextdns_blocker.init import _install_windows_task

        mock_log_dir.return_value = tmp_path / "logs"
        mock_exe_path.side_effect = Exception("Unexpected error")

        success, message = _install_windows_task()

        assert success is False
        assert "Task Scheduler error" in message


class TestInteractiveWizard:
    """Tests for the interactive wizard flow."""

    @responses.activate
    @patch("nextdns_blocker.init.install_scheduling")
    @patch("nextdns_blocker.init.run_initial_sync")
    @patch("click.prompt")
    @patch("click.confirm")
    def test_interactive_wizard_success(
        self,
        mock_confirm: MagicMock,
        mock_prompt: MagicMock,
        mock_sync: MagicMock,
        mock_scheduling: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test successful interactive wizard flow."""
        from nextdns_blocker.init import run_interactive_wizard

        # Mock user inputs
        mock_prompt.side_effect = [
            "valid-api-key",  # API key
            "abc123",  # Profile ID
            "UTC",  # Timezone
            "",  # Domains URL (empty = skip)
        ]
        mock_confirm.return_value = True  # Create sample domains

        # Mock API validation
        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"data": []},
            status=200,
        )

        mock_scheduling.return_value = (True, "launchd")
        mock_sync.return_value = True

        config_dir = tmp_path / "config"
        result = run_interactive_wizard(config_dir)

        assert result is True
        assert (config_dir / ".env").exists()

    @responses.activate
    @patch("click.prompt")
    def test_interactive_wizard_empty_api_key(
        self,
        mock_prompt: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test interactive wizard fails with empty API key."""
        from nextdns_blocker.init import run_interactive_wizard

        mock_prompt.return_value = ""  # Empty API key

        config_dir = tmp_path / "config"
        result = run_interactive_wizard(config_dir)

        assert result is False

    @responses.activate
    @patch("click.prompt")
    def test_interactive_wizard_empty_profile_id(
        self,
        mock_prompt: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test interactive wizard fails with empty profile ID."""
        from nextdns_blocker.init import run_interactive_wizard

        mock_prompt.side_effect = [
            "valid-api-key",  # API key
            "",  # Empty Profile ID
        ]

        config_dir = tmp_path / "config"
        result = run_interactive_wizard(config_dir)

        assert result is False

    @responses.activate
    @patch("click.prompt")
    def test_interactive_wizard_invalid_timezone(
        self,
        mock_prompt: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test interactive wizard fails with invalid timezone."""
        from nextdns_blocker.init import run_interactive_wizard

        mock_prompt.side_effect = [
            "valid-api-key",  # API key
            "abc123",  # Profile ID
            "Invalid/TZ",  # Invalid timezone
        ]

        config_dir = tmp_path / "config"
        result = run_interactive_wizard(config_dir)

        assert result is False

    @responses.activate
    @patch("click.prompt")
    def test_interactive_wizard_invalid_credentials(
        self,
        mock_prompt: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test interactive wizard fails with invalid credentials."""
        from nextdns_blocker.init import run_interactive_wizard

        mock_prompt.side_effect = [
            "invalid-key",  # API key
            "abc123",  # Profile ID
            "UTC",  # Timezone
        ]

        # Mock API validation failure
        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"error": "Unauthorized"},
            status=401,
        )

        config_dir = tmp_path / "config"
        result = run_interactive_wizard(config_dir)

        assert result is False

    @responses.activate
    @patch("nextdns_blocker.init.install_scheduling")
    @patch("nextdns_blocker.init.run_initial_sync")
    @patch("click.prompt")
    @patch("click.confirm")
    def test_interactive_wizard_with_domains_url(
        self,
        mock_confirm: MagicMock,
        mock_prompt: MagicMock,
        mock_sync: MagicMock,
        mock_scheduling: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test interactive wizard with domains URL."""
        from nextdns_blocker.init import run_interactive_wizard

        mock_prompt.side_effect = [
            "valid-api-key",  # API key
            "abc123",  # Profile ID
            "UTC",  # Timezone
            "https://example.com/domains.json",  # Domains URL
        ]
        mock_confirm.return_value = False

        # Mock API validation
        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"data": []},
            status=200,
        )

        mock_scheduling.return_value = (True, "launchd")
        mock_sync.return_value = True

        config_dir = tmp_path / "config"
        result = run_interactive_wizard(config_dir)

        assert result is True
        content = (config_dir / ".env").read_text()
        assert "DOMAINS_URL=https://example.com/domains.json" in content

    @responses.activate
    @patch("click.prompt")
    def test_interactive_wizard_invalid_url(
        self,
        mock_prompt: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test interactive wizard fails with invalid URL."""
        from nextdns_blocker.init import run_interactive_wizard

        mock_prompt.side_effect = [
            "valid-api-key",  # API key
            "abc123",  # Profile ID
            "UTC",  # Timezone
            "not-a-valid-url",  # Invalid URL
        ]

        # Mock API validation
        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"data": []},
            status=200,
        )

        config_dir = tmp_path / "config"
        result = run_interactive_wizard(config_dir)

        assert result is False

    @responses.activate
    @patch("nextdns_blocker.init.install_scheduling")
    @patch("nextdns_blocker.init.run_initial_sync")
    @patch("click.prompt")
    @patch("click.confirm")
    @patch("nextdns_blocker.init.is_macos", return_value=True)
    @patch("nextdns_blocker.init.is_windows", return_value=False)
    def test_interactive_wizard_macos_output(
        self,
        mock_is_windows: MagicMock,
        mock_is_macos: MagicMock,
        mock_confirm: MagicMock,
        mock_prompt: MagicMock,
        mock_sync: MagicMock,
        mock_scheduling: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test interactive wizard shows macOS-specific output."""
        from nextdns_blocker.init import run_interactive_wizard

        mock_prompt.side_effect = [
            "valid-api-key",
            "abc123",
            "UTC",
            "",
        ]
        mock_confirm.return_value = False

        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"data": []},
            status=200,
        )

        mock_scheduling.return_value = (True, "launchd")
        mock_sync.return_value = True

        result = run_interactive_wizard(tmp_path / "config")

        assert result is True

    @responses.activate
    @patch("nextdns_blocker.init.install_scheduling")
    @patch("nextdns_blocker.init.run_initial_sync")
    @patch("click.prompt")
    @patch("click.confirm")
    @patch("nextdns_blocker.init.is_macos", return_value=False)
    @patch("nextdns_blocker.init.is_windows", return_value=True)
    def test_interactive_wizard_windows_output(
        self,
        mock_is_windows: MagicMock,
        mock_is_macos: MagicMock,
        mock_confirm: MagicMock,
        mock_prompt: MagicMock,
        mock_sync: MagicMock,
        mock_scheduling: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test interactive wizard shows Windows-specific output."""
        from nextdns_blocker.init import run_interactive_wizard

        mock_prompt.side_effect = [
            "valid-api-key",
            "abc123",
            "UTC",
            "",
        ]
        mock_confirm.return_value = False

        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"data": []},
            status=200,
        )

        mock_scheduling.return_value = (True, "Task Scheduler")
        mock_sync.return_value = True

        result = run_interactive_wizard(tmp_path / "config")

        assert result is True

    @responses.activate
    @patch("nextdns_blocker.init.install_scheduling")
    @patch("nextdns_blocker.init.run_initial_sync")
    @patch("click.prompt")
    @patch("click.confirm")
    @patch("nextdns_blocker.init.is_macos", return_value=False)
    @patch("nextdns_blocker.init.is_windows", return_value=False)
    def test_interactive_wizard_linux_output(
        self,
        mock_is_windows: MagicMock,
        mock_is_macos: MagicMock,
        mock_confirm: MagicMock,
        mock_prompt: MagicMock,
        mock_sync: MagicMock,
        mock_scheduling: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test interactive wizard shows Linux-specific output."""
        from nextdns_blocker.init import run_interactive_wizard

        mock_prompt.side_effect = [
            "valid-api-key",
            "abc123",
            "UTC",
            "",
        ]
        mock_confirm.return_value = False

        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"data": []},
            status=200,
        )

        mock_scheduling.return_value = (True, "cron")
        mock_sync.return_value = True

        result = run_interactive_wizard(tmp_path / "config")

        assert result is True

    @responses.activate
    @patch("nextdns_blocker.init.install_scheduling")
    @patch("nextdns_blocker.init.run_initial_sync")
    @patch("click.prompt")
    @patch("click.confirm")
    def test_interactive_wizard_scheduling_failure(
        self,
        mock_confirm: MagicMock,
        mock_prompt: MagicMock,
        mock_sync: MagicMock,
        mock_scheduling: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test interactive wizard handles scheduling failure."""
        from nextdns_blocker.init import run_interactive_wizard

        mock_prompt.side_effect = [
            "valid-api-key",
            "abc123",
            "UTC",
            "",
        ]
        mock_confirm.return_value = False

        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"data": []},
            status=200,
        )

        mock_scheduling.return_value = (False, "Scheduling failed")
        mock_sync.return_value = True

        result = run_interactive_wizard(tmp_path / "config")

        # Should still succeed
        assert result is True

    @responses.activate
    @patch("nextdns_blocker.init.install_scheduling")
    @patch("nextdns_blocker.init.run_initial_sync")
    @patch("click.prompt")
    @patch("click.confirm")
    def test_interactive_wizard_sync_failure(
        self,
        mock_confirm: MagicMock,
        mock_prompt: MagicMock,
        mock_sync: MagicMock,
        mock_scheduling: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test interactive wizard handles sync failure."""
        from nextdns_blocker.init import run_interactive_wizard

        mock_prompt.side_effect = [
            "valid-api-key",
            "abc123",
            "UTC",
            "",
        ]
        mock_confirm.return_value = False

        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"data": []},
            status=200,
        )

        mock_scheduling.return_value = (True, "launchd")
        mock_sync.return_value = False  # Sync fails

        result = run_interactive_wizard(tmp_path / "config")

        # Should still succeed
        assert result is True

    @responses.activate
    @patch("nextdns_blocker.init.install_scheduling")
    @patch("nextdns_blocker.init.run_initial_sync")
    @patch("click.prompt")
    @patch("click.confirm")
    def test_interactive_wizard_with_url_flag(
        self,
        mock_confirm: MagicMock,
        mock_prompt: MagicMock,
        mock_sync: MagicMock,
        mock_scheduling: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test interactive wizard with --url flag and existing local file."""
        from nextdns_blocker.init import run_interactive_wizard

        # Create existing local file
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "domains.json").write_text('{"domains": []}')

        mock_prompt.side_effect = [
            "valid-api-key",
            "abc123",
            "UTC",
        ]
        mock_confirm.return_value = True  # Delete local file

        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"data": []},
            status=200,
        )

        mock_scheduling.return_value = (True, "launchd")
        mock_sync.return_value = True

        result = run_interactive_wizard(config_dir, domains_url="https://example.com/domains.json")

        assert result is True
        # Local file should be deleted
        assert not (config_dir / "domains.json").exists()

    @responses.activate
    @patch("nextdns_blocker.init.install_scheduling")
    @patch("nextdns_blocker.init.run_initial_sync")
    @patch("nextdns_blocker.init.prompt_domains_migration")
    @patch("nextdns_blocker.init.handle_domains_migration")
    @patch("click.prompt")
    @patch("click.confirm")
    def test_interactive_wizard_with_existing_config(
        self,
        mock_confirm: MagicMock,
        mock_prompt: MagicMock,
        mock_handle_migration: MagicMock,
        mock_prompt_migration: MagicMock,
        mock_sync: MagicMock,
        mock_scheduling: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test interactive wizard with existing configuration."""
        from nextdns_blocker.init import run_interactive_wizard

        # Create existing local file
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "domains.json").write_text('{"domains": []}')

        mock_prompt.side_effect = [
            "valid-api-key",
            "abc123",
            "UTC",
        ]
        mock_confirm.return_value = False
        mock_prompt_migration.return_value = ("local", None)
        mock_handle_migration.return_value = (None, False)

        responses.add(
            responses.GET,
            f"{NEXTDNS_API_URL}/profiles/abc123/denylist",
            json={"data": []},
            status=200,
        )

        mock_scheduling.return_value = (True, "launchd")
        mock_sync.return_value = True

        result = run_interactive_wizard(config_dir)

        assert result is True


class TestPromptDomainsMigration:
    """Tests for the prompt_domains_migration function."""

    @patch("click.echo")
    @patch("click.prompt")
    def test_prompt_both_local_and_url_keep_url(
        self,
        mock_prompt: MagicMock,
        mock_echo: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test prompt when both local and URL exist - keep URL."""
        from nextdns_blocker.init import prompt_domains_migration

        existing: dict[str, Any] = {
            "has_local": True,
            "has_url": True,
            "url": "https://example.com/domains.json",
            "local_path": tmp_path / "domains.json",
        }

        mock_prompt.return_value = "1"  # Keep URL

        choice, url = prompt_domains_migration(existing)

        assert choice == "keep_url"
        assert url == "https://example.com/domains.json"

    @patch("click.echo")
    @patch("click.prompt")
    def test_prompt_both_local_and_url_switch_to_local(
        self,
        mock_prompt: MagicMock,
        mock_echo: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test prompt when both local and URL exist - switch to local."""
        from nextdns_blocker.init import prompt_domains_migration

        existing: dict[str, Any] = {
            "has_local": True,
            "has_url": True,
            "url": "https://example.com/domains.json",
            "local_path": tmp_path / "domains.json",
        }

        mock_prompt.return_value = "2"  # Switch to local

        choice, url = prompt_domains_migration(existing)

        assert choice == "local"
        assert url is None

    @patch("click.echo")
    @patch("click.prompt")
    def test_prompt_both_local_and_url_change_url(
        self,
        mock_prompt: MagicMock,
        mock_echo: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test prompt when both local and URL exist - change URL."""
        from nextdns_blocker.init import prompt_domains_migration

        existing: dict[str, Any] = {
            "has_local": True,
            "has_url": True,
            "url": "https://example.com/domains.json",
            "local_path": tmp_path / "domains.json",
        }

        mock_prompt.side_effect = ["3", "https://newurl.com/d.json"]

        choice, url = prompt_domains_migration(existing)

        assert choice == "url"
        assert url == "https://newurl.com/d.json"

    @patch("click.echo")
    @patch("click.prompt")
    def test_prompt_both_local_and_url_invalid_new_url(
        self,
        mock_prompt: MagicMock,
        mock_echo: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test prompt with invalid new URL falls back to keeping current."""
        from nextdns_blocker.init import prompt_domains_migration

        existing: dict[str, Any] = {
            "has_local": True,
            "has_url": True,
            "url": "https://example.com/domains.json",
            "local_path": tmp_path / "domains.json",
        }

        mock_prompt.side_effect = ["3", "not-a-url"]  # Invalid URL

        choice, url = prompt_domains_migration(existing)

        assert choice == "keep_url"
        assert url == "https://example.com/domains.json"

    @patch("click.echo")
    @patch("click.prompt")
    def test_prompt_both_keep_both(
        self,
        mock_prompt: MagicMock,
        mock_echo: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test prompt when both local and URL exist - keep both."""
        from nextdns_blocker.init import prompt_domains_migration

        existing: dict[str, Any] = {
            "has_local": True,
            "has_url": True,
            "url": "https://example.com/domains.json",
            "local_path": tmp_path / "domains.json",
        }

        mock_prompt.return_value = "4"  # Keep both

        choice, url = prompt_domains_migration(existing)

        assert choice == "both"
        assert url == "https://example.com/domains.json"

    @patch("click.echo")
    @patch("click.prompt")
    def test_prompt_local_only_keep(
        self,
        mock_prompt: MagicMock,
        mock_echo: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test prompt with local file only - keep local."""
        from nextdns_blocker.init import prompt_domains_migration

        existing: dict[str, Any] = {
            "has_local": True,
            "has_url": False,
            "url": None,
            "local_path": tmp_path / "domains.json",
        }

        mock_prompt.return_value = "1"  # Keep local

        choice, url = prompt_domains_migration(existing)

        assert choice == "local"
        assert url is None

    @patch("click.echo")
    @patch("click.prompt")
    def test_prompt_local_only_switch_to_url(
        self,
        mock_prompt: MagicMock,
        mock_echo: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test prompt with local file only - switch to URL."""
        from nextdns_blocker.init import prompt_domains_migration

        existing: dict[str, Any] = {
            "has_local": True,
            "has_url": False,
            "url": None,
            "local_path": tmp_path / "domains.json",
        }

        mock_prompt.side_effect = ["2", "https://example.com/d.json"]

        choice, url = prompt_domains_migration(existing)

        assert choice == "url"
        assert url == "https://example.com/d.json"

    @patch("click.echo")
    @patch("click.prompt")
    def test_prompt_local_only_invalid_url(
        self,
        mock_prompt: MagicMock,
        mock_echo: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test prompt with local file only - invalid URL falls back to local."""
        from nextdns_blocker.init import prompt_domains_migration

        existing: dict[str, Any] = {
            "has_local": True,
            "has_url": False,
            "url": None,
            "local_path": tmp_path / "domains.json",
        }

        mock_prompt.side_effect = ["2", "not-a-url"]

        choice, url = prompt_domains_migration(existing)

        assert choice == "local"
        assert url is None

    @patch("click.echo")
    @patch("click.prompt")
    def test_prompt_url_only_keep(
        self,
        mock_prompt: MagicMock,
        mock_echo: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test prompt with URL only - keep URL."""
        from nextdns_blocker.init import prompt_domains_migration

        existing: dict[str, Any] = {
            "has_local": False,
            "has_url": True,
            "url": "https://example.com/domains.json",
            "local_path": tmp_path / "domains.json",
        }

        mock_prompt.return_value = "1"  # Keep URL

        choice, url = prompt_domains_migration(existing)

        assert choice == "keep_url"
        assert url == "https://example.com/domains.json"

    @patch("click.echo")
    @patch("click.prompt")
    def test_prompt_url_only_switch_to_local(
        self,
        mock_prompt: MagicMock,
        mock_echo: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test prompt with URL only - switch to local."""
        from nextdns_blocker.init import prompt_domains_migration

        existing: dict[str, Any] = {
            "has_local": False,
            "has_url": True,
            "url": "https://example.com/domains.json",
            "local_path": tmp_path / "domains.json",
        }

        mock_prompt.return_value = "2"  # Switch to local

        choice, url = prompt_domains_migration(existing)

        assert choice == "local"
        assert url is None

    @patch("click.echo")
    @patch("click.prompt")
    def test_prompt_url_only_change_url(
        self,
        mock_prompt: MagicMock,
        mock_echo: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test prompt with URL only - change URL."""
        from nextdns_blocker.init import prompt_domains_migration

        existing: dict[str, Any] = {
            "has_local": False,
            "has_url": True,
            "url": "https://example.com/domains.json",
            "local_path": tmp_path / "domains.json",
        }

        mock_prompt.side_effect = ["3", "https://newurl.com/d.json"]

        choice, url = prompt_domains_migration(existing)

        assert choice == "url"
        assert url == "https://newurl.com/d.json"

    @patch("click.echo")
    @patch("click.prompt")
    def test_prompt_url_only_invalid_new_url(
        self,
        mock_prompt: MagicMock,
        mock_echo: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test prompt with URL only - invalid new URL keeps current."""
        from nextdns_blocker.init import prompt_domains_migration

        existing: dict[str, Any] = {
            "has_local": False,
            "has_url": True,
            "url": "https://example.com/domains.json",
            "local_path": tmp_path / "domains.json",
        }

        mock_prompt.side_effect = ["3", "not-a-url"]

        choice, url = prompt_domains_migration(existing)

        assert choice == "keep_url"
        assert url == "https://example.com/domains.json"

    def test_prompt_no_existing_config(self, tmp_path: Path) -> None:
        """Test prompt with no existing configuration."""
        from nextdns_blocker.init import prompt_domains_migration

        existing: dict[str, Any] = {
            "has_local": False,
            "has_url": False,
            "url": None,
            "local_path": tmp_path / "domains.json",
        }

        choice, url = prompt_domains_migration(existing)

        assert choice == "none"
        assert url is None
