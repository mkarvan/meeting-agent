# Meeting Agent

An AI agent that joins online meetings, transcribes audio in real-time, and produces structured notes with summaries, action items, and key decisions.

## Features

- **Join meetings automatically** — Google Meet, Zoom, Microsoft Teams via browser automation (Webex URLs are parsed but auto-join is not yet supported)
- **Transcribe locally** — faster-whisper (large-v3-turbo) runs entirely on your machine; audio never leaves it
- **LLM-powered summaries** — structured notes with key topics, decisions, and action items
- **Multi-provider** — OpenAI, Anthropic, OpenCode Go, Ollama, or any OpenAI-compatible endpoint
- **Three run modes** — full (summary + transcript), transcript_only (free, no LLM), summary_only (no transcript saved)
- **Privacy-first** — WAV audio chunks deleted immediately after transcription; only text is retained
- **Configurable** — CLI flags, environment variables, or TOML config file for every setting
- **Cross-platform** — Linux (PulseAudio + Xvfb), macOS (BlackHole/AVFoundation), Windows

## Use Cases

- **Standup / sprint meetings** — auto-capture action items, who said what needs doing
- **Client calls** — full transcripts for compliance, executive summaries for stakeholders
- **Interviews** — searchable transcripts without manual note-taking
- **All-hands / town halls** — key decisions and announcements extracted automatically
- **Research / focus groups** — raw transcripts for qualitative analysis

## Architecture

```
Audio -> PulseAudio/AVFoundation -> FFmpeg (30s WAV chunks)
                     |
              faster-whisper (local STT)
                     |
              Text transcript (in memory)
                     |                          +----------+
            +--------+--------+                 |  OpenAI  |
            | transcript_only |                 | Anthropic|
            |  (no LLM, free) |                 | OpenCode |
            +--------+--------+                 |  Ollama  |
                     |  (full / summary_only)   |  Custom  |
                     v                          +----------+
              LLM -> JSON -> Markdown notes
```

## Requirements

- **OS:** Linux (PulseAudio), macOS 12+ (BlackHole), or Windows
- **Python:** 3.11+
- **Disk:** ~4 GB for the Whisper model (downloaded on first run)
- **Memory:** 4 GB+ recommended (Whisper large-v3-turbo)
- **Network:** For LLM summarization (not needed for transcript_only mode)

## Installation

```bash
# 1. Clone and enter the project
git clone https://github.com/mkarvan/meeting-agent.git
cd meeting-agent

# 2. Install dependencies with uv (recommended)
uv sync

# 3. Install Playwright browser
uv run playwright install chromium

# 4. Pre-download the Whisper model (downloaded automatically on first run if skipped)
uv run python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')"
```

> **Note:** The Whisper model (~3.3 GB) is downloaded from Hugging Face on first use and cached in `~/.cache/huggingface/`. Set `HF_TOKEN` for faster downloads if you have rate-limiting issues.

### Linux headless (CI / Docker / SSH servers)

If you run on a Linux server with no display (no `$DISPLAY`), the browser needs Xvfb to avoid automation fingerprints. Install the extra:

```bash
# System package
sudo apt-get install xvfb

# Python package
pip install 'meeting-agent[linux]'
# or with uv:
uv add pyvirtualdisplay
```

Xvfb is started automatically when `$DISPLAY` is not set. On macOS and Windows, or on a Linux desktop, it is never used.

## Setup

### 1. Audio Capture (one-time)

**Linux:**
Create a PulseAudio virtual sink to capture meeting audio:

```bash
uv run meeting-agent setup
```

This creates a virtual sink named `meeting-agent-sink`. Use `pavucontrol` to route your browser's audio into it.

**macOS:**
Install BlackHole and create a Multi-Output Device:

```bash
# Option 1: Show setup instructions
uv run meeting-agent setup

# Option 2: Auto-install BlackHole via Homebrew + show instructions
bash scripts/setup-audio-macos.sh
```

Then open **Audio MIDI Setup**, create a Multi-Output Device with both BlackHole 2ch and your speakers/headphones, and set it as your output.

### 2. Choosing an Audio Device

You can capture from any audio device with the `--device` / `-d` flag:

```bash
# Linux: capture from the virtual sink (default)
uv run meeting-agent listen --title "Standup"

# Linux: capture from headphones/speakers directly
uv run meeting-agent listen --title "Standup" --device @DEFAULT_SINK@.monitor

# Linux: capture from a specific hardware device
uv run meeting-agent listen --title "Standup" --device alsa_output.pci-0000_00_1f.3.analog-stereo.monitor

# macOS: capture from BlackHole (default)
uv run meeting-agent listen --title "Standup" --device ':0'

# macOS: list available devices
ffmpeg -f avfoundation -list_devices true -i ''
```

### 3. LLM API Key

For summarization (not required for transcript_only mode):

```bash
# OpenCode Go (default)
export OPENCODE_API_KEY="your-key"

# Or OpenAI
export OPENAI_API_KEY="sk-..."

# Or Anthropic (requires an OpenAI-compatible proxy — see note below)
export ANTHROPIC_API_KEY="***"

# Or Ollama (local, no key needed)
# Ensure ollama is running: ollama serve
```

## Usage

### Listen Mode (recommended for Google Meet)

Capture audio from a meeting you join yourself. Works with any meeting platform since it captures system audio directly:

```bash
# Transcript only — no LLM call, free, saves raw transcript
uv run meeting-agent listen --title "Standup"

# Full mode — transcript + LLM-generated summary
uv run meeting-agent listen --title "Standup" --mode full

# Summary only — LLM summary, no full transcript saved
uv run meeting-agent listen --title "Standup" --mode summary_only --provider openai --model gpt-4o
```

### Join Mode (browser automation)

Automatically join a meeting via browser and take notes. The browser launches in headed mode with stealth patches applied. On Linux headless servers, Xvfb is started automatically.

```bash
# Zoom — standard /j/ URL is rewritten to the web client automatically
uv run meeting-agent join "https://zoom.us/j/123456789?pwd=abc"

# Microsoft Teams — anonymous guest join works without a Microsoft account
uv run meeting-agent join "https://teams.microsoft.com/l/meetup-join/..."

# Custom bot name and title
uv run meeting-agent join "https://zoom.us/j/123456789" --name "Notes Bot" --title "Sprint Review"

# Google Meet — works best with a pre-authenticated Chrome profile (see below)
uv run meeting-agent join "https://meet.google.com/abc-defg-hij" --chrome-profile ~/.meeting-agent-chrome
```

#### Google Meet and `--chrome-profile`

Google Meet requires a signed-in Google account for reliable joining — anonymous guest access is increasingly restricted. The `--chrome-profile` flag points to a Chrome user data directory that already has a Google account authenticated:

```bash
# Step 1: create the profile directory and sign in to Google (one-time setup)
chromium --user-data-dir=~/.meeting-agent-chrome
# → sign in to your Google account, then close Chrome

# Step 2: use the profile for all subsequent joins
uv run meeting-agent join "https://meet.google.com/abc-defg-hij" \
  --chrome-profile ~/.meeting-agent-chrome \
  --name "Meeting Notes Bot"
```

You can also set it permanently in the config file:

```toml
[meeting]
chrome_user_data_dir = "/home/you/.meeting-agent-chrome"
```

If you prefer not to set up a Chrome profile, use `listen` mode and join Google Meet manually — it captures audio from any meeting regardless of how you joined.

#### How bot detection is avoided

| Signal | Mitigation |
|--------|-----------|
| `navigator.webdriver` | Patched by playwright-stealth |
| CDP connection traces | `headless=False` — browser runs in a real window |
| Fake media devices | Real virtual audio devices used (no `--use-fake-device-for-media-stream`) |
| No X display (Linux) | Xvfb virtual display via pyvirtualdisplay |
| No persistent session | `--chrome-profile` reuses real browser cookies |

#### Zoom web client

The Zoom Meeting SDK is a native C++ library with no Python bindings. The correct approach for Python is Zoom's web client (`zoom.us/wc/join/MEETING_ID`), which is Zoom's own browser-based joining path — identical to what human guests use. The agent automatically rewrites standard `/j/` links to the web client URL to skip the "Open Zoom?" native-app interstitial, preserving any password parameters.

```
https://zoom.us/j/123456789?pwd=abc  →  https://zoom.us/wc/join/123456789?pwd=abc
```

### Run Modes

```bash
# Transcript only — no LLM call, free, saves raw transcript
uv run meeting-agent listen --title "Meeting" --mode transcript_only

# Full — transcript + LLM summary with action items
uv run meeting-agent listen --title "Meeting" --mode full

# Summary only — LLM summary + action items, no full transcript saved
uv run meeting-agent listen --title "Meeting" --mode summary_only
```

### LLM Provider

```bash
# Use OpenAI
uv run meeting-agent listen --title "Meeting" --mode full --provider openai --model gpt-4o

# Use Anthropic Claude (requires an OpenAI-compatible proxy like LiteLLM)
uv run meeting-agent listen --title "Meeting" --mode full --provider anthropic --model claude-sonnet-4-20250514

# Use local Ollama
uv run meeting-agent listen --title "Meeting" --mode full --provider ollama --model llama3.1

# Use a custom OpenAI-compatible endpoint
export CUSTOM_API_KEY="your-key"
export CUSTOM_BASE_URL="http://localhost:8080/v1"
uv run meeting-agent listen --title "Meeting" --mode full --provider custom --model my-model
```

### Status Check

```bash
# Check that all dependencies are installed and configured
uv run meeting-agent status
```

### Debugging

```bash
# Keep WAV audio files after transcription (for debugging)
uv run meeting-agent listen --title "Debug" --keep-audio

# Verbose logging
uv run meeting-agent --log-level DEBUG listen --title "Debug"
uv run meeting-agent --log-level DEBUG join "https://zoom.us/j/123"
```

### Output

Meeting notes are saved to `notes/` with this structure:

- **Transcript:** `notes/{Title}_{YYYY-MM-DD_HHMM}_transcript.md` (always saved)
- **Summary:** `notes/{YYYY-MM-DD_HHMM}_{Title}.md` (when using `full` or `summary_only` mode)

Summary files follow this format:

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

Settings are loaded in this priority order: **CLI flags > environment variables > config file > defaults**.

### Config File

Create a config file to avoid repeating settings:

```bash
# Generate a starter config file at ~/.config/meeting-agent/config.toml
uv run meeting-agent config --init

# Show current effective settings
uv run meeting-agent config --show

# Show which config file is active
uv run meeting-agent config --path
```

Config file locations (first found wins):
1. `.meeting-agent.toml` (project-local)
2. `~/.config/meeting-agent/config.toml`

Example config file:

```toml
[audio]
device = ":0"                    # macOS: BlackHole device
volume_boost_db = 15.0

[whisper]
model = "large-v3-turbo"
device = "cpu"

[llm]
provider = "openai"
model = "gpt-4o"
temperature = 0.3

# API keys — prefer env vars for secrets, but you can set them here:
# openai_api_key = "sk-..."

[meeting]
bot_name = "Meeting Notes Bot"
mode = "full"
# chrome_user_data_dir = "/home/you/.meeting-agent-chrome"  # for Google Meet
# virtual_display = true   # auto (Xvfb on headless Linux, no-op elsewhere)
```

### Environment Variables

All settings can also be set via environment variables (prefixed with `MEETING_AGENT_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `MEETING_AGENT_MODE` | `full` (config default; `listen` CLI defaults to `transcript_only`) | Run mode: `full`, `transcript_only`, `summary_only` |
| `MEETING_AGENT_LLM_PROVIDER` | `opencode-go` | LLM provider |
| `MEETING_AGENT_LLM_MODEL` | `deepseek-v4-pro` | Model name |
| `MEETING_AGENT_LLM_TEMPERATURE` | `0.3` | LLM temperature |
| `MEETING_AGENT_AUDIO_DEVICE` | `meeting-agent-sink.monitor` (Linux) / `:0` (macOS) | Audio capture device |
| `MEETING_AGENT_VOLUME_BOOST_DB` | `15.0` | Audio volume boost in dB |
| `MEETING_AGENT_KEEP_AUDIO` | `false` | Retain WAV files |
| `MEETING_AGENT_BOT_NAME` | `Meeting Notes Bot` | Display name in meetings |
| `MEETING_AGENT_WHISPER_MODEL` | `large-v3-turbo` | Whisper model variant |
| `MEETING_AGENT_CHUNK_DURATION` | `30` | Audio chunk duration in seconds |
| `MEETING_AGENT_CHROME_USER_DATA_DIR` | _(unset)_ | Chrome profile with signed-in Google account |
| `MEETING_AGENT_VIRTUAL_DISPLAY` | `true` | Auto-start Xvfb on headless Linux |

## Privacy & Data Retention

- **Audio:** WAV chunks stored in `/tmp/meeting-agent-audio/`, deleted immediately after transcription. Never persisted to disk beyond a few seconds.
- **Text:** Transcript and notes saved to `notes/` directory. Delete manually when no longer needed.
- **LLM:** Only transcribed text (never audio) is sent to the LLM provider. Provider data policies apply.
- **Local mode:** Use `--mode transcript_only` to keep everything on your machine with zero API calls.
- **Chrome profile:** If using `--chrome-profile`, the profile directory contains Google account cookies. Store it in a private location and do not share it.

## Platform Support

| Platform | Join mode | Listen mode | Notes |
|----------|-----------|-------------|-------|
| **Google Meet** | ✓ (with `--chrome-profile`) | ✓ (recommended) | Requires pre-authenticated Chrome profile for reliable auto-join |
| **Zoom** | ✓ | ✓ | Uses Zoom web client (`/wc/join/`); no Zoom account required |
| **Microsoft Teams** | ✓ | ✓ | Anonymous guest join; most permissive of the three |
| **Webex** | — | ✓ | Auto-join not yet supported |

### Virtual Display (Linux)

| Environment | `$DISPLAY` | Behavior |
|-------------|------------|---------|
| Linux desktop | set | `headless=False`, no Xvfb needed |
| Linux CI / Docker / SSH | not set | Xvfb started automatically via pyvirtualdisplay |
| macOS | n/a | Native display session, no Xvfb |
| Windows | n/a | Native display session, no Xvfb |

## Limitations

- **Platform UI changes** — Google Meet, Zoom, and Teams change their DOM frequently. Join flows may need selector updates.
- **Google Meet without a profile** — Without `--chrome-profile`, Meet may limit guests or block the join entirely depending on the meeting's settings.
- **macOS audio routing** — On macOS, you need BlackHole + Multi-Output Device to capture system audio while hearing it. Use `scripts/setup-audio-macos.sh`.
- **Linux audio routing** — On Linux, you must route browser audio into the virtual sink (use `pavucontrol`), or use `--device @DEFAULT_SINK@.monitor` to capture from speakers/headphones.
- **Anthropic provider** — Requires an OpenAI-compatible proxy (e.g. [LiteLLM](https://github.com/BerriAI/litellm)) to translate the Anthropic Messages API into the OpenAI chat completions format the agent uses. Alternatively, use `--provider custom` with the proxy's base URL.
- **Speaker diarization** — Does not identify "who said what" (planned for v0.2).
- **No calendar integration** — Meeting URLs must be provided manually (calendar integration planned).

## License

MIT
