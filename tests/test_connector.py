"""Tests for the meeting connector module with mocked Playwright."""
from unittest.mock import patch, AsyncMock, MagicMock
import pytest

from src.meeting.connector import MeetingConnector, _zoom_web_client_url
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
        """Start should launch Chromium and create a page via context."""
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
        ):
            await connector.start()

        mock_ctx.start.assert_called_once()
        mock_instance.chromium.launch.assert_called_once()
        mock_browser.new_context.assert_called_once()
        mock_context.new_page.assert_called_once()

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

        with (
            patch("src.meeting.connector.async_playwright", return_value=mock_ctx),
            patch("src.meeting.display.VirtualDisplay.is_needed", return_value=False),
        ):
            await connector.start(user_data_dir="/tmp/chrome-profile")

        mock_instance.chromium.launch_persistent_context.assert_called_once()
        assert connector.browser is None
        assert connector._context is mock_context

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
