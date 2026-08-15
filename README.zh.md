# 🔌 hua-mcp — MCP 舰队

一份代码、按宿主系统分桶、**一个 MCP 一个目录一个端口**。任何 agent(Win 的 Claude、WSL 的 Claude)只连 `localhost:<端口>`,不关心服务实际在哪台机跑。

## 结构

```
huamcp.py          共享运行时(绑定/health/鉴权/传输)——你只管写工具
fleet.sh           一键入口(validate/test/up/down/health/config…)
gen_config.py      扫描 */*/mcp.json → 生成客户端 .mcp.json
_template/         复制它来新建一个 MCP
win/   <name>/     Windows 主机启动(任务计划)
wsl/   <name>/     WSL 启动(PM2)
```

一个 MCP 目录 = `server.py` + `mcp.json` + `requirements.txt`(+`requirements.lock`)+ `run.sh`(wsl)/`run.ps1`(win)。`mcp.json`(`name`/`port`/`os`/`public`/可选 `auth_env`)是它**唯一的元数据**,没有中心 registry。

## 契约(为什么 agent 改它不易出错)

`server.py` 只做一件事:**声明工具**。横切关注点全在 `huamcp.py` 一处:

```python
import pathlib, sys
for _p in pathlib.Path(__file__).resolve().parents:
    if (_p/"huamcp.py").exists(): sys.path.insert(0, str(_p)); break
import huamcp

mcp = huamcp.server(__file__)          # 读自己的 mcp.json,绑定+/health+鉴权

@mcp.tool()
def my_tool(...): ...                   # ← agent 只动这里

if __name__ == "__main__":
    huamcp.run(mcp)                     # streamable-http(--stdio 切本地)
```

- **安全默认**:`huamcp` 绑 `127.0.0.1`。公网开放才用 `--public`(或 `HUAMCP_PUBLIC=1`)绑 `0.0.0.0`。WSL2 mirrored 网络下 `127.0.0.1` 仍 Win↔WSL 双向可达,所以安全默认不影响舰队。
- **统一鉴权缝**:`mcp.json` 里写 `auth_env`(或设 `HUAMCP_TOKEN`)并给该环境变量赋值后,除 `/health` 外所有路由都要 `Authorization: Bearer <token>`;不设 = 开放(本地)。**公网化 = 配一个环境变量,不改代码。**
- **统一 `/health`**:`{ok,mcp,os,port,public}`,每个 MCP 一致。

## 加 / 改 / 删一个 MCP

```bash
cp -r _template wsl/myname        # 或 win/myname;改 mcp.json(name==目录名/port/os)
# 在 server.py 写 @mcp.tool();依赖进 requirements.txt
uv pip compile requirements.txt -o requirements.lock   # 锁依赖(可复现)
./fleet.sh validate               # 校验:键全/端口唯一且在段内/文件齐(出错即退 1)
./fleet.sh test                   # 冒烟:每个 MCP 装依赖 + import server
./fleet.sh up                     # 起(wsl);win 重跑 win/install-autostart.ps1
```
删一个 MCP = 删目录(+ `./fleet.sh down` 前)。`fleet.sh`/`gen_config.py` 全靠扫描发现,**永不需要改中心文件**。端口段:`win 8001-8099`,`wsl 8100+`。

## 现有 MCP

| MCP | 端口 | 宿主 | 工具 |
|---|---|---|---|
| `vpn` | 8001 | Windows | `vpn_restart` `vpn_status` `vpn_connectivity_test` `vpn_logs` `vpn_config` `vpn_config_write` `vpn_apply` `vpn_switch_node` `vpn_route_test` |
| `identity` | 8101 | WSL | 9 个模型身份/运行环境检测 |
| `md2pdf` | 8110 | WSL | `md_to_pdf`;另开 REST `POST /pdf`(将来公网端点) |

> 范围:hua-mcp 只收**个人通用**工具。业务/项目耦合的企业级 MCP(如 `ics`)留在各自项目。

## 跑 / 自启(脚本都在仓库里)

```bash
./fleet.sh doctor     # 查 uv/node/pm2/nix
./fleet.sh up         # PM2 拉起全部 wsl MCP(各一进程)
./fleet.sh health     # 逐个 curl /health
./fleet.sh autostart  # pm2 save + 提示开机自启命令
./fleet.sh config     # 生成客户端 .mcp.json
# list / validate / test [--live] / down / restart / status / logs [name]
```

- **WSL 侧**:`./fleet.sh up` → `./fleet.sh autostart`(底层 PM2,详见 `PM2_MANUAL.md`)。开机自启已装好:systemd 单元 `pm2-bohea`(`pm2 startup` + `pm2 save` 生成),WSL 起来后自动 resurrect 全部 wsl MCP。
- **Windows 侧**(os=win):Windows 上管理员跑一次 `win/install-autostart.ps1`(登录自启,跑 `\\wsl.localhost` 路径下各 MCP 的 `run.ps1`)。完全静默(无窗口),日志落在 `%LOCALAPPDATA%\hua-mcp\<name>\server.log`。
- 跨边界靠 `.wslconfig` 的 `networkingMode=mirrored`(已开),两侧 Claude 用同一份 `gen_config.py` 输出。

## 疑难速查(踩过的坑,别再踩)

| 症状 | 根因 | 解法(已内建) |
|---|---|---|
| 服务里 node/Chromium 必崩 SIGABRT,手动跑却正常 | PM2 给子进程注入 `NODE_CHANNEL_FD`(IPC fd),孙代 node 拿到死 fd 直接 abort | `run.sh` 开头 `unset NODE_CHANNEL_FD`(模板已带) |
| 开机弹出可见控制台窗口,`-WindowStyle Hidden` 无效 | Windows Terminal 作为默认终端会无视 Hidden | 启动链用 `conhost.exe --headless`(`start-all.ps1` / `install-autostart.ps1` 已改) |
| 加了日志重定向后服务"起来即死" | PowerShell 在 `$ErrorActionPreference=Stop` 下,把原生程序被重定向的第一行 stderr(uvicorn 日志走 stderr)当成致命错误,杀掉进程 | 长驻进程用 `cmd /c "... >> log 2>&1"` 做重定向(`run.ps1` 模板已带) |

排查入口:WSL 侧 `pm2 logs mcp-<name>-<port>`;Windows 侧 `%LOCALAPPDATA%\hua-mcp\<name>\server.log`。从 WSL 测 Windows 自启链路要用 `Start-ScheduledTask -TaskName hua-mcp-win`(直接 interop 拉起的进程树会随命令结束被回收,测不准)。

## 可复现 / 可测

- 依赖锁定:python 用 `requirements.lock`(`uv pip compile`,run 脚本优先用它),node 用提交的 `package-lock.json`(`npm ci`),md2pdf 系统层用 `flake.lock` 钉 Chromium/字体。
- `./fleet.sh validate` + `./fleet.sh test` 是每次改动的安全闸门;`--live` 还会真起来 curl `/health`。

## 运维经验

新成员检查单、streamable-http 会话铁律(重启 MCP 后必须重启客户端)、各客户端接线位置、DSH 平滑重启、agy 特记 —— 见 [OPS_NOTES.md](OPS_NOTES.md)。
