# 舰队运维经验 (OPS_NOTES)

> 踩过的坑与铁律。新成员创建、重启服务、接线客户端前先看这里。
> 与 `PM2_MANUAL.md`(PM2 命令) / `README.zh.md`(架构) 配套。

## 一、新成员创建检查单

1. `cp -r _template wsl/<name>` —— **目录名 = mcp.json 的 name = 服务名**，三处一致
2. 起名规则: 小写英文连字符, **`hb-<能力>` 前缀**做个人命名空间, 防与官方/他人 MCP 撞名(如 `hb-tts`); 端口沿用舰队规则 **wsl 8100+ / win 8001-8099**
3. **必须带 `requirements.lock`** —— 从 `wsl/identity/requirements.lock` 复制或用 `uv pip compile requirements.txt -o requirements.lock` 生成。没有 lock 时 `mcp[cli]>=1.2.0` 会装到最新版 SDK, 其中 `mcp.server.fastmcp` 已挪走 → `ModuleNotFoundError` 起不来
4. `./fleet.sh validate && ./fleet.sh up`
5. **pm2 环境陷阱**: pm2 把启动 shell 的 PATH 存进 app。从缺 `~/.local/bin` 的 shell 启动 → `run.sh: uv: command not found` → crash loop。修复: 从带完整 PATH 的 shell 重建 app:
   ```bash
   export PATH="/home/bohea/.local/bin:$PATH"
   pm2 delete <app> && pm2 start <dir>/run.sh --name <app> --interpreter none --max-memory-restart 500M
   pm2 save
   ```
6. 模型类工具统一参数规范: **`model` / `effort` 两个可选参数, 默认值写死在服务端**(小写官方模型 id); 说明里写清"何时用、怎么选、代价"

## 二、streamable-http 会话铁律 (最重要)

- MCP 会话是**服务端进程内存态**: 服务端一重启, 所有已连接客户端的会话全部作废
- 症状: 工具仍挂在客户端, 但调用报 `Session not found (JSON-RPC -32600, Streamable HTTP)`
- 客户端**不会**因为 -32600 自动重握手(重连只由传输层断连/配置变更触发)
- 铁律: **`pm2 restart` 任何舰队 MCP 之后, 顺手重启所有客户端侧**:
  ```bash
  systemctl --user restart dsh-web      # DSH harness
  # Claude / Codex: 新开会话即可(工具列表是会话快照)
  ```

## 三、客户端接线位置与统一 URL

统一地址 `http://localhost:<port>/mcp` (streamable-http; WSL2 mirrored 网络下 Windows 侧同用 `127.0.0.1` 直通)。

| 客户端 | 配置文件 | 形状 |
|--------|----------|------|
| DSH harness | `deepseek-harness/packages/bundle/web-app/cordis.patch.yml` | `@deepseek-ai/dsh-mcp-client` 行, `transport: streamable-http` |
| WSL Claude | `~/.claude.json` → `mcpServers` | `{"type":"http","url":"http://localhost:8103/mcp"}` |
| Win Claude | `C:\Users\bohea\.claude.json` → `mcpServers` | 同上 |
| Codex | `~/.codex/config.toml` | `[mcp_servers.agy]` + `url = "http://127.0.0.1:8103/mcp"` |
| agy 自身 | `~/.gemini/antigravity-cli/mcp_config.json` | (它的 MCP 客户端) |
| 一键生成 | `python gen_config.py > fleet-mcp.json` | 扫全部 `*/*/mcp.json` |

- **DSH 的 bundle patch 只在启动时加载**(不支持热加载)——任何改动后必须 `systemctl --user restart dsh-web`; profile 的 `cordis.patch.yml` 是热加载的, 但 MCP 行已统一收在 bundle patch
- Claude / Codex 的工具列表是**会话启动时快照**——配完/改完要新开会话才生效

## 四、dsh-web 平滑重启(不打断正在进行的回合)

```bash
# 延迟 35s 重启, 让当前回合的回复先落盘
nohup bash -c 'sleep 35; systemctl --user restart dsh-web' >/tmp/dsh-restart.log 2>&1 &
```

会话持久化在磁盘, 重启后不丢; 网页刷新即可继续。

## 五、agy (Antigravity) 特记

- `--agent` 选角色包: 需先在 Antigravity 里定义 agent(当前没有, `agy agent` 空列表); 定义后再给 MCP 加参数
- `--mode plan` 在 print 模式会转"计划评审流"(写 plan 文件等人确认), **无头不可用**
- print 每次调用在 `~/.gemini/antigravity-cli/conversations/` 留一个 `.db`(可达 MB 级), agy 无删除命令, 需定期清理:
  ```bash
  find ~/.gemini/antigravity-cli/conversations -name '*.db*' -mtime +30 -delete
  ```
- 额度: 无官方无头接口; 方案 = PTY 驱动 TUI 的 `/usage` 面板(见 `wsl/agy/server.py` 的 `_capture_usage_panel`: 自动确认信任 → 发 `/usage\r` → 抓屏解析)
- 多轮协作: `agy_ask` 返回 `conversation_id`, 下次调用传 `conversation` 参数续聊(同一会话勿并发)

## 六、agy-sdk (官方 SDK 版) 现状与结论 (2026-08-15)

- 成员 `wsl/agy-sdk` (8105), 工具 `mcp__agy-sdk__agy_sdk_ask`, 描述注明"建议优先, 不通回退 agy"。
- **SDK 鉴权限制(实测)**: `google-antigravity` 的 localharness 强制把 `api_key` 作为
  `x-goog-api-key` 发出; 而 Code Assist 订阅端点 (aicode.googleapis.com) 只认
  `Authorization: Bearer` OAuth。因此 **SDK Agent 会话无法走订阅额度**, 会快速失败。
- 裸 httpx + Bearer 能过鉴权(401→400), 但请求体格式未明, 且高频探测触发连接重置
  (Google 侧风控)——**不要拿它当稳定通道**。
- 结论: CLI 版 (8103) 继续是订阅额度的唯一稳定通道; SDK 版等官方支持 Bearer 后自动点亮,
  到时只需 `pm2 restart mcp-agy-sdk-8105` + 重启客户端, 无需改任何接线。

## 七、委托决策指南 (已内建到各工具描述, 所有客户端可见)

| 场景 | 用谁 | 理由 |
|---|---|---|
| 纯看图 / OCR / 截图识别 | `mcp__glmvision__describe_image` | 秒级、便宜、不走 agy 额度、不留会话; 429 自动降级免费档 |
| 看图 + 深度推理 / 联网 / 多步操作 | `mcp__agy__agy_ask` (或 agy-sdk) | agy 自己看图并继续推理 |
| 复杂推理 / 联网调研 / 重活 | `mcp__agy__agy_ask` | 主模型不够用时外包 |
| 简单问答 / 主模型自己能答的 | **别调** | 省额度省时间 |
| 批量任务前 | `mcp__agy__agy_quota` | 油表, 防中途耗尽 |
| 多轮追问 | 传回上次的 `[会话ID]` 给 conversation | 同一会话续聊, 别另开 |

这条决策已写进 wsl/glmvision、wsl/agy、wsl/agy-sdk 三个成员的
工具描述, Claude/Codex/harness 任何客户端看到的 schema 即含此指南。

## 八、gemini-sub 桥 (订阅额度 OpenAI 兼容端点, 8120)

- 位置: `wsl/gemini-sub/` (run.sh + .venv), pm2 托管 `gemini-sub-8120`, 非 MCP。
- 底层: `antigravity-auth` 库 (opencode 方案的 Python 移植) — 自己实现 OAuth + 内部 Cloud Code API,
  **不 spawn agy 二进制, 不经过官方 SDK**。订阅额度(Gemini 3 / Claude 4.5)。
- 登录态: **直接导入 agy CLI 的 refresh_token**(免浏览器登录):
  `~/.gemini/antigravity-cli/antigravity-oauth-token` → `antigravity_auth.storage.add_or_update_account(refresh_token=..., email=...)`。
- 端点: `http://127.0.0.1:8120` `/health` `/v1/models` `/v1/chat/completions`(流式) `/v1/images/generations`。
- **能力边界: 不支持工具调用**(纯文本/图生成) → 只适合当"模型 API", 不能当 agent。
- harness 接入: `~/.dsh/settings.yaml` 的 `llm-pi-ai.providers.gemini-sub` (openai-completions,
  baseURL /v1, apiKeyEnv GEMINI_SUB_KEY), 热加载即生效, 无需重启。
- CC 接入: 协议层可加 Anthropic shim, 但**桥无工具调用 → CC 直连桥只能纯聊天, 不实用**, 不建议。
- 注意: 未公开内部 API, Google 一改可能失效; 个人自用安全港。
