"""Tests for the meeting connector module with mocked Playwright."""
from unittest.mock import patch, AsyncMock, call
import pytest

from src.meeting.connector import (
    MeetingConnector,
    _zoom_web_client_url,
    _resolve_channels,
)
from src.errors import BrowserError


class TestMeetingConnector:
    """Tests for MeetingConnector with mocked Playwright."""

    @pytest.fixture
    def connector(self):
        return MeetingConnector()

    @pytest.fixture
    def connected_connector(self, connector):
        """A connector that already has mocked page/browser set up."""
        connector.page = AsyncMock()
        connector.browser = AsyncMock()
        return connector

    def test_init(self, connector):
        """New connector should have None browser, page, and playwright."""
        assert connector._playwright is None
        assert connector.browser is None
        assert connector.page is None

    @pytest.mark.asyncio
    async def test_start_launches_browser(self, connector):
        """Start should launch Chromium and create a page via context.

        channel="" forces the bundled Playwright Chromium, bypassing the
        channel-fallback logic so the test stays deterministic.
        """
        mock_page = AsyncMock()
        mock_browser = AsyncMock()
        mock_instance = AsyncMock()
        mock_ctx = AsyncMock()
        mock_context = AsyncMock()

        mock_ctx.start.return_value = mock_instance
        mock_instance.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        mock_stealth_instance = AsyncMock()
        with (
            patch("src.meeting.connector.async_playwright", return_value=mock_ctx),
            patch("src.meeting.display.VirtualDisplay.is_needed", return_value=False),
            patch("src.meeting.connector.Stealth", return_value=mock_stealth_instance),
        ):
            await connector.start(channel="")  # bundled Chromium, no channel fallback

        mock_ctx.start.assert_called_once()
        mock_instance.chromium.launch.assert_called_once()
        mock_browser.new_context.assert_called_once()
        mock_context.new_page.assert_called_once()
        # Stealth must be applied to the *context* (not just the page) so all
        # pages opened from the context — including popups — are patched.
        mock_stealth_instance.apply_stealth_async.assert_called_once_with(mock_context)

    @pytest.mark.asyncio
    async def test_start_uses_persistent_context_when_user_data_dir_set(self, connector):
        """When user_data_dir is given, start should use launch_persistent_context."""
        mock_page = AsyncMock()
        mock_instance = AsyncMock()
        mock_ctx = AsyncMock()
        mock_context = AsyncMock()

        mock_ctx.start.return_value = mock_instance
        mock_instance.chromium.launch_persistent_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        mock_stealth_instance = AsyncMock()
        with (
            patch("src.meeting.connector.async_playwright", return_value=mock_ctx),
            patch("src.meeting.display.VirtualDisplay.is_needed", return_value=False),
            patch("src.meeting.connector.Stealth", return_value=mock_stealth_instance),
        ):
            await connector.start(user_data_dir="/tmp/chrome-profile", channel="")

        mock_instance.chromium.launch_persistent_context.assert_called_once()
        assert connector.browser is None
        assert connector._context is mock_context
        # Stealth must be applied to the context (covers all pages from this context).
        mock_stealth_instance.apply_stealth_async.assert_called_once_with(mock_context)

    @pytest.mark.asyncio
    async def test_start_tries_system_chrome_first(self, connector):
        """With channel='auto', start should try system Chrome before bundled Chromium."""
        mock_page = AsyncMock()
        mock_browser = AsyncMock()
        mock_instance = AsyncMock()
        mock_ctx = AsyncMock()
        mock_context = AsyncMock()

        mock_ctx.start.return_value = mock_instance
        mock_instance.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        with (
            patch("src.meeting.connector.async_playwright", return_value=mock_ctx),
            patch("src.meeting.display.VirtualDisplay.is_needed", return_value=False),
            patch("src.meeting.connector.Stealth", return_value=AsyncMock()),
        ):
            await connector.start(channel="auto")

        # First call should have been with channel="chrome"
        first_call_kwargs = mock_instance.chromium.launch.call_args_list[0][1]
        assert first_call_kwargs.get("channel") == "chrome"

    @pytest.mark.asyncio
    async def test_start_falls_back_to_bundled_when_system_chrome_missing(self, connector):
        """When system Chrome is absent, start should fall back to bundled Chromium."""
        mock_page = AsyncMock()
        mock_browser = AsyncMock()
        mock_instance = AsyncMock()
        mock_ctx = AsyncMock()
        mock_context = AsyncMock()

        mock_ctx.start.return_value = mock_instance
        mock_context.new_page.return_value = mock_page
        mock_browser.new_context.return_value = mock_context

        def launch_side_effect(*args, **kwargs):
            if kwargs.get("channel") in ("chrome", "chromium"):
                raise Exception("browser not found")
            return mock_browser

        mock_instance.chromium.launch.side_effect = launch_side_effect

        with (
            patch("src.meeting.connector.async_playwright", return_value=mock_ctx),
            patch("src.meeting.display.VirtualDisplay.is_needed", return_value=False),
            patch("src.meeting.connector.Stealth", return_value=AsyncMock()),
        ):
            await connector.start(channel="auto")

        assert connector.browser is mock_browser
        # Should have been called 3 times: chrome (fail), chromium (fail), bundled (ok)
        assert mock_instance.chromium.launch.call_count == 3

    @pytest.mark.asyncio
    async def test_join_google_meet_navigates(self, connected_connector):
        """join_google_meet should navigate to the Meet URL."""
        connector = connected_connector

        await connector.join_google_meet("https://meet.google.com/abc-defg-hij")

        # Check goto was called with the URL (kwargs may include timeout/wait_until)
        call_args = connector.page.goto.call_args
        assert call_args[0][0] == "https://meet.google.com/abc-defg-hij"

    @pytest.mark.asyncio
    async def test_join_zoom_navigates(self, connected_connector):
        """join_zoom should rewrite /j/ URLs to the web client path."""
        await connected_connector.join_zoom("https://zoom.us/j/123456789")

        call_args = connected_connector.page.goto.call_args
        assert call_args[0][0] == "https://zoom.us/wc/join/123456789"

    @pytest.mark.asyncio
    async def test_join_zoom_preserves_web_client_url(self, connected_connector):
        """join_zoom should not rewrite a URL that is already a web client URL."""
        await connected_connector.join_zoom("https://zoom.us/wc/join/99887766")

        call_args = connected_connector.page.goto.call_args
        assert call_args[0][0] == "https://zoom.us/wc/join/99887766"

    @pytest.mark.asyncio
    async def test_join_teams_navigates(self, connected_connector):
        """join_teams should navigate to Teams web client."""
        await connected_connector.join_teams("https://teams.microsoft.com/l/meetup-join/abc")

        call_args = connected_connector.page.goto.call_args
        assert call_args[0][0] == "https://teams.microsoft.com/l/meetup-join/abc"

    @pytest.mark.asyncio
    async def test_join_meeting_dispatches_correctly(self, connected_connector):
        """join_meeting should dispatch to correct platform method."""
        with patch.object(connected_connector, "join_google_meet", AsyncMock()) as mock_join:
            await connected_connector.join_meeting("google_meet", "https://meet.google.com/abc", "Bot")
            mock_join.assert_called_once_with("https://meet.google.com/abc", "Bot")

    @pytest.mark.asyncio
    async def test_join_meeting_unsupported_raises(self, connected_connector):
        """join_meeting with unknown platform should raise BrowserError."""
        with pytest.raises(BrowserError, match="[Uu]nsupported"):
            await connected_connector.join_meeting("unknown", "http://example.com", "Bot")

    @pytest.mark.asyncio
    async def test_leave_clicks_button(self, connected_connector):
        """leave should click the Leave button."""
        await connected_connector.leave()
        connected_connector.page.click.assert_called()

    @pytest.mark.asyncio
    async def test_leave_handles_error(self, connected_connector):
        """leave should not raise on error."""
        connected_connector.page.click.side_effect = Exception("button not found")
        # Should not raise
        await connected_connector.leave()

    @pytest.mark.asyncio
    async def test_stop_closes_page_browser_and_playwright(self, connected_connector):
        """stop should close page, browser, and playwright instance."""
        connected_connector._playwright = AsyncMock()
        await connected_connector.stop()

        connected_connector.page.close.assert_called_once()
        connected_connector.browser.close.assert_called_once()
        connected_connector._playwright.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_handles_none(self, connector):
        """stop should not raise if browser/page/playwright is None."""
        await connector.stop()

    @pytest.mark.asyncio
    async def test_wait_for_meeting_end(self, connected_connector):
        """wait_for_meeting_end should handle meeting ending."""
        connected_connector.page.wait_for_selector.side_effect = Exception("meeting ended")
        await connected_connector.wait_for_meeting_end(timeout_minutes=1)


class TestResolveChannels:
    """Unit tests for the channel resolution helper."""

    def test_auto_returns_three_options(self):
        assert _resolve_channels("auto") == ["chrome", "chromium", None]

    def test_chrome_returns_chrome_then_bundled(self):
        assert _resolve_channels("chrome") == ["chrome", None]

    def test_chromium_returns_chromium_then_bundled(self):
        assert _resolve_channels("chromium") == ["chromium", None]

    def test_empty_string_returns_bundled_only(self):
        assert _resolve_channels("") == [None]

    def test_none_returns_bundled_only(self):
        assert _resolve_channels(None) == [None]

    def test_case_insensitive(self):
        assert _resolve_channels("AUTO") == ["chrome", "chromium", None]
        assert _resolve_channels("Chrome") == ["chrome", None]


class TestZoomWebClientUrl:
    """Unit tests for the Zoom URL rewrite helper."""

    def test_rewrites_standard_join_url(self):
        result = _zoom_web_client_url("https://zoom.us/j/123456789")
        assert result == "https://zoom.us/wc/join/123456789"

    def test_preserves_password_query_param(self):
        result = _zoom_web_client_url("https://zoom.us/j/123456789?pwd=abc123")
        assert result == "https://zoom.us/wc/join/123456789?pwd=abc123"

    def test_preserves_already_web_client_url(self):
        url = "https://zoom.us/wc/join/99887766"
        assert _zoom_web_client_url(url) == url

    def test_returns_non_zoom_url_unchanged(self):
        url = "https://meet.google.com/abc-defg-hij"
        assert _zoom_web_client_url(url) == url

    def test_returns_url_without_meeting_id_unchanged(self):
        url = "https://zoom.us/profile"
        assert _zoom_web_client_url(url) == url
