# 舰队运维经验 (OPS_NOTES)

> 踩过的坑与铁律。新成员创建、重启服务、接线客户端前先看这里。
> 与 `PM2_MANUAL.md`(PM2 命令) / `README.zh.md`(架构) 配套。

## 一、新成员创建检查单

1. `cp -r _template wsl/<name>` —— **目录名 = mcp.json 的 name = 服务名**，三处一致
2. 起名规则: 小写英文连字符, **`hb-<能力>` 前缀**做个人命名空间, 防与官方/他人 MCP 撞名(如 `hb-tts`); 端口沿用舰队规则 **wsl 8100+ / win 8001-8099**
3. **必须带 `requirements.lock`** —— `fleet.sh new` 复制 `_template` 时会带上模板的
   lock(已钉 `mcp==1.28.0`)。没有 lock 时 `mcp[cli]>=1.2.0` 会装到最新版 SDK, 其中
   `mcp.server.fastmcp` 已挪走 → `ModuleNotFoundError` 起不来(2026-08-25 已给 _template
   补 lock 并修复其 import 冒烟自败; 加了新依赖记得 `uv pip compile` 重生成)
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
  systemctl --user restart dsh       # DSH harness (单元名是 dsh, 不是 dsh-web)
  # Claude / Codex / agy: 新开会话即可(工具列表是会话快照)
  ```

## 三、客户端接线位置与统一 URL

统一地址 `http://localhost:<port>/mcp` (streamable-http; WSL2 mirrored 网络下 Windows 侧同用 `127.0.0.1` 直通)。

各客户端(Claude/Codex/agy/dsh)配置位置、写入命令、重同步清单与疑难速查,
以 **[CLIENTS.md](CLIENTS.md)** 为权威(2026-08-25 全量接线后整理)。

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

## 六、本地模型 (8105) — local-model v2 (2026-08-25 重写)

- 后端已从本机 ollama(11434, 已死)切到 **lb 台式机 llama-server**(OpenAI 兼容,
  `LB_LLM_URL`, 默认 `http://192.168.31.71:8080/v1`)。
- lb 单卡互斥(同时只跑一个模型 set); 工具启动/缓存期自动发现 `/v1/models` 活模型,
  lb 上换模型(stop 旧 + start 新)**客户端零改动**。模型资产单一事实源:
  `~/bh-workspace/docs/model-registry/README.md`。
- 工具: `local_ask`(文本委托) + `local_vision`(本地看图, 需多模态 set 如 qwen3.8-27b)。
- lb 不可达时工具返回带台账指引的错误(区分"主机关机/服务未起"与"在线但无模型")。
- WSL mirrored networking 下客户端统一 `http://127.0.0.1:8105/mcp`; 服务默认回环绑定。
- 该服务重启后, Claude/Codex 需新开会话, DSH 需重启 web 服务(§二铁律)。

## 七、委托决策指南 (已内建到各工具描述, 所有客户端可见)

| 场景 | 用谁 | 理由 |
|---|---|---|
| 纯看图 / OCR / 截图识别 | `mcp__glmvision__describe_image` | 秒级、便宜、不走 agy 额度、不留会话; 429 自动降级免费档 |
| 看图 + 深度推理 / 联网 / 多步操作 | `mcp__agy__agy_ask` | agy 自己看图并继续推理 |
| 复杂推理 / 联网调研 / 重活 | `mcp__agy__agy_ask` | 主模型不够用时外包 |
| 简单问答 / 主模型自己能答的 | **别调** | 省额度省时间 |
| 批量任务前 | `mcp__agy__agy_quota` | 油表, 防中途耗尽 |
| 多轮追问 | 传回上次的 `[会话ID]` 给 conversation | 同一会话续聊, 别另开 |

这条决策已写进 wsl/glmvision、wsl/agy 两个成员的
工具描述, Claude/Codex/harness 任何客户端看到的 schema 即含此指南。
(历史: 已删除的 agy-sdk 也曾携带; 2026-08-25 清引用。)

## 七点五、PM2/systemd 常驻总图 (2026-08-25 整备定稿)

常驻服务分两族, 互不隶属, 各有各的自启单元:

| 族 | 单元 | 管什么 |
|---|---|---|
| **hua-mcp 舰队** | `pm2-fleet.service` → `~/.pm2` → 各 MCP | resurrect dump.pm2 (改进程列表后要 `pm2 save`) |

- **已退役**: 老 `pm2.service`(8/24 生成, 与 pm2-fleet 重复 resurrect 同一 dump, 且
  `ExecStop=pm2 kill` 会在登出杀掉舰队守护进程)。已 disable + 单元文件改名
  `pm2.service.disabled-bak` 留档。**不要再跑裸 `pm2 startup`** —— 会重新生成同名单元。
- **已拆除(2026-08-26)**: zcode 桥一族(`zcode-bridge.service` CDP 9222 +
  `zcode-bridge-api.service` HTTP 9230 + 舰队成员 `zcode-bridge:8123`)——上游项目有
  严重 bug, 整体拆除, 单元文件已删, 港位 8123 让渡。技术经验保留: 旧提交 a56efb9,
  以及下面这条 HOME 陷阱(当年就是它踩出来的)。
- **agent 沙箱 HOME 陷阱仍在**: 非常规 shell(HOME 被改写, 如当年 zcode 桥的 bridge-home)里
  裸跑 `pm2 ls` 会连到/新建**错误的 daemon**(空表误判"舰队掉了", `fleet.sh up` 还会
  在占用端口重复起进程)。铁律: 前缀 `PM2_HOME=/home/bohea/.pm2 pm2 ...`。
  变体(2026-08-26 实锤, 比空表更凶): **cgroup 陷阱**——从 dsh 会话里跑 `fleet.sh up`/`pm2`,
  daemon 作为子孙进程挂进 `dsh.service` cgroup, dsh 重启时 systemd 杀整树=舰队全体陪葬
  (当日 02:05、14:57 两次"神秘掉 fleet"同根因), 且事后任何 `pm2 ls` 又自动拉起空 daemon
  (不 resurrect)仍困在陷阱里。正解: `pm2 kill` → `pkill -f 'God Daem[o]n'`(防 pm2 kill
  自己再拉一个; 括号防 pkill 自匹配) → `systemctl --user restart pm2-fleet.service`
  (oneshot 已 active 时 start 是空操作, 必须 restart) → 验证 daemon cgroup=pm2-fleet.service。
  **铁律升级: 舰队常驻只走 systemctl; agent 会话里起的 pm2 daemon 都是临时货。**
  连锁坑: 舰队 DOWN 时 dsh 启动, mcp-client 插件连接 ECONNREFUSED **静默不注册工具**
  (stderr 零输出)——修好舰队后必须重启 dsh profile, 工具才会回来。

## 八、gemini-sub 桥 (订阅额度 OpenAI 兼容端点) — **已停用, 端口已让渡**

> ⚠️ 2026-08-25 状态: 该桥不在 pm2 里(未运行)。**8120 已划给 printctl**,
> `wsl/gemini-sub/run.sh` 若原样重启会端口冲突。复活时先改端口(如 8124)+
> 同步 `~/.dsh/settings.yaml` 的 gemini-sub provider + 本节。以下为历史档案。

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

## 九、gemini-sub 新模型实测结论 (2026-08-16)

| 模型 | 状态 | 说明 |
|------|------|------|
| claude-sonnet-4-6 / claude-opus-4-6-thinking | ✅ 可用 | 桥直接支持, harness 已加 |
| gemini-3-pro / gemini-3-flash / gemini-2.5-* / claude-4.5 系 | ✅ 可用 | 库原生支持 |
| gemini-3.7 / 3.6 / 3.5 / 3.1-pro | ❌ 403 | 库的 gemini 3.x 路由只认无版本号名; 已给 client.py 打补丁让
  resolve_gemini3_model 识别版本化名, 但 403 是路由/宿主层问题, 等 antigravity-auth 上游更新 |
| gpt-oss-120b | ❌ 403 | 库不支持该模型族 |

- 补丁位置: `.venv/site-packages/antigravity_auth/client.py` 的 is_pro/is_flash 正则 +
  `constants.py` 的 UA 版本(1.11.5→1.1.13)。venv 重装会丢, 重装后要重打。
- 已排查: 模型名语法(社区用 thinkingLevel 参数 + :antigravity 后缀路由, 库已实现)、
  限流状态(清 accounts.json)、UA 版本(1.1.13)——3.7 仍 403。
  推测: 库的默认 project_id 通道没覆盖 3.7(CLI 用自己 workspace 的 project),
  或请求体/requestType 差异。等 antigravity-auth 上游更新(模型表滞后于 CLI)。
- 探测成本警告: 一次调用 = 库内部 3 端点 × 3 重试 ≈ 9 个请求, 别连环试, 有风控风险。
- 谨慎原则: 探测性调用会污染库的限流状态 (accounts.json rateLimitResetTimes),
  恢复: 清空该字段 + pm2 restart gemini-sub-8120。

## 十、gemini-sub 根因修复 (2026-08-16): project_id + 版本化名不存在

**根因**: antigravity-auth 库写死了演示 project_id `rising-fact-p41fc`。
真实 Code Assist project 是 `bamboo-coast-6zftk` (通过 loadCodeAssist 获取)。
错误 project 下后端会**静默回落到默认模型**(请求 claude 返回 gemini-2.5-flash 的输出)，
而非报错——极其隐蔽。

**修复**: `constants.py` 里 `ANTIGRAVITY_DEFAULT_PROJECT_ID = "bamboo-coast-6zftk"`。

**关于版本化名 (gemini-3.7/3.6/3.5)**:
- 内部通道**不认版本化名** (404), 只有 `gemini-3-flash` / `gemini-3-pro`
- 无版本名 = 当前最新版 (gemini-3-flash 现在就是 3.7 Flash)
- thinking 通过 `-high/-low` 后缀 → thinkingLevel 参数, 不是模型名的一部分
- `gemini-3-pro` 在 Antigravity 通道 404 (当前无 pro 档)

**配额双通道**:
- Antigravity 配额: gemini-3-flash + claude 系 (走 cloudcode-pa 内部端点)
- Gemini CLI 配额: gemini-2.5-pro/flash (走 GEMINI_CLI_ENDPOINT 端点)

**最终确认 (2026-08-16 二轮排查)**:
- CLI 会话库记录的真实 wire 名: gemini-3.7-flash / gemini-3.7-flash-high / claude-sonnet-4-6 /
  gemini-3.5-flash-extra-low。版本化名在 CLI 侧真实存在。
- 桥侧照抄 CLI 请求(streamGenerateContent + 全名 + 真实 project + Bearer)仍 404
  "Requested entity was not found" → 桥无法直连版本化模型, CLI 请求链路有未复刻部分。
- 桥可用清单(已确认): gemini-3-flash(无版本别名, 当前 Antigravity agent persona)、
  claude-sonnet-4-6 / claude-opus-4-6-thinking / claude-4.5 系(Antigravity 通道)、
  gemini-2.5-flash/pro(Gemini CLI 配额通道)。
- 桥不可用: gemini-3.x 版本化名、gemini-3-pro、gpt-oss。
- 结论: "用桥拿 gemini 3.7" 到此为止(库/协议缺口), gemini 3.7 agent 活走 mcp__agy__agy_ask。

**loadCodeAssist 获取真实 project**:
```python
POST https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist
Headers: Authorization Bearer <token>, User-Agent antigravity/1.1.13 windows/amd64
Body: {"metadata": {"ideType": "ANTIGRAVITY"}}
→ response.cloudaicompanionProject
```

## 十一、故障档 · mcp__agy__agy_ask 超时 (2026-08-25)

dsh 会话调 agy MCP 立即 `MCP error -32001 timeout`, 同期 agy CLI 本体两轮联网调研全成功
(旁证: agy CLI 作为 client 连自己也 5 分钟握手不上 → 问题在 agy server 端)。
完整时间线/排查单/CLI 替代姿势: `docs/incident-agy-mcp-timeout-20260825.md`。
临时替代 = CLI 后台跑 (`agy --effort medium --print-timeout 10m --output-format text --print='...'`)。
