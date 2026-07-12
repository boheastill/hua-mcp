# 🛠️ PM2 终极运维指南 (MCP 宇宙版)

本指南包含了所有你需要的 PM2 操作命令，用于管理 `hua-mcp` (MCP 宇宙) 中的常驻服务。

---

## 1. 初始安装与启动

如果你的环境还没有 PM2，请先全局安装（需要 Node.js 环境）：
```bash
npm install -g pm2
```

进入项目根目录，用 `fleet.sh` 一键启动所有 WSL 侧 MCP（它扫描各 `wsl/<name>/mcp.json`，按 `mcp-<name>-<port>` 注册到 PM2，无需中心配置文件）：
```bash
cd /home/bohea/code-workspace/hua-mcp
./fleet.sh up          # 等价于对每个 wsl MCP 跑 pm2 start <dir>/run.sh
./fleet.sh status      # = pm2 ls
```
（已无 `ecosystem.config.js`；进程名形如 `mcp-identity-8101`、`mcp-md2pdf-8110`。）

---

## 2. 设置开机自动启动 (守护进程)

为了让 WSL/Linux 重启后，MCP 服务器能自动恢复运行：

**第一步：保存当前正在运行的进程列表**
```bash
pm2 save
```

**第二步：生成开机自启脚本**
```bash
pm2 startup
```
*(⚠️ 注意：执行此命令后，PM2 会在终端最后输出一行以 `sudo env PATH...` 开头的命令，你需要**复制那一行代码**并在终端再执行一次，才能真正生效！)*

---

## 3. 日常监控与运维 (高频指令)

- **查看所有服务状态（列表）**
  ```bash
  pm2 list
  # 或者简写
  pm2 ls
  ```

- **打开实时监控面板（黑客仪表盘）**
  ```bash
  pm2 monit
  ```
  *可以实时查看各个 MCP server 的 CPU、内存占用以及滚动的日志。*

- **查看服务日志（排错必备）**
  ```bash
  pm2 logs                # 查看所有服务的混合日志
  pm2 logs mcp-identity-8101   # 仅查看 WSL 服务的日志
  pm2 logs --lines 100    # 查看最后 100 行日志
  ```

---

## 4. 控制与管理命令

- **重启服务**
  ```bash
  pm2 restart mcp-identity-8101  # 重启单个服务
  pm2 restart all           # 重启所有服务 (修改代码后常用)
  ```

- **停止服务**
  ```bash
  pm2 stop mcp-identity-8101     # 停止单个服务
  pm2 stop all              # 停止所有服务
  ```

- **重载服务 (零停机热重载，适合高可用场景)**
  ```bash
  pm2 reload all
  ```

- **删除/移除服务 (不再用 PM2 接管它)**
  ```bash
  pm2 delete mcp-identity-8101   # 删除单个
  pm2 delete all            # 清空列表
  ```

---

## 5. 常见问题排查

如果某个 MCP Server 一直显示 `errored` 或者不断重启：
1. 先用 `pm2 logs mcp-identity-8101` 看最后报错的具体信息。
2. 确认 `uv` 是否在系统 PATH 中，如果 PM2 找不到 `uv`，服务会起不来。
3. 检查代码本身是否有 SyntaxError 导致一启动就崩溃。
4. **服务里再起 node(puppeteer/mmdc 等)必崩 SIGABRT、但手动跑正常**：PM2 会向子进程注入
   `NODE_CHANNEL_FD` 环境变量（它的 IPC 管道 fd），孙代 node 拿到一个已失效的 fd 直接 abort。
   解法：`run.sh` 开头 `unset NODE_CHANNEL_FD`（`_template/run.sh` 已内建）。

## 6. 本机开机自启（已配置）

本机已装 systemd 单元 `pm2-bohea`（`sudo env "PATH=$PATH:<nvm bin>" pm2 startup systemd -u bohea --hp /home/bohea` 生成，
注意 `"PATH=..."` 必须带引号——WSL 的 PATH 里混有带空格的 Windows 路径）。改动进程列表后记得 `pm2 save`，
否则重启后 resurrect 的还是旧快照。验证：`systemctl is-enabled pm2-bohea`。
