#!/bin/bash
# Setup PulseAudio virtual sink for meeting audio capture
# Run: bash scripts/setup-audio-sink.sh

SINK_NAME="meeting-agent-sink"
SINK_DESC="Meeting Agent Audio Capture"

# Check if already exists
if pactl list short sinks | grep -q "$SINK_NAME"; then
    echo "Audio sink '$SINK_NAME' already exists. Skipping creation."
    echo "Monitor source: ${SINK_NAME}.monitor"
    exit 0
fi

# Load the null sink module
pactl load-module module-null-sink \
    sink_name=$SINK_NAME \
    sink_properties="device.description='$SINK_DESC'" 2>/dev/null

# Load loopback from default sink monitor to our sink
DEFAULT_SINK=$(pactl get-default-sink 2>/dev/null || echo "@DEFAULT_SINK@")
if [ "$DEFAULT_SINK" != "@DEFAULT_SINK@" ]; then
    pactl load-module module-loopback \
        source="${DEFAULT_SINK}.monitor" \
        sink=$SINK_NAME \
        latency_msec=1 2>/dev/null
fi

echo "Audio sink '$SINK_NAME' created."
echo "Monitor source: ${SINK_NAME}.monitor"
echo "To route a specific app: pavucontrol"
