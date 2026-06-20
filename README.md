# 🔌 hua-mcp — 分布式 MCP 舰队

按**运行环境物理隔离**、用**端口**暴露的 MCP Server 集合。任何 agent（Windows 上的 Claude、WSL 里的 Claude）都只看 `localhost:<端口>`，不关心服务实际跑在哪台 / 哪个系统 —— 这是这套架构的核心价值。

> 这里是所有 MCP 的**唯一正主**。其它目录（如旧的 `mcp-servers/`）逐步并入，新 MCP 直接生在这里。

## 拓扑（唯一真相源 = `registry.json`）

| Server | 端口 | 宿主 | 传输 | 工具 | 自启 |
|---|---|---|---|---|---|
| `win-agents` | 8001 | **Windows** | streamable-http | vpn_restart（原子重启 sing-box 服务） | Win 任务计划 |
| `wsl-agents` | 8002 | WSL | streamable-http | identity_checker | PM2 |
| `cloud-api` | 8003 | WSL | streamable-http | （待填） | PM2 |
| `md2pdf` | 8010 | WSL | streamable-http + REST `/pdf` | md_to_pdf | PM2 |

> **范围**：hua-mcp 只收**个人通用**工具。项目/业务耦合的「企业级」MCP（如 `ics/ics-mcp-server`）留在各自项目里，**不并入**；需要时在 `registry.json` 登记其端口即可被同一份客户端配置发现。

端口段约定：`8001-8009` 按环境划分的多工具服务器；`8010+` 重型 / 单一职责 / 拟公开服务（一个一进程一端口，崩了不连累别人）。**改拓扑只改 `registry.json`**，server 配置、客户端配置、健康检查都从它派生。

每个 server 都有统一的 `GET /health`，MCP 端点在 `/mcp`。

## 架子：怎么扩（长期 ROI 的关键）

**加一个工具** → 在对应 server 的 `tools/` 丢一个 `<名字>.py`，定义 `register(mcp)`，里面 `mcp.tool()(你的函数)`。重启即生效，**不用动 server 文件**（`shared/fleet.py` 自动发现；`_` 开头的文件会被忽略，见 `cloud_api_agents/tools/_template.py`）。

**加一个 server** → 在 `registry.json` 加一条；env 服务器照抄某个 5 行 `*_mcp_server.py`（只调用 `fleet.serve("名字")`）；重型服务放 `servers/`，自带 `flake.nix`/`run.sh`。

**强环境隔离**：依赖互不污染（`pywin32` 只在 `win_agents`，Chromium 只在 `servers/md2pdf` 的 Nix 结界）。每个 server 一个 `.venv` + 独立 `requirements.txt`，由各自的 `run.sh`/`run.ps1` 拉起。

## 客户端配置（Win / WSL 通用）

```bash
python shared/gen_config.py          # 从 registry.json 生成 .mcp.json 片段
```

因为 `.wslconfig` 已开 `networkingMode=mirrored`，`localhost:<端口>` 双向可达，所以 **Windows 的 Claude 和 WSL 的 Claude 用同一份配置**，四个 server 都能调。

## 一键运行（自包含，所有脚本都在仓库里）

```bash
./fleet.sh doctor     # 检查 uv/node/pm2/nix 是否就绪
./fleet.sh up         # PM2 拉起全部 WSL 服务（wsl/cloud/md2pdf）
./fleet.sh health     # 从 registry 逐个 curl /health
./fleet.sh autostart  # pm2 save + 提示开机自启那行命令
./fleet.sh config     # 生成客户端 .mcp.json
# 其它：down / restart / status / logs [name]
```

## 进程守护 / 开机自启

- **WSL 侧**（wsl/cloud/md2pdf）：`./fleet.sh up` → `./fleet.sh autostart`（按提示执行 `pm2 startup` 给出的那行 sudo）。底层就是 PM2 + `ecosystem.config.js`，细节见 `PM2_MANUAL.md`。
- **Windows 侧**（win-agents:8001）：在 Windows 上以管理员跑一次 `win_agents/install-autostart.ps1`（登录自启的任务计划，直接跑 WSL 路径下的 `run.ps1`，无需二次 clone）。

## 目录

```
fleet.sh                   一键入口（up/down/health/config/autostart/doctor）
registry.json              拓扑唯一真相源
ecosystem.config.js        PM2（WSL 侧）
shared/fleet.py            通用运行时：读 registry + 工具自动发现 + /health
shared/gen_config.py       从 registry 生成客户端 MCP 配置
win_agents/   wsl_agents/   cloud_api_agents/   每个 = 5行 server.py + tools/ + run.*
servers/md2pdf/            重型隔离服务（自带 flake.nix）
```
