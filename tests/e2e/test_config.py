"""E2E tests for configuration module."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import responses

from nextdns_blocker.config import (
    fetch_remote_domains,
    get_cache_dir,
    get_cache_status,
    get_cached_domains,
    get_config_dir,
    get_data_dir,
    get_domains_cache_file,
    get_log_dir,
    load_config,
    load_domains,
    save_domains_cache,
    validate_allowlist_config,
    validate_api_key,
    validate_domain_config,
    validate_no_overlap,
    validate_profile_id,
    verify_remote_domains_hash,
)
from nextdns_blocker.exceptions import ConfigurationError


class TestValidateApiKey:
    """Tests for API key validation."""

    def test_valid_api_key(self) -> None:
        """Test with valid API key."""
        assert validate_api_key("abcd1234efgh") is True

    def test_api_key_with_dashes(self) -> None:
        """Test API key with dashes."""
        assert validate_api_key("abcd-1234-efgh") is True

    def test_api_key_with_underscores(self) -> None:
        """Test API key with underscores."""
        assert validate_api_key("abcd_1234_efgh") is True

    def test_empty_api_key(self) -> None:
        """Test with empty API key."""
        assert validate_api_key("") is False

    def test_none_api_key(self) -> None:
        """Test with None API key."""
        assert validate_api_key(None) is False  # type: ignore

    def test_short_api_key(self) -> None:
        """Test API key that's too short."""
        assert validate_api_key("short") is False

    def test_non_string_api_key(self) -> None:
        """Test with non-string API key."""
        assert validate_api_key(12345678) is False  # type: ignore


class TestValidateProfileId:
    """Tests for profile ID validation."""

    def test_valid_profile_id(self) -> None:
        """Test with valid profile ID."""
        assert validate_profile_id("abc123") is True

    def test_profile_id_with_dashes(self) -> None:
        """Test profile ID with dashes."""
        assert validate_profile_id("abc-123") is True

    def test_empty_profile_id(self) -> None:
        """Test with empty profile ID."""
        assert validate_profile_id("") is False

    def test_none_profile_id(self) -> None:
        """Test with None profile ID."""
        assert validate_profile_id(None) is False  # type: ignore

    def test_short_profile_id(self) -> None:
        """Test profile ID that's too short."""
        assert validate_profile_id("ab") is False

    def test_non_string_profile_id(self) -> None:
        """Test with non-string profile ID."""
        assert validate_profile_id(123456) is False  # type: ignore


class TestGetConfigDir:
    """Tests for get_config_dir function."""

    def test_with_override(self, tmp_path: Path) -> None:
        """Test config dir with override."""
        override = tmp_path / "custom_config"
        result = get_config_dir(override)
        assert result == override

    def test_with_cwd_env_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test config dir uses CWD when .env exists."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST=value")
        monkeypatch.chdir(tmp_path)

        result = get_config_dir()
        assert result == tmp_path

    def test_with_cwd_domains_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test config dir uses CWD when domains.json exists."""
        domains_file = tmp_path / "domains.json"
        domains_file.write_text('{"domains": []}')
        monkeypatch.chdir(tmp_path)

        result = get_config_dir()
        assert result == tmp_path


class TestGetDataDir:
    """Tests for get_data_dir function."""

    def test_returns_path(self) -> None:
        """Test data dir returns a path."""
        result = get_data_dir()
        assert isinstance(result, Path)
        assert "nextdns-blocker" in str(result)


class TestGetLogDir:
    """Tests for get_log_dir function."""

    def test_returns_logs_subdir(self) -> None:
        """Test log dir is under data dir."""
        result = get_log_dir()
        assert result.name == "logs"
        assert "nextdns-blocker" in str(result)


class TestGetCacheDir:
    """Tests for get_cache_dir function."""

    def test_returns_cache_subdir(self) -> None:
        """Test cache dir is under data dir."""
        result = get_cache_dir()
        assert result.name == "cache"
        assert "nextdns-blocker" in str(result)


class TestDomainsCaching:
    """Tests for domains caching functions."""

    def test_get_domains_cache_file_path(self) -> None:
        """Test cache file path."""
        result = get_domains_cache_file()
        assert result.name == "domains_cache.json"

    def test_get_cached_domains_no_file(self, tmp_path: Path) -> None:
        """Test get cached domains when no cache exists."""
        with patch(
            "nextdns_blocker.config.get_domains_cache_file",
            return_value=tmp_path / "nonexistent.json",
        ):
            result = get_cached_domains()
        assert result is None

    def test_get_cached_domains_valid(self, tmp_path: Path) -> None:
        """Test get cached domains with valid cache."""
        import time

        cache_file = tmp_path / "domains_cache.json"
        cache_data = {"timestamp": time.time(), "data": {"domains": []}}
        cache_file.write_text(json.dumps(cache_data))

        with patch("nextdns_blocker.config.get_domains_cache_file", return_value=cache_file):
            result = get_cached_domains()

        assert result == {"domains": []}

    def test_get_cached_domains_expired(self, tmp_path: Path) -> None:
        """Test get cached domains when cache is expired."""
        import time

        cache_file = tmp_path / "domains_cache.json"
        # Set timestamp to 2 hours ago
        cache_data = {"timestamp": time.time() - 7200, "data": {"domains": []}}
        cache_file.write_text(json.dumps(cache_data))

        with patch("nextdns_blocker.config.get_domains_cache_file", return_value=cache_file):
            result = get_cached_domains(max_age=3600)

        assert result is None

    def test_get_cached_domains_corrupted(self, tmp_path: Path) -> None:
        """Test get cached domains with corrupted cache."""
        cache_file = tmp_path / "domains_cache.json"
        cache_file.write_text("not valid json")

        with patch("nextdns_blocker.config.get_domains_cache_file", return_value=cache_file):
            result = get_cached_domains()

        assert result is None

    def test_save_domains_cache_success(self, tmp_path: Path) -> None:
        """Test saving domains cache."""
        cache_file = tmp_path / "cache" / "domains_cache.json"

        with patch("nextdns_blocker.config.get_domains_cache_file", return_value=cache_file):
            result = save_domains_cache({"domains": []})

        assert result is True
        assert cache_file.exists()

    def test_save_domains_cache_oserror(self, tmp_path: Path) -> None:
        """Test save domains cache handles OSError."""
        cache_file = tmp_path / "cache" / "domains_cache.json"

        with patch("nextdns_blocker.config.get_domains_cache_file", return_value=cache_file):
            with patch("os.open", side_effect=OSError("Permission denied")):
                result = save_domains_cache({"domains": []})

        assert result is False

    def test_save_domains_cache_fdopen_oserror(self, tmp_path: Path) -> None:
        """Test save domains cache handles OSError in fdopen."""
        cache_file = tmp_path / "cache" / "domains_cache.json"
        (tmp_path / "cache").mkdir()

        with patch("nextdns_blocker.config.get_domains_cache_file", return_value=cache_file):
            with patch("os.fdopen", side_effect=OSError("Permission denied")):
                result = save_domains_cache({"domains": []})

        assert result is False


class TestGetCacheStatus:
    """Tests for cache status function."""

    def test_cache_status_no_file(self, tmp_path: Path) -> None:
        """Test cache status when no file exists."""
        with patch(
            "nextdns_blocker.config.get_domains_cache_file",
            return_value=tmp_path / "nonexistent.json",
        ):
            result = get_cache_status()

        assert result["exists"] is False

    def test_cache_status_valid(self, tmp_path: Path) -> None:
        """Test cache status with valid cache."""
        import time

        cache_file = tmp_path / "domains_cache.json"
        cache_data = {"timestamp": time.time(), "data": {"domains": []}}
        cache_file.write_text(json.dumps(cache_data))

        with patch("nextdns_blocker.config.get_domains_cache_file", return_value=cache_file):
            result = get_cache_status()

        assert result["exists"] is True
        assert result["expired"] is False

    def test_cache_status_expired(self, tmp_path: Path) -> None:
        """Test cache status with expired cache."""
        import time

        cache_file = tmp_path / "domains_cache.json"
        cache_data = {"timestamp": time.time() - 7200, "data": {"domains": []}}
        cache_file.write_text(json.dumps(cache_data))

        with patch("nextdns_blocker.config.get_domains_cache_file", return_value=cache_file):
            result = get_cache_status()

        assert result["exists"] is True
        assert result["expired"] is True

    def test_cache_status_corrupted(self, tmp_path: Path) -> None:
        """Test cache status with corrupted file."""
        cache_file = tmp_path / "domains_cache.json"
        cache_file.write_text("not valid json")

        with patch("nextdns_blocker.config.get_domains_cache_file", return_value=cache_file):
            result = get_cache_status()

        assert result["exists"] is True
        assert result["corrupted"] is True


class TestVerifyRemoteDomainsHash:
    """Tests for hash verification."""

    def test_no_hash_url_returns_true(self) -> None:
        """Test that no hash URL returns True."""
        result = verify_remote_domains_hash(b"test content", None)
        assert result is True

    @responses.activate
    def test_valid_hash_matches(self) -> None:
        """Test valid hash verification."""
        import hashlib

        content = b"test content"
        expected_hash = hashlib.sha256(content).hexdigest()

        responses.add(
            responses.GET,
            "https://example.com/hash.sha256",
            body=expected_hash,
            status=200,
        )

        result = verify_remote_domains_hash(content, "https://example.com/hash.sha256")
        assert result is True

    @responses.activate
    def test_hash_mismatch(self) -> None:
        """Test hash mismatch."""
        responses.add(
            responses.GET,
            "https://example.com/hash.sha256",
            body="0000000000000000000000000000000000000000000000000000000000000000",
            status=200,
        )

        result = verify_remote_domains_hash(b"test content", "https://example.com/hash.sha256")
        assert result is False

    @responses.activate
    def test_hash_with_filename(self) -> None:
        """Test hash file that includes filename (sha256sum format)."""
        import hashlib

        content = b"test content"
        expected_hash = hashlib.sha256(content).hexdigest()
        # sha256sum format: "hash  filename"
        hash_content = f"{expected_hash}  domains.json"

        responses.add(
            responses.GET,
            "https://example.com/hash.sha256",
            body=hash_content,
            status=200,
        )

        result = verify_remote_domains_hash(content, "https://example.com/hash.sha256")
        assert result is True

    @responses.activate
    def test_hash_fetch_failure_returns_true(self) -> None:
        """Test that hash fetch failure returns True (allow through)."""
        import requests

        responses.add(
            responses.GET,
            "https://example.com/hash.sha256",
            body=requests.exceptions.ConnectionError(),
        )

        result = verify_remote_domains_hash(b"test content", "https://example.com/hash.sha256")
        assert result is True  # Should return True on failure


class TestFetchRemoteDomains:
    """Tests for fetching remote domains."""

    @responses.activate
    def test_fetch_success(self, tmp_path: Path) -> None:
        """Test successful fetch."""
        responses.add(
            responses.GET,
            "https://example.com/domains.json",
            json={"domains": [{"domain": "example.com"}]},
            status=200,
        )

        with patch(
            "nextdns_blocker.config.get_domains_cache_file",
            return_value=tmp_path / "cache.json",
        ):
            result = fetch_remote_domains("https://example.com/domains.json")

        assert "domains" in result

    @responses.activate
    def test_fetch_invalid_json(self) -> None:
        """Test fetch with invalid JSON response."""
        responses.add(
            responses.GET,
            "https://example.com/domains.json",
            body="not json",
            status=200,
        )

        with pytest.raises(ConfigurationError, match="Invalid JSON"):
            fetch_remote_domains("https://example.com/domains.json")

    @responses.activate
    def test_fetch_not_dict(self) -> None:
        """Test fetch when response is not a dict."""
        responses.add(
            responses.GET,
            "https://example.com/domains.json",
            json=["list", "not", "dict"],
            status=200,
        )

        with pytest.raises(ConfigurationError, match="must be a JSON object"):
            fetch_remote_domains("https://example.com/domains.json")

    @responses.activate
    def test_fetch_failure_with_cache_fallback(self, tmp_path: Path) -> None:
        """Test fetch failure falls back to cache."""
        import time

        import requests

        # Set up cache
        cache_file = tmp_path / "cache.json"
        cache_data = {"timestamp": time.time(), "data": {"domains": []}}
        cache_file.write_text(json.dumps(cache_data))

        responses.add(
            responses.GET,
            "https://example.com/domains.json",
            body=requests.exceptions.ConnectionError(),
        )

        with patch("nextdns_blocker.config.get_domains_cache_file", return_value=cache_file):
            result = fetch_remote_domains("https://example.com/domains.json")

        assert result == {"domains": []}

    @responses.activate
    def test_fetch_failure_no_cache(self) -> None:
        """Test fetch failure with no cache raises error."""
        import requests

        responses.add(
            responses.GET,
            "https://example.com/domains.json",
            body=requests.exceptions.ConnectionError(),
        )

        with patch("nextdns_blocker.config.get_cached_domains", return_value=None):
            with pytest.raises(ConfigurationError, match="Failed to load domains"):
                fetch_remote_domains("https://example.com/domains.json")

    @responses.activate
    def test_fetch_with_hash_verification_failure(self, tmp_path: Path) -> None:
        """Test fetch with hash verification failure."""
        responses.add(
            responses.GET,
            "https://example.com/domains.json",
            json={"domains": []},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://example.com/hash.sha256",
            body="0000000000000000000000000000000000000000000000000000000000000000",
            status=200,
        )

        with patch.dict(os.environ, {"DOMAINS_HASH_URL": "https://example.com/hash.sha256"}):
            with pytest.raises(ConfigurationError, match="hash verification failed"):
                fetch_remote_domains("https://example.com/domains.json")


class TestValidateDomainConfig:
    """Tests for domain configuration validation."""

    def test_valid_domain_no_schedule(self) -> None:
        """Test valid domain without schedule."""
        config: dict[str, Any] = {"domain": "example.com"}
        errors = validate_domain_config(config, 0)
        assert len(errors) == 0

    def test_missing_domain_field(self) -> None:
        """Test missing domain field."""
        config: dict[str, Any] = {}
        errors = validate_domain_config(config, 0)
        assert len(errors) == 1
        assert "Missing 'domain'" in errors[0]

    def test_empty_domain(self) -> None:
        """Test empty domain."""
        config: dict[str, Any] = {"domain": ""}
        errors = validate_domain_config(config, 0)
        assert len(errors) == 1
        assert "Empty or invalid" in errors[0]

    def test_invalid_domain_format(self) -> None:
        """Test invalid domain format."""
        config: dict[str, Any] = {"domain": "not-a-domain!"}
        errors = validate_domain_config(config, 0)
        assert len(errors) == 1
        assert "Invalid domain format" in errors[0]

    def test_schedule_not_dict(self) -> None:
        """Test schedule that's not a dict."""
        config: dict[str, Any] = {"domain": "example.com", "schedule": "invalid"}
        errors = validate_domain_config(config, 0)
        assert len(errors) == 1
        assert "must be a dictionary" in errors[0]

    def test_available_hours_not_list(self) -> None:
        """Test available_hours that's not a list."""
        config: dict[str, Any] = {
            "domain": "example.com",
            "schedule": {"available_hours": "not a list"},
        }
        errors = validate_domain_config(config, 0)
        assert len(errors) == 1
        assert "must be a list" in errors[0]

    def test_schedule_block_not_dict(self) -> None:
        """Test schedule block that's not a dict."""
        config: dict[str, Any] = {
            "domain": "example.com",
            "schedule": {"available_hours": ["not a dict"]},
        }
        errors = validate_domain_config(config, 0)
        assert len(errors) == 1
        assert "must be a dictionary" in errors[0]

    def test_invalid_day_name(self) -> None:
        """Test invalid day name in schedule."""
        config: dict[str, Any] = {
            "domain": "example.com",
            "schedule": {
                "available_hours": [
                    {
                        "days": ["funday"],
                        "time_ranges": [{"start": "09:00", "end": "17:00"}],
                    }
                ]
            },
        }
        errors = validate_domain_config(config, 0)
        assert len(errors) == 1
        assert "invalid day" in errors[0]

    def test_time_range_not_dict(self) -> None:
        """Test time_range that's not a dict."""
        config: dict[str, Any] = {
            "domain": "example.com",
            "schedule": {
                "available_hours": [
                    {
                        "days": ["monday"],
                        "time_ranges": ["not a dict"],
                    }
                ]
            },
        }
        errors = validate_domain_config(config, 0)
        assert len(errors) == 1
        assert "must be a dictionary" in errors[0]

    def test_missing_start_time(self) -> None:
        """Test missing start time in time_range."""
        config: dict[str, Any] = {
            "domain": "example.com",
            "schedule": {
                "available_hours": [
                    {
                        "days": ["monday"],
                        "time_ranges": [{"end": "17:00"}],
                    }
                ]
            },
        }
        errors = validate_domain_config(config, 0)
        assert len(errors) == 1
        assert "missing 'start'" in errors[0]

    def test_missing_end_time(self) -> None:
        """Test missing end time in time_range."""
        config: dict[str, Any] = {
            "domain": "example.com",
            "schedule": {
                "available_hours": [
                    {
                        "days": ["monday"],
                        "time_ranges": [{"start": "09:00"}],
                    }
                ]
            },
        }
        errors = validate_domain_config(config, 0)
        assert len(errors) == 1
        assert "missing 'end'" in errors[0]

    def test_invalid_time_format(self) -> None:
        """Test invalid time format."""
        config: dict[str, Any] = {
            "domain": "example.com",
            "schedule": {
                "available_hours": [
                    {
                        "days": ["monday"],
                        "time_ranges": [{"start": "9am", "end": "5pm"}],
                    }
                ]
            },
        }
        errors = validate_domain_config(config, 0)
        assert len(errors) == 2  # Both start and end invalid


class TestValidateAllowlistConfig:
    """Tests for allowlist configuration validation."""

    def test_valid_allowlist_entry(self) -> None:
        """Test valid allowlist entry."""
        config: dict[str, Any] = {"domain": "example.com"}
        errors = validate_allowlist_config(config, 0)
        assert len(errors) == 0

    def test_missing_domain(self) -> None:
        """Test missing domain in allowlist."""
        config: dict[str, Any] = {}
        errors = validate_allowlist_config(config, 0)
        assert len(errors) == 1
        assert "Missing 'domain'" in errors[0]

    def test_schedule_not_allowed(self) -> None:
        """Test that schedule in allowlist generates warning."""
        config: dict[str, Any] = {
            "domain": "example.com",
            "schedule": {"available_hours": []},
        }
        errors = validate_allowlist_config(config, 0)
        assert len(errors) == 1
        assert "not allowed" in errors[0]


class TestValidateNoOverlap:
    """Tests for overlap validation."""

    def test_no_overlap(self) -> None:
        """Test no overlap between lists."""
        domains = [{"domain": "example.com"}]
        allowlist = [{"domain": "other.com"}]
        errors = validate_no_overlap(domains, allowlist)
        assert len(errors) == 0

    def test_overlap_detected(self) -> None:
        """Test overlap is detected."""
        domains = [{"domain": "example.com"}]
        allowlist = [{"domain": "example.com"}]
        errors = validate_no_overlap(domains, allowlist)
        assert len(errors) == 1
        assert "example.com" in errors[0]


class TestLoadDomains:
    """Tests for loading domains."""

    @responses.activate
    def test_load_from_url(self, tmp_path: Path) -> None:
        """Test loading domains from URL."""
        responses.add(
            responses.GET,
            "https://example.com/domains.json",
            json={
                "domains": [{"domain": "example.com"}],
                "allowlist": [],
            },
            status=200,
        )

        with patch(
            "nextdns_blocker.config.get_domains_cache_file",
            return_value=tmp_path / "cache.json",
        ):
            domains, allowlist = load_domains(
                str(tmp_path),
                domains_url="https://example.com/domains.json",
            )

        assert len(domains) == 1
        assert domains[0]["domain"] == "example.com"

    def test_load_from_local_file(self, tmp_path: Path) -> None:
        """Test loading domains from local file."""
        domains_file = tmp_path / "domains.json"
        domains_file.write_text(
            json.dumps(
                {
                    "domains": [{"domain": "example.com"}],
                    "allowlist": [],
                }
            )
        )

        domains, allowlist = load_domains(str(tmp_path))

        assert len(domains) == 1
        assert domains[0]["domain"] == "example.com"

    def test_load_missing_file(self, tmp_path: Path) -> None:
        """Test loading from missing file."""
        with pytest.raises(ConfigurationError, match="not found"):
            load_domains(str(tmp_path))

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        """Test loading invalid JSON file."""
        domains_file = tmp_path / "domains.json"
        domains_file.write_text("not valid json")

        with pytest.raises(ConfigurationError, match="Invalid JSON"):
            load_domains(str(tmp_path))

    def test_load_no_domains(self, tmp_path: Path) -> None:
        """Test loading file with no domains."""
        domains_file = tmp_path / "domains.json"
        domains_file.write_text(json.dumps({"domains": []}))

        with pytest.raises(ConfigurationError, match="No domains configured"):
            load_domains(str(tmp_path))


class TestLoadConfig:
    """Tests for loading configuration."""

    def test_load_config_success(self, tmp_path: Path) -> None:
        """Test successful config loading."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "NEXTDNS_API_KEY=test-api-key\nNEXTDNS_PROFILE_ID=abc123\nTIMEZONE=UTC\n"
        )

        config = load_config(tmp_path)

        assert config["api_key"] == "test-api-key"
        assert config["profile_id"] == "abc123"
        assert config["timezone"] == "UTC"

    def test_load_config_missing_api_key(self, tmp_path: Path) -> None:
        """Test config loading fails without API key."""
        env_file = tmp_path / ".env"
        env_file.write_text("NEXTDNS_PROFILE_ID=abc123\n")

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError, match="Missing NEXTDNS_API_KEY"):
                load_config(tmp_path)

    def test_load_config_invalid_api_key(self, tmp_path: Path) -> None:
        """Test config loading fails with invalid API key."""
        env_file = tmp_path / ".env"
        env_file.write_text("NEXTDNS_API_KEY=short\nNEXTDNS_PROFILE_ID=abc123\n")

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError, match="Invalid NEXTDNS_API_KEY"):
                load_config(tmp_path)

    def test_load_config_missing_profile_id(self, tmp_path: Path) -> None:
        """Test config loading fails without profile ID."""
        env_file = tmp_path / ".env"
        env_file.write_text("NEXTDNS_API_KEY=valid-api-key\n")

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError, match="Missing NEXTDNS_PROFILE_ID"):
                load_config(tmp_path)

    def test_load_config_invalid_profile_id(self, tmp_path: Path) -> None:
        """Test config loading fails with invalid profile ID."""
        env_file = tmp_path / ".env"
        env_file.write_text("NEXTDNS_API_KEY=valid-api-key\nNEXTDNS_PROFILE_ID=ab\n")

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError, match="Invalid NEXTDNS_PROFILE_ID"):
                load_config(tmp_path)

    def test_load_config_invalid_timezone(self, tmp_path: Path) -> None:
        """Test config loading fails with invalid timezone."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "NEXTDNS_API_KEY=valid-api-key\nNEXTDNS_PROFILE_ID=abc123\nTIMEZONE=Invalid/TZ\n"
        )

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError, match="Invalid TIMEZONE"):
                load_config(tmp_path)

    def test_load_config_invalid_domains_url(self, tmp_path: Path) -> None:
        """Test config loading fails with invalid domains URL."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "NEXTDNS_API_KEY=valid-api-key\nNEXTDNS_PROFILE_ID=abc123\nDOMAINS_URL=not-a-url\n"
        )

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError, match="Invalid DOMAINS_URL"):
                load_config(tmp_path)

    def test_load_config_with_quoted_values(self, tmp_path: Path) -> None:
        """Test config loading with quoted values in .env."""
        env_file = tmp_path / ".env"
        env_file.write_text("NEXTDNS_API_KEY=\"test-api-key\"\nNEXTDNS_PROFILE_ID='abc123'\n")

        config = load_config(tmp_path)

        assert config["api_key"] == "test-api-key"
        assert config["profile_id"] == "abc123"

    def test_load_config_skips_comments(self, tmp_path: Path) -> None:
        """Test config loading skips comment lines."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# This is a comment\n"
            "NEXTDNS_API_KEY=test-api-key\n"
            "# Another comment\n"
            "NEXTDNS_PROFILE_ID=abc123\n"
        )

        config = load_config(tmp_path)

        assert config["api_key"] == "test-api-key"

    def test_load_config_handles_malformed_lines(self, tmp_path: Path) -> None:
        """Test config loading handles malformed lines gracefully."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "NEXTDNS_API_KEY=test-api-key\n"
            "NEXTDNS_PROFILE_ID=abc123\n"
            "MALFORMED LINE WITHOUT EQUALS\n"
            "=empty_key\n"
        )

        config = load_config(tmp_path)

        assert config["api_key"] == "test-api-key"

    def test_load_config_with_bom(self, tmp_path: Path) -> None:
        """Test config loading handles BOM in .env file."""
        env_file = tmp_path / ".env"
        # Write with BOM
        with open(env_file, "w", encoding="utf-8-sig") as f:
            f.write("NEXTDNS_API_KEY=test-api-key\n")
            f.write("NEXTDNS_PROFILE_ID=abc123\n")

        config = load_config(tmp_path)

        assert config["api_key"] == "test-api-key"
