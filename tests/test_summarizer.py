"""Unit tests for src/notes/summarizer.py — all modes, buffer ops, JSON edge cases."""
import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.notes.summarizer import MeetingSummary, Summarizer
from src.audio.transcriber import TranscriptionSegment
from src.config import RunMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_segment(start: float, end: float, text: str, speaker: str = "Alice") -> TranscriptionSegment:
    """Quick factory for test segments."""
    return TranscriptionSegment(start=start, end=end, text=text, speaker=speaker)


def make_mock_openai_response(content: str | None) -> MagicMock:
    """Build a mock OpenAI chat.completions.create response returning `content`."""
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ---------------------------------------------------------------------------
# add_segments & buffer
# ---------------------------------------------------------------------------

class TestBufferOperations:
    """Tests for add_segments() and internal buffer state."""

    @patch("src.notes.summarizer.OpenAI")
    @patch("src.notes.summarizer.settings")
    def test_add_segments_populates_buffer(self, mock_settings, _mock_openai):
        mock_settings.get_llm_config.return_value = {
            "api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test-model",
        }
        s = Summarizer()
        segs = [
            make_segment(0.0, 2.5, "Hello everyone"),
            make_segment(3.0, 7.0, "Let's discuss the budget"),
        ]
        s.add_segments(segs)
        assert len(s._transcript_buffer) == 2
        assert s._transcript_buffer[0].text == "Hello everyone"

    @patch("src.notes.summarizer.OpenAI")
    @patch("src.notes.summarizer.settings")
    def test_add_segments_extends_existing(self, mock_settings, _mock_openai):
        mock_settings.get_llm_config.return_value = {
            "api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test-model",
        }
        s = Summarizer()
        s.add_segments([make_segment(0.0, 1.0, "First")])
        s.add_segments([make_segment(2.0, 3.0, "Second")])
        assert len(s._transcript_buffer) == 2

    @patch("src.notes.summarizer.OpenAI")
    @patch("src.notes.summarizer.settings")
    def test_add_segments_empty_list(self, mock_settings, _mock_openai):
        mock_settings.get_llm_config.return_value = {
            "api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test-model",
        }
        s = Summarizer()
        s.add_segments([])
        assert len(s._transcript_buffer) == 0


# ---------------------------------------------------------------------------
# build_raw_transcript
# ---------------------------------------------------------------------------

class TestBuildRawTranscript:
    """Tests for timestamp formatting and transcript assembly."""

    @patch("src.notes.summarizer.OpenAI")
    @patch("src.notes.summarizer.settings")
    def test_empty_buffer_returns_empty_string(self, mock_settings, _mock_openai):
        mock_settings.get_llm_config.return_value = {
            "api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test-model",
        }
        s = Summarizer()
        assert s.build_raw_transcript() == ""

    @patch("src.notes.summarizer.OpenAI")
    @patch("src.notes.summarizer.settings")
    def test_single_segment_timestamp_format(self, mock_settings, _mock_openai):
        mock_settings.get_llm_config.return_value = {
            "api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test-model",
        }
        s = Summarizer()
        s.add_segments([make_segment(0.0, 5.0, "Hello")])
        out = s.build_raw_transcript()
        assert out == "[00:00] Hello"

    @patch("src.notes.summarizer.OpenAI")
    @patch("src.notes.summarizer.settings")
    def test_multiple_segments_newline_separated(self, mock_settings, _mock_openai):
        mock_settings.get_llm_config.return_value = {
            "api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test-model",
        }
        s = Summarizer()
        s.add_segments([
            make_segment(0.0, 2.0, "Line one"),
            make_segment(5.0, 8.0, "Line two"),
        ])
        out = s.build_raw_transcript()
        assert out == "[00:00] Line one\n[00:05] Line two"

    @patch("src.notes.summarizer.OpenAI")
    @patch("src.notes.summarizer.settings")
    def test_timestamps_handle_minutes_correctly(self, mock_settings, _mock_openai):
        mock_settings.get_llm_config.return_value = {
            "api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test-model",
        }
        s = Summarizer()
        # 125 seconds = 2 min 5 sec
        s.add_segments([make_segment(125.0, 130.0, "Minute two")])
        out = s.build_raw_transcript()
        assert out == "[02:05] Minute two"

    @patch("src.notes.summarizer.OpenAI")
    @patch("src.notes.summarizer.settings")
    def test_timestamps_zero_pad(self, mock_settings, _mock_openai):
        mock_settings.get_llm_config.return_value = {
            "api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test-model",
        }
        s = Summarizer()
        s.add_segments([make_segment(61.0, 65.0, "One minute")])
        out = s.build_raw_transcript()
        # 61 sec → 1 min 1 sec → [01:01]
        assert out == "[01:01] One minute"


# ---------------------------------------------------------------------------
# generate_summary — TRANSCRIPT_ONLY mode
# ---------------------------------------------------------------------------

class TestTranscriptOnlyMode:
    """When settings.mode == RunMode.TRANSCRIPT_ONLY, no LLM call is made."""

    @pytest.mark.asyncio
    @patch("src.notes.summarizer.settings")
    @patch("src.notes.summarizer.OpenAI")
    async def test_no_llm_call_in_transcript_only_mode(self, mock_openai_cls, mock_settings):
        mock_settings.mode = RunMode.TRANSCRIPT_ONLY
        mock_settings.get_llm_config.return_value = {
            "api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test-model",
        }
        s = Summarizer()
        s.add_segments([make_segment(0.0, 3.0, "Hello world")])

        summary = await s.generate_summary()

        # The OpenAI client should NOT have been used
        client_instance = mock_openai_cls.return_value
        client_instance.chat.completions.create.assert_not_called()

        assert summary.title == "Meeting Transcript"
        assert summary.date == ""
        assert summary.duration_minutes == 0
        assert summary.participants == []
        assert summary.key_topics == []
        assert summary.decisions == []
        assert summary.action_items == []
        assert summary.full_transcript == "[00:00] Hello world"
        assert "[Transcript-only mode" in summary.summary


# ---------------------------------------------------------------------------
# generate_summary — non-TRANSCRIPT_ONLY with mocked LLM
# ---------------------------------------------------------------------------

class TestGenerateSummaryWithMockedLLM:
    """Tests for the LLM path: valid JSON, invalid JSON, empty/Nones."""

    @staticmethod
    def _patch_summarizer(*, mode: RunMode = RunMode.FULL):
        """Convenience: create a patched Summarizer ready for LLM testing."""
        openai_patch = patch("src.notes.summarizer.OpenAI")
        settings_patch = patch("src.notes.summarizer.settings", mode=mode)
        return openai_patch, settings_patch

    @pytest.mark.asyncio
    async def test_valid_json_parsed_correctly(self):
        openai_patch, settings_patch = self._patch_summarizer()
        with openai_patch as mock_openai_cls, settings_patch as mock_settings:
            mock_settings.get_llm_config.return_value = {
                "api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test-model",
            }
            mock_settings.llm_temperature = 0.3

            # Build mock client
            mock_client = mock_openai_cls.return_value
            mock_create = mock_client.chat.completions.create
            mock_create.return_value = make_mock_openai_response(json.dumps({
                "title": "Q2 Budget Review",
                "key_topics": ["Budget", "Hiring", "Timeline"],
                "decisions": ["Approve budget", "Hire 2 engineers"],
                "action_items": [
                    {"assignee": "Alice", "task": "Draft proposal", "deadline": "2026-06-15"},
                ],
                "summary": "An executive summary of the meeting.",
            }))

            s = Summarizer()
            s.add_segments([make_segment(0.0, 5.0, "Let's talk budget.")])
            result = await s.generate_summary()

            # Metadata
            assert result.title == "Q2 Budget Review"
            assert result.key_topics == ["Budget", "Hiring", "Timeline"]
            assert result.decisions == ["Approve budget", "Hire 2 engineers"]
            assert len(result.action_items) == 1
            assert result.action_items[0]["assignee"] == "Alice"
            assert result.summary == "An executive summary of the meeting."
            # In FULL mode the transcript is included
            assert result.full_transcript == "[00:00] Let's talk budget."

            # Verify the LLM was called with correct arguments
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["model"] == "test-model"
            assert call_kwargs["temperature"] == 0.3
            assert call_kwargs["timeout"] == 120
            assert "budget" in call_kwargs["messages"][0]["content"].lower()

    @pytest.mark.asyncio
    async def test_invalid_json_fallback(self):
        """When LLM returns non-JSON, fall back to Untitled Meeting with raw content as summary."""
        openai_patch, settings_patch = self._patch_summarizer()
        with openai_patch as mock_openai_cls, settings_patch as mock_settings:
            mock_settings.get_llm_config.return_value = {
                "api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test-model",
            }
            mock_settings.llm_temperature = 0.3

            mock_client = mock_openai_cls.return_value
            mock_client.chat.completions.create.return_value = make_mock_openai_response(
                "Oops, not JSON — just some raw text."
            )

            s = Summarizer()
            s.add_segments([make_segment(0.0, 2.0, "Test")])
            result = await s.generate_summary()

            assert result.title == "Untitled Meeting"
            assert result.key_topics == []
            assert result.decisions == []
            assert result.action_items == []
            assert result.summary == "Oops, not JSON — just some raw text."
            assert result.full_transcript == "[00:00] Test"

    @pytest.mark.asyncio
    async def test_empty_string_response(self):
        """LLM returns empty string — fallback with empty summary, no crash."""
        openai_patch, settings_patch = self._patch_summarizer()
        with openai_patch as mock_openai_cls, settings_patch as mock_settings:
            mock_settings.get_llm_config.return_value = {
                "api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test-model",
            }
            mock_settings.llm_temperature = 0.3

            mock_client = mock_openai_cls.return_value
            mock_client.chat.completions.create.return_value = make_mock_openai_response("")

            s = Summarizer()
            s.add_segments([make_segment(0.0, 1.0, "Hi")])
            result = await s.generate_summary()

            assert result.title == "Untitled Meeting"
            assert result.summary == "Failed to parse summary"
            assert result.key_topics == []

    @pytest.mark.asyncio
    async def test_none_content_response(self):
        """LLM response content is None — fallback without crash."""
        openai_patch, settings_patch = self._patch_summarizer()
        with openai_patch as mock_openai_cls, settings_patch as mock_settings:
            mock_settings.get_llm_config.return_value = {
                "api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test-model",
            }
            mock_settings.llm_temperature = 0.3

            mock_client = mock_openai_cls.return_value
            mock_client.chat.completions.create.return_value = make_mock_openai_response(None)

            s = Summarizer()
            s.add_segments([make_segment(0.0, 1.0, "Hi")])
            result = await s.generate_summary()

            # content = None, so content or "" → "" → json.loads("") fails → fallback
            # data["summary"] = content or "Failed to parse summary" → "" or ... → "Failed to parse summary"
            assert result.summary == "Failed to parse summary"
            assert result.title == "Untitled Meeting"

    @pytest.mark.asyncio
    async def test_json_missing_fields_defaulted(self):
        """LLM returns valid JSON but missing some expected keys — defaults kick in."""
        openai_patch, settings_patch = self._patch_summarizer()
        with openai_patch as mock_openai_cls, settings_patch as mock_settings:
            mock_settings.get_llm_config.return_value = {
                "api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test-model",
            }
            mock_settings.llm_temperature = 0.3

            mock_client = mock_openai_cls.return_value
            mock_client.chat.completions.create.return_value = make_mock_openai_response(json.dumps({
                "title": "Minimal",
                # no key_topics, no decisions, no action_items, no summary
            }))

            s = Summarizer()
            s.add_segments([make_segment(0.0, 1.0, "Hello")])
            result = await s.generate_summary()

            assert result.title == "Minimal"
            assert result.key_topics == []
            assert result.decisions == []
            assert result.action_items == []
            assert result.summary == ""


# ---------------------------------------------------------------------------
# SUMMARY_ONLY mode — transcript is omitted
# ---------------------------------------------------------------------------

class TestSummaryOnlyMode:
    """When settings.mode == RunMode.SUMMARY_ONLY, transcript is excluded."""

    @pytest.mark.asyncio
    async def test_summary_only_omits_transcript(self):
        openai_patch = patch("src.notes.summarizer.OpenAI")
        settings_patch = patch("src.notes.summarizer.settings", mode=RunMode.SUMMARY_ONLY)

        with openai_patch as mock_openai_cls, settings_patch as mock_settings:
            mock_settings.get_llm_config.return_value = {
                "api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test-model",
            }
            mock_settings.llm_temperature = 0.3

            mock_client = mock_openai_cls.return_value
            mock_client.chat.completions.create.return_value = make_mock_openai_response(json.dumps({
                "title": "Secret Meeting",
                "key_topics": ["Confidential"],
                "decisions": [],
                "action_items": [],
                "summary": "Can't share transcript.",
            }))

            s = Summarizer()
            s.add_segments([make_segment(0.0, 5.0, "Top secret content")])
            result = await s.generate_summary()

            assert result.title == "Secret Meeting"
            assert result.full_transcript == ""   # <-- omitted in SUMMARY_ONLY
            assert result.summary == "Can't share transcript."


# ---------------------------------------------------------------------------
# MeetingSummary dataclass
# ---------------------------------------------------------------------------

class TestMeetingSummaryDataclass:
    """Sanity-checks on the MeetingSummary dataclass itself."""

    def test_default_construction(self):
        ms = MeetingSummary(
            title="T", date="2026-06-11", duration_minutes=30,
            participants=["Alice", "Bob"],
            key_topics=["Topic1"], decisions=["D1"],
            action_items=[{"assignee": "A", "task": "X", "deadline": "soon"}],
            full_transcript="...", summary="Summary text",
        )
        assert ms.title == "T"
        assert ms.participants == ["Alice", "Bob"]
        assert len(ms.action_items) == 1

    def test_equality(self):
        a = MeetingSummary(title="X", date="", duration_minutes=0, participants=[],
                           key_topics=[], decisions=[], action_items=[],
                           full_transcript="", summary="")
        b = MeetingSummary(title="X", date="", duration_minutes=0, participants=[],
                           key_topics=[], decisions=[], action_items=[],
                           full_transcript="", summary="")
        assert a == b

    def test_inequality(self):
        a = MeetingSummary(title="X", date="", duration_minutes=0, participants=[],
                           key_topics=[], decisions=[], action_items=[],
                           full_transcript="", summary="")
        b = MeetingSummary(title="Y", date="", duration_minutes=0, participants=[],
                           key_topics=[], decisions=[], action_items=[],
                           full_transcript="", summary="")
        assert a != b
