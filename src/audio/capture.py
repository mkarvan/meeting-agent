"""Audio capture using FFmpeg — supports PulseAudio (Linux) and AVFoundation (macOS)."""
import asyncio
import platform
import subprocess
import time
from pathlib import Path
from typing import AsyncIterator, Iterator

from src.config import settings

_IS_MACOS = platform.system() == "Darwin"


class AudioCapture:
    """Captures system audio via PulseAudio virtual sink (Linux) or BlackHole/AVFoundation (macOS)."""

    def __init__(self):
        self.chunk_dir = settings.audio_dir
        self.chunk_dir.mkdir(parents=True, exist_ok=True)
        self._process = None
        self._current_chunk = 0
        self.stopped = False

    @property
    def monitor_source(self) -> str:
        return settings.audio_device

    def start(self) -> None:
        """Start FFmpeg process capturing audio in 30s chunks."""
        self.stopped = False
        output_pattern = str(self.chunk_dir / "chunk_%05d.wav")

        if _IS_MACOS:
            # macOS: use AVFoundation (e.g. BlackHole virtual device)
            cmd = [
                "ffmpeg",
                "-f", "avfoundation",
                "-i", self.monitor_source,   # e.g. ":0" or "BlackHole 2ch"
                "-ac", "1",                   # mono
                "-ar", str(settings.sample_rate),  # 16kHz for whisper
                "-f", "segment",
                "-segment_time", str(settings.chunk_duration),
                "-reset_timestamps", "1",
                output_pattern,
            ]
            # Apply volume boost via audio filter
            if settings.volume_boost_db != 0.0:
                # Insert -af volume= before -ac
                ac_idx = cmd.index("-ac")
                cmd.insert(ac_idx, f"volume={settings.volume_boost_db}dB")
                cmd.insert(ac_idx, "-af")
        else:
            # Linux: use PulseAudio
            cmd = [
                "ffmpeg",
                "-f", "pulse",
                "-i", self.monitor_source,
                "-af", f"volume={settings.volume_boost_db}dB",
                "-ac", "1",                   # mono
                "-ar", str(settings.sample_rate),  # 16kHz for whisper
                "-f", "segment",
                "-segment_time", str(settings.chunk_duration),
                "-reset_timestamps", "1",
                output_pattern,
            ]

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    async def get_new_chunks(self) -> AsyncIterator[Path]:
        """Yield newly created WAV chunk files without blocking the event loop."""
        while not self.stopped:
            chunk_path = self.chunk_dir / f"chunk_{self._current_chunk:05d}.wav"
            if chunk_path.exists():
                self._current_chunk += 1
                yield chunk_path
            else:
                await asyncio.sleep(0.5)

    def get_new_chunks_sync(self) -> Iterator[Path]:
        """Synchronous variant for non-async callers."""
        while not self.stopped:
            chunk_path = self.chunk_dir / f"chunk_{self._current_chunk:05d}.wav"
            if chunk_path.exists():
                self._current_chunk += 1
                yield chunk_path
            else:
                time.sleep(0.5)

    def cleanup_chunk(self, chunk_path: Path) -> None:
        """Delete a WAV chunk after successful transcription."""
        if not settings.keep_audio and chunk_path.exists():
            chunk_path.unlink()

    def cleanup_all(self) -> None:
        """Remove all remaining audio chunks (called on agent exit)."""
        if not settings.keep_audio and self.chunk_dir.exists():
            import shutil
            shutil.rmtree(self.chunk_dir, ignore_errors=True)

    def stop(self) -> None:
        """Stop the FFmpeg capture process."""
        self.stopped = True
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            self._process = None
