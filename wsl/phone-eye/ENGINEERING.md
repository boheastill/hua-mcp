# Phone-Eye 工程实录(对内)

> 对外契约页: **github.com/boheastill/phone-eye**(本地 `app/phone-eye/`, 即 git 仓,
> 客户视角, 稳定; 本文可随意改)。对内文档包(档案/推广/产品/评审)在
> `app/phone-eye/.internal/`(gitignore, 不进公开仓)。
> 2026-08-25 v0.1 落地实录(M1 完成)。改内部实现前读这里, 改完更新这里。

## 一、它是什么(一句话)

hua-mcp 舰队第 10 个成员(端口 8122): 把"真手机屏幕"变成任何 MCP 客户端可调的工具
—— 看(phone_look) + 点/滑/输(phone_tap/swipe/type) + 截屏(phone_screenshot)。
一个实现喂 dsh/claude/codex/agy 四家。

**M1 架构变更(2026-08-25 晚)**: 独立可分发版 server.py 落在 `app/phone-eye/`
(单一事实源, 纯 FastMCP stdio, 零舰队依赖); **本目录 server.py 退化为薄壳**
(import 独立版, 挂 huamcp HTTP 传输 + 默认 env 指向舰队视觉成员)。
改代码 → 改 `app/phone-eye/server.py`, 两处(独立/舰队)同时生效。

⚠️ 壳的实现坑(2026-08-25 CR 修): 壳自己也叫 server, 用 `import server as core`
会在壳被当作 `server` 模块导入时(fleet.sh test 的 import 冒烟)递归命中自己 →
AttributeError。已改 `importlib.util.spec_from_file_location("phone_eye_core", ...)`
按路径加载, 勿改回。另: 截图文件名用毫秒时间戳(防同秒覆盖)。

## 二、部署形态(全部 2026-08-25 实测)

```
┌ sliver (笔记本, 192.168.31.109) ─────────────────────────┐
│ hua-mcp 舰队 (PM2)                                        │
│  ├ phone-eye MCP  :8122  ← 本体(server.py, ~180 行)      │
│  └ glmvision MCP  :8102  ← 视觉后端(GLM 4.6v-flash)      │
│ adb (android-tools 37)                                   │
│  └ -s 192.168.31.41:5555  ← 手机 Wi-Fi adb 直连           │
└──────────────────────┬───────────────────────────────────┘
                       │ LAN Wi-Fi "Part"
              📱 ares / K40G / Android 13 (192.168.31.41)
```

- 手机侧: `adb tcpip 5555` 一次(经 lb USB 触发), 之后 Wi-Fi 直连, 不依赖任何 USB。
- 密钥: sliver 复用了 lb 的 `~/.android/adbkey`(手机已授权过该密钥)→ 无需再点授权。
  ⚠️ 这意味着 sliver 与 lb 共享 adb 身份; 若手机重置授权, 两台都要重auth。
- 视觉链: phone-eye →(MCP streamable-http)→ glmvision → GLM API, 自动降级
  5v-turbo→4.6v-flash(订阅 1311 时)。隐私场景把 `GLMVISION_URL` 指向
  local-model(8105) 即可全离线(需为其补 describe_image 工具, 见待办)。

## 三、工具契约(对外稳定面, 改动需走版本号)

| 工具 | 签名 | 实现要点 |
|---|---|---|
| phone_look | (question?, use_tree=true) | screencap→临时文件→视觉 MCP SSE; +uiautomator dump 文本/坐标清单; 截图空(已知 MIUI 毛病)时提示走 use_tree |
| phone_tap | (x, y) | input tap |
| phone_swipe | (x1,y1,x2,y2,duration_ms=300) | input swipe |
| phone_type | (text) | 仅 ASCII(中文 adb 静默丢, 拒绝并提示剪贴板方案); 空格→%s |
| phone_screenshot | () | 存 /tmp/phone-eye/screen_*.png 返回路径 |

## 四、踩过的坑(内化, 别再踩)

1. **SSE 多行 data 帧**: 视觉 MCP 返回的 `data:` JSON 可能跨多行 → 必须按空行分帧
   聚合再解析; 逐行 json.loads 会 `Unterminated string`。
2. **requests 编码陷阱**: Content-Type 无 charset 时 requests 按 ISO-8859-1 解
   `.text` → 中文全变 å¥æª。**永远用 `r.content` + 显式 utf-8**。
3. base64 走 ssh 传文件: 输出可能混 stderr/换行 → `tr -d '\n\r '` 再解;
   二进制(adbkey)直接 `cat` 重定向最稳。
4. 手机 Wi-Fi adb 断线(重启/换网)后: `adb connect 192.168.31.41:5555` 重连;
   IP 由路由器 DHCP, 变了改 `ANDROID_SERIAL` env(pm2 --update-env)。
5. ~~`_template` 的 import 冒烟测试自败(历史遗留)~~ → 2026-08-25 已修: _template 补了
   requirements.lock(钉 mcp==1.28.0), fleet.sh new 不再删 lock; fleet.sh test 全绿。
6. **mcp 2.x 删了 fastmcp 路径**(M1 公开化时踩): `from mcp.server.fastmcp import
   FastMCP` 在 2.x `ModuleNotFoundError` —— requirements 必须锁 `mcp[cli]>=1.2.0,<2`
   (OPS_NOTES 已有的老坑, 换新环境就会重演)。

## 五、验证记录(2026-08-25, 全链路)

1. `phone_screenshot` → `/tmp/phone-eye/screen_*.png` ✅
2. `phone_look` 中文返回正常(vision+ui-tree 双通道, 含按钮精确 bounds)✅
3. **dogfood 闭环**: phone_look 发现手机上挂着 USB 授权弹窗 → 读出"确定"按钮
   坐标 → phone_tap (763,2232) → 复查弹窗仍在(坐标偏移)→ tap(763,2200) →
   `adb shell echo` 直接通 ✅ — **产品用自己的眼睛和手完成了自身的设备配置**。
4. dsh headless 代理调 `mcp__phone-eye__phone_screenshot` 返回路径 ✅
5. 四客户端接线: dsh(web+headless patch)/claude(.claude.json)/agy/codex ✅

## 六、待办(Phase 2 候选, 按价值排)

- [ ] local-model 补 describe_image → phone-eye 可全离线(隐私卖点兑现)
- [ ] phone_look 结果缓存 N 秒(连续 tap+look 循环省 API)
- [ ] 多设备: ANDROID_SERIAL 参数化到工具级(fleet 场景)
- [ ] uiautomator dump 失败时的退化策略已内建, 但 dump 本身偶尔 0 字节 → 重试 1 次
- [ ] 独立打包(npm/pip)+ awesome-dsh-plugin 收录申请 → 对外发布动作
- [ ] GitHub 公开仓 + README(对外页直接搬) + 相位承诺对齐

## 七、事实源与关联

- 对外 README: `README.md`(同目录) — 客户语言, 接口承诺, 不写实现
- 踩坑手册(手机基建): `~/bh-workspace/infra/phone/手机测试基建-踩坑手册.md`
- 舰队接线: `~/bh-workspace/infra/hua-mcp/CLIENTS.md`
- 分享战略: `~/bh-workspace/docs/dsh-mobile-access/README.md` §七
