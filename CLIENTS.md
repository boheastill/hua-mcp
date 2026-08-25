# CLIENTS — 舰队 MCP → 本机 agent CLI 接线手册

> 一页说清:哪些 CLI 接了舰队、配置落在哪、怎么重新同步、坏了怎么查。
> 舰队本身见 [README.zh.md](README.zh.md);运维铁律见 [OPS_NOTES.md](OPS_NOTES.md)。
> 2026-08-25 首次全量接线(含 ics-core),此后新增成员按 §4 重同步。

## 1. 接线总览(2026-08-25 状态)

统一地址 `http://localhost:<port>/mcp`(streamable-http,本机回环;
WSL2 mirrored 网络下 Win 侧同样可达)。

| CLI | 配置位置 | 写入方式 | 覆盖成员 | 实测 |
|---|---|---|---|---|
| **Claude Code** | `~/.claude.json` 顶层 `mcpServers` | 手写 / gen_config.py 粘贴 | 全部成员 | 既有 ✅ |
| **Codex** | `~/.codex/config.toml` `[mcp_servers.*]` | `codex mcp add --url <url> <name>`(全局) | 全部成员 | enabled ✅ |
| **agy**(Antigravity 系) | `~/.gemini/config/mcp_config.json` | `agy mcp add <name> <url>` | 全部成员 | enabled ✅ |
| **dsh web** | `~/.dsh/profiles/web/cordis.patch.yml` 末尾 `insert:` 块 + `@deepseek-ai/dsh-mcp-client` 依赖 | 手写 YAML(dump-config 验证) | 全部成员 | 组合 ✅(重启生效) |
| **dsh headless** | `~/.dsh/profiles/headless/cordis.patch.yml` 同上 | 同上 | 全部成员 | **live ✅ 工具注册** |

成员数以 `python3 gen_config.py` 输出为准(写死数字必漂移——2026-08-25 一天内 9→10→11 三连改)。

antigravity-cli 与 agy 共用 `~/.gemini/config/mcp_config.json`,一处写入两边生效。

**dsh 的 MCP 工具名**: `mcp__<serverName>__<tool>`(与 Claude/Codex 同款),
如 `mcp__ics-core__push_message`。

> **local-model 说明**(2026-08-25 v2 重写): 后端已从本机死掉的 ollama 切到 **lb 台式机
> llama-server**(`http://192.168.31.71:8080/v1`),`local_ask` 自动发现活模型(单卡互斥换模型
> 零改动), 新增 `local_vision` 本地看图(qwen3.8-27b 多模态)。模型资产单一事实源:
> `~/bh-workspace/docs/model-registry/README.md`。dsh 侧另有原生 provider `lb-local`
> (~/.dsh/settings.yaml), 可让 dsh 直接作为本地模型跑。

## 2. 舰队成员与端口(gen_config.py 是唯一事实源)

```
cd /home/bohea/bh-workspace/infra/hua-mcp && python3 gen_config.py
```

vpn:8001(Win) · identity:8101 · glmvision:8102 · agy:8103 · **ics-core:8104** ·
local-model:8105 · md2pdf:8110 · printctl:8120 · paper-hub:8121 · **phone-eye:8122**
(公开项目 github.com/boheastill/phone-eye, 舰队壳 wsl/phone-eye 复用其 server.py) ·
**zcode-bridge:8123**(重活委托进 zcode 的 1.5x 额度通道, 见文末追加节)

## 3. dsh 专属:插件接线法

dsh 不内置 MCP 客户端,用官方插件 `@deepseek-ai/dsh-mcp-client`
(一个实例管一个服务器,一个 entry 一个 `serverName`)。

已装依赖(两档都装了):

```bash
dsh plugin --profile web add @deepseek-ai/dsh-mcp-client
dsh plugin --profile headless add @deepseek-ai/dsh-mcp-client
```

patch 写法(**新增条目必须用无 id 的 `- insert:` 行**;带 id 会被当覆盖,
报 `patch: entry "xxx" not found`——2026-08-25 踩过):

```yaml
- insert:
  - id: mcp-ics-core                      # 条目 id,习惯 mcp-<成员名>
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: ics-core                # 决定工具前缀 mcp__ics-core__*
      transport: streamable-http
      url: http://localhost:8104/mcp
```

验证与生效:

```bash
dsh --profile <p> --dump-config | grep -c dsh-mcp-client   # 应等于当前成员数(对齐 gen_config.py), 且无 warn
# web 档重启后生效(正在跑的 GUI 重启即断当前会话,挑空闲时机)
# headless 每次新进程自然生效
```

## 4. 新增舰队成员的重同步清单

1. `cp -r _template wsl/<name>` 起服务(见 README.zh.md),`fleet.sh up`
2. `python3 gen_config.py` 拿到新 JSON
3. 逐 CLI 写入:
   - Claude: `~/.claude.json` 的 `mcpServers` 加一项
   - Codex: `codex mcp add --url http://localhost:<port>/mcp <name>`
   - agy: `agy mcp add <name> http://localhost:<port>/mcp`
   - dsh: 两个 profile 的 `cordis.patch.yml` 各加一个 `- id: mcp-<name>` 块
4. `codex mcp list` / `agy mcp list` / `dsh --dump-config` 三处核验

## 5. 疑难速查

| 症状 | 根因 | 解法 |
|---|---|---|
| 工具在但调用报 `Session not found (-32600)` | 舰队服务端重启过,客户端会话作废(OPS_NOTES §二铁律) | 重启 dsh 进程;Claude/Codex/agy 新开会话 |
| dsh 启动报 `patch: entry "mcp-x" not found` | patch 行带了 id 当新增用 | 改成无 id 的 `- insert:` 列表(见 §3) |
| dsh 工具列表没有 mcp__* | 正在跑的进程早于 patch 写入 / 插件未装 | 重启该 profile;确认 `dsh plugin ls` 里有 dsh-mcp-client |
| codex `mcp list` 显示 Auth: Unsupported | OAuth 发现标记,本地舰队无需鉴权 | 忽略,正常 |
| 某成员 health 不通 | PM2 挂了 / 端口变更 | `./fleet.sh health` → `./fleet.sh restart <name>` |
| agent 沙箱里 `pm2 ls` 空表, 但 health 全绿 | HOME/PM2_HOME 被沙箱改写, 连到别的 daemon(OPS_NOTES §七点五) | 前缀 `PM2_HOME=/home/bohea/.pm2 pm2 ...` |
| ics-core 调用 401 | 服务端 token 轮换 | 改 `~/.ics/token`(600 权限, 不进 git)或设 `ICS_TOKEN` env → `PM2_HOME=/home/bohea/.pm2 pm2 restart mcp-ics-core-8104`(见 ics-mcp-server/README.md) |

## 2026-08-25 追加: zcode-bridge (8123)

- 工具: `zcode_task`(一次调用=派活+阻塞等结果, 重编码活专用, GLM-5.3 OAuth 1.5x 通道) / `zcode_status`
- 已接线: dsh web+headless profiles / claude.json / codex config.toml / gemini mcp_config.json (gen_config.py 已重跑)
- **各客户端需重启一次加载**; 依赖链: mcp(8123) → bridge-api(9230, systemd) → zcode(9222, systemd `zcode-bridge.service`)
- 排障从底层往上: `systemctl --user status zcode-bridge zcode-bridge-api` → `curl 127.0.0.1:9230/health` → `curl 127.0.0.1:8123/health`
