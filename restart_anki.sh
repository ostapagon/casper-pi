#!/bin/bash
# Restart Anki - works with or without physical display

echo "🔄 Restarting Anki..."

# Stop Anki and Xvfb (but not this script)
echo "🛑 Stopping Anki..."
pkill -9 -f "python.*anki" 2>/dev/null || true
pkill -9 -f "aqt" 2>/dev/null || true
pkill -9 Xvfb 2>/dev/null || true
sleep 2

# Check if display is available
echo "🚀 Starting Anki..."
if [ -n "$DISPLAY" ] && xdpyinfo > /dev/null 2>&1; then
    echo "   Using connected display: $DISPLAY"
    anki > /tmp/anki_restart.log 2>&1 &
else
    echo "   No display connected, starting virtual display (Xvfb)"
    
    # Install Xvfb if not present
    if ! command -v Xvfb > /dev/null 2>&1; then
        echo "   Installing Xvfb..."
        sudo apt-get update -qq && sudo apt-get install -y xvfb
    fi
    
    # Start Xvfb with additional extensions for Qt
    Xvfb :99 -screen 0 1024x768x24 +extension GLX +render -noreset > /tmp/xvfb.log 2>&1 &
    XVFB_PID=$!
    sleep 2
    
    # Verify Xvfb started
    if ! kill -0 $XVFB_PID 2>/dev/null; then
        echo "❌ Failed to start Xvfb"
        exit 1
    fi
    
    # Start Anki with virtual display and Qt workarounds
    # Use newer flags to prevent WebEngine crashes
    export DISPLAY=:99
    export QT_QPA_PLATFORM=offscreen
    export QTWEBENGINE_DISABLE_SANDBOX=1
    export QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --no-sandbox --disable-dev-shm-usage --disable-software-rasterizer"
    export QT_LOGGING_RULES="*.debug=false;qt.qpa.*=false"
    export LIBGL_ALWAYS_SOFTWARE=1
    
    # Start with default profile (has AnkiConnect addon)
    anki > /tmp/anki_restart.log 2>&1 &
fi

ANKI_PID=$!

# Wait for Anki to initialize
echo "   Waiting for Anki to start..."
sleep 8

# Check if running
if pgrep -f "python.*anki" > /dev/null; then
    echo "✓ Anki is running"
    
    # Check AnkiConnect
    sleep 2
    if curl -s http://127.0.0.1:8765 > /dev/null 2>&1; then
        echo "✓ AnkiConnect is responding"
        exit 0
    else
        echo "⚠️ Anki is running but AnkiConnect may not be ready yet"
        echo "   Wait a few more seconds and try again"
        exit 0
    fi
else
    echo "❌ Anki failed to start"
    echo "   Last lines of log:"
    tail -10 /tmp/anki_restart.log 2>/dev/null || echo "   (no log)"
    exit 1
fi

