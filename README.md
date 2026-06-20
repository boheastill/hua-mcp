# 🔌 hua-mcp — MCP 舰队

一份代码、按宿主系统分桶、**一个 MCP 一个目录一个端口**。任何 agent(Win 的 Claude、WSL 的 Claude)只连 `localhost:<端口>`,不关心服务实际在哪台机跑。

## 结构

```
fleet.sh           一键入口(扫描各 MCP,无需中心文件)
gen_config.py      扫描 */*/mcp.json → 生成客户端 .mcp.json
_template/         复制它来新建一个 MCP
win/               Windows 主机启动(任务计划)
  vpn/             server.py  mcp.json(:8001)  run.ps1  requirements.txt
  install-autostart.ps1   start-all.ps1
wsl/               WSL 启动(PM2)
  identity/        server.py  checker.py  mcp.json(:8101)  run.sh
  md2pdf/          server.py  renderer.py  templates/  flake.nix  mcp.json(:8110)  run.sh
```

每个 MCP **自包含、自描述**:目录里一个 `mcp.json`(`name`/`port`/`os`/`public`)就是它的全部元数据。`server.py` 读自己的 `mcp.json` 起服务,内联 `@mcp.tool()`,带 `GET /health`,默认 streamable-http(`--stdio` 可切本地)。**没有共享运行时、没有自动发现魔法、没有中心 registry**——打开一个目录就是一个完整的 MCP。

端口段:`win 8001-8099`,`wsl 8100+`。

## 现有 MCP

| MCP | 端口 | 宿主 | 工具 |
|---|---|---|---|
| `vpn` | 8001 | Windows | `vpn_restart`(原子重启 sing-box 服务) |
| `identity` | 8101 | WSL | 9 个模型身份/运行环境检测 |
| `md2pdf` | 8110 | WSL | `md_to_pdf`;另开 REST `POST /pdf`(将来公网端点) |

> 范围:hua-mcp 只收**个人通用**工具。业务/项目耦合的企业级 MCP(如 `ics`)留在各自项目,需要时让 agent 直接连它的端口即可。

## 加一个 MCP

```bash
cp -r _template wsl/myname      # 或 win/myname
# 改 mcp.json(name/port/os),在 server.py 写 @mcp.tool(),deps 进 requirements.txt
./fleet.sh up                   # wsl;win 则重跑 win/install-autostart.ps1
```
`fleet.sh` 和 `gen_config.py` 靠扫描 `*/*/mcp.json` 自动发现它,**不用改任何中心文件**。

## 跑 / 自启(自包含,脚本都在仓库里)

```bash
./fleet.sh doctor     # 查 uv/node/pm2/nix
./fleet.sh list       # 列出发现的 MCP
./fleet.sh up         # PM2 拉起全部 wsl MCP(各一进程)
./fleet.sh health     # 逐个 curl /health
./fleet.sh autostart  # pm2 save + 提示开机自启命令
./fleet.sh config     # 生成客户端 .mcp.json
# down / restart / status / logs [name]
```

- **WSL 侧**:`./fleet.sh up` → `./fleet.sh autostart`(底层 PM2,详见 `PM2_MANUAL.md`)。
- **Windows 侧**(os=win):Windows 上管理员跑一次 `win/install-autostart.ps1`(登录自启任务计划,跑 `\\wsl.localhost` 路径下各 MCP 的 `run.ps1`,无需二次 clone)。
- 跨边界靠 `.wslconfig` 的 `networkingMode=mirrored`,`localhost` 双向可达(已开启),故 Win/WSL 两侧 Claude 用同一份 `gen_config.py` 输出。
