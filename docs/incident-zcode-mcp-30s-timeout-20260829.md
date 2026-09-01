# 故障单:ZCode 会话内 mcp__agy__agy_ask / mcp__kimi__kimi_ask 全部 30 秒超时(2026-08-29)

> 症状:ZCode(sliver 本机)会话里调用 `mcp__agy__agy_ask` 或 `mcp__kimi__kimi_ask`,
> 均在 **30 秒整** 返回 `Tool execution timed out after 30000ms`。
> 高/低 effort、长/短 prompt **全部一样超时**(四连超时实测:agy high/medium、kimi high/low)。
>
> **同会话 `mcp__agy__agy_quota` 秒回正常** —— server 进程活着、握手/协议无问题,
> 死的是"长任务":分析类请求(server 端需 >30s)被掐,轻请求(quota)正常。
>
> 与 [incident-agy-mcp-timeout-20260825.md](incident-agy-mcp-timeout-20260825.md) **不同根因**:
> 8/25 那单是 server 侧握手不动(MCP error -32001,连 quota 都超时,CLI 侧也连不上);
> 本单 server 健康,是 **ZCode 客户端工具执行的 30s 硬超时**。kimi 一起中招说明
> 不是 agy 单家问题,是 ZCode → hua-mcp 舰队所有"分钟级长任务"工具的共性问题。

## 时间线(2026-08-29 00:3x-00:4x)

| 时间 | 事件 |
|---|---|
| 00:3x | `mcp__kimi__kimi_ask`(长 prompt, effort high)→ 30s 超时 |
| 00:3x | `mcp__agy__agy_quota` → **秒回正常**(99% remaining) |
| 00:3x | `mcp__agy__agy_ask` high + `mcp__kimi__kimi_ask` high 并行 → 双双 30s 超时 |
| 00:4x | 双方再降 effort(medium/low)+ 精简 prompt 重试 → 仍 30s 超时 |
| 00:4x | 用户裁定:写 bug 单 + 直连 CLI 绕过 |

## 根因定位(待 hua-mcp 侧确认)

- ZCode 客户端对 MCP 工具调用存在 **30000ms 硬超时**,未见可配置项(待查 ZCode 文档);
- hua-mcp 的 ask 类工具(agy_ask/kimi_ask)是同步阻塞式,分钟级任务无法在 30s 内返回;
- 两者错配:凡"长思考"请求必死,"轻"请求(查额度/读文件)正常。

## 建议修复方向(hua-mcp 侧任选其一)

1. **异步任务模式**(治本):ask 类工具立即返回 task_id,新增 `*_result(task_id)` 轮询工具,
   客户端 30s 内拿到回执,结果稍后取——兼容一切带硬超时的客户端;
2. **缩短首字节时延**:让 ask 尽快返回"已受理+stream 提示",正文走 side-channel 文件;
3. 或在 ZCode 侧找到/放开 MCP 工具超时配置(若存在)。

## 临时替代(本次在用)

```bash
# agy:CLI 后台直跑(8/25 单已验证的姿势)
~/.local/bin/agy --effort medium --print-timeout 10m --output-format text \
  --print='<问题>' > /tmp/agy-out.md 2>&1 &
# kimi:model-hub kimi-coding 路由 或 ~/.kimi-code/bin/kimi CLI
```

## 状态

- [x] **已修复(2026-09-01, 方案①异步任务模式)**:
  - `huamcp.py` 新增共享后台任务器 `submit_task()`/`poll_task()`(守护线程跑慢活,
    结果保留 30 分钟, 并发上限 agy=2/kimi=3);
  - `agy_ask`/`kimi_ask` 改快慢双路: ≤12s 快任务就地等完**直接返回结果**(老客户端
    体验不变); 慢任务 12s 整点立即返回 `[任务受理] task_id=xxx`, 新工具
    `agy_task_result`/`kimi_task_result` 每 5-10s 轮询取果 —— ZCode 30s 硬超时下
    每次调用都在秒级完成, 分钟级任务照常拿到全文;
  - **实测(2026-09-01)**: kimi high 写作 25s 任务全程轮询无超时拿到 800 字全文;
    agy 慢任务执行期间成员 /health 持续 200 —— 顺带缓解了 OPS_NOTES 记录的
    "agy 长调用冻结全成员"问题(重活已挪后台线程);
  - **附带发现并修复**: agy CLI 1.1.22 起模型名自带档位后缀(gemini-3.7-flash-high 等),
    与 `--effort` 冲突会直接报错 —— agy_ask 现在对带后缀模型自动切到 effort 对应
    变体并省掉 --effort(claude 系仍走 --effort), 实测 -high+low → 自动切 -low 档通过。
- 影响面(修复前): 所有经 ZCode 调 hua-mcp 长任务工具的会话;CLI/其他客户端不受影响
