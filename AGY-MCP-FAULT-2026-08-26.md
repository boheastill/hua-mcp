# 故障报告:agy MCP 调用失败(2026-08-26 凌晨)

## 现象
- `mcp__agy__agy_ask` 三次失败:
  1. 高 effort 长任务 → `MCP error -32001: Request timed out`(超时)
  2. medium effort 短任务 → `agy 失败 (exit 1)` 无输出
  3. low effort 极简任务 → `agy 失败 (exit 1)` 无输出
- `agy_quota` 也失败:面板解析错误(`Error: unexpected argument "usage"`)

## 排查建议(给修的人)
1. agy CLI 本体是否还活着:终端手动 `agy -p "test"` 看输出
2. MCP wrapper 的会话/登录态可能过期(额度面板都解析不了,疑未登录)
3. timeout 参数:高 effort 长任务 MCP 层 30s 就断了,考虑后台化或分片

## 影响范围
- 本会话的"联网调研"通道受阻,改用 curl 直搜 + agy CLI 兜底
- glmvision MCP 也出现 Session not found(可能同因:舰队会话老化)

## 报告人
DSH 会话(2026-08-25 深夜视频管线冲刺期间)

## 修复结论 (2026-08-26, 舰队侧)

1. **`agy_quota` 根因 = CLI 升到 1.1.20 后 `usage` 子命令已删除**(报错
   `unexpected argument "usage"`)。已改 `_capture_usage_panel` 裸起 TUI 后发
   `/usage`, 实测面板解析恢复(Gemini 周额度 76% / 5h 档 97%)。
2. **`agy_ask` exit-1 无输出 = 瞬态**: 当夜正撞舰队重启窗口(session 全废)+
   并发 agy 实例锁。CLI 本体复测正常(7s SUCCESS)。wrapper 已增强: 失败时
   stdout 也透传, 无输出时提示"疑登录态失效, 终端跑 agy 看真实报错"。
3. glmvision 的 Session not found 同为重启窗口所致(OPS_NOTES §二铁律)。
4. 处置: `pm2 restart mcp-agy-8103` 已加载修复; 客户端新开会话即恢复。
