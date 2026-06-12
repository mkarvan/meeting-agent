"""Command-line interface for the meeting agent."""
import asyncio
import os
import sys
from pathlib import Path

# Force unbuffered output so real-time transcript lines appear immediately
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None
os.environ.setdefault("PYTHONUNBUFFERED", "1")

import click
from src.config import settings, RunMode, LLMProvider
from src.orchestrator import MeetingAgent


@click.group()
def cli():
    """Meeting Agent — AI-powered meeting notes."""
    pass


@cli.command()
@click.argument("url")
@click.option("--name", "-n", default="Meeting Notes Bot", help="Bot display name")
@click.option(
    "--mode", "-m",
    type=click.Choice(["full", "transcript_only", "summary_only"]),
    default="full",
    help="Agent run mode (transcript_only for no LLM, summary_only for no transcript)",
)
@click.option(
    "--provider", "-p",
    type=click.Choice(["openai", "anthropic", "opencode-go", "ollama", "custom"]),
    default="opencode-go",
    help="LLM provider",
)
@click.option("--model", type=str, default=None, help="LLM model name (e.g. gpt-4o, claude-sonnet-4-20250514)")
@click.option("--keep-audio", is_flag=True, help="Keep WAV audio chunks after transcription (debug only)")
def join(url: str, name: str, mode: str, provider: str, model: str, keep_audio: bool):
    """Join a meeting via browser automation and take notes.
    NOTE: Google Meet actively blocks automated browsers.
    For Google Meet, use the 'listen' command instead and join manually."""
    _apply_settings(mode, provider, model, keep_audio)
    agent = MeetingAgent()
    asyncio.run(agent.run(url, name))


@cli.command()
@click.option("--title", "-t", default="Meeting", help="Meeting title for the saved notes")
@click.option(
    "--mode", "-m",
    type=click.Choice(["full", "transcript_only", "summary_only"]),
    default="transcript_only",
    help="Agent run mode (default: transcript_only — no LLM API cost)",
)
@click.option(
    "--provider", "-p",
    type=click.Choice(["openai", "anthropic", "opencode-go", "ollama", "custom"]),
    default="opencode-go",
    help="LLM provider (only used with --mode full or summary_only)",
)
@click.option("--model", type=str, default=None, help="LLM model name")
@click.option("--keep-audio", is_flag=True, help="Keep WAV audio chunks (debug)")
def listen(title: str, mode: str, provider: str, model: str, keep_audio: bool):
    """Capture & transcribe system audio — you join the meeting manually.

    1. Join the meeting yourself in a browser or app
    2. Route audio via pavucontrol to 'Meeting Agent Audio Capture'
    3. Run this command — it transcribes in real-time
    4. Press Ctrl+C when the meeting ends to save the transcript
    """
    _apply_settings(mode, provider, model, keep_audio)
    agent = MeetingAgent()
    try:
        asyncio.run(agent.listen(title))
    except KeyboardInterrupt:
        print("\n👋 Stopped by user.")


@cli.command()
def setup():
    """Set up audio sink and dependencies."""
    import subprocess
    script = Path(__file__).parent.parent / "scripts" / "setup-audio-sink.sh"
    if script.exists():
        subprocess.run(["bash", str(script)])
    else:
        print(f"Setup script not found: {script}")
        print("Run manually: bash scripts/setup-audio-sink.sh")


@cli.command()
def status():
    """Check system readiness for meeting capture."""
    import subprocess

    print("🔍 Meeting Agent Status Check\n")

    # Check ffmpeg
    r = subprocess.run(["which", "ffmpeg"], capture_output=True)
    print(f"{'✅' if r.returncode == 0 else '❌'} ffmpeg: {r.stdout.decode().strip() or 'not found'}")

    # Check pulseaudio
    r = subprocess.run(["pactl", "list", "sources", "short"], capture_output=True, text=True)
    has_sink = "meeting-agent-sink" in r.stdout
    print(f"{'✅' if has_sink else '❌'} Audio sink 'meeting-agent-sink': {'present' if has_sink else 'missing — run: meeting-agent setup'}")

    # Check whisper model
    wm = Path.home() / ".cache" / "huggingface" / "hub"
    has_model = False
    if wm.exists():
        for p in wm.rglob("model.bin"):
            has_model = True
            break
    print(f"{'✅' if has_model else '❌'} faster-whisper model: {'cached' if has_model else 'missing — will download on first use'}")

    # Check chromium
    cr = Path.home() / ".cache" / "ms-playwright" / "chromium-1223" / "chrome-linux64" / "chrome"
    print(f"{'✅' if cr.exists() else '❌'} Playwright Chromium: {'installed' if cr.exists() else 'missing'}")

    # Check notes dir
    nd = settings.notes_dir
    print(f"{'✅' if nd.exists() else 'ℹ️'} Notes directory: {nd}")

    print("\n💡 Quick start:  meeting-agent listen --title 'Standup'")


def _apply_settings(mode: str, provider: str, model: str | None, keep_audio: bool):
    settings.mode = RunMode(mode)
    settings.llm_provider = LLMProvider(provider)
    if model:
        settings.llm_model = model
    if keep_audio:
        settings.keep_audio = True


if __name__ == "__main__":
    cli()
