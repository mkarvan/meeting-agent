"""Speech-to-text using faster-whisper."""
import logging
import wave
import os
from pathlib import Path
from typing import List
from dataclasses import dataclass

from faster_whisper import WhisperModel
from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionSegment:
    """A transcribed segment with timestamp."""
    start: float  # seconds from meeting start
    end: float
    text: str
    speaker: str = "Unknown"


class Transcriber:
    """Transcribes audio using faster-whisper."""

    def __init__(self):
        self.model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
        self._meeting_offset: float = 0.0

    def transcribe(self, audio_path: Path) -> List[TranscriptionSegment]:
        """Transcribe a WAV file. Returns segments with meeting-relative timestamps.
        Gracefully handles empty or silent chunks."""
        # --- Guard: empty or invalid file ---
        if not audio_path.exists():
            return []
        file_size = audio_path.stat().st_size
        if file_size == 0:
            return []

        # Get actual audio duration for offset tracking
        duration = 0.0
        try:
            with wave.open(str(audio_path), 'r') as wf:
                nframes = wf.getnframes()
                rate = wf.getframerate()
                if nframes > 0 and rate > 0:
                    duration = nframes / rate
        except (wave.Error, EOFError, OSError):
            # Corrupt WAV — skip
            return []

        if duration < 0.1:  # skip near-silent/<100ms chunks
            self._meeting_offset += duration
            return []

        try:
            segments, _ = self.model.transcribe(
                str(audio_path),
                beam_size=5,
                language=None,  # auto-detect
                vad_filter=True,
                vad_parameters=dict(
                    threshold=0.3,           # lower threshold for quiet speech
                    min_speech_duration_ms=250,
                    min_silence_duration_ms=100,
                ),
            )
        except Exception as e:
            # Invalid data, corrupted audio, etc.
            logger.error("Transcriber error on %s: %s", audio_path.name, e)
            return []

        results = []
        for seg in segments:
            results.append(TranscriptionSegment(
                start=self._meeting_offset + seg.start,
                end=self._meeting_offset + seg.end,
                text=seg.text.strip(),
            ))

        # Update offset for next chunk
        self._meeting_offset += duration
        return results

    def reset_offset(self) -> None:
        """Reset meeting time offset (for new meetings)."""
        self._meeting_offset = 0.0
