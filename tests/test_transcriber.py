"""Tests for the audio transcriber module."""
import wave
import struct
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from src.audio.transcriber import Transcriber, TranscriptionSegment


class TestTranscriptionSegment:
    """Tests for the TranscriptionSegment dataclass."""

    def test_create_segment(self):
        seg = TranscriptionSegment(start=10.5, end=15.2, text="hello world")
        assert seg.start == 10.5
        assert seg.end == 15.2
        assert seg.text == "hello world"
        assert seg.speaker == "Unknown"

    def test_custom_speaker(self):
        seg = TranscriptionSegment(start=0.0, end=5.0, text="hi", speaker="Alice")
        assert seg.speaker == "Alice"

    def test_equality(self):
        seg1 = TranscriptionSegment(start=1.0, end=2.0, text="a")
        seg2 = TranscriptionSegment(start=1.0, end=2.0, text="a")
        assert seg1 == seg2

    def test_inequality(self):
        seg1 = TranscriptionSegment(start=1.0, end=2.0, text="a")
        seg2 = TranscriptionSegment(start=1.0, end=2.0, text="b")
        assert seg1 != seg2


class TestTranscriber:
    """Tests for the Transcriber class with mocked WhisperModel."""

    @pytest.fixture
    def mock_whisper_model(self):
        with patch("src.audio.transcriber.WhisperModel") as mock:
            yield mock

    @pytest.fixture
    def transcriber(self, mock_whisper_model):
        return Transcriber()

    @pytest.fixture
    def sample_wav(self, tmp_path):
        """Create a minimal valid WAV file for testing."""
        wav_path = tmp_path / "test_audio.wav"
        sample_rate = 16000
        duration_seconds = 5
        num_samples = sample_rate * duration_seconds

        with wave.open(str(wav_path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(struct.pack("h", 0) * num_samples)

        return wav_path

    def test_whisper_model_loaded(self, mock_whisper_model):
        """WhisperModel should be initialized with config settings."""
        tr = Transcriber()
        mock_whisper_model.assert_called_once()
        args, kwargs = mock_whisper_model.call_args
        assert kwargs["device"] == "cpu"
        assert kwargs["compute_type"] == "int8"

    def test_initial_offset_is_zero(self, transcriber):
        """New transcriber starts with zero offset."""
        assert transcriber._meeting_offset == 0.0

    def test_reset_offset(self, transcriber):
        """Reset should set offset to zero."""
        transcriber._meeting_offset = 42.5
        transcriber.reset_offset()
        assert transcriber._meeting_offset == 0.0

    def test_transcribe_returns_segments(self, transcriber, sample_wav, mock_whisper_model):
        """Transcribe should return list of TranscriptionSegment objects."""
        # Set up the mock model to return segments
        mock_segments = [
            MagicMock(start=0.0, end=2.5, text="Hello world"),
            MagicMock(start=2.5, end=5.0, text="Testing transcription"),
        ]
        mock_instance = mock_whisper_model.return_value
        mock_instance.transcribe.return_value = (mock_segments, None)

        segments = transcriber.transcribe(sample_wav)

        assert len(segments) == 2
        assert isinstance(segments[0], TranscriptionSegment)
        assert segments[0].text == "Hello world"
        assert segments[0].start == 0.0
        assert segments[0].end == 2.5
        assert segments[1].text == "Testing transcription"

    def test_transcribe_updates_offset(self, transcriber, sample_wav, mock_whisper_model):
        """Offset should increase by the WAV duration after transcribing."""
        mock_segments = [MagicMock(start=0.0, end=2.0, text="test")]
        mock_instance = mock_whisper_model.return_value
        mock_instance.transcribe.return_value = (mock_segments, None)

        initial_offset = transcriber._meeting_offset
        transcriber.transcribe(sample_wav)

        # The WAV duration is 5 seconds
        assert transcriber._meeting_offset == initial_offset + 5.0

    def test_transcribe_multiple_chunks_accumulates_offset(self, transcriber, sample_wav, mock_whisper_model):
        """Multiple transcribe calls should accumulate the offset."""
        mock_segments = [MagicMock(start=0.0, end=1.0, text="one")]
        mock_instance = mock_whisper_model.return_value
        mock_instance.transcribe.return_value = (mock_segments, None)

        transcriber.transcribe(sample_wav)  # +5s
        transcriber.transcribe(sample_wav)  # +5s
        transcriber.transcribe(sample_wav)  # +5s

        assert transcriber._meeting_offset == 15.0

    def test_transcribe_empty_segments(self, transcriber, sample_wav, mock_whisper_model):
        """Empty segments should return empty list."""
        mock_instance = mock_whisper_model.return_value
        mock_instance.transcribe.return_value = ([], None)

        segments = transcriber.transcribe(sample_wav)
        assert segments == []
        assert transcriber._meeting_offset == 5.0  # Offset still accumulated

    def test_transcribe_segment_offset_is_accumulated(self, transcriber, sample_wav, mock_whisper_model):
        """Segment timestamps should have meeting_offset added."""
        # Set a non-zero offset to test accumulation
        transcriber._meeting_offset = 10.0

        mock_segments = [MagicMock(start=1.0, end=3.0, text="accumulated")]
        mock_instance = mock_whisper_model.return_value
        mock_instance.transcribe.return_value = (mock_segments, None)

        segments = transcriber.transcribe(sample_wav)

        assert segments[0].start == 11.0  # 10.0 (offset) + 1.0 (segment)
        assert segments[0].end == 13.0    # 10.0 (offset) + 3.0 (segment)

    def test_transcribe_strips_whitespace(self, transcriber, sample_wav, mock_whisper_model):
        """Segment text should have leading/trailing whitespace stripped."""
        mock_segments = [
            MagicMock(start=0.0, end=1.0, text="  hello world  "),
        ]
        mock_instance = mock_whisper_model.return_value
        mock_instance.transcribe.return_value = (mock_segments, None)

        segments = transcriber.transcribe(sample_wav)
        assert segments[0].text == "hello world"

    def test_transcribe_passes_correct_args(self, transcriber, sample_wav, mock_whisper_model):
        """Transcribe should pass beam_size, language, vad_filter to Whisper."""
        mock_instance = mock_whisper_model.return_value
        mock_instance.transcribe.return_value = ([], None)

        transcriber.transcribe(sample_wav)

        call_args = mock_instance.transcribe.call_args
        assert call_args[0][0] == str(sample_wav)  # first positional arg is path
        assert call_args[1]["beam_size"] == 5
        assert call_args[1]["language"] is None
        assert call_args[1]["vad_filter"] is True

    def test_transcribe_with_long_filename(self, transcriber, tmp_path, mock_whisper_model):
        """Should handle long file paths."""
        long_name = tmp_path / ("a" * 100 + ".wav")
        sample_rate = 16000
        with wave.open(str(long_name), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(struct.pack("h", 0) * sample_rate)

        mock_instance = mock_whisper_model.return_value
        mock_instance.transcribe.return_value = ([], None)

        segments = transcriber.transcribe(long_name)
        assert segments == []
