"""User-facing error types with actionable messages."""
import platform

_IS_MACOS = platform.system() == "Darwin"


class MeetingAgentError(Exception):
    """Base for all user-facing errors. The message should be human-readable."""


class AudioError(MeetingAgentError):
    """Audio capture or device problems."""


class TranscriberError(MeetingAgentError):
    """Whisper model loading or transcription failures."""


class BrowserError(MeetingAgentError):
    """Playwright / Chromium problems."""


class LLMError(MeetingAgentError):
    """LLM API call failures."""


class ConfigError(MeetingAgentError):
    """Invalid configuration."""


def ffmpeg_not_found() -> AudioError:
    if _IS_MACOS:
        return AudioError("FFmpeg not found. Install it: brew install ffmpeg")
    return AudioError("FFmpeg not found. Install it: sudo apt install ffmpeg")


def audio_device_error(device: str, detail: str = "") -> AudioError:
    hint = detail + "\n" if detail else ""
    if _IS_MACOS:
        hint += (
            f"Device '{device}' is not available.\n"
            "List devices: ffmpeg -f avfoundation -list_devices true -i ''\n"
            "Common fix: install BlackHole (brew install blackhole-2ch) and use --device ':0'"
        )
    else:
        hint += (
            f"Device '{device}' is not available.\n"
            "List devices: pactl list sources short\n"
            "Common fix: run 'meeting-agent setup' then use pavucontrol to route audio"
        )
    return AudioError(hint)


def whisper_load_error(detail: str) -> TranscriberError:
    return TranscriberError(
        f"Failed to load Whisper model: {detail}\n"
        "Try: rm -rf ~/.cache/huggingface/hub && uv run meeting-agent listen --title test"
    )


def chromium_not_found() -> BrowserError:
    return BrowserError(
        "Playwright Chromium not installed.\n"
        "Install it: uv run playwright install chromium"
    )


def llm_credentials_missing(provider: str) -> LLMError:
    env_hints = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "opencode-go": "OPENCODE_API_KEY",
        "custom": "CUSTOM_API_KEY",
    }
    env_var = env_hints.get(provider, "the appropriate API key env var")
    return LLMError(
        f"No API key configured for provider '{provider}'.\n"
        f"Set it via: export {env_var}=your-key\n"
        "Or add it to ~/.config/meeting-agent/config.toml under [llm]\n"
        "Or use --mode transcript_only to skip LLM summarization"
    )


def llm_api_error(detail: str) -> LLMError:
    return LLMError(f"LLM API request failed: {detail}")
