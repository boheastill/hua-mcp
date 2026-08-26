"""browser MCP — npm-native member: 真身是 `npx @playwright/mcp`(见 run.sh),
本文件只为满足舰队契约(fleet.sh validate/test 要求每成员有 server.py), 不声明任何工具。

上游工具(自动透出): browser_navigate / browser_snapshot / browser_click /
browser_type / browser_tab_* / browser_pdf / browser_console_messages 等。
无 /health 端点 — fleet.sh health 会用 /mcp initialize 兜底探活。
"""
if __name__ == "__main__":
    raise SystemExit("npm-native member: start via run.sh (npx @playwright/mcp), not server.py")
