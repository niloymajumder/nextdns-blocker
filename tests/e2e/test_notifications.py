"""E2E tests for Discord notifications."""

from __future__ import annotations

import os
from unittest.mock import patch

import responses

from nextdns_blocker.notifications import (
    COLOR_BLOCK,
    COLOR_UNBLOCK,
    get_webhook_url,
    is_notifications_enabled,
    send_discord_notification,
)


class TestNotificationsEnabled:
    """Tests for is_notifications_enabled function."""

    def test_disabled_by_default(self) -> None:
        """Test notifications are disabled by default."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_notifications_enabled() is False

    def test_enabled_when_true(self) -> None:
        """Test notifications enabled when set to 'true'."""
        with patch.dict(os.environ, {"DISCORD_NOTIFICATIONS_ENABLED": "true"}):
            assert is_notifications_enabled() is True

    def test_enabled_case_insensitive(self) -> None:
        """Test 'TRUE' also enables notifications."""
        with patch.dict(os.environ, {"DISCORD_NOTIFICATIONS_ENABLED": "TRUE"}):
            assert is_notifications_enabled() is True

    def test_disabled_when_false(self) -> None:
        """Test notifications disabled when set to 'false'."""
        with patch.dict(os.environ, {"DISCORD_NOTIFICATIONS_ENABLED": "false"}):
            assert is_notifications_enabled() is False

    def test_disabled_when_other_value(self) -> None:
        """Test notifications disabled with other values."""
        with patch.dict(os.environ, {"DISCORD_NOTIFICATIONS_ENABLED": "1"}):
            assert is_notifications_enabled() is False


class TestGetWebhookUrl:
    """Tests for get_webhook_url function."""

    def test_returns_none_when_not_set(self) -> None:
        """Test returns None when env var not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_webhook_url() is None

    def test_returns_url_when_set(self) -> None:
        """Test returns URL when env var is set."""
        url = "https://discord.com/api/webhooks/123/abc"
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": url}):
            assert get_webhook_url() == url


class TestSendDiscordNotification:
    """Tests for send_discord_notification function."""

    def test_skips_when_disabled(self) -> None:
        """Test notification is skipped when disabled."""
        with patch.dict(os.environ, {"DISCORD_NOTIFICATIONS_ENABLED": "false"}):
            # Should not raise any errors
            send_discord_notification("example.com", "block")

    def test_skips_when_no_webhook_url(self) -> None:
        """Test notification is skipped when webhook URL not set."""
        env = {"DISCORD_NOTIFICATIONS_ENABLED": "true"}
        with patch.dict(os.environ, env, clear=True):
            # Should not raise any errors
            send_discord_notification("example.com", "block")

    @responses.activate
    def test_sends_block_notification(self) -> None:
        """Test sending block notification."""
        webhook_url = "https://discord.com/api/webhooks/123/abc"
        env = {
            "DISCORD_NOTIFICATIONS_ENABLED": "true",
            "DISCORD_WEBHOOK_URL": webhook_url,
        }

        responses.add(
            responses.POST,
            webhook_url,
            json={"success": True},
            status=200,
        )

        with patch.dict(os.environ, env):
            send_discord_notification("example.com", "block")

        assert len(responses.calls) == 1
        request_body = responses.calls[0].request.body
        assert b"example.com" in request_body
        assert b"Domain Blocked" in request_body

    @responses.activate
    def test_sends_unblock_notification(self) -> None:
        """Test sending unblock notification."""
        webhook_url = "https://discord.com/api/webhooks/123/abc"
        env = {
            "DISCORD_NOTIFICATIONS_ENABLED": "true",
            "DISCORD_WEBHOOK_URL": webhook_url,
        }

        responses.add(
            responses.POST,
            webhook_url,
            json={"success": True},
            status=200,
        )

        with patch.dict(os.environ, env):
            send_discord_notification("example.com", "unblock")

        assert len(responses.calls) == 1
        request_body = responses.calls[0].request.body
        assert b"example.com" in request_body
        assert b"Domain Unblocked" in request_body

    @responses.activate
    def test_skips_unknown_event_type(self) -> None:
        """Test notification is skipped for unknown event type."""
        webhook_url = "https://discord.com/api/webhooks/123/abc"
        env = {
            "DISCORD_NOTIFICATIONS_ENABLED": "true",
            "DISCORD_WEBHOOK_URL": webhook_url,
        }

        with patch.dict(os.environ, env):
            send_discord_notification("example.com", "unknown_event")

        # No HTTP calls should be made
        assert len(responses.calls) == 0

    @responses.activate
    def test_handles_timeout(self) -> None:
        """Test notification handles timeout gracefully."""
        import requests

        webhook_url = "https://discord.com/api/webhooks/123/abc"
        env = {
            "DISCORD_NOTIFICATIONS_ENABLED": "true",
            "DISCORD_WEBHOOK_URL": webhook_url,
        }

        responses.add(
            responses.POST,
            webhook_url,
            body=requests.exceptions.Timeout(),
        )

        with patch.dict(os.environ, env):
            # Should not raise
            send_discord_notification("example.com", "block")

    @responses.activate
    def test_handles_request_exception(self) -> None:
        """Test notification handles request exception gracefully."""
        import requests

        webhook_url = "https://discord.com/api/webhooks/123/abc"
        env = {
            "DISCORD_NOTIFICATIONS_ENABLED": "true",
            "DISCORD_WEBHOOK_URL": webhook_url,
        }

        responses.add(
            responses.POST,
            webhook_url,
            body=requests.exceptions.ConnectionError(),
        )

        with patch.dict(os.environ, env):
            # Should not raise
            send_discord_notification("example.com", "block")

    @responses.activate
    def test_handles_http_error(self) -> None:
        """Test notification handles HTTP error gracefully."""
        webhook_url = "https://discord.com/api/webhooks/123/abc"
        env = {
            "DISCORD_NOTIFICATIONS_ENABLED": "true",
            "DISCORD_WEBHOOK_URL": webhook_url,
        }

        responses.add(
            responses.POST,
            webhook_url,
            json={"error": "Bad request"},
            status=400,
        )

        with patch.dict(os.environ, env):
            # Should not raise
            send_discord_notification("example.com", "block")

    @responses.activate
    def test_handles_unexpected_exception(self) -> None:
        """Test notification handles unexpected exception gracefully."""
        webhook_url = "https://discord.com/api/webhooks/123/abc"
        env = {
            "DISCORD_NOTIFICATIONS_ENABLED": "true",
            "DISCORD_WEBHOOK_URL": webhook_url,
        }

        responses.add(
            responses.POST,
            webhook_url,
            body=Exception("Unexpected error"),
        )

        with patch.dict(os.environ, env):
            # Should not raise
            send_discord_notification("example.com", "block")


class TestNotificationColors:
    """Tests for notification color constants."""

    def test_block_color_is_red(self) -> None:
        """Test block color is red-ish."""
        # 15158332 = 0xE74C3C (red)
        assert COLOR_BLOCK == 15158332

    def test_unblock_color_is_green(self) -> None:
        """Test unblock color is green-ish."""
        # 3066993 = 0x2ECC71 (green)
        assert COLOR_UNBLOCK == 3066993
