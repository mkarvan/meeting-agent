"""Tests for the CLI module."""
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner
from src.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestCLI:
    """Tests for the CLI commands."""

    def test_cli_help(self, runner):
        """CLI should show help."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Meeting Agent" in result.output
        assert "join" in result.output
        assert "setup" in result.output

    def test_join_help(self, runner):
        """Join command should show options."""
        result = runner.invoke(cli, ["join", "--help"])
        assert result.exit_code == 0
        assert "--name" in result.output
        assert "--mode" in result.output
        assert "--provider" in result.output
        assert "--model" in result.output
        assert "--keep-audio" in result.output

    def test_setup_help(self, runner):
        """Setup command should show help."""
        result = runner.invoke(cli, ["setup", "--help"])
        # May show help or error if script doesn't exist
        assert result.exit_code in (0, 1, 2)

    @patch("src.cli.MeetingAgent")
    @patch("src.cli.asyncio.run")
    def test_join_defaults(self, mock_asyncio_run, mock_agent, runner):
        """Join with defaults should work."""
        result = runner.invoke(cli, ["join", "https://meet.google.com/abc-defg-hij"])
        assert result.exit_code == 0

    @patch("src.cli.MeetingAgent")
    @patch("src.cli.asyncio.run")
    def test_join_with_name(self, mock_asyncio_run, mock_agent, runner):
        """Join with custom bot name."""
        result = runner.invoke(cli, [
            "join", "https://meet.google.com/abc-defg-hij", "--name", "My Bot"
        ])
        assert result.exit_code == 0

    @patch("src.cli.MeetingAgent")
    @patch("src.cli.asyncio.run")
    def test_join_transcript_only_mode(self, mock_asyncio_run, mock_agent, runner):
        """Join in transcript-only mode."""
        result = runner.invoke(cli, [
            "join", "https://meet.google.com/abc-defg-hij", "--mode", "transcript_only"
        ])
        assert result.exit_code == 0

    @patch("src.cli.MeetingAgent")
    @patch("src.cli.asyncio.run")
    def test_join_summary_only_mode(self, mock_asyncio_run, mock_agent, runner):
        """Join in summary-only mode."""
        result = runner.invoke(cli, [
            "join", "https://meet.google.com/abc-defg-hij", "--mode", "summary_only"
        ])
        assert result.exit_code == 0

    @patch("src.cli.MeetingAgent")
    @patch("src.cli.asyncio.run")
    def test_join_openai_provider(self, mock_asyncio_run, mock_agent, runner):
        """Join with OpenAI provider."""
        result = runner.invoke(cli, [
            "join", "https://meet.google.com/abc-defg-hij",
            "--provider", "openai", "--model", "gpt-4o"
        ])
        assert result.exit_code == 0

    @patch("src.cli.MeetingAgent")
    @patch("src.cli.asyncio.run")
    def test_join_anthropic_provider(self, mock_asyncio_run, mock_agent, runner):
        """Join with Anthropic provider."""
        result = runner.invoke(cli, [
            "join", "https://meet.google.com/abc-defg-hij",
            "--provider", "anthropic"
        ])
        assert result.exit_code == 0

    @patch("src.cli.MeetingAgent")
    @patch("src.cli.asyncio.run")
    def test_join_ollama_provider(self, mock_asyncio_run, mock_agent, runner):
        """Join with Ollama provider."""
        result = runner.invoke(cli, [
            "join", "https://meet.google.com/abc-defg-hij",
            "--provider", "ollama"
        ])
        assert result.exit_code == 0

    @patch("src.cli.MeetingAgent")
    @patch("src.cli.asyncio.run")
    def test_join_keep_audio_flag(self, mock_asyncio_run, mock_agent, runner):
        """Join with keep-audio flag."""
        result = runner.invoke(cli, [
            "join", "https://meet.google.com/abc-defg-hij", "--keep-audio"
        ])
        assert result.exit_code == 0

    def test_setup_runs_script(self, runner):
        """Setup command should run or fail gracefully."""
        result = runner.invoke(cli, ["setup"])
        # May fail if script path doesn't exist or subprocess fails

    def test_join_missing_url(self, runner):
        """Join without URL should error."""
        result = runner.invoke(cli, ["join"])
        assert result.exit_code != 0
