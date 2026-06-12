#!/bin/bash
# macOS audio setup for Meeting Agent — BlackHole + Multi-Output Device
# Run: bash scripts/setup-audio-macos.sh

set -e

echo "🍎 Meeting Agent — macOS Audio Setup"
echo "===================================="
echo ""

# ── Check for Homebrew ──────────────────────
if ! command -v brew &>/dev/null; then
    echo "❌ Homebrew not found. Install it first:"
    echo "   /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi

# ── Install BlackHole ──────────────────────
echo "1. Installing BlackHole virtual audio driver..."
if ! brew list --cask blackhole-2ch &>/dev/null; then
    brew install --cask blackhole-2ch
    echo "   ✅ BlackHole 2ch installed."
else
    echo "   ✅ BlackHole 2ch already installed."
fi

echo ""

# ── Multi-Output Device instructions ────────
echo "2. Multi-Output Device setup:"
echo ""
echo "   ╔════════════════════════════════════════════════════════╗"
echo "   ║  MANUAL STEP REQUIRED                                 ║"
echo "   ║                                                        ║"
echo "   ║  Open Audio MIDI Setup (Applications → Utilities)      ║"
echo "   ║  Click '+' (bottom-left) → 'Create Multi-Output Device'║"
echo "   ║  Check BOTH:                                           ║"
echo "   ║    ☑ BlackHole 2ch                                     ║"
echo "   ║    ☑ Your speakers/headphones (e.g. MacBook Speakers)  ║"
echo "   ║  Right-click the new device → 'Use This Device For     ║"
echo "   ║  Sound Output'                                         ║"
echo "   ╚════════════════════════════════════════════════════════╝"
echo ""
echo "   This lets you hear the meeting WHILE capturing audio."

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Setup complete!"
echo ""
echo "To use:  meeting-agent listen --device ':0' --title 'Meeting'"
echo ""
echo "To capture from a different device, list them with:"
echo "  ffmpeg -f avfoundation -list_devices true -i ''"
echo ""
echo "The BlackHole device is typically ':0' or ':1'."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
