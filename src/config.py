"""Configuration for the meeting agent — supports multiple LLM providers and run modes.

Priority: CLI flags > env vars > config file > defaults.
Config file locations (first found wins):
  1. .meeting-agent.toml  (project-local)
  2. ~/.config/meeting-agent/config.toml
"""
import os
import platform
import tomllib
from pathlib import Path
from enum import Enum
from typing import Any, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

_IS_MACOS = platform.system() == "Darwin"

CONFIG_PATHS = [
    Path(".meeting-agent.toml"),
    Path.home() / ".config" / "meeting-agent" / "config.toml",
]


def _load_config_file() -> dict[str, Any]:
    """Load the first config file found, or return empty dict."""
    for path in CONFIG_PATHS:
        if path.is_file():
            try:
                with open(path, "rb") as f:
                    return tomllib.load(f)
            except tomllib.TOMLDecodeError as e:
                import sys
                print(f"Warning: invalid config file {path}: {e}", file=sys.stderr)
                return {}
    return {}


def _flatten_toml(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested TOML sections into dot-free keys matching Settings fields.

    E.g. {"llm": {"provider": "openai"}} -> {"llm_provider": "openai"}
    """
    flat: dict[str, Any] = {}
    for key, value in data.items():
        full_key = f"{prefix}_{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten_toml(value, full_key))
        else:
            flat[full_key] = value
    return flat


class RunMode(str, Enum):
    FULL = "full"
    TRANSCRIPT_ONLY = "transcript_only"
    SUMMARY_ONLY = "summary_only"


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENCODE_GO = "opencode-go"
    OLLAMA = "ollama"
    CUSTOM = "custom"


class Settings(BaseSettings):
    """Agent settings loaded from config file, env vars, or CLI flags."""

    # Paths
    project_root: Path = Path(__file__).resolve().parent.parent  # repo root
    notes_dir: Path = Path("notes")   # resolved relative to project_root below
    audio_dir: Path = Path("/tmp/meeting-agent-audio")

    # Audio
    sample_rate: int = 16000
    chunk_duration: int = 30
    audio_device: str = ":0" if _IS_MACOS else "meeting-agent-sink.monitor"
    volume_boost_db: float = 15.0
    keep_audio: bool = False

    # Whisper
    whisper_model: str = "large-v3-turbo"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # Run mode
    mode: RunMode = RunMode.FULL

    # LLM — provider-agnostic
    llm_provider: LLMProvider = LLMProvider.OPENCODE_GO
    llm_model: str = "deepseek-v4-pro"
    llm_temperature: float = 0.3

    # Provider-specific settings
    openai_api_key: Optional[str] = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: Optional[str] = None
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    opencode_api_key: Optional[str] = None
    ollama_base_url: str = "http://localhost:11434/v1"
    custom_api_key: Optional[str] = None
    custom_base_url: Optional[str] = None

    # Meeting defaults
    bot_name: str = "Meeting Notes Bot"
    join_muted: bool = True
    join_video_off: bool = True

    # Browser automation
    chrome_user_data_dir: Optional[str] = None
    virtual_display: bool = True
    # "auto" tries system Chrome → system Chromium → Playwright bundled Chromium.
    # Set to "" to always use the bundled Playwright Chromium (no system Chrome needed).
    chrome_channel: str = "auto"

    def get_llm_config(self) -> dict:
        """Resolve active LLM configuration based on provider."""
        if self.llm_provider == LLMProvider.OPENAI:
            return {
                "api_key": self.openai_api_key or os.environ.get("OPENAI_API_KEY", ""),
                "base_url": self.openai_base_url,
                "model": self.llm_model or "gpt-4o",
            }
        elif self.llm_provider == LLMProvider.ANTHROPIC:
            # Anthropic's native API is not OpenAI-compatible.
            # To use Anthropic, point an OpenAI-compatible proxy (e.g. LiteLLM)
            # at your proxy URL and set anthropic_base_url accordingly.
            return {
                "api_key": self.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
                "base_url": self.anthropic_base_url,
                "model": self.llm_model or "claude-sonnet-4-20250514",
            }
        elif self.llm_provider == LLMProvider.OPENCODE_GO:
            return {
                "api_key": self.opencode_api_key or os.environ.get("OPENCODE_API_KEY", ""),
                "base_url": "https://opencode.ai/zen/go/v1",
                "model": self.llm_model or "deepseek-v4-pro",
            }
        elif self.llm_provider == LLMProvider.OLLAMA:
            return {
                "api_key": "ollama",
                "base_url": self.ollama_base_url,
                "model": self.llm_model or "llama3.1",
            }
        elif self.llm_provider == LLMProvider.CUSTOM:
            return {
                "api_key": self.custom_api_key or os.environ.get("CUSTOM_API_KEY", ""),
                "base_url": self.custom_base_url or os.environ.get("CUSTOM_BASE_URL", "http://localhost:8080/v1"),
                "model": self.llm_model or "local-model",
            }
        # Fallback
        return {
            "api_key": os.environ.get("OPENCODE_API_KEY", ""),
            "base_url": "https://opencode.ai/zen/go/v1",
            "model": self.llm_model or "deepseek-v4-pro",
        }

    def model_post_init(self, __context) -> None:
        """Resolve relative paths against project_root."""
        if not self.notes_dir.is_absolute():
            object.__setattr__(self, 'notes_dir', (self.project_root / self.notes_dir).resolve())

    model_config = SettingsConfigDict(env_prefix="MEETING_AGENT_")


def _build_settings() -> Settings:
    """Build Settings with config-file values as defaults (env vars override)."""
    file_config = _flatten_toml(_load_config_file())
    try:
        if file_config:
            return Settings(**file_config)
        return Settings()
    except Exception as e:
        import sys
        from pydantic import ValidationError
        if isinstance(e, ValidationError):
            print(f"Warning: invalid configuration — {e}", file=sys.stderr)
        else:
            print(f"Warning: invalid configuration: {e}", file=sys.stderr)
        print("Falling back to defaults.", file=sys.stderr)
        return Settings()


settings = _build_settings()
