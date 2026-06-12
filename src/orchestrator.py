"""Main orchestrator — ties together audio capture, transcription, summarization, and cleanup."""
import asyncio
import logging
import platform
import signal
import time
from pathlib import Path
from datetime import datetime

from src.config import settings, RunMode
from src.audio.capture import AudioCapture
from src.audio.transcriber import Transcriber
from src.notes.summarizer import Summarizer
from src.notes.formatter import save_notes
from src.meeting.connector import MeetingConnector
from src.meeting.parser import parse_meeting_url

logger = logging.getLogger(__name__)


class MeetingAgent:
    """Main orchestrator for the meeting notes agent."""

    def __init__(self):
        self.audio = AudioCapture()
        self.transcriber = Transcriber()
        self.summarizer = Summarizer()
        self.connector = MeetingConnector()
        self._running = False
        self._start_time: float | None = None
        self._chunk_count = 0
        self._transcript_lines: list[str] = []
        self._stop_requested = False
        self._browser_mode = False

    # ── Browser-auto-join mode ───────────────────────────────────────────

    async def run(self, meeting_url: str, bot_name: str | None = None):
        """Join a meeting via browser and take notes (full-auto mode)."""
        name = bot_name or settings.bot_name
        meeting = parse_meeting_url(meeting_url)

        logger.info("Joining %s meeting as '%s'", meeting.platform.value, name)
        logger.info("Mode: %s | LLM: %s/%s", settings.mode.value, settings.llm_provider.value, settings.llm_model)

        # 1. Start audio capture
        self.audio.start()

        # 2. Join meeting via browser
        self._browser_mode = True
        await self.connector.start()
        await self.connector.join_meeting(meeting.platform.value, meeting_url, name)

        self._start_time = time.time()
        self._running = True

        logger.info("Connected — capturing audio and transcribing")
        await self._capture_loop()

        await self._finalize()

    # ── Audio-only mode (user joins manually) ────────────────────────────

    async def listen(self, meeting_title: str = "Meeting"):
        """Capture & transcribe audio only — user joins the meeting manually."""
        _sys = platform.system()

        logger.info("Meeting Agent — audio-only mode")
        logger.info("Mode: %s", settings.mode.value)
        logger.info("Device: %s", settings.audio_device)

        if _sys == "Darwin":
            logger.info(
                "macOS setup: install BlackHole (brew install blackhole-2ch), "
                "create Multi-Output Device in Audio MIDI Setup, "
                "set system output to Multi-Output, join meeting, then Ctrl+C to stop"
            )
        else:
            logger.info(
                "Linux setup: join meeting in browser, open pavucontrol, "
                "route browser audio to '%s', then Ctrl+C to stop",
                settings.audio_device,
            )

        logger.info("Waiting for audio... (stop with Ctrl+C)")

        self._start_time = time.time()
        self._running = True
        self.audio.start()

        try:
            await self._capture_loop()
        except KeyboardInterrupt:
            logger.info("Stopping...")
        finally:
            await self._finalize(meeting_title)

    # ── Shared capture loop ──────────────────────────────────────────────

    async def _capture_loop(self):
        """Main loop: yield chunks, transcribe, print real-time output."""
        self._setup_signal_handlers()
        loop = asyncio.get_running_loop()

        async for chunk_path in self.audio.get_new_chunks():
            if self._stop_requested or not self._running:
                break

            segments = await loop.run_in_executor(
                None, self.transcriber.transcribe, chunk_path
            )

            if segments:
                for seg in segments:
                    ts = self._format_timestamp(seg.start)
                    line = f"[{ts}] {seg.text}"
                    self._transcript_lines.append(line)
                    logger.info(line)

                if settings.mode != RunMode.TRANSCRIPT_ONLY:
                    self.summarizer.add_segments(segments)

            self.audio.cleanup_chunk(chunk_path)
            self._chunk_count += 1

    async def _finalize(self, meeting_title: str = "Meeting"):
        """Stop capture, generate notes, clean up."""
        self._running = False
        self.audio.stopped = True
        self.audio.stop()
        self.audio.cleanup_all()

        if self._browser_mode:
            try:
                await self.connector.leave()
            except Exception:
                pass
            try:
                await self.connector.stop()
            except Exception:
                pass

        duration = int((time.time() - self._start_time) / 60) if self._start_time else 0

        # Save transcript
        ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        title = Path(meeting_title).stem if meeting_title else "meeting"
        transcript_path = settings.notes_dir / f"{title}_{ts}_transcript.md"

        transcript_md = f"# {meeting_title}\n\n"
        transcript_md += f"**Date:** {datetime.now().strftime('%Y-%m-%d')}\n"
        transcript_md += f"**Duration:** {duration} min\n"
        transcript_md += f"**Mode:** {settings.mode.value}\n\n"
        transcript_md += "## Transcript\n\n"
        transcript_md += "\n".join(self._transcript_lines) if self._transcript_lines else "*No speech detected.*"
        transcript_md += "\n"

        settings.notes_dir.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(transcript_md)

        logger.info("Transcript saved to: %s", transcript_path)
        logger.info("Duration: %d min", duration)
        logger.info("Lines transcribed: %d", len(self._transcript_lines))
        logger.info("Audio chunks processed & deleted: %d", self._chunk_count)

        # Generate LLM summary if in full mode
        if settings.mode != RunMode.TRANSCRIPT_ONLY and self._transcript_lines:
            summary = self.summarizer.generate_summary()
            summary.duration_minutes = duration
            summary.date = datetime.now().strftime("%Y-%m-%d")
            summary_path = save_notes(summary)
            logger.info("Summary saved to: %s", summary_path)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _setup_signal_handlers(self):
        """Catch SIGINT/SIGTERM to stop cleanly."""
        def _handler(signum, frame):
            self.audio.stopped = True
            self._stop_requested = True
            logger.info("Stop signal received, finishing current chunk...")
        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
