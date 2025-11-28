"""Tests for CLI command handlers."""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import responses

from nextdns_blocker import (
    cmd_pause,
    cmd_resume,
    cmd_unblock,
    cmd_sync,
    cmd_status,
    cmd_health,
    cmd_stats,
    get_stats,
    is_paused,
    get_pause_remaining,
    set_pause,
    clear_pause,
    NextDNSClient,
    ScheduleEvaluator,
    API_URL,
    DomainValidationError,
    main,
    print_usage,
    audit_log,
    write_secure_file,
    read_secure_file,
    AUDIT_LOG_FILE,
    LOG_DIR,
)


@pytest.fixture
def temp_log_dir():
    """Create temporary log directory for pause file tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir)
        yield log_dir


@pytest.fixture
def mock_pause_file(temp_log_dir):
    """Mock the PAUSE_FILE location."""
    pause_file = temp_log_dir / ".paused"
    with patch('nextdns_blocker.PAUSE_FILE', pause_file):
        with patch('nextdns_blocker.LOG_DIR', temp_log_dir):
            yield pause_file


@pytest.fixture
def mock_client():
    """Create a mock NextDNS client."""
    return MagicMock(spec=NextDNSClient)


class TestPauseFunctions:
    """Tests for pause/resume functionality."""

    def test_is_paused_no_file(self, mock_pause_file):
        """Test is_paused returns False when no pause file exists."""
        assert is_paused() is False

    def test_is_paused_active(self, mock_pause_file):
        """Test is_paused returns True when pause is active."""
        future_time = datetime.now() + timedelta(minutes=30)
        mock_pause_file.write_text(future_time.isoformat())
        assert is_paused() is True

    def test_is_paused_expired(self, mock_pause_file):
        """Test is_paused returns False and cleans up when pause expired."""
        past_time = datetime.now() - timedelta(minutes=5)
        mock_pause_file.write_text(past_time.isoformat())
        assert is_paused() is False
        # File should be removed
        assert not mock_pause_file.exists()

    def test_get_pause_remaining_no_file(self, mock_pause_file):
        """Test get_pause_remaining returns None when no pause file."""
        assert get_pause_remaining() is None

    def test_get_pause_remaining_active(self, mock_pause_file):
        """Test get_pause_remaining returns time string when paused."""
        future_time = datetime.now() + timedelta(minutes=15)
        mock_pause_file.write_text(future_time.isoformat())
        remaining = get_pause_remaining()
        assert remaining is not None
        assert "min" in remaining

    def test_get_pause_remaining_less_than_minute(self, mock_pause_file):
        """Test get_pause_remaining shows '< 1 min' for short remaining time."""
        future_time = datetime.now() + timedelta(seconds=30)
        mock_pause_file.write_text(future_time.isoformat())
        remaining = get_pause_remaining()
        assert remaining == "< 1 min"

    def test_set_pause(self, mock_pause_file):
        """Test set_pause creates pause file correctly."""
        with patch('nextdns_blocker.audit_log'):
            pause_until = set_pause(30)
        assert mock_pause_file.exists()
        assert pause_until > datetime.now()

    def test_clear_pause_when_paused(self, mock_pause_file):
        """Test clear_pause removes pause file."""
        future_time = datetime.now() + timedelta(minutes=30)
        mock_pause_file.write_text(future_time.isoformat())
        with patch('nextdns_blocker.audit_log'):
            result = clear_pause()
        assert result is True
        assert not mock_pause_file.exists()

    def test_clear_pause_when_not_paused(self, mock_pause_file):
        """Test clear_pause returns False when not paused."""
        with patch('nextdns_blocker.audit_log'):
            result = clear_pause()
        assert result is False


class TestCmdPause:
    """Tests for cmd_pause command handler."""

    def test_cmd_pause_default(self, mock_pause_file, capsys):
        """Test pause command with default duration."""
        with patch('nextdns_blocker.audit_log'):
            result = cmd_pause()
        assert result == 0
        captured = capsys.readouterr()
        assert "30 minutes" in captured.out

    def test_cmd_pause_custom_duration(self, mock_pause_file, capsys):
        """Test pause command with custom duration."""
        with patch('nextdns_blocker.audit_log'):
            result = cmd_pause(60)
        assert result == 0
        captured = capsys.readouterr()
        assert "60 minutes" in captured.out


class TestCmdResume:
    """Tests for cmd_resume command handler."""

    def test_cmd_resume_when_paused(self, mock_pause_file, capsys):
        """Test resume command when system is paused."""
        future_time = datetime.now() + timedelta(minutes=30)
        mock_pause_file.write_text(future_time.isoformat())
        with patch('nextdns_blocker.audit_log'):
            result = cmd_resume()
        assert result == 0
        captured = capsys.readouterr()
        assert "resumed" in captured.out

    def test_cmd_resume_when_not_paused(self, mock_pause_file, capsys):
        """Test resume command when system is not paused."""
        with patch('nextdns_blocker.audit_log'):
            result = cmd_resume()
        assert result == 0
        captured = capsys.readouterr()
        assert "not paused" in captured.out


class TestCmdUnblock:
    """Tests for cmd_unblock command handler."""

    def test_cmd_unblock_success(self, mock_client, capsys):
        """Test successful unblock command."""
        mock_client.unblock.return_value = True
        with patch('nextdns_blocker.audit_log'):
            result = cmd_unblock("example.com", mock_client, [])
        assert result == 0
        captured = capsys.readouterr()
        assert "Unblocked" in captured.out

    def test_cmd_unblock_protected_domain(self, mock_client, capsys):
        """Test unblock command fails for protected domain."""
        result = cmd_unblock("protected.com", mock_client, ["protected.com"])
        assert result == 1
        captured = capsys.readouterr()
        assert "protected" in captured.out

    def test_cmd_unblock_invalid_domain(self, mock_client, capsys):
        """Test unblock command fails for invalid domain."""
        result = cmd_unblock("invalid domain!", mock_client, [])
        assert result == 1
        captured = capsys.readouterr()
        assert "Invalid domain" in captured.out

    def test_cmd_unblock_api_failure(self, mock_client, capsys):
        """Test unblock command handles API failure."""
        mock_client.unblock.return_value = False
        with patch('nextdns_blocker.audit_log'):
            result = cmd_unblock("example.com", mock_client, [])
        assert result == 1
        captured = capsys.readouterr()
        assert "Failed" in captured.out


class TestCmdSync:
    """Tests for cmd_sync command handler."""

    def test_cmd_sync_skips_when_paused(self, mock_pause_file, mock_client, capsys):
        """Test sync skips execution when paused."""
        future_time = datetime.now() + timedelta(minutes=30)
        mock_pause_file.write_text(future_time.isoformat())

        result = cmd_sync(mock_client, [], [], "UTC")
        assert result == 0
        mock_client.block.assert_not_called()

    def test_cmd_sync_invalid_timezone(self, mock_pause_file, mock_client, capsys):
        """Test sync fails with invalid timezone."""
        result = cmd_sync(mock_client, [], [], "Invalid/Timezone")
        assert result == 1
        captured = capsys.readouterr()
        assert "Invalid timezone" in captured.out

    @responses.activate
    def test_cmd_sync_blocks_domain(self, mock_pause_file):
        """Test sync blocks domains that should be blocked."""
        client = NextDNSClient("test_key", "test_profile")

        # Mock API calls
        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": []},
            status=200
        )
        responses.add(
            responses.POST,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"success": True},
            status=200
        )

        domains = [{"domain": "block-me.com", "schedule": None}]

        result = cmd_sync(client, domains, [], "UTC")
        assert result == 0


class TestCmdStatus:
    """Tests for cmd_status command handler."""

    @responses.activate
    def test_cmd_status_shows_blocked(self, capsys):
        """Test status command shows blocked domains."""
        client = NextDNSClient("test_key", "test_profile")

        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": [{"id": "example.com", "active": True}]},
            status=200
        )

        domains = [{"domain": "example.com", "schedule": None}]

        result = cmd_status(client, domains, [])
        assert result == 0
        captured = capsys.readouterr()
        assert "blocked" in captured.out

    def test_cmd_status_shows_pause_state(self, mock_pause_file, mock_client, capsys):
        """Test status command shows pause state."""
        future_time = datetime.now() + timedelta(minutes=30)
        mock_pause_file.write_text(future_time.isoformat())

        mock_client.find_domain.return_value = None

        result = cmd_status(mock_client, [], [])
        assert result == 0
        captured = capsys.readouterr()
        assert "PAUSED" in captured.out

    def test_cmd_status_shows_protected_domains(self, mock_pause_file, mock_client, capsys):
        """Test status command shows protected domains."""
        mock_client.find_domain.return_value = "protected.com"

        domains = [{"domain": "protected.com", "protected": True}]

        result = cmd_status(mock_client, domains, ["protected.com"])
        assert result == 0
        captured = capsys.readouterr()
        assert "protected" in captured.out


class TestDomainValidationInClient:
    """Tests for domain validation in client methods."""

    @responses.activate
    def test_block_validates_domain(self):
        """Test that block method validates domain format."""
        client = NextDNSClient("test_key", "test_profile")

        with pytest.raises(DomainValidationError):
            client.block("invalid domain!")

    @responses.activate
    def test_unblock_validates_domain(self):
        """Test that unblock method validates domain format."""
        client = NextDNSClient("test_key", "test_profile")

        with pytest.raises(DomainValidationError):
            client.unblock("invalid domain!")


class TestMain:
    """Tests for main() CLI entry point."""

    def test_main_no_args(self, capsys):
        """Test main with no arguments prints usage."""
        with patch.object(sys, 'argv', ['blocker.bin']):
            result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "Usage:" in captured.out

    def test_main_pause_default(self, mock_pause_file, capsys):
        """Test main with pause command uses default minutes."""
        with patch.object(sys, 'argv', ['blocker.bin', 'pause']):
            with patch('nextdns_blocker.audit_log'):
                result = main()
        assert result == 0
        captured = capsys.readouterr()
        assert "30 minutes" in captured.out

    def test_main_pause_custom(self, mock_pause_file, capsys):
        """Test main with pause command and custom minutes."""
        with patch.object(sys, 'argv', ['blocker.bin', 'pause', '45']):
            with patch('nextdns_blocker.audit_log'):
                result = main()
        assert result == 0
        captured = capsys.readouterr()
        assert "45 minutes" in captured.out

    def test_main_pause_invalid_minutes(self, capsys):
        """Test main with pause and invalid minutes."""
        with patch.object(sys, 'argv', ['blocker.bin', 'pause', 'abc']):
            result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "not a valid number" in captured.out

    def test_main_pause_negative_minutes(self, capsys):
        """Test main with pause and negative minutes."""
        with patch.object(sys, 'argv', ['blocker.bin', 'pause', '-5']):
            result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "positive number" in captured.out

    def test_main_resume(self, mock_pause_file, capsys):
        """Test main with resume command."""
        with patch.object(sys, 'argv', ['blocker.bin', 'resume']):
            with patch('nextdns_blocker.audit_log'):
                result = main()
        assert result == 0

    def test_main_unknown_command(self, capsys):
        """Test main with unknown command."""
        with patch.object(sys, 'argv', ['blocker.bin', 'unknown']):
            with patch('nextdns_blocker.load_config') as mock_config:
                with patch('nextdns_blocker.load_domains') as mock_domains:
                    with patch('nextdns_blocker.audit_log'):
                        mock_config.return_value = {
                            'api_key': 'test',
                            'profile_id': 'test',
                            'timeout': 10,
                            'retries': 2,
                            'timezone': 'UTC',
                            'script_dir': '/tmp'
                        }
                        mock_domains.return_value = []
                        result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "Usage:" in captured.out

    def test_main_config_error(self, capsys):
        """Test main handles configuration error."""
        from nextdns_blocker import ConfigurationError
        with patch.object(sys, 'argv', ['blocker.bin', 'status']):
            with patch('nextdns_blocker.load_config') as mock_config:
                mock_config.side_effect = ConfigurationError("Missing API key")
                result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "Configuration error" in captured.out

    def test_main_domains_error(self, capsys):
        """Test main handles domains loading error."""
        from nextdns_blocker import ConfigurationError
        with patch.object(sys, 'argv', ['blocker.bin', 'status']):
            with patch('nextdns_blocker.load_config') as mock_config:
                with patch('nextdns_blocker.load_domains') as mock_domains:
                    mock_config.return_value = {
                        'api_key': 'test',
                        'profile_id': 'test',
                        'timeout': 10,
                        'retries': 2,
                        'timezone': 'UTC',
                        'script_dir': '/tmp'
                    }
                    mock_domains.side_effect = ConfigurationError("Invalid domains")
                    result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "Configuration error" in captured.out

    def test_main_unblock_no_domain(self, capsys):
        """Test main with unblock but no domain argument."""
        with patch.object(sys, 'argv', ['blocker.bin', 'unblock']):
            with patch('nextdns_blocker.load_config') as mock_config:
                with patch('nextdns_blocker.load_domains') as mock_domains:
                    mock_config.return_value = {
                        'api_key': 'test',
                        'profile_id': 'test',
                        'timeout': 10,
                        'retries': 2,
                        'timezone': 'UTC',
                        'script_dir': '/tmp'
                    }
                    mock_domains.return_value = []
                    result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "Usage: unblock" in captured.out


class TestAuditLog:
    """Tests for audit_log function."""

    def test_audit_log_creates_file(self, temp_log_dir):
        """Test audit_log creates log file if not exists."""
        audit_file = temp_log_dir / "audit.log"
        with patch('common.AUDIT_LOG_FILE', audit_file):
            audit_log("TEST_ACTION", "test detail")
        assert audit_file.exists()

    def test_audit_log_writes_entry(self, temp_log_dir):
        """Test audit_log writes correct format."""
        audit_file = temp_log_dir / "audit.log"
        with patch('common.AUDIT_LOG_FILE', audit_file):
            audit_log("BLOCK", "example.com")
        content = audit_file.read_text()
        assert "BLOCK" in content
        assert "example.com" in content

    def test_audit_log_with_prefix(self, temp_log_dir):
        """Test audit_log with prefix."""
        audit_file = temp_log_dir / "audit.log"
        with patch('common.AUDIT_LOG_FILE', audit_file):
            audit_log("ACTION", "detail", prefix="WD")
        content = audit_file.read_text()
        assert "WD" in content

    def test_audit_log_handles_error(self, temp_log_dir):
        """Test audit_log handles write errors gracefully."""
        with patch('common.AUDIT_LOG_FILE', Path("/nonexistent/path/audit.log")):
            # Should not raise
            audit_log("ACTION", "detail")


class TestWriteSecureFile:
    """Tests for write_secure_file function."""

    def test_write_secure_file_creates_file(self, temp_log_dir):
        """Test write_secure_file creates file with content."""
        test_file = temp_log_dir / "test.txt"
        write_secure_file(test_file, "test content")
        assert test_file.exists()
        assert test_file.read_text() == "test content"

    def test_write_secure_file_permissions(self, temp_log_dir):
        """Test write_secure_file sets secure permissions."""
        test_file = temp_log_dir / "test.txt"
        write_secure_file(test_file, "content")
        mode = test_file.stat().st_mode & 0o777
        assert mode == 0o600

    def test_write_secure_file_creates_parents(self, temp_log_dir):
        """Test write_secure_file creates parent directories."""
        test_file = temp_log_dir / "subdir" / "test.txt"
        write_secure_file(test_file, "content")
        assert test_file.exists()

    def test_write_secure_file_overwrites(self, temp_log_dir):
        """Test write_secure_file overwrites existing file."""
        test_file = temp_log_dir / "test.txt"
        test_file.write_text("old content")
        write_secure_file(test_file, "new content")
        assert test_file.read_text() == "new content"


class TestReadSecureFile:
    """Tests for read_secure_file function."""

    def test_read_secure_file_exists(self, temp_log_dir):
        """Test read_secure_file reads existing file."""
        test_file = temp_log_dir / "test.txt"
        test_file.write_text("  content  ")
        result = read_secure_file(test_file)
        assert result == "content"

    def test_read_secure_file_not_exists(self, temp_log_dir):
        """Test read_secure_file returns None for missing file."""
        test_file = temp_log_dir / "nonexistent.txt"
        result = read_secure_file(test_file)
        assert result is None


class TestPrintUsage:
    """Tests for print_usage function."""

    def test_print_usage_output(self, capsys):
        """Test print_usage shows all commands."""
        print_usage()
        captured = capsys.readouterr()
        assert "sync" in captured.out
        assert "status" in captured.out
        assert "unblock" in captured.out
        assert "pause" in captured.out
        assert "resume" in captured.out

    def test_print_usage_shows_options(self, capsys):
        """Test print_usage shows sync options."""
        print_usage()
        captured = capsys.readouterr()
        assert "--dry-run" in captured.out
        assert "--verbose" in captured.out


class TestCmdSyncDryRun:
    """Tests for cmd_sync dry-run functionality."""

    @responses.activate
    def test_dry_run_shows_would_block(self, mock_pause_file, capsys):
        """Test dry-run shows what would be blocked."""
        client = NextDNSClient("test_key", "test_profile")

        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": []},
            status=200
        )

        domains = [{"domain": "block-me.com", "schedule": None}]

        result = cmd_sync(client, domains, [], "UTC", dry_run=True)
        assert result == 0
        captured = capsys.readouterr()
        assert "DRY RUN MODE" in captured.out
        assert "WOULD BLOCK" in captured.out
        assert "block-me.com" in captured.out

    @responses.activate
    def test_dry_run_shows_would_unblock(self, mock_pause_file, capsys):
        """Test dry-run shows what would be unblocked."""
        from freezegun import freeze_time

        client = NextDNSClient("test_key", "test_profile")

        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": [{"id": "unblock-me.com", "active": True}]},
            status=200
        )

        # Domain is available all day on Wednesday
        domains = [{
            "domain": "unblock-me.com",
            "schedule": {
                "available_hours": [{
                    "days": ["wednesday"],
                    "time_ranges": [{"start": "00:00", "end": "23:59"}]
                }]
            }
        }]

        # Freeze time to Wednesday at noon UTC
        with freeze_time("2025-11-26 12:00:00"):
            result = cmd_sync(client, domains, [], "UTC", dry_run=True)

        assert result == 0
        captured = capsys.readouterr()
        assert "DRY RUN MODE" in captured.out
        assert "WOULD UNBLOCK" in captured.out

    @responses.activate
    def test_dry_run_no_api_changes(self, mock_pause_file):
        """Test dry-run doesn't make any API changes."""
        client = NextDNSClient("test_key", "test_profile")

        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": []},
            status=200
        )
        # No POST should be made in dry-run

        domains = [{"domain": "block-me.com", "schedule": None}]

        cmd_sync(client, domains, [], "UTC", dry_run=True)

        # Only GET request should have been made, no POST
        assert len(responses.calls) == 1
        assert responses.calls[0].request.method == "GET"

    @responses.activate
    def test_dry_run_shows_summary(self, mock_pause_file, capsys):
        """Test dry-run shows summary."""
        client = NextDNSClient("test_key", "test_profile")

        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": []},
            status=200
        )

        domains = [{"domain": "block-me.com", "schedule": None}]

        cmd_sync(client, domains, [], "UTC", dry_run=True)
        captured = capsys.readouterr()
        assert "Summary (DRY RUN)" in captured.out


class TestCmdSyncVerbose:
    """Tests for cmd_sync verbose functionality."""

    @responses.activate
    def test_verbose_shows_blocked_domains(self, mock_pause_file, capsys):
        """Test verbose shows blocked domains."""
        client = NextDNSClient("test_key", "test_profile")

        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": []},
            status=200
        )
        responses.add(
            responses.POST,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"success": True},
            status=200
        )

        domains = [{"domain": "block-me.com", "schedule": None}]

        result = cmd_sync(client, domains, [], "UTC", verbose=True)
        assert result == 0
        captured = capsys.readouterr()
        assert "[BLOCKED]" in captured.out

    @responses.activate
    def test_verbose_shows_summary(self, mock_pause_file, capsys):
        """Test verbose shows summary at the end."""
        client = NextDNSClient("test_key", "test_profile")

        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": [{"id": "already-blocked.com", "active": True}]},
            status=200
        )

        domains = [{"domain": "already-blocked.com", "schedule": None}]

        cmd_sync(client, domains, [], "UTC", verbose=True)
        captured = capsys.readouterr()
        assert "Summary:" in captured.out
        assert "Unchanged:" in captured.out

    @responses.activate
    def test_verbose_shows_unblocked_domains(self, mock_pause_file, capsys):
        """Test verbose shows unblocked domains."""
        from freezegun import freeze_time
        client = NextDNSClient("test_key", "test_profile")

        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": [{"id": "unblock-me.com", "active": True}]},
            status=200
        )
        responses.add(
            responses.DELETE,
            f"{API_URL}/profiles/test_profile/denylist/unblock-me.com",
            json={"success": True},
            status=200
        )

        # Domain available all day on Wednesday
        domains = [{
            "domain": "unblock-me.com",
            "schedule": {
                "available_hours": [{
                    "days": ["wednesday"],
                    "time_ranges": [{"start": "00:00", "end": "23:59"}]
                }]
            }
        }]

        with freeze_time("2025-11-26 12:00:00"):
            result = cmd_sync(client, domains, [], "UTC", verbose=True)

        assert result == 0
        captured = capsys.readouterr()
        assert "[UNBLOCKED]" in captured.out

    @responses.activate
    def test_verbose_protected_domain_block(self, mock_pause_file, capsys):
        """Test verbose shows protected domain blocking."""
        client = NextDNSClient("test_key", "test_profile")

        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": []},
            status=200
        )
        responses.add(
            responses.POST,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"success": True},
            status=200
        )

        domains = [{"domain": "protected.com", "protected": True, "schedule": None}]
        protected = ["protected.com"]

        with patch('nextdns_blocker.audit_log'):
            result = cmd_sync(client, domains, protected, "UTC", verbose=True)

        assert result == 0
        captured = capsys.readouterr()
        assert "[BLOCKED]" in captured.out
        assert "protected" in captured.out

    @responses.activate
    def test_verbose_paused_message(self, mock_pause_file, capsys):
        """Test verbose shows paused message."""
        client = NextDNSClient("test_key", "test_profile")

        future_time = datetime.now() + timedelta(minutes=15)
        mock_pause_file.write_text(future_time.isoformat())

        result = cmd_sync(client, [], [], "UTC", verbose=True)
        assert result == 0
        captured = capsys.readouterr()
        assert "paused" in captured.out.lower()


class TestCmdSyncProtectedDomains:
    """Tests for cmd_sync with protected domains."""

    @responses.activate
    def test_dry_run_protected_unblocked(self, mock_pause_file, capsys):
        """Test dry-run shows protected domain that needs blocking."""
        client = NextDNSClient("test_key", "test_profile")

        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": []},  # Protected domain is NOT blocked
            status=200
        )

        domains = [{"domain": "protected.com", "protected": True, "schedule": None}]
        protected = ["protected.com"]

        result = cmd_sync(client, domains, protected, "UTC", dry_run=True)
        assert result == 0
        captured = capsys.readouterr()
        assert "WOULD BLOCK" in captured.out
        assert "protected" in captured.out

    @responses.activate
    def test_dry_run_protected_already_blocked(self, mock_pause_file, capsys):
        """Test dry-run shows protected domain already blocked."""
        client = NextDNSClient("test_key", "test_profile")

        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": [{"id": "protected.com", "active": True}]},
            status=200
        )

        domains = [{"domain": "protected.com", "protected": True, "schedule": None}]
        protected = ["protected.com"]

        result = cmd_sync(client, domains, protected, "UTC", dry_run=True)
        assert result == 0
        captured = capsys.readouterr()
        assert "[OK]" in captured.out
        assert "protected" in captured.out


class TestMainWithSyncOptions:
    """Tests for main() with sync options."""

    @responses.activate
    def test_main_sync_dry_run(self, mock_pause_file, capsys):
        """Test main passes dry-run flag to cmd_sync."""
        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": []},
            status=200
        )

        with patch.object(sys, 'argv', ['blocker.bin', 'sync', '--dry-run']):
            with patch('nextdns_blocker.load_config') as mock_config:
                with patch('nextdns_blocker.load_domains') as mock_domains:
                    mock_config.return_value = {
                        'api_key': 'test',
                        'profile_id': 'test_profile',
                        'timeout': 10,
                        'retries': 3,
                        'timezone': 'UTC',
                        'script_dir': '/tmp'
                    }
                    mock_domains.return_value = [{"domain": "test.com", "schedule": None}]
                    result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "DRY RUN MODE" in captured.out

    @responses.activate
    def test_main_sync_verbose(self, mock_pause_file, capsys):
        """Test main passes verbose flag to cmd_sync."""
        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": [{"id": "test.com", "active": True}]},
            status=200
        )

        with patch.object(sys, 'argv', ['blocker.bin', 'sync', '-v']):
            with patch('nextdns_blocker.load_config') as mock_config:
                with patch('nextdns_blocker.load_domains') as mock_domains:
                    mock_config.return_value = {
                        'api_key': 'test',
                        'profile_id': 'test_profile',
                        'timeout': 10,
                        'retries': 3,
                        'timezone': 'UTC',
                        'script_dir': '/tmp'
                    }
                    mock_domains.return_value = [{"domain": "test.com", "schedule": None}]
                    result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Summary:" in captured.out


class TestCmdHealth:
    """Tests for cmd_health command."""

    @responses.activate
    def test_health_all_ok(self, mock_pause_file, capsys):
        """Test health command when everything is healthy."""
        client = NextDNSClient("test_key", "test_profile")

        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": [{"id": "example.com"}]},
            status=200
        )

        config = {
            'api_key': 'test_key',
            'profile_id': 'test_profile',
            'timezone': 'UTC'
        }

        with patch('nextdns_blocker.LOG_DIR', mock_pause_file.parent):
            result = cmd_health(client, config)

        assert result == 0
        captured = capsys.readouterr()
        assert "HEALTHY" in captured.out
        assert "[OK]" in captured.out

    @responses.activate
    def test_health_api_failure(self, mock_pause_file, capsys):
        """Test health command when API fails."""
        client = NextDNSClient("test_key", "test_profile")

        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"error": "unauthorized"},
            status=401
        )

        config = {
            'api_key': 'bad_key',
            'profile_id': 'test_profile',
            'timezone': 'UTC'
        }

        with patch('nextdns_blocker.LOG_DIR', mock_pause_file.parent):
            result = cmd_health(client, config)

        assert result == 1
        captured = capsys.readouterr()
        assert "UNHEALTHY" in captured.out

    @responses.activate
    def test_health_shows_pause_state(self, mock_pause_file, capsys):
        """Test health command shows pause state."""
        client = NextDNSClient("test_key", "test_profile")

        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": []},
            status=200
        )

        # Set pause state
        future_time = datetime.now() + timedelta(minutes=15)
        mock_pause_file.write_text(future_time.isoformat())

        config = {
            'api_key': 'test_key',
            'profile_id': 'test_profile',
            'timezone': 'UTC'
        }

        with patch('nextdns_blocker.LOG_DIR', mock_pause_file.parent):
            result = cmd_health(client, config)

        captured = capsys.readouterr()
        assert "PAUSED" in captured.out

    @responses.activate
    def test_health_invalid_timezone(self, mock_pause_file, capsys):
        """Test health command with invalid timezone."""
        client = NextDNSClient("test_key", "test_profile")

        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": []},
            status=200
        )

        config = {
            'api_key': 'test_key',
            'profile_id': 'test_profile',
            'timezone': 'Invalid/Timezone'
        }

        with patch('nextdns_blocker.LOG_DIR', mock_pause_file.parent):
            result = cmd_health(client, config)

        assert result == 1
        captured = capsys.readouterr()
        assert "Invalid timezone" in captured.out


class TestCmdStats:
    """Tests for cmd_stats command."""

    def test_stats_no_audit_file(self, temp_log_dir, capsys):
        """Test stats with no audit log file."""
        with patch('nextdns_blocker.AUDIT_LOG_FILE', temp_log_dir / "audit.log"):
            result = cmd_stats()

        assert result == 0
        captured = capsys.readouterr()
        assert "Total blocks:" in captured.out
        assert "0" in captured.out

    def test_stats_with_audit_data(self, temp_log_dir, capsys):
        """Test stats with audit log data."""
        audit_file = temp_log_dir / "audit.log"
        audit_file.write_text(
            "2025-01-01 10:00:00 | BLOCK | example.com\n"
            "2025-01-01 11:00:00 | BLOCK | test.com\n"
            "2025-01-01 12:00:00 | UNBLOCK | example.com\n"
            "2025-01-01 13:00:00 | PAUSE | 30 minutes\n"
        )

        with patch('nextdns_blocker.AUDIT_LOG_FILE', audit_file):
            result = cmd_stats()

        assert result == 0
        captured = capsys.readouterr()
        assert "Total blocks:" in captured.out
        assert "2" in captured.out  # 2 blocks
        assert "Total unblocks:" in captured.out
        assert "1" in captured.out  # 1 unblock
        assert "Total pauses:" in captured.out


class TestGetStats:
    """Tests for get_stats function."""

    def test_get_stats_no_file(self, temp_log_dir):
        """Test get_stats when file doesn't exist."""
        with patch('nextdns_blocker.AUDIT_LOG_FILE', temp_log_dir / "nonexistent.log"):
            stats = get_stats()

        assert stats['total_blocks'] == 0
        assert stats['total_unblocks'] == 0
        assert stats['total_pauses'] == 0

    def test_get_stats_parses_correctly(self, temp_log_dir):
        """Test get_stats parses audit log correctly."""
        audit_file = temp_log_dir / "audit.log"
        audit_file.write_text(
            "2025-01-01 10:00:00 | BLOCK | a.com\n"
            "2025-01-01 11:00:00 | BLOCK | b.com\n"
            "2025-01-01 12:00:00 | BLOCK | c.com\n"
            "2025-01-01 13:00:00 | UNBLOCK | a.com\n"
            "2025-01-01 14:00:00 | UNBLOCK | b.com\n"
            "2025-01-01 15:00:00 | PAUSE | 60\n"
        )

        with patch('nextdns_blocker.AUDIT_LOG_FILE', audit_file):
            stats = get_stats()

        assert stats['total_blocks'] == 3
        assert stats['total_unblocks'] == 2
        assert stats['total_pauses'] == 1
        assert stats['last_action'] == "2025-01-01 15:00:00"


class TestMainHealthAndStats:
    """Tests for main() with health and stats commands."""

    @responses.activate
    def test_main_health_command(self, mock_pause_file, capsys):
        """Test main with health command."""
        responses.add(
            responses.GET,
            f"{API_URL}/profiles/test_profile/denylist",
            json={"data": []},
            status=200
        )

        with patch.object(sys, 'argv', ['blocker.bin', 'health']):
            with patch('nextdns_blocker.load_config') as mock_config:
                with patch('nextdns_blocker.load_domains') as mock_domains:
                    with patch('nextdns_blocker.LOG_DIR', mock_pause_file.parent):
                        mock_config.return_value = {
                            'api_key': 'test',
                            'profile_id': 'test_profile',
                            'timeout': 10,
                            'retries': 3,
                            'timezone': 'UTC',
                            'script_dir': '/tmp'
                        }
                        mock_domains.return_value = []
                        result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Health Check" in captured.out

    def test_main_stats_command(self, temp_log_dir, capsys):
        """Test main with stats command."""
        with patch.object(sys, 'argv', ['blocker.bin', 'stats']):
            with patch('nextdns_blocker.load_config') as mock_config:
                with patch('nextdns_blocker.load_domains') as mock_domains:
                    with patch('nextdns_blocker.AUDIT_LOG_FILE', temp_log_dir / "audit.log"):
                        mock_config.return_value = {
                            'api_key': 'test',
                            'profile_id': 'test_profile',
                            'timeout': 10,
                            'retries': 3,
                            'timezone': 'UTC',
                            'script_dir': '/tmp'
                        }
                        mock_domains.return_value = []
                        result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Statistics" in captured.out
