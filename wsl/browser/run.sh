#!/usr/bin/env bash
# npm-native MCP launcher (PM2 / manual): @playwright/mcp as a resident
# streamable-http server. Port comes from mcp.json (single source of truth).
set -euo pipefail
cd "$(dirname "$0")"
# PM2 injects NODE_CHANNEL_FD (its IPC pipe fd); any node child would inherit
# it, try to use the dead fd, and SIGABRT. Strip it defensively.
unset NODE_CHANNEL_FD
port=$(python3 -c 'import json; print(json.load(open("mcp.json"))["port"])')
# ensure the chromium build matching this @playwright/mcp version is present
# (no-op when already cached in ~/.cache/ms-playwright; failure is non-fatal —
# the server itself will report a clearer error if the browser is missing)
npx -y -p @playwright/mcp@latest playwright install chromium >/dev/null 2>&1 || true
exec npx -y @playwright/mcp@latest --host 127.0.0.1 --port "$port" --browser chromium --headless
