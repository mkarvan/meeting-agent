"""Main orchestrator — ties together audio capture, transcription, summarization, and cleanup."""
import asyncio
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

    # ── Browser-auto-join mode ───────────────────────────────────────────

    async def run(self, meeting_url: str, bot_name: str | None = None):
        """Join a meeting via browser and take notes (full-auto mode)."""
        name = bot_name or settings.bot_name
        meeting = parse_meeting_url(meeting_url)

        print(f"🎙️  Joining {meeting.platform.value} meeting as '{name}'...")
        print(f"📋  Mode: {settings.mode.value} | LLM: {settings.llm_provider.value}/{settings.llm_model}")

        # 1. Start audio capture
        self.audio.start()

        # 2. Join meeting via browser
        await self.connector.start()
        await self.connector.join_meeting(meeting.platform.value, meeting_url, name)

        self._start_time = time.time()
        self._running = True

        print("✅ Connected. Capturing audio and transcribing...")
        await self._capture_loop()

        await self._finalize()

    # ── Audio-only mode (user joins manually) ────────────────────────────

    async def listen(self, meeting_title: str = "Meeting"):
        """Capture & transcribe audio only — user joins the meeting manually.

        The user must:
        Linux:
          1. Join the meeting in their own browser/app
          2. Route browser audio to the meeting-agent-sink via pavucontrol
          3. Press Ctrl+C here when the meeting ends
        macOS:
          1. Set system output to Multi-Output Device (BlackHole + speakers)
          2. Join the meeting in their own browser/app
          3. Press Ctrl+C here when the meeting ends
        """
        _sys = platform.system()

        print("🎙️  Meeting Agent — audio-only mode", flush=True)
        print(f"📋  Mode: {settings.mode.value}", flush=True)
        print(f"🎤  Device: {settings.audio_device}", flush=True)
        print(flush=True)

        if _sys == "Darwin":
            print("   ╔══════════════════════════════════════════════╗", flush=True)
            print("   ║  macOS SETUP                                 ║", flush=True)
            print("   ║                                              ║", flush=True)
            print("   ║  1. Install BlackHole:                       ║", flush=True)
            print("   ║     brew install blackhole-2ch               ║", flush=True)
            print("   ║  2. Create Multi-Output Device               ║", flush=True)
            print("   ║     (Audio MIDI Setup → + → Multi-Output)     ║", flush=True)
            print("   ║  3. Set system output to Multi-Output        ║", flush=True)
            print("   ║  4. Join meeting in your browser             ║", flush=True)
            print("   ║  5. Press Ctrl+C when the meeting ends       ║", flush=True)
            print("   ╚══════════════════════════════════════════════╝", flush=True)
        else:
            print("   ╔══════════════════════════════════════════════╗", flush=True)
            print("   ║  LINUX SETUP                                 ║", flush=True)
            print("   ║                                              ║", flush=True)
            print("   ║  1. Join the meeting in your browser         ║", flush=True)
            print("   ║  2. Open pavucontrol                         ║", flush=True)
            print("   ║  3. Playback tab → browser → output →       ║", flush=True)
            print(f"   ║     '{settings.audio_device}'                ║", flush=True)
            print("   ║  4. Press Ctrl+C when the meeting ends       ║", flush=True)
            print("   ╚══════════════════════════════════════════════╝", flush=True)

        print(flush=True)
        print("Waiting for audio... (stop with Ctrl+C)", flush=True)

        self._start_time = time.time()
        self._running = True
        self.audio.start()

        try:
            await self._capture_loop()
        except KeyboardInterrupt:
            print("\n🛑 Stopping...")
        finally:
            await self._finalize(meeting_title)

    # ── Shared capture loop ──────────────────────────────────────────────

    async def _capture_loop(self):
        """Main loop: yield chunks, transcribe, print real-time output."""
        self._setup_signal_handlers()
        loop = asyncio.get_running_loop()

        for chunk_path in self.audio.get_new_chunks():
            if self._stop_requested or not self._running:
                break

            # Transcribe (runs sync, offload to thread so event loop stays responsive)
            segments = await loop.run_in_executor(
                None, self.transcriber.transcribe, chunk_path
            )

            if segments:
                for seg in segments:
                    ts = self._format_timestamp(seg.start)
                    line = f"[{ts}] {seg.text}"
                    self._transcript_lines.append(line)
                    print(line, flush=True)

                if settings.mode != RunMode.TRANSCRIPT_ONLY:
                    self.summarizer.add_segments(segments)

            self.audio.cleanup_chunk(chunk_path)
            self._chunk_count += 1

    async def _finalize(self, meeting_title: str = "Meeting"):
        """Stop capture, generate notes, clean up."""
        self._running = False
        self.audio.stopped = True  # stop the chunk generator
        self.audio.stop()
        self.audio.cleanup_all()

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

        print(f"\n📝 Transcript saved to: {transcript_path}")
        print(f"⏱️  Duration: {duration} min")
        print(f"💬 Lines transcribed: {len(self._transcript_lines)}")
        print(f"🗑️  Audio chunks processed & deleted: {self._chunk_count}")

        # Generate LLM summary if in full mode
        if settings.mode != RunMode.TRANSCRIPT_ONLY and self._transcript_lines:
            summary = self.summarizer.generate_summary()
            summary.duration_minutes = duration
            summary.date = datetime.now().strftime("%Y-%m-%d")
            summary_path = save_notes(summary)
            print(f"🤖 Summary saved to: {summary_path}")

    # ── Helpers ──────────────────────────────────────────────────────────

    def _setup_signal_handlers(self):
        """Catch SIGINT/SIGTERM to stop cleanly."""
        def _handler(signum, frame):
            self.audio.stopped = True
            self._stop_requested = True
            print("\n🛑 Stop signal received, finishing current chunk...", flush=True)
        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
