# Meeting Agent

An AI agent that joins online meetings, transcribes audio in real-time, and produces structured notes with summaries, action items, and key decisions.

## Features

- **🎙️ Join meetings automatically** — Google Meet, Zoom, Microsoft Teams via browser automation
- **📝 Transcribe locally** — faster-whisper (large-v3-turbo) runs entirely on your machine; audio never leaves it
- **🤖 LLM-powered summaries** — structured notes with key topics, decisions, and action items
- **🔌 Multi-provider** — OpenAI, Anthropic, OpenCode Go, Ollama, or any OpenAI-compatible endpoint
- **🔀 Three run modes** — full (summary + transcript), transcript-only (free, no LLM), summary-only (no transcript saved)
- **🗑️ Privacy-first** — WAV audio chunks deleted immediately after transcription; only text is retained
- **⚙️ Configurable** — CLI flags or environment variables for every setting

## Use Cases

- **Standup / sprint meetings** — auto-capture action items, who said what needs doing
- **Client calls** — full transcripts for compliance, executive summaries for stakeholders
- **Interviews** — searchable transcripts without manual note-taking
- **All-hands / town halls** — key decisions and announcements extracted automatically
- **Research / focus groups** — raw transcripts for qualitative analysis

## Architecture

```
🎙️ Audio → PulseAudio sink → FFmpeg (30s WAV chunks)
                                     ↓
                              🎯 faster-whisper (local STT)
                                     ↓
                              📝 Text transcript (in memory)
                                     ↓                          ┌──────────┐
                        ┌────────────┴────────────┐            │  OpenAI   │
                        │   transcript-only mode   │            │ Anthropic │
                        │     (no LLM, free)       │            │ OpenCode  │
                        └────────────┬────────────┘            │  Ollama   │
                                     │  (full / summary-only)  │  Custom   │
                                     ↓                         └──────────┘
                              🤖 LLM → JSON → Markdown notes
```

## Requirements

- **OS:** Linux with PulseAudio (tested on Linux Mint 22.3 / Ubuntu 24.04)
- **Python:** 3.11+
- **Disk:** ~4 GB for the Whisper model (downloaded on first run)
- **Memory:** 4 GB+ recommended (Whisper large-v3-turbo)
- **Network:** For LLM summarization (not needed for transcript-only mode)

## Installation

```bash
# 1. Clone or enter the project directory
cd /home/herm/meeting-agent

# 2. Install dependencies with uv (recommended)
uv sync

# 3. Install Playwright browser
uv run playwright install chromium

# 4. Pre-download the Whisper model (downloaded automatically on first run if skipped)
uv run python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')"
```

> **Note:** The Whisper model (~3.3 GB) is downloaded from Hugging Face on first use and cached in `~/.cache/huggingface/`. Set `HF_TOKEN` for faster downloads if you have rate-limiting issues.

## Setup

### 1. Audio Sink (one-time)

Create a PulseAudio virtual sink to capture meeting audio:

```bash
uv run meeting-agent setup
```

This creates a virtual sink named `meeting-agent-sink`. Use `pavucontrol` to route your browser's audio into it.

### 2. LLM API Key

For summarization (not required for transcript-only mode):

```bash
# OpenCode Go (default)
export OPENCODE_API_KEY="your-key"

# Or OpenAI
export OPENAI_API_KEY="sk-..."

# Or Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# Or Ollama (local, no key needed)
# Ensure ollama is running: ollama serve
```

## Usage

### Basic

```bash
# Full mode — join a meeting, transcribe, and generate notes
uv run meeting-agent join "https://meet.google.com/abc-defg-hij"

# Custom bot name
uv run meeting-agent join "https://zoom.us/j/123456789" --name "Notes Bot"
```

### Run Modes

```bash
# Transcript only — no LLM call, free, saves raw transcript
uv run meeting-agent join <url> --mode transcript-only

# Summary only — LLM summary + action items, no full transcript saved
uv run meeting-agent join <url> --mode summary-only
```

### LLM Provider

```bash
# Use OpenAI
uv run meeting-agent join <url> --provider openai --model gpt-4o

# Use Anthropic Claude
uv run meeting-agent join <url> --provider anthropic --model claude-sonnet-4-20250514

# Use local Ollama
uv run meeting-agent join <url> --provider ollama --model llama3.1

# Use a custom OpenAI-compatible endpoint
export CUSTOM_API_KEY="your-key"
export CUSTOM_BASE_URL="http://localhost:8080/v1"
uv run meeting-agent join <url> --provider custom --model my-model
```

### Debugging

```bash
# Keep WAV audio files after transcription (for debugging)
uv run meeting-agent join <url> --keep-audio
```

### Output

Meeting notes are saved to `notes/YYYY-MM-DD_HHMM_Title.md` with this structure:

```markdown
# Project Roadmap Review

**Date:** 2026-06-11 | **Time:** 15:30 | **Duration:** 45 min

## Executive Summary
...2-3 paragraph overview...

## Key Topics Discussed
- Q3 OKR planning
- Engineering hiring update

## Decisions Made
- Move launch date to August 1st
- Open 2 senior backend roles

## Action Items
| Assignee | Task | Deadline |
|----------|------|----------|
| Alice | Prepare migration plan | June 18 |
| Bob | Post job descriptions | June 13 |

## Full Transcript
[00:00] Okay, let's get started...
[00:15] First topic: Q3 OKRs...
```

## Configuration

All settings can be set via environment variables (prefixed with `MEETING_AGENT_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `MEETING_AGENT_MODE` | `full` | Run mode: full, transcript_only, summary_only |
| `MEETING_AGENT_LLM_PROVIDER` | `opencode-go` | LLM provider |
| `MEETING_AGENT_LLM_MODEL` | `deepseek-v4-pro` | Model name |
| `MEETING_AGENT_LLM_TEMPERATURE` | `0.3` | LLM temperature |
| `MEETING_AGENT_KEEP_AUDIO` | `false` | Retain WAV files |
| `MEETING_AGENT_BOT_NAME` | `Meeting Notes Bot` | Display name in meetings |
| `MEETING_AGENT_WHISPER_MODEL` | `large-v3-turbo` | Whisper model variant |
| `MEETING_AGENT_CHUNK_DURATION` | `30` | Audio chunk duration in seconds |

## Privacy & Data Retention

- **Audio:** WAV chunks stored in `/tmp/meeting-agent-audio/`, deleted immediately after transcription. Never persisted to disk beyond a few seconds.
- **Text:** Transcript and notes saved to `notes/` directory. Delete manually when no longer needed.
- **LLM:** Only transcribed text (never audio) is sent to the LLM provider. Provider data policies apply.
- **Local mode:** Use `--mode transcript-only` to keep everything on your machine with zero API calls.

## Limitations

- **Platform UI changes** — Google Meet, Zoom, and Teams change their DOM frequently. Join flows may need updates.
- **Audio routing** — You must route browser audio into the virtual sink (use `pavucontrol`).
- **Speaker diarization** — Does not identify "who said what" (planned for v0.2).
- **No calendar integration** — Meeting URLs must be provided manually (calendar integration planned).

## License

MIT
