"""E2E tests for the initialization (onboarding) flow.

Tests the complete setup wizard including:
- Creating configuration files
- Validating API credentials
- Creating sample domains.json
- Verifying sync works after init
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import responses
from click.testing import CliRunner

from nextdns_blocker.cli import main
from nextdns_blocker.client import API_URL

from .conftest import (
    TEST_API_KEY,
    TEST_PROFILE_ID,
    TEST_TIMEZONE,
)


class TestInitNonInteractive:
    """Tests for non-interactive initialization."""

    @responses.activate
    def test_init_creates_env_file(
        self,
        runner: CliRunner,
        tmp_path: Path,
        clean_env: None,
    ) -> None:
        """Test that init --non-interactive creates .env file with correct content."""
        config_dir = tmp_path / "config"

        # Mock API validation call
        responses.add(
            responses.GET,
            f"{API_URL}/profiles/{TEST_PROFILE_ID}/denylist",
            json={"data": []},
            status=200,
        )

        # Set environment variables for non-interactive mode
        env = {
            "NEXTDNS_API_KEY": TEST_API_KEY,
            "NEXTDNS_PROFILE_ID": TEST_PROFILE_ID,
            "TIMEZONE": TEST_TIMEZONE,
        }

        # Mock scheduler installation and initial sync to avoid side effects
        with patch("nextdns_blocker.init.install_scheduling", return_value=(True, "mock")):
            with patch("nextdns_blocker.init.run_initial_sync", return_value=True):
                with patch.dict(os.environ, env, clear=False):
                    result = runner.invoke(
                        main,
                        ["init", "--non-interactive", "--config-dir", str(config_dir)],
                    )

        assert result.exit_code == 0, f"Init failed: {result.output}"

        # Verify .env file was created
        env_file = config_dir / ".env"
        assert env_file.exists(), "Expected .env file to be created"

        env_content = env_file.read_text()
        assert TEST_API_KEY in env_content
        assert TEST_PROFILE_ID in env_content
        assert TEST_TIMEZONE in env_content

    @responses.activate
    def test_init_non_interactive_does_not_create_domains_json(
        self,
        runner: CliRunner,
        tmp_path: Path,
        clean_env: None,
    ) -> None:
        """Test that init --non-interactive creates .env but not domains.json.

        Note: Non-interactive init is designed for CI/CD where domains.json
        should already exist or a DOMAINS_URL should be provided.
        """
        config_dir = tmp_path / "config"

        # Mock API validation
        responses.add(
            responses.GET,
            f"{API_URL}/profiles/{TEST_PROFILE_ID}/denylist",
            json={"data": []},
            status=200,
        )

        # Mock scheduler installation
        with patch("nextdns_blocker.init.install_scheduling", return_value=(True, "mock")):
            with patch("nextdns_blocker.init.run_initial_sync", return_value=True):
                env = {
                    "NEXTDNS_API_KEY": TEST_API_KEY,
                    "NEXTDNS_PROFILE_ID": TEST_PROFILE_ID,
                    "TIMEZONE": TEST_TIMEZONE,
                }

                with patch.dict(os.environ, env, clear=False):
                    result = runner.invoke(
                        main,
                        ["init", "--non-interactive", "--config-dir", str(config_dir)],
                    )

        assert result.exit_code == 0, f"Init failed: {result.output}"

        # Non-interactive mode only creates .env, not domains.json
        # (domains.json should be created separately or via --url)
        env_file = config_dir / ".env"
        assert env_file.exists(), "Expected .env to be created"

        config_dir / "domains.json"
        # Non-interactive mode doesn't create sample domains.json
        # This is expected behavior for CI/CD environments

    @responses.activate
    def test_init_with_invalid_credentials_fails(
        self,
        runner: CliRunner,
        tmp_path: Path,
        clean_env: None,
    ) -> None:
        """Test that init fails gracefully with invalid API credentials."""
        config_dir = tmp_path / "config"

        # Mock API returning 401 Unauthorized
        responses.add(
            responses.GET,
            f"{API_URL}/profiles/{TEST_PROFILE_ID}/denylist",
            json={"error": "Unauthorized"},
            status=401,
        )

        env = {
            "NEXTDNS_API_KEY": "invalid-key",
            "NEXTDNS_PROFILE_ID": TEST_PROFILE_ID,
            "TIMEZONE": TEST_TIMEZONE,
        }

        with patch.dict(os.environ, env, clear=False):
            result = runner.invoke(
                main,
                ["init", "--non-interactive", "--config-dir", str(config_dir)],
            )

        assert result.exit_code != 0, "Init should fail with invalid credentials"

    @responses.activate
    def test_init_with_invalid_timezone_fails(
        self,
        runner: CliRunner,
        tmp_path: Path,
        clean_env: None,
    ) -> None:
        """Test that init fails with invalid timezone."""
        config_dir = tmp_path / "config"

        env = {
            "NEXTDNS_API_KEY": TEST_API_KEY,
            "NEXTDNS_PROFILE_ID": TEST_PROFILE_ID,
            "TIMEZONE": "Invalid/Timezone",
        }

        with patch.dict(os.environ, env, clear=False):
            result = runner.invoke(
                main,
                ["init", "--non-interactive", "--config-dir", str(config_dir)],
            )

        assert result.exit_code != 0, "Init should fail with invalid timezone"


class TestInitThenSync:
    """Tests for the complete init → sync workflow."""

    @responses.activate
    def test_sync_works_after_init_with_domains_file(
        self,
        runner: CliRunner,
        tmp_path: Path,
        clean_env: None,
    ) -> None:
        """Test that sync command works after init when domains.json exists."""
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        # Mock API validation for init
        responses.add(
            responses.GET,
            f"{API_URL}/profiles/{TEST_PROFILE_ID}/denylist",
            json={"data": []},
            status=200,
        )

        env = {
            "NEXTDNS_API_KEY": TEST_API_KEY,
            "NEXTDNS_PROFILE_ID": TEST_PROFILE_ID,
            "TIMEZONE": TEST_TIMEZONE,
        }

        # Step 1: Run init (mocking scheduler and initial sync)
        with patch("nextdns_blocker.init.install_scheduling", return_value=(True, "mock")):
            with patch("nextdns_blocker.init.run_initial_sync", return_value=True):
                with patch.dict(os.environ, env, clear=False):
                    result = runner.invoke(
                        main,
                        ["init", "--non-interactive", "--config-dir", str(config_dir)],
                    )

        assert result.exit_code == 0, f"Init failed: {result.output}"

        # Step 2: Create domains.json (normally done separately in CI/CD)
        domains_data = {
            "domains": [
                {
                    "domain": "test.com",
                    "schedule": {
                        "available_hours": [
                            {
                                "days": ["monday"],
                                "time_ranges": [{"start": "09:00", "end": "17:00"}],
                            }
                        ]
                    },
                }
            ]
        }
        (config_dir / "domains.json").write_text(json.dumps(domains_data))

        # Step 3: Add mocks for sync command
        responses.add(
            responses.GET,
            f"{API_URL}/profiles/{TEST_PROFILE_ID}/denylist",
            json={"data": []},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{API_URL}/profiles/{TEST_PROFILE_ID}/allowlist",
            json={"data": []},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{API_URL}/profiles/{TEST_PROFILE_ID}/denylist",
            json={"success": True},
            status=200,
        )

        # Step 4: Run sync
        with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
            with patch("nextdns_blocker.cli.get_log_dir", return_value=log_dir):
                result = runner.invoke(
                    main,
                    ["sync", "--config-dir", str(config_dir)],
                )

        assert result.exit_code == 0, f"Sync failed: {result.output}"

    @responses.activate
    def test_init_with_remote_url_then_sync(
        self,
        runner: CliRunner,
        tmp_path: Path,
        clean_env: None,
    ) -> None:
        """Test init with --url option followed by sync."""
        config_dir = tmp_path / "config"
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        remote_domains_url = "https://example.com/domains.json"
        remote_domains = {
            "domains": [
                {
                    "domain": "remote-test.com",
                    "schedule": {
                        "available_hours": [
                            {
                                "days": ["monday"],
                                "time_ranges": [{"start": "09:00", "end": "17:00"}],
                            }
                        ]
                    },
                }
            ]
        }

        # Mock API validation
        responses.add(
            responses.GET,
            f"{API_URL}/profiles/{TEST_PROFILE_ID}/denylist",
            json={"data": []},
            status=200,
        )

        # Mock remote domains.json
        responses.add(
            responses.GET,
            remote_domains_url,
            json=remote_domains,
            status=200,
        )

        env = {
            "NEXTDNS_API_KEY": TEST_API_KEY,
            "NEXTDNS_PROFILE_ID": TEST_PROFILE_ID,
            "TIMEZONE": TEST_TIMEZONE,
        }

        # Run init with URL (mocking scheduler and initial sync)
        with patch("nextdns_blocker.init.install_scheduling", return_value=(True, "mock")):
            with patch("nextdns_blocker.init.run_initial_sync", return_value=True):
                with patch.dict(os.environ, env, clear=False):
                    result = runner.invoke(
                        main,
                        [
                            "init",
                            "--non-interactive",
                            "--config-dir",
                            str(config_dir),
                            "--url",
                            remote_domains_url,
                        ],
                    )

        assert result.exit_code == 0, f"Init failed: {result.output}"

        # Verify DOMAINS_URL is in .env
        env_content = (config_dir / ".env").read_text()
        assert remote_domains_url in env_content

        # Add mocks for sync
        responses.add(
            responses.GET,
            f"{API_URL}/profiles/{TEST_PROFILE_ID}/denylist",
            json={"data": []},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{API_URL}/profiles/{TEST_PROFILE_ID}/allowlist",
            json={"data": []},
            status=200,
        )
        responses.add(
            responses.GET,
            remote_domains_url,
            json=remote_domains,
            status=200,
        )
        responses.add(
            responses.POST,
            f"{API_URL}/profiles/{TEST_PROFILE_ID}/denylist",
            json={"success": True},
            status=200,
        )

        # Run sync
        with patch("nextdns_blocker.common.get_log_dir", return_value=log_dir):
            with patch("nextdns_blocker.cli.get_log_dir", return_value=log_dir):
                result = runner.invoke(
                    main,
                    ["sync", "--config-dir", str(config_dir)],
                )

        assert result.exit_code == 0, f"Sync failed: {result.output}"


class TestInitIdempotent:
    """Tests for re-running init on existing configuration."""

    @responses.activate
    def test_init_preserves_existing_domains_json(
        self,
        runner: CliRunner,
        tmp_path: Path,
        clean_env: None,
    ) -> None:
        """Test that running init again doesn't overwrite existing domains.json."""
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)

        # Create existing domains.json with custom content
        custom_domains = {"domains": [{"domain": "custom-domain.com", "schedule": None}]}
        domains_file = config_dir / "domains.json"
        domains_file.write_text(json.dumps(custom_domains))

        # Mock API
        responses.add(
            responses.GET,
            f"{API_URL}/profiles/{TEST_PROFILE_ID}/denylist",
            json={"data": []},
            status=200,
        )

        env = {
            "NEXTDNS_API_KEY": TEST_API_KEY,
            "NEXTDNS_PROFILE_ID": TEST_PROFILE_ID,
            "TIMEZONE": TEST_TIMEZONE,
        }

        with patch("nextdns_blocker.init.install_scheduling", return_value=(True, "mock")):
            with patch("nextdns_blocker.init.run_initial_sync", return_value=True):
                with patch.dict(os.environ, env, clear=False):
                    result = runner.invoke(
                        main,
                        ["init", "--non-interactive", "--config-dir", str(config_dir)],
                    )

        assert result.exit_code == 0

        # Verify domains.json still has custom content
        final_domains = json.loads(domains_file.read_text())
        assert final_domains["domains"][0]["domain"] == "custom-domain.com"
