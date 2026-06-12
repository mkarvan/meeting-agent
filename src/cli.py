"""Command-line interface for the meeting agent."""
import asyncio
import logging
import os
import platform
import sys
from pathlib import Path

import click
from src.config import settings, RunMode, LLMProvider, CONFIG_PATHS
from src.errors import MeetingAgentError
from src.orchestrator import MeetingAgent

logger = logging.getLogger("meeting_agent")


def _configure_logging(level: str = "INFO"):
    """Set up console logging with a clean format for CLI use."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    root = logging.getLogger("src")
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))


def _handle_error(e: Exception) -> None:
    """Print a user-friendly error and exit."""
    if isinstance(e, MeetingAgentError):
        click.echo(f"\nError: {e}", err=True)
    else:
        click.echo(f"\nUnexpected error: {e}", err=True)
        click.echo("If this persists, please file an issue.", err=True)
    sys.exit(1)


class SafeGroup(click.Group):
    """Click group that catches MeetingAgentError and shows clean messages."""

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except MeetingAgentError as e:
            _handle_error(e)


@click.group(cls=SafeGroup)
@click.option("--log-level", type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]), default="INFO", help="Set log verbosity")
def cli(log_level: str):
    """Meeting Agent — AI-powered meeting notes."""
    _configure_logging(log_level)


@cli.command()
@click.argument("url")
@click.option("--name", "-n", default="Meeting Notes Bot", help="Bot display name")
@click.option("--title", "-t", default="Meeting", help="Meeting title for saved notes")
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
@click.option("--device", "-d", type=str, default=None, help="Audio capture device (e.g. meeting-agent-sink.monitor, @DEFAULT_SINK@.monitor)")
@click.option("--keep-audio", is_flag=True, help="Keep WAV audio chunks after transcription (debug only)")
def join(url: str, name: str, title: str, mode: str, provider: str, model: str, device: str, keep_audio: bool):
    """Join a meeting via browser automation and take notes.
    NOTE: Google Meet actively blocks automated browsers.
    For Google Meet, use the 'listen' command instead and join manually."""
    _apply_settings(mode, provider, model, keep_audio, device)
    try:
        agent = MeetingAgent()
        asyncio.run(agent.run(url, name, title=title))
    except MeetingAgentError:
        raise
    except Exception as e:
        _handle_error(e)


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
@click.option("--device", "-d", type=str, default=None, help="Audio capture device (Linux: meeting-agent-sink.monitor, @DEFAULT_SINK@.monitor; macOS: :0, 'BlackHole 2ch')")
@click.option("--keep-audio", is_flag=True, help="Keep WAV audio chunks (debug)")
def listen(title: str, mode: str, provider: str, model: str, device: str, keep_audio: bool):
    """Capture & transcribe system audio — you join the meeting manually.

    Linux:
      1. Join the meeting yourself in a browser or app
      2. Route audio via pavucontrol to 'Meeting Agent Audio Capture'
      3. Run this command — it transcribes in real-time
      4. Press Ctrl+C when the meeting ends

    macOS:
      1. Install BlackHole: brew install blackhole-2ch
      2. Create a Multi-Output Device in Audio MIDI Setup (BlackHole + your speakers)
      3. Join the meeting and set system output to the Multi-Output Device
      4. Run this command with --device ':0'
      5. Press Ctrl+C when the meeting ends

    You can capture from any device with --device:
      Linux:   --device @DEFAULT_SINK@.monitor (headphones/speakers)
      macOS:   --device ':0' (BlackHole) or --device ':1' (mic)
    """
    _apply_settings(mode, provider, model, keep_audio, device)
    try:
        agent = MeetingAgent()
        asyncio.run(agent.listen(title))
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
    except MeetingAgentError:
        raise
    except Exception as e:
        _handle_error(e)


@cli.command()
def setup():
    """Set up audio capture for your platform.

    Linux:   Creates PulseAudio virtual sink + loopback
    macOS:   Instructions for BlackHole + Multi-Output Device
    """
    import subprocess

    if platform.system() == "Darwin":
        click.echo("macOS audio setup")
        click.echo()
        click.echo("1. Install BlackHole virtual audio driver:")
        click.echo("   brew install blackhole-2ch")
        click.echo()
        click.echo("2. Open Audio MIDI Setup (Applications > Utilities)")
        click.echo("3. Click '+' -> 'Create Multi-Output Device'")
        click.echo("4. Check both 'BlackHole 2ch' AND your speakers/headphones")
        click.echo("5. Right-click the Multi-Output Device -> 'Use This Device For Sound Output'")
        click.echo()
        click.echo("Then run:  meeting-agent listen --device ':0' --title 'Meeting'")
        return

    # Linux: run the PulseAudio setup script
    script = Path(__file__).parent.parent / "scripts" / "setup-audio-sink.sh"
    if script.exists():
        subprocess.run(["bash", str(script)])
    else:
        click.echo(f"Setup script not found: {script}", err=True)
        click.echo("Run manually: bash scripts/setup-audio-sink.sh")


@cli.command()
def status():
    """Check system readiness for meeting capture (Linux/macOS)."""
    import shutil
    import subprocess

    _sys = platform.system()
    click.echo(f"Meeting Agent Status Check ({_sys})\n")

    # Check ffmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    click.echo(f"{'[ok]' if ffmpeg_path else '[missing]'} ffmpeg: {ffmpeg_path or 'not found — brew install ffmpeg'}")

    if _sys == "Darwin":
        if ffmpeg_path:
            r = subprocess.run(
                ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                capture_output=True, text=True
            )
            has_blackhole = "BlackHole" in r.stderr
            click.echo(f"{'[ok]' if has_blackhole else '[missing]'} BlackHole: {'found' if has_blackhole else 'missing — run: brew install blackhole-2ch'}")
        else:
            click.echo("[skip] BlackHole: cannot check without ffmpeg")
    else:
        if shutil.which("pactl"):
            r = subprocess.run(["pactl", "list", "sources", "short"], capture_output=True, text=True)
            has_sink = "meeting-agent-sink" in r.stdout
            click.echo(f"{'[ok]' if has_sink else '[missing]'} Audio sink 'meeting-agent-sink': {'present' if has_sink else 'missing — run: meeting-agent setup'}")
        else:
            click.echo("[missing] pactl: PulseAudio not installed")

    # Check whisper model
    wm = Path.home() / ".cache" / "huggingface" / "hub"
    has_model = False
    if wm.exists():
        for p in wm.rglob("model.bin"):
            has_model = True
            break
    click.echo(f"{'[ok]' if has_model else '[missing]'} faster-whisper model: {'cached' if has_model else 'missing — will download on first use'}")

    # Check chromium (any installed version)
    if _sys == "Darwin":
        pw_dir = Path.home() / "Library" / "Caches" / "ms-playwright"
    else:
        pw_dir = Path.home() / ".cache" / "ms-playwright"
    has_chromium = any(pw_dir.glob("chromium-*")) if pw_dir.exists() else False
    click.echo(f"{'[ok]' if has_chromium else '[missing]'} Playwright Chromium: {'installed' if has_chromium else 'missing — run: playwright install chromium'}")

    # Config file
    config_file = next((p for p in CONFIG_PATHS if p.is_file()), None)
    if config_file:
        click.echo(f"[ok] Config file: {config_file}")
    else:
        click.echo(f"[info] Config file: none found (create ~/.config/meeting-agent/config.toml)")

    # Check notes dir
    nd = settings.notes_dir
    click.echo(f"{'[ok]' if nd.exists() else '[info]'} Notes directory: {nd}")

    # Show configured audio device
    click.echo(f"Audio device: {settings.audio_device}")
    click.echo(f"Volume boost: {settings.volume_boost_db} dB")

    click.echo(f"\nQuick start:  meeting-agent listen --title 'Standup'")


@cli.command()
@click.option("--init", "do_init", is_flag=True, help="Create a starter config file")
@click.option("--path", "show_path", is_flag=True, help="Show active config file path")
@click.option("--show", "show_config", is_flag=True, help="Show current effective settings")
def config(do_init: bool, show_path: bool, show_config: bool):
    """Manage the meeting-agent configuration file."""
    if show_path:
        active = next((p for p in CONFIG_PATHS if p.is_file()), None)
        if active:
            click.echo(active)
        else:
            click.echo("No config file found. Create one with: meeting-agent config --init")
        return

    if show_config:
        click.echo(f"mode:           {settings.mode.value}")
        click.echo(f"llm_provider:   {settings.llm_provider.value}")
        click.echo(f"llm_model:      {settings.llm_model}")
        click.echo(f"llm_temperature: {settings.llm_temperature}")
        click.echo(f"audio_device:   {settings.audio_device}")
        click.echo(f"volume_boost_db: {settings.volume_boost_db}")
        click.echo(f"whisper_model:  {settings.whisper_model}")
        click.echo(f"whisper_device: {settings.whisper_device}")
        click.echo(f"notes_dir:      {settings.notes_dir}")
        click.echo(f"keep_audio:     {settings.keep_audio}")
        click.echo(f"bot_name:       {settings.bot_name}")
        active = next((p for p in CONFIG_PATHS if p.is_file()), None)
        click.echo(f"\nConfig file:    {active or 'none'}")
        return

    if do_init:
        target = CONFIG_PATHS[1]  # ~/.config/meeting-agent/config.toml
        if target.exists():
            click.echo(f"Config file already exists: {target}")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_STARTER_CONFIG)
        click.echo(f"Created config file: {target}")
        click.echo("Edit it with your preferred settings, then re-run meeting-agent.")
        return

    # No flags: show help
    ctx = click.get_current_context()
    click.echo(ctx.get_help())


_STARTER_CONFIG = """\
# Meeting Agent configuration
# Docs: https://github.com/mkarvan/meeting-agent#configuration
# Priority: CLI flags > env vars > this file > defaults

[audio]
# device = ":0"                  # macOS: BlackHole device index
# device = "meeting-agent-sink.monitor"  # Linux: PulseAudio virtual sink
# volume_boost_db = 15.0
# chunk_duration = 30
# keep_audio = false

[whisper]
# model = "large-v3-turbo"
# device = "cpu"                 # "cpu" or "cuda"
# compute_type = "int8"

[llm]
# provider = "opencode-go"       # openai, anthropic, opencode-go, ollama, custom
# model = "deepseek-v4-pro"
# temperature = 0.3

# API keys — prefer env vars for secrets, but you can set them here:
# openai_api_key = "sk-..."
# anthropic_api_key = "sk-ant-..."
# opencode_api_key = "..."
# custom_api_key = "..."
# custom_base_url = "http://localhost:8080/v1"

[meeting]
# bot_name = "Meeting Notes Bot"
# mode = "full"                  # full, transcript_only, summary_only
"""


def _apply_settings(mode: str, provider: str, model: str | None, keep_audio: bool, device: str | None = None):
    settings.mode = RunMode(mode)
    settings.llm_provider = LLMProvider(provider)
    if model:
        settings.llm_model = model
    if keep_audio:
        settings.keep_audio = True
    if device:
        settings.audio_device = device


if __name__ == "__main__":
    cli()
