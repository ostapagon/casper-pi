#!/bin/bash
# Restart Anki application

echo "🔄 Restarting Anki..."

# Step 1: Stop Anki
echo "🛑 Stopping Anki..."
pkill -9 -f "^anki" 2>/dev/null || true
pkill -9 -f "python.*anki" 2>/dev/null || true
pkill -9 -f "QtWebEngineProcess.*Anki" 2>/dev/null || true

sleep 2

# Verify all processes are stopped
if pgrep -f "^anki" > /dev/null || pgrep -f "python.*anki" > /dev/null || pgrep -f "QtWebEngineProcess.*Anki" > /dev/null; then
    echo "⚠️ Some processes still running, force killing..."
    pkill -9 -f "^anki" 2>/dev/null || true
    pkill -9 -f "python.*anki" 2>/dev/null || true
    pkill -9 -f "QtWebEngineProcess.*Anki" 2>/dev/null || true
    sleep 1
fi

# Step 2: Start Anki (AnkiConnect will start automatically when Anki loads)
echo "🚀 Starting Anki..."

# Check if we have a real display (X11 or Wayland with XWayland)
XAUTH_FILE=$(find /home/rasberry_pi/.Xauthority /run/user/*/gdm/Xauthority /var/run/lightdm/*/Xauthority 2>/dev/null | head -1)

# Check if Wayland is running (desktop is active)
if [ -n "$WAYLAND_DISPLAY" ] || [ -f "/run/user/$(id -u)/wayland-0" ] || pgrep -x labwc > /dev/null; then
    # Wayland desktop is running, use :0 (XWayland will handle it)
    echo "   Desktop detected (Wayland), using display :0"
    DISPLAY_NUM=:0
    if [ -n "$XAUTH_FILE" ]; then
        export XAUTHORITY="$XAUTH_FILE"
    fi
elif DISPLAY=:0 xdpyinfo > /dev/null 2>&1; then
    # Real X11 display available
    echo "   Using real X11 display :0"
    DISPLAY_NUM=:0
    if [ -n "$XAUTH_FILE" ]; then
        export XAUTHORITY="$XAUTH_FILE"
    fi
else
    # No real display, use virtual framebuffer (Xvfb)
    echo "   No display available, using virtual framebuffer (Xvfb)"
    
    # Check if Xvfb is installed
    if ! command -v Xvfb > /dev/null 2>&1; then
        echo "   Installing Xvfb..."
        sudo apt-get install -y xvfb > /dev/null 2>&1
    fi
    
    # Start Xvfb on display :99
    DISPLAY_NUM=:99
    Xvfb $DISPLAY_NUM -screen 0 1024x768x24 > /tmp/xvfb.log 2>&1 &
    XVFB_PID=$!
    sleep 2
    
    # Verify Xvfb started
    if ! kill -0 $XVFB_PID 2>/dev/null; then
        echo "❌ Failed to start Xvfb"
        exit 1
    fi
fi

# Start Anki in background - it will automatically load AnkiConnect addon
# Use nohup to ensure it keeps running even if terminal closes
nohup env DISPLAY=$DISPLAY_NUM XAUTHORITY="$XAUTH_FILE" anki > /tmp/anki_restart.log 2>&1 &
ANKI_PID=$!

# Wait for Anki to start and AnkiConnect to initialize
echo "   Waiting for Anki to start (this may take a few seconds)..."
sleep 5

# Check if Anki process is still running (not crashed)
if kill -0 $ANKI_PID 2>/dev/null 2>/dev/null; then
    # Anki is running, wait a bit more for AnkiConnect to start
    sleep 3
    
    # Check if AnkiConnect is responding
    if curl -s http://127.0.0.1:8765 > /dev/null 2>&1; then
        echo "✓ Anki restarted successfully (AnkiConnect is running)"
        exit 0
    else
        echo "⚠️ Anki started but AnkiConnect may not be ready yet"
        echo "   AnkiConnect usually takes 5-10 seconds to start"
        echo "   Check if AnkiConnect addon is installed and enabled"
        exit 0  # Still consider it success since Anki is running
    fi
elif pgrep -f "^anki" > /dev/null; then
    # Anki process exists but PID changed (might have forked)
    echo "✓ Anki restarted successfully"
    exit 0
else
    echo "❌ Failed to start Anki"
    echo "   Check /tmp/anki_restart.log for details"
    echo "   Last 15 lines of log:"
    tail -15 /tmp/anki_restart.log 2>/dev/null || echo "   (log file not found)"
    exit 1
fi

