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
| 联网查资料 / 搜最新信息 | `mcp__glm-search__web_search_prime` | 套餐搜索 ×1.2积分/次, 比 agy 便宜直接; 搜完要深读推理再交 agy |
| 读具体网页 / 抓正文 | `mcp__glm-reader__webReader` | 主模型无浏览器时的读页通道(×1.2积分/次) |
| 吃透一个公开 GitHub 仓库 | `mcp__glm-repo__search_doc` 等 | zread 文档/结构/文件三件套, 先于 clone 通读(×1.2积分/次) |
| 浏览网页/操作网页(非 ZCode 客户端) | `mcp__browser__browser_navigate` 等 | Playwright 常驻, 全端浏览器自动化; ZCode 自己优先用内置 browser-use |
| 查新版库的准确 API/用法 | `mcp__context7__query-docs` | 免费按版本拉最新文档, 压 GLM/DeepSeek 的版本幻觉; 先 resolve-library-id 拿 ID |
| 查 SQLite/Postgres 数据 | `mcp__db-browser__sqlite_query` 等 | 引擎级只读优先, 写库显式 write=true; 拿到陌生 .db 先 sqlite_schema |
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

## 十二、BigModel 套餐专属 MCP 中继 (2026-08-26 接入)

智谱编程套餐四个专属 MCP(文档 docs.bigmodel.cn/cn/coding-plan/mcp/): 视觉理解/联网搜索/网页读取/开源仓库(zread)。
接入决策与实锤:

- **三个远程 HTTP 型以本地中继成员入舰队**: `glm-search:8100`(web_search_prime)、
  `glm-reader:8106`(web_reader)、`glm-repo:8107`(zread)。server.py 各 ~15 行, 核心就一句
  `huamcp.relay(__file__, 上游URL)`(plumbing 在 huamcp.py, §见下)。
  **取舍**: 直连远程 MCP 得把 Bearer key 复制进 4 个客户端配置(dsh 的 dsh-mcp-client 还未必支持自定义 header);
  中继后客户端照常连 localhost 零凭据, key 只存 `~/.glm/key.txt` 一处(与 glmvision 同一把,
  **已实测该 key initialize 200 过套餐 MCP 鉴权**), 且统一进 pm2/health/接线流程。
- **额度**: 联网搜索/网页读取/zread 每次调用 ×1.2 积分; 视觉 MCP 是 GLM-5.3-Flash ×8。中继不缓存, 省额度靠少调。
- **实测要点**: 搜索工具真名 `web_search_prime`(文档页写的 `webSearchPrime` 不准), 必填 `search_query`
  (另有 search_domain_filter / search_recency_filter: oneDay~noLimit / content_size: medium|high / location: cn|us);
  reader 工具 `webReader(url, ...)`; zread 三件套 `search_doc` / `get_repo_structure` / `read_file`
  (仅限 zread.ai 收录的公开 GitHub 仓库, owner/repo 格式)。
- **中继工具的 description 是上游透传的, 本地改不了** — §七委托指南写不进它们的工具描述, 只在本档。
- **视觉理解 MCP 未入舰队**(有意取舍): 官方是 npm stdio 包 `@z_ai/mcp-server`(8 工具, 需 Z_AI_API_KEY,
  积分 ×8)。舰队 glmvision(8102, 按量+429 自动降级) + ZCode/Claude 内置 image_analysis 已覆盖看图主力场景;
  桥接 stdio→HTTP 要给纯 Python 舰队引 node 常驻, 不值。真需要专用工具(ui_to_artifact/ui_diff_check/video_analysis)时
  按官方文档给单个客户端直连:
  `claude mcp add -s user zai-mcp-server --env Z_AI_API_KEY=<套餐key> -- npx -y @z_ai/mcp-server@latest`。
- **huamcp.relay 实现注意**: hop-by-hop 头(content-length/content-encoding 等)不过河;
  GET 长连流不设 read 超时; 上游 401/限流**原样透传**不掩盖; key 每请求重读, 换 key 免重启;
  /health 额外带 `upstream` 与 `key_ok` 字段可快速排障。

## 十三、生产力三件套 browser/context7/db-browser (2026-08-27 接入)

调研 2026-08 MCP 生态后补的三个缺口(Playwright 是全球用量第一), 全部实测通过:

- **browser:8108 — npm 原生成员(舰队第三种形态)**: run.sh 直接常驻
  `npx -y @playwright/mcp@latest --host 127.0.0.1 --port 8108 --browser chromium --headless`,
  server.py 只留契约占位(不声明工具), requirements.txt 仅注释。要点:
  - 启动前 `npx -p @playwright/mcp playwright install chromium` 兜底装浏览器(缓存于
    `~/.cache/ms-playwright`, 已预装 113MB headless-shell 152); pm2 重启秒起。
  - mcp.json 标 `heavy: true`(pm2 1G 档)。chromium 常驻 ~130MB。
  - **它没有 /health 端点** → `fleet.sh health` 已加兜底: /health 不通时改 POST /mcp
    initialize, 任何 <5xx 的 HTTP 应答即视为存活(输出注明 "alive via /mcp")。
  - **set -e 陷阱(实锤)**: health 的 `code=$(curl ...)` 对 DOWN 端口返回非零, 赋值失败
    直接杀死整个脚本(fleet health 静默无输出, exit 7)——已修(`|| code=000`)。
    在 fleet.sh 里新增任何裸 `$(curl/命令替换)` 都要带 `|| 兜底`。
- **context7:8109 — 免鉴权中继**: `huamcp.relay(..., auth_required=False)`(relay 新增
  可选鉴权参数); 上游 Context7 4.0.3 工具名已改: `resolve-library-id` + `query-docs`
  (网上旧文档的 get-library-docs 已废弃)。上游是 **stateless MCP**(initialize 不返回
  mcp-session-id 头), 中继透传无碍; 免费档有速率限制, 提速可配 CONTEXT7_API_KEY
  (env 或 ~/.context7/key.txt, 中继自动带上)。
- **db-browser:8111 — 自研门面**: sqlite_query/sqlite_schema + pg_query/pg_schema。
  - 安全模式: SQLite 默认 URI `mode=ro`(**引擎级**只读, 写语句报
    "attempt to write a readonly database", 已实测); PG 默认会话
    `default_transaction_read_only=on`。写库必须显式 `write=true`(自动 commit)。
  - PG 连接: `dsn` 参数或环境变量 `PG_DSN`(pm2 进程加 env 后要 restart
    mcp-db-browser-8111); 无 DSN 时工具返回指引而非报错崩溃。
  - 结果防失控: 默认 max_rows=50 截断, 单元格 500 字符截断。

## 十四、长期化四件套 verify/secrets/dry-run/clients + 沙箱决策 (2026-08-27)

调研吸收落地(吸收源与理由见当日调研结论), 全部零新依赖、不动 pm2 架构:

- **`fleet.sh verify`** — 协议级 E2E: 每成员真跑 MCP initialize + tools/list,
  打印工具数与上游 serverInfo。能抓 /health 抓不到的病(venv 坏/工具代码坏/中继上游挂)。
  **只读不重启**(绝不静默 pm2 restart, 不会打断客户端会话); 实测 16/16 全绿。
- **`fleet.sh secrets`** — 密钥审计: 元数据在 mcp.json 可选 `secrets: [{env, path,
  optional?, note?}]`(auth_env 自动并入为 optional)。查存在性+0600; required 缺失才 FAIL。
  当前台账: glm 全家+glmvision 用 ~/.glm/key.txt, kimi 用 ~/.kimi/key.txt, ics-core 用
  ~/.ics/token(均 600 ✓), context7 key 可选未配。
- **`install-clients --dry-run`** — 五端变更预览(+/~/stale 一览)再落盘。
  坑: dsh 的 cordis.patch.yml 允许 `!!js` 表达式, `yaml.safe_load` 直接抛异常 —
  已用宽容 loader(未知 tag 置 None)+ 正则兜底双保险。
- **mcp.json 可选 `clients` 字段** — 成员级注册白名单(claude/codex/agy/dsh/zcode),
  缺省=全端。控制工具列表噪音(每多一条成员, 所有客户端会话的系统提示词就多一分)。
  validate 会校验未知 client 名。当前无人使用(行为零变化), 需要时再加。
- **沙箱硬化决策(有意不做 per-member systemd unit)**: 威胁模型=全回环+单用户,
  真实风险面是"本用户任意进程", 给个别成员单开 unit 会破坏 pm2 统一模型
  (resurrect 链复杂化=长期维护成本↑), 收益不抵。已落地的等效缓解:
  db-browser 引擎级只读+显式 write; 真要隔离某成员时的 opt-in 配方:
  `systemd-run --user --scope -p ProtectHome=read-only -p PrivateTmp=yes \
    -- pm2 start <dir>/run.sh ...`(临时) 或独立 user unit + `ProtectHome=read-only`
  (常驻, 但该成员要移出 pm2 改自启清单, 三思)。
- **待决观察**: md2pdf `public:true` 且 MD2PDF_TOKEN 未设 = LAN 开放的 PDF 生成器
  (回环外可达)。secrets 审计以 ⚠ optional 提示。要收紧: 设 MD2PDF_TOKEN 后
  `pm2 restart mcp-md2pdf-8110` + 客户端 header, 或把 public 改回 false。
- **Smithery 发布决策**: phone-eye 已加 podman 实测过的 Dockerfile+README Docker 段
  (f6c047a); smithery.yaml 的 configSchema 注入机制当时文档 404 无法验证,
  **不发布未验证的 manifest** — 提交时对照 smithery.ai 活文档写(stdio 型,
  需 ANDROID_SERIAL/PHONE_EYE_VISION_URL 两个 config 字段)。
