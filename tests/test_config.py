"""Unit tests for config.py — RunMode, LLMProvider, Settings, get_llm_config()."""

import os
import pytest
from pathlib import Path

from src.config import RunMode, LLMProvider, Settings


# ── RunMode enum ────────────────────────────────────────────────────────────

class TestRunMode:
    def test_values(self):
        assert RunMode.FULL.value == "full"
        assert RunMode.TRANSCRIPT_ONLY.value == "transcript_only"
        assert RunMode.SUMMARY_ONLY.value == "summary_only"

    def test_membership(self):
        """All expected members are present."""
        members = set(RunMode)
        assert members == {RunMode.FULL, RunMode.TRANSCRIPT_ONLY, RunMode.SUMMARY_ONLY}

    def test_str_enum(self):
        """RunMode is a string enum so it compares naturally with strings."""
        assert RunMode.FULL == "full"
        assert RunMode("full") == RunMode.FULL


# ── LLMProvider enum ────────────────────────────────────────────────────────

class TestLLMProvider:
    def test_values(self):
        assert LLMProvider.OPENAI.value == "openai"
        assert LLMProvider.ANTHROPIC.value == "anthropic"
        assert LLMProvider.OPENCODE_GO.value == "opencode-go"
        assert LLMProvider.OLLAMA.value == "ollama"
        assert LLMProvider.CUSTOM.value == "custom"

    def test_membership(self):
        members = set(LLMProvider)
        assert members == {
            LLMProvider.OPENAI,
            LLMProvider.ANTHROPIC,
            LLMProvider.OPENCODE_GO,
            LLMProvider.OLLAMA,
            LLMProvider.CUSTOM,
        }

    def test_str_enum(self):
        assert LLMProvider.OPENAI == "openai"
        assert LLMProvider("opencode-go") == LLMProvider.OPENCODE_GO


# ── Settings defaults ───────────────────────────────────────────────────────

class TestSettingsDefaults:
    """Verify every field has the expected default value."""

    def test_path_defaults(self):
        s = Settings()
        # project_root is auto-detected from __file__
        assert s.project_root.name == "meeting-agent"
        # notes_dir is resolved to project_root/notes by model_post_init
        assert s.notes_dir.name == "notes"
        assert s.notes_dir.parent == s.project_root
        assert s.audio_dir == Path("/tmp/meeting-agent-audio")

    def test_audio_defaults(self):
        s = Settings()
        assert s.sample_rate == 16000
        assert s.chunk_duration == 30
        # Default audio_device varies by platform
        import platform
        if platform.system() == "Darwin":
            assert s.audio_device == ":0"
        else:
            assert s.audio_device == "meeting-agent-sink.monitor"
        assert s.volume_boost_db == 15.0
        assert s.keep_audio is False

    def test_whisper_defaults(self):
        s = Settings()
        assert s.whisper_model == "large-v3-turbo"
        assert s.whisper_device == "cpu"
        assert s.whisper_compute_type == "int8"

    def test_mode_default(self):
        s = Settings()
        assert s.mode == RunMode.FULL

    def test_llm_defaults(self):
        s = Settings()
        assert s.llm_provider == LLMProvider.OPENCODE_GO
        assert s.llm_model == "deepseek-v4-pro"
        assert s.llm_temperature == 0.3

    def test_provider_specific_defaults(self):
        s = Settings()
        assert s.openai_api_key is None
        assert s.openai_base_url == "https://api.openai.com/v1"
        assert s.anthropic_api_key is None
        assert s.opencode_api_key is None
        assert s.ollama_base_url == "http://localhost:11434/v1"
        assert s.custom_api_key is None
        assert s.custom_base_url is None

    def test_meeting_defaults(self):
        s = Settings()
        assert s.bot_name == "Meeting Notes Bot"
        assert s.join_muted is True
        assert s.join_video_off is True

    def test_env_prefix(self):
        assert Settings.model_config["env_prefix"] == "MEETING_AGENT_"


# ── get_llm_config() ────────────────────────────────────────────────────────

class TestGetLLMConfig:
    """Cover get_llm_config() for every provider."""

    def test_openai(self):
        s = Settings(
            llm_provider=LLMProvider.OPENAI,
            openai_api_key="sk-test",
            llm_model="gpt-4o-mini",
        )
        cfg = s.get_llm_config()
        assert cfg["api_key"] == "sk-test"
        assert cfg["base_url"] == "https://api.openai.com/v1"
        assert cfg["model"] == "gpt-4o-mini"

    def test_openai_fallback_model(self):
        """When llm_model is empty, fallback to gpt-4o."""
        s = Settings(llm_provider=LLMProvider.OPENAI, llm_model="")
        cfg = s.get_llm_config()
        assert cfg["model"] == "gpt-4o"

    def test_openai_env_fallback(self, monkeypatch):
        """api_key falls back to OPENAI_API_KEY env var."""
        monkeypatch.setenv("OPENAI_API_KEY", "env-key-openai")
        s = Settings(llm_provider=LLMProvider.OPENAI, openai_api_key=None)
        cfg = s.get_llm_config()
        assert cfg["api_key"] == "env-key-openai"

    def test_anthropic(self):
        s = Settings(
            llm_provider=LLMProvider.ANTHROPIC,
            anthropic_api_key="ant-key",
            llm_model="claude-opus",
        )
        cfg = s.get_llm_config()
        assert cfg["api_key"] == "ant-key"
        assert cfg["base_url"] == "https://api.anthropic.com/v1"
        assert cfg["model"] == "claude-opus"

    def test_anthropic_fallback_model(self):
        s = Settings(llm_provider=LLMProvider.ANTHROPIC, llm_model="")
        cfg = s.get_llm_config()
        assert cfg["model"] == "claude-sonnet-4-20250514"

    def test_anthropic_env_fallback(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-ant-key")
        s = Settings(llm_provider=LLMProvider.ANTHROPIC, anthropic_api_key=None)
        cfg = s.get_llm_config()
        assert cfg["api_key"] == "env-ant-key"

    def test_opencode_go(self):
        s = Settings(
            llm_provider=LLMProvider.OPENCODE_GO,
            opencode_api_key="oc-key",
            llm_model="custom-model",
        )
        cfg = s.get_llm_config()
        assert cfg["api_key"] == "oc-key"
        assert cfg["base_url"] == "https://opencode.ai/zen/go/v1"
        assert cfg["model"] == "custom-model"

    def test_opencode_go_fallback_model(self):
        s = Settings(llm_provider=LLMProvider.OPENCODE_GO, llm_model="")
        cfg = s.get_llm_config()
        assert cfg["model"] == "deepseek-v4-pro"

    def test_opencode_go_env_fallback(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", "env-oc-key")
        s = Settings(llm_provider=LLMProvider.OPENCODE_GO, opencode_api_key=None)
        cfg = s.get_llm_config()
        assert cfg["api_key"] == "env-oc-key"

    def test_ollama(self):
        s = Settings(
            llm_provider=LLMProvider.OLLAMA,
            ollama_base_url="http://ollama:11434/v1",
            llm_model="mistral",
        )
        cfg = s.get_llm_config()
        assert cfg["api_key"] == "ollama"  # hardcoded
        assert cfg["base_url"] == "http://ollama:11434/v1"
        assert cfg["model"] == "mistral"

    def test_ollama_fallback_model(self):
        s = Settings(llm_provider=LLMProvider.OLLAMA, llm_model="")
        cfg = s.get_llm_config()
        assert cfg["model"] == "llama3.1"

    def test_custom(self):
        s = Settings(
            llm_provider=LLMProvider.CUSTOM,
            custom_api_key="cust-key",
            custom_base_url="https://my-llm.example.com/v1",
            llm_model="my-model",
        )
        cfg = s.get_llm_config()
        assert cfg["api_key"] == "cust-key"
        assert cfg["base_url"] == "https://my-llm.example.com/v1"
        assert cfg["model"] == "my-model"

    def test_custom_fallback_model(self):
        s = Settings(llm_provider=LLMProvider.CUSTOM, llm_model="")
        cfg = s.get_llm_config()
        assert cfg["model"] == "local-model"

    def test_custom_fallback_base_url(self):
        """When custom_base_url is None, fallback to localhost."""
        s = Settings(
            llm_provider=LLMProvider.CUSTOM,
            custom_api_key="k",
            custom_base_url=None,
        )
        cfg = s.get_llm_config()
        assert cfg["base_url"] == "http://localhost:8080/v1"

    def test_custom_env_fallback(self, monkeypatch):
        monkeypatch.setenv("CUSTOM_API_KEY", "env-cust-key")
        s = Settings(llm_provider=LLMProvider.CUSTOM, custom_api_key=None)
        cfg = s.get_llm_config()
        assert cfg["api_key"] == "env-cust-key"

    @pytest.mark.parametrize("provider,expected_model", [
        (LLMProvider.OPENAI, "gpt-4o"),
        (LLMProvider.ANTHROPIC, "claude-sonnet-4-20250514"),
        (LLMProvider.OPENCODE_GO, "deepseek-v4-pro"),
        (LLMProvider.OLLAMA, "llama3.1"),
        (LLMProvider.CUSTOM, "local-model"),
    ])
    def test_fallback_models_parameterized(self, provider, expected_model):
        """Every provider falls back when llm_model is empty."""
        s = Settings(llm_provider=provider, llm_model="")
        cfg = s.get_llm_config()
        assert cfg["model"] == expected_model


# ── Env var overrides ───────────────────────────────────────────────────────

class TestEnvVarOverrides:
    """Settings should be overridable via MEETING_AGENT_* env vars."""

    def test_mode_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_MODE", "transcript_only")
        s = Settings()
        assert s.mode == RunMode.TRANSCRIPT_ONLY

    def test_llm_provider_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_LLM_PROVIDER", "ollama")
        s = Settings()
        assert s.llm_provider == LLMProvider.OLLAMA

    def test_llm_model_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_LLM_MODEL", "gpt-5")
        s = Settings()
        assert s.llm_model == "gpt-5"

    def test_llm_temperature_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_LLM_TEMPERATURE", "0.7")
        s = Settings()
        assert s.llm_temperature == 0.7

    def test_sample_rate_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_SAMPLE_RATE", "48000")
        s = Settings()
        assert s.sample_rate == 48000

    def test_chunk_duration_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_CHUNK_DURATION", "60")
        s = Settings()
        assert s.chunk_duration == 60

    def test_whisper_model_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_WHISPER_MODEL", "tiny")
        s = Settings()
        assert s.whisper_model == "tiny"

    def test_openai_api_key_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_OPENAI_API_KEY", "env-sk")
        s = Settings()
        assert s.openai_api_key == "env-sk"

    def test_anthropic_api_key_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_ANTHROPIC_API_KEY", "env-ant")
        s = Settings()
        assert s.anthropic_api_key == "env-ant"

    def test_opencode_api_key_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_OPENCODE_API_KEY", "env-oc")
        s = Settings()
        assert s.opencode_api_key == "env-oc"

    def test_ollama_base_url_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_OLLAMA_BASE_URL", "http://gpu:11434/v1")
        s = Settings()
        assert s.ollama_base_url == "http://gpu:11434/v1"

    def test_custom_api_key_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_CUSTOM_API_KEY", "env-cust")
        s = Settings()
        assert s.custom_api_key == "env-cust"

    def test_custom_base_url_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_CUSTOM_BASE_URL", "https://llm.mycorp.com")
        s = Settings()
        assert s.custom_base_url == "https://llm.mycorp.com"

    def test_audio_device_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_AUDIO_DEVICE", "custom-sink.monitor")
        s = Settings()
        assert s.audio_device == "custom-sink.monitor"

    def test_bot_name_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_BOT_NAME", "Zoom Notes Bot")
        s = Settings()
        assert s.bot_name == "Zoom Notes Bot"

    def test_join_muted_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_JOIN_MUTED", "false")
        s = Settings()
        assert s.join_muted is False

    def test_join_video_off_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_JOIN_VIDEO_OFF", "false")
        s = Settings()
        assert s.join_video_off is False

    def test_project_root_override(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_PROJECT_ROOT", "/custom/path")
        s = Settings()
        assert s.project_root == Path("/custom/path")


# ── keep_audio flag ─────────────────────────────────────────────────────────

class TestKeepAudio:
    def test_default_false(self):
        s = Settings()
        assert s.keep_audio is False

    def test_override_true(self):
        s = Settings(keep_audio=True)
        assert s.keep_audio is True

    def test_env_override_true(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_KEEP_AUDIO", "true")
        s = Settings()
        assert s.keep_audio is True

    def test_env_override_false(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_KEEP_AUDIO", "false")
        s = Settings()
        assert s.keep_audio is False


# ── Mode switching ──────────────────────────────────────────────────────────

class TestModeSwitching:
    """Verify mode can be switched via constructor and env var."""

    def test_constructor_full(self):
        s = Settings(mode=RunMode.FULL)
        assert s.mode == RunMode.FULL

    def test_constructor_transcript_only(self):
        s = Settings(mode=RunMode.TRANSCRIPT_ONLY)
        assert s.mode == RunMode.TRANSCRIPT_ONLY

    def test_constructor_summary_only(self):
        s = Settings(mode=RunMode.SUMMARY_ONLY)
        assert s.mode == RunMode.SUMMARY_ONLY

    def test_env_full(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_MODE", "full")
        s = Settings()
        assert s.mode == RunMode.FULL

    def test_env_transcript_only(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_MODE", "transcript_only")
        s = Settings()
        assert s.mode == RunMode.TRANSCRIPT_ONLY

    def test_env_summary_only(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_MODE", "summary_only")
        s = Settings()
        assert s.mode == RunMode.SUMMARY_ONLY

    def test_env_invalid_mode_raises(self, monkeypatch):
        monkeypatch.setenv("MEETING_AGENT_MODE", "invalid_mode")
        with pytest.raises(ValueError):
            Settings()


# ── Edge cases ──────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_extra_fields_ignored(self):
        """pydantic ignores extra fields by default for BaseSettings."""
        s = Settings()  # no extra fields
        assert s.mode == RunMode.FULL

    def test_multiple_env_overrides(self, monkeypatch):
        """Many env vars can be set simultaneously."""
        monkeypatch.setenv("MEETING_AGENT_MODE", "summary_only")
        monkeypatch.setenv("MEETING_AGENT_LLM_PROVIDER", "openai")
        monkeypatch.setenv("MEETING_AGENT_LLM_MODEL", "gpt-4o-mini")
        monkeypatch.setenv("MEETING_AGENT_OPENAI_API_KEY", "multi-key")
        s = Settings()
        assert s.mode == RunMode.SUMMARY_ONLY
        assert s.llm_provider == LLMProvider.OPENAI
        assert s.llm_model == "gpt-4o-mini"
        assert s.openai_api_key == "multi-key"

    def test_constructor_overrides_env(self, monkeypatch):
        """Explicit constructor args take precedence over env vars."""
        monkeypatch.setenv("MEETING_AGENT_MODE", "transcript_only")
        s = Settings(mode=RunMode.SUMMARY_ONLY)
        assert s.mode == RunMode.SUMMARY_ONLY

    def test_get_llm_config_returns_keys(self):
        """Every config dict has the expected keys."""
        s = Settings(llm_provider=LLMProvider.OPENAI)
        cfg = s.get_llm_config()
        assert set(cfg.keys()) == {"api_key", "base_url", "model"}

    def test_env_prefix_isolated(self, monkeypatch):
        """Env vars without the prefix should not affect settings."""
        monkeypatch.setenv("MODE", "transcript_only")  # no prefix!
        s = Settings()
        assert s.mode == RunMode.FULL  # default — not overridden
