"""Configuration for the meeting agent — supports multiple LLM providers and run modes."""
import os
from pathlib import Path
from enum import Enum
from typing import Optional
from pydantic_settings import BaseSettings


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
    """Agent settings loaded from env vars."""

    # Paths
    project_root: Path = Path("/home/herm/meeting-agent")
    notes_dir: Path = Path("/home/herm/meeting-agent/notes")
    audio_dir: Path = Path("/tmp/meeting-agent-audio")

    # Audio
    sample_rate: int = 16000
    chunk_duration: int = 30
    audio_device: str = "meeting-agent-sink.monitor"
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
    opencode_api_key: Optional[str] = None
    ollama_base_url: str = "http://localhost:11434/v1"
    custom_api_key: Optional[str] = None
    custom_base_url: Optional[str] = None

    # Meeting defaults
    bot_name: str = "Meeting Notes Bot"
    join_muted: bool = True
    join_video_off: bool = True

    def get_llm_config(self) -> dict:
        """Resolve active LLM configuration based on provider."""
        if self.llm_provider == LLMProvider.OPENAI:
            return {
                "api_key": self.openai_api_key or os.environ.get("OPENAI_API_KEY", ""),
                "base_url": self.openai_base_url,
                "model": self.llm_model or "gpt-4o",
            }
        elif self.llm_provider == LLMProvider.ANTHROPIC:
            return {
                "api_key": self.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
                "base_url": "https://api.anthropic.com/v1",
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
                "base_url": self.custom_base_url or "http://localhost:8080/v1",
                "model": self.llm_model or "local-model",
            }
        # Fallback
        return {
            "api_key": os.environ.get("OPENCODE_API_KEY", ""),
            "base_url": "https://opencode.ai/zen/go/v1",
            "model": self.llm_model or "deepseek-v4-pro",
        }

    class Config:
        env_prefix = "MEETING_AGENT_"


settings = Settings()
