"""E2E tests for the stats command.

Tests the statistics display including:
- Reading audit log file
- Counting different action types
- Handling missing audit log
- Handling corrupted audit log
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from nextdns_blocker.cli import main


class TestStatsBasic:
    """Tests for basic stats command functionality."""

    def test_stats_shows_action_counts(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Test that stats command shows action counts from audit log."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        # Create audit log with various actions
        audit_file = log_dir / "audit.log"
        audit_entries = [
            "2024-01-15T10:00:00 | BLOCK | youtube.com",
            "2024-01-15T10:05:00 | BLOCK | twitter.com",
            "2024-01-15T10:10:00 | UNBLOCK | youtube.com",
            "2024-01-15T10:15:00 | PAUSE | 30 minutes",
            "2024-01-15T10:45:00 | RESUME | Manual resume",
            "2024-01-15T11:00:00 | BLOCK | facebook.com",
        ]
        audit_file.write_text("\n".join(audit_entries))

        with patch("nextdns_blocker.cli.get_audit_log_file", return_value=audit_file):
            result = runner.invoke(main, ["stats"])

        assert result.exit_code == 0
        assert "BLOCK" in result.output
        assert "UNBLOCK" in result.output
        assert "PAUSE" in result.output
        assert "RESUME" in result.output
        assert "Total entries: 6" in result.output

    def test_stats_handles_empty_log(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Test that stats handles empty audit log gracefully."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        audit_file = log_dir / "audit.log"
        audit_file.write_text("")

        with patch("nextdns_blocker.cli.get_audit_log_file", return_value=audit_file):
            result = runner.invoke(main, ["stats"])

        assert result.exit_code == 0
        assert "No actions recorded" in result.output or "Total entries: 0" in result.output

    def test_stats_handles_missing_log(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Test that stats handles missing audit log gracefully."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        audit_file = log_dir / "audit.log"
        # Don't create the file

        with patch("nextdns_blocker.cli.get_audit_log_file", return_value=audit_file):
            result = runner.invoke(main, ["stats"])

        assert result.exit_code == 0
        assert "No audit log found" in result.output


class TestStatsWatchdogEntries:
    """Tests for stats handling watchdog entries."""

    def test_stats_parses_watchdog_entries(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Test that stats correctly parses WD-prefixed entries."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        audit_file = log_dir / "audit.log"
        audit_entries = [
            "2024-01-15T10:00:00 | BLOCK | youtube.com",
            "2024-01-15T10:05:00 | WD | RESTORE | cron jobs restored",
            "2024-01-15T10:10:00 | WD | CHECK | jobs ok",
            "2024-01-15T10:15:00 | UNBLOCK | youtube.com",
        ]
        audit_file.write_text("\n".join(audit_entries))

        with patch("nextdns_blocker.cli.get_audit_log_file", return_value=audit_file):
            result = runner.invoke(main, ["stats"])

        assert result.exit_code == 0
        assert "BLOCK" in result.output
        assert "UNBLOCK" in result.output
        # WD entries should be parsed as their actual action
        assert "RESTORE" in result.output or "CHECK" in result.output


class TestStatsActionTypes:
    """Tests for stats with various action types."""

    def test_stats_shows_allow_disallow_actions(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Test that stats shows ALLOW and DISALLOW actions."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        audit_file = log_dir / "audit.log"
        audit_entries = [
            "2024-01-15T10:00:00 | ALLOW | trusted-site.com",
            "2024-01-15T10:05:00 | ALLOW | another-trusted.com",
            "2024-01-15T10:10:00 | DISALLOW | untrusted.com",
        ]
        audit_file.write_text("\n".join(audit_entries))

        with patch("nextdns_blocker.cli.get_audit_log_file", return_value=audit_file):
            result = runner.invoke(main, ["stats"])

        assert result.exit_code == 0
        assert "ALLOW" in result.output
        assert "DISALLOW" in result.output

    def test_stats_shows_sorted_actions(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Test that stats shows actions sorted alphabetically."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        audit_file = log_dir / "audit.log"
        audit_entries = [
            "2024-01-15T10:00:00 | UNBLOCK | site.com",
            "2024-01-15T10:05:00 | BLOCK | site.com",
            "2024-01-15T10:10:00 | ALLOW | site.com",
        ]
        audit_file.write_text("\n".join(audit_entries))

        with patch("nextdns_blocker.cli.get_audit_log_file", return_value=audit_file):
            result = runner.invoke(main, ["stats"])

        assert result.exit_code == 0
        # ALLOW should come before BLOCK, which should come before UNBLOCK
        allow_pos = result.output.find("ALLOW")
        block_pos = result.output.find("BLOCK")
        unblock_pos = result.output.find("UNBLOCK")

        assert allow_pos < block_pos < unblock_pos


class TestStatsMalformedEntries:
    """Tests for stats handling malformed log entries."""

    def test_stats_handles_malformed_entries(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Test that stats handles malformed log entries gracefully."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        audit_file = log_dir / "audit.log"
        audit_entries = [
            "2024-01-15T10:00:00 | BLOCK | youtube.com",
            "malformed line without proper format",
            "2024-01-15T10:10:00 | UNBLOCK | youtube.com",
            "",  # Empty line
            "another bad line",
        ]
        audit_file.write_text("\n".join(audit_entries))

        with patch("nextdns_blocker.cli.get_audit_log_file", return_value=audit_file):
            result = runner.invoke(main, ["stats"])

        assert result.exit_code == 0
        # Should still show valid entries
        assert "BLOCK" in result.output
        assert "UNBLOCK" in result.output


class TestStatsLargeLog:
    """Tests for stats with large audit logs."""

    def test_stats_handles_large_log(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Test that stats handles large audit log efficiently."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        audit_file = log_dir / "audit.log"

        # Create a log file with 100 entries (reduced from 1000 for faster tests)
        entries = []
        for i in range(100):
            action = ["BLOCK", "UNBLOCK", "PAUSE", "RESUME"][i % 4]
            entries.append(f"2024-01-15T10:{i:02d}:00 | {action} | domain{i}.com")

        audit_file.write_text("\n".join(entries))

        with patch("nextdns_blocker.cli.get_audit_log_file", return_value=audit_file):
            result = runner.invoke(main, ["stats"])

        assert result.exit_code == 0
        assert "Total entries: 100" in result.output
        # Each action should appear 25 times
        assert "25" in result.output
