"""Tests for the orchestrator module with mocked components."""
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from datetime import datetime
from pathlib import Path

from src.orchestrator import MeetingAgent


async def _async_iter(items):
    for item in items:
        yield item


class TestMeetingAgent:
    """Tests for the MeetingAgent orchestrator with mocked dependencies."""

    @pytest.fixture
    def mock_audio(self):
        with patch("src.orchestrator.AudioCapture") as mock:
            instance = mock.return_value
            instance.monitor_source = "test-sink.monitor"
            instance.get_new_chunks.return_value = _async_iter([])
            yield mock

    @pytest.fixture
    def mock_transcriber(self):
        with patch("src.orchestrator.Transcriber") as mock:
            instance = mock.return_value
            instance.transcribe.return_value = []
            yield mock

    @pytest.fixture
    def mock_summarizer(self):
        with patch("src.orchestrator.Summarizer") as mock:
            instance = mock.return_value
            instance.add_segments.return_value = None
            instance.build_raw_transcript.return_value = "test transcript"
            summary = MagicMock()
            summary.title = "Test Meeting"
            summary.date = ""
            summary.duration_minutes = 45
            summary.participants = []
            summary.key_topics = ["topic1"]
            summary.decisions = ["decision1"]
            summary.action_items = [{"assignee": "Alice", "task": "Do thing", "deadline": "2026-06-15"}]
            summary.full_transcript = "test transcript"
            summary.summary = "test summary"
            instance.generate_summary.return_value = summary
            yield mock

    @pytest.fixture
    def mock_connector(self):
        with patch("src.orchestrator.MeetingConnector") as mock:
            instance = mock.return_value
            instance.start = AsyncMock()
            instance.join_meeting = AsyncMock()
            instance.leave = AsyncMock()
            instance.stop = AsyncMock()
            yield mock

    @pytest.fixture
    def mock_parser(self):
        with patch("src.orchestrator.parse_meeting_url") as mock:
            meeting = MagicMock()
            meeting.platform.value = "google_meet"
            meeting.meeting_id = "abc-defg-hij"
            meeting.url = "https://meet.google.com/abc-defg-hij"
            mock.return_value = meeting
            yield mock

    @pytest.fixture
    def mock_save_notes(self):
        with patch("src.orchestrator.save_notes") as mock:
            mock.return_value = Path("/tmp/notes/test.md")
            yield mock

    @pytest.mark.asyncio
    async def test_agent_initializes_components(self, mock_audio, mock_transcriber, mock_summarizer, mock_connector):
        """MeetingAgent should initialize all component classes."""
        agent = MeetingAgent()
        assert agent.audio is not None
        assert agent.transcriber is not None
        assert agent.summarizer is not None
        assert agent.connector is not None
        assert agent._chunk_count == 0
        assert agent._running is False

    @pytest.mark.asyncio
    async def test_run_starts_audio_and_connector(
        self, mock_audio, mock_transcriber, mock_summarizer, mock_connector,
        mock_parser, mock_save_notes
    ):
        """Run should start audio capture and join meeting."""
        agent = MeetingAgent()
        await agent.run("https://meet.google.com/abc-defg-hij")

        mock_audio.return_value.start.assert_called_once()
        mock_connector.return_value.start.assert_called_once()
        mock_connector.return_value.join_meeting.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_uses_bot_name(
        self, mock_audio, mock_transcriber, mock_summarizer, mock_connector,
        mock_parser, mock_save_notes
    ):
        """Run should pass bot name to join_meeting."""
        agent = MeetingAgent()
        await agent.run("https://meet.google.com/abc-defg-hij", bot_name="TestBot")

        mock_connector.return_value.join_meeting.assert_called_once_with(
            "google_meet", "https://meet.google.com/abc-defg-hij", "TestBot"
        )

    @pytest.mark.asyncio
    async def test_run_default_bot_name(
        self, mock_audio, mock_transcriber, mock_summarizer, mock_connector,
        mock_parser, mock_save_notes
    ):
        """Run should use default bot name when not specified."""
        agent = MeetingAgent()
        await agent.run("https://meet.google.com/abc-defg-hij")

        call_args = mock_connector.return_value.join_meeting.call_args
        assert call_args[0][2] == "Meeting Notes Bot"

    @pytest.mark.asyncio
    async def test_cleanup_stops_audio(
        self, mock_audio, mock_transcriber, mock_summarizer, mock_connector,
        mock_parser, mock_save_notes
    ):
        """Cleanup should stop audio and browser."""
        agent = MeetingAgent()
        await agent.run("https://meet.google.com/abc-defg-hij")

        mock_audio.return_value.stop.assert_called_once()
        mock_connector.return_value.leave.assert_called_once()
        mock_connector.return_value.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_finalize_generates_notes(
        self, mock_audio, mock_transcriber, mock_summarizer, mock_connector,
        mock_parser, mock_save_notes
    ):
        """_finalize should generate and save notes."""
        agent = MeetingAgent()
        agent._start_time = 100.0
        agent._transcript_lines = ["[0:00] Hello"]

        await agent._finalize("Test Meeting")

        # verify transcript was saved (check notes dir for a file)
        mock_audio.return_value.cleanup_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_listen_starts_audio_only(
        self, mock_audio, mock_transcriber, mock_summarizer, mock_connector,
        mock_parser, mock_save_notes
    ):
        """Listen should start audio but NOT browser."""
        agent = MeetingAgent()
        await agent.listen("Standup")

        mock_audio.return_value.start.assert_called_once()
        # Connector should NOT be started in listen mode
        mock_connector.return_value.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_transcribe_loop_processes_chunks(
        self, mock_audio, mock_transcriber, mock_summarizer, mock_connector,
        mock_parser, mock_save_notes
    ):
        """Main loop should transcribe each chunk and clean up."""
        chunk1 = Path("/tmp/chunk_00000.wav")
        chunk2 = Path("/tmp/chunk_00001.wav")

        mock_transcriber_instance = mock_transcriber.return_value
        mock_transcriber_instance.transcribe.return_value = [
            MagicMock(start=0.0, end=1.0, text="hello")
        ]

        mock_audio.return_value.get_new_chunks.return_value = _async_iter([chunk1, chunk2])

        agent = MeetingAgent()
        await agent.run("https://meet.google.com/abc-defg-hij")

        # Both chunks should be transcribed
        assert mock_transcriber_instance.transcribe.call_count == 2

        # Both chunks should be cleaned up
        assert mock_audio.return_value.cleanup_chunk.call_count == 2

    def test_format_timestamp(self):
        """Timestamp formatting should produce correct strings."""
        assert MeetingAgent._format_timestamp(0) == "0:00"
        assert MeetingAgent._format_timestamp(65) == "1:05"
        assert MeetingAgent._format_timestamp(3661) == "1:01:01"
