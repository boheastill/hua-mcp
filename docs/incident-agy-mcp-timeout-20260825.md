# 故障记录：mcp__agy__agy_ask MCP 通道超时（2026-08-25）

> 症状：dsh 会话里调 `mcp__agy__agy_ask` 立即返回 `Error: MCP error -32001: Request timed out`。
> 同期 `mcp__agy__agy_quota` 也超时（15:19 首次尝试即失败）。
> **agy 本体（CLI）完全正常**——同一时间段 CLI 跑了两轮联网调研均成功，
> 见 `~/bh-workspace/agent/agy/agy-web-search-playbook.md`。

## 时间线（2026-08-25）

| 时间 | 事件 |
|---|---|
| 15:19 | 首次 `mcp__agy__agy_ask`（GLM coding plan 调研）→ MCP error -32001 超时 |
| 15:20 | 改走 CLI：`agy --effort medium --print=...` 后台 → **成功**，产出带 URL 调研 |
| 15:52 | 第二轮 `mcp__agy__agy_ask`（官方规则查证）→ 仍超时 |
| 15:55 | CLI 第二轮 → 成功 |

## 旁证：CLI 的 MCP 反向印证

CLI 跑动时 stderr 出现 `MCP: 1 server(s) still connecting after 30s/1m/.../5m0s: agy` ——
agy CLI 自己作为 MCP **client** 连自己舰队里的 agy server 也连不上（5 分钟没握手成功）。
说明问题不在"谁调 agy"，而在 **agy 这个 MCP server 进程/端口本身没有及时响应**。

另注：CLI stderr 里大量 `read-only file system`（写 ~/.gemini/antigravity-cli/ 被拒），
这是 dsh 沙箱只读约束，**只影响日志落盘，不是超时根因**（结果照样返回）。

## 排查方向（下次复发的检查单）

1. `pm2 list` 看 agy server 是否 online（舰队规矩：pm2 restart 后所有 MCP **客户端**要重启，见 CLIENTS.md 铁律——dsh 也是客户端之一）
2. `curl -m 3 http://localhost:<agy端口>/health`（端口见 `*/*/mcp.json` 扫描）
3. dsh 侧配置：`~/.dsh/profiles/*/cordis.patch.yml` 里 hua-mcp insert 块是否指向正确端口
4. 若 fleet 掉光（所有 mcp__* 工具齐超时）→ `systemctl --user restart pm2-fleet.service` 再重启 dsh（INDEX §D 已列）

## 临时替代（已在用）

CLI 后台跑，等价拿结果：
```bash
~/.local/bin/agy --effort medium --print-timeout 10m --output-format text \
  --print='问题（要求出处URL）' > out.md 2>&1
```
完整姿势与坑见 `~/bh-workspace/agent/agy/agy-web-search-playbook.md`。

## 状态

- [ ] 未修复（记录时点 MCP 仍超时；本轮任务用 CLI 绕过完成）
- 影响面：所有依赖 `mcp__agy__agy_ask` 的 agent 会话；agy CLI 用户不受影响
