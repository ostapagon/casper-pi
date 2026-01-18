# MCP (Model Context Protocol) Integration

This module provides MCP server integration for the Casper Pi application.

## Why This Integration Exists

**The Gemini Live API does not natively support MCP servers.** The model we're using (`gemini-2.5-flash-native-audio-preview-12-2025`) supports function calling/tool use, but it does not have built-in support for connecting to external MCP servers.

This module acts as a **middleware layer** that:
- Connects to MCP servers (via stdio or HTTP transport)
- Discovers available tools from MCP servers
- Converts MCP tool schemas to Gemini function declarations
- Routes Gemini function calls back to the appropriate MCP servers
- Handles the translation between Gemini's function calling API and the MCP protocol

This allows us to use any MCP-compatible server (like AnkiMCP) with Gemini Live, even though Gemini doesn't support MCP directly.

## Overview

The MCP registry automatically discovers and manages tools from all configured MCP servers. Servers are registered in `mcp_servers.json` in this directory - **one place to manage all servers**.

## Architecture

- `registry.py` - Core MCP registry that manages client connections and tool discovery
- `servers/` - Directory for custom MCP server implementations (if needed)

## Configuration

All MCP servers are configured in `mcp_servers.json` (in this directory):

```json
{
  "mcp_servers": [
    {
      "name": "server_name",
      "enabled": true,
      "transport": "stdio",  // or "http"
      "command": "command_to_run",  // for stdio
      "url": "http://...",  // for http
      "args": [],
      "env": {},
      "headers": {}  // for http authentication
    }
  ]
}
```

## Supported Transports

- **stdio**: Run MCP server as subprocess, communicate via stdin/stdout
- **http**: Connect to HTTP-based MCP server (e.g., AnkiMCP addon)

## Custom MCP Servers

### Custom Anki MCP Server

**This project uses a custom Anki MCP server** (not the AnkiMCP addon). The custom server is located in `servers/anki/`:

- **Location**: `src/mcp/servers/anki/server.py`
- **Transport**: stdio
- **Dependencies**: Requires Anki desktop app with AnkiConnect addon running on port 8765
- **Configuration**: Deck settings in `servers/anki/decks.json`

**Why Custom Server?**
- Better due date filtering logic
- Proper handling of "Again" cards
- Deck-specific configuration support
- More accurate card selection based on Anki's internal state

**Features:**
- `list_decks` - List all Anki decks
- `get_due_cards` - Get cards due for review today (respects deck limits and sorting)
- `get_next_card` - Get the next card to review (top of sorted list)
- `rate_card` - Rate a card (1=Again, 2=Hard, 3=Good, 4=Easy)
- `sync` - Sync Anki with AnkiWeb

**Deck Configuration:**
Deck-specific settings are configured in `servers/anki/decks.json`:
- `new.perDay` - New cards per day limit
- `rev.perDay` - Review cards per day limit
- `reviewOrder` - Review sorting order (0=Random, 1=Due date, 3=Intervals)
- `mixNewAndReview` - Whether to mix new and review cards

**Logic:**
- Filters cards to only those actually due today (`prop:due=0`)
- Excludes cards already reviewed today (except "Again" cards)
- Includes cards rated "Again" today (they need review again)
- If not enough cards due today, fills from tomorrow (`prop:due>=1`) to reach review limit
- New cards are limited separately by `new.perDay` setting

### Setup Instructions

1. **Install Anki Desktop Application**:
   ```bash
   # On Raspberry Pi/Debian
   # Anki is typically installed via pip or downloaded from ankiweb.net
   ```

2. **Install AnkiConnect Addon** (required for custom MCP server):
   - Open Anki
   - Tools → Add-ons → Get Add-ons...
   - Enter code: **2055492159**
   - Restart Anki

3. **Start Anki**:
   - AnkiConnect runs automatically when Anki starts
   - Server runs on `http://127.0.0.1:8765`
   - Use `./restart_anki.sh` script to restart Anki if needed

4. **Configure Deck Settings** (optional):
   - Edit `src/mcp/servers/anki/decks.json` for deck-specific settings
   - Or configure in Anki's Deck Options UI
   - Settings include: new cards/day, review cards/day, review order, etc.

5. **Sync your cards** (if needed):
   - File → Sync in Anki
   - Enter AnkiWeb credentials

**Note**: This project uses a custom MCP server, not the AnkiMCP addon. The custom server provides better filtering and configuration options.

### Testing Connection

```bash
python3 cursor_tests/test_mcp_connection.py
```

## Adding New MCP Servers

1. Add entry to `mcp_servers.json` (in this directory) with appropriate transport
2. Restart the application - tools are automatically discovered
3. Tools become available to Gemini via function calling

## Authentication

For HTTP servers, authentication can be configured via `headers`:

```json
{
  "headers": {
    "Authorization": "Bearer YOUR_TOKEN",
    "X-API-Key": "YOUR_API_KEY"
  }
}
```

For local AnkiMCP addon (`127.0.0.1`), authentication is not required.

## GUI Access (Raspberry Pi)

If running Anki on Raspberry Pi and need GUI access:

### Method 1: Physical Access
```bash
export DISPLAY=:0
anki
```

### Method 2: SSH with X11 Forwarding
```bash
ssh -X rasberry_pi@your-pi-ip
anki
```

### Method 3: VNC
```bash
vncserver :1 -geometry 1920x1080 -depth 24
# Connect with VNC client to your-pi-ip:5901
```

## Troubleshooting

- **Can't connect to AnkiMCP**: Make sure Anki is running and addon is installed
- **Port conflict**: Change port in addon settings and update `mcp_servers.json` (in this directory)
- **No tools discovered**: Check server is enabled in config and transport is correct
- **Authentication errors**: Verify headers are correctly configured

