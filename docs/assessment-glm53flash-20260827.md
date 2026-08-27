# GLM-5.3-Flash 对舰队的影响评估 — glm* 四服务盘点与更新建议

> 2026-08-27, 由 zcode 会话在"dsh 接入 glm-5.3-flash"任务中顺带排查产出。
> 背景：智谱 2026-08-26 发布 **GLM-5.3-Flash**（320B-A18B 原生多模态，1M ctx/128K 输出，
> 已纳入 GLM Coding Plan 订阅，**订阅内耗额 ≈ glm-5.3 的 1/3**，非高峰时段再半价）。
> 本文档只描述与建议，不替执行者拍板；所有"未实施"项均标注。

## 一、盘点结论（谁真调 GLM 模型）

| 服务 | 端口 | 调什么 | 要不要更新 |
|---|---|---|---|
| `wsl/glmvision/server.py` | 8102 | **直调 chat completions**：按量端点 paas/v4，视觉降级链 glm-5v-turbo→4.6v-flash→4v-flash | **唯一候选**（见 §三） |
| `wsl/glm-reader` | 8106 | 纯中继官方 MCP 网关 `api/mcp/web_reader/mcp`，不带模型名 | 不用动 |
| `wsl/glm-search` | 8100 | 纯中继 `api/mcp/web_search_prime/mcp` | 不用动 |
| `wsl/glm-repo` | 8107 | 纯中继 `api/mcp/zread/mcp`（zread.ai） | 不用动 |

三个 relay 类共用同一把 GLM_API_KEY（环境变量 → `~/.glm/key.txt`），走的是**套餐 MCP 鉴权**，
与新模型发布无关，无版本耦合。

## 二、实测数据点（2026-08-27，GLM_API_KEY 直连 curl）

1. **coding 端点** `/api/coding/paas/v4/chat/completions` + glm-5.3-flash：
   文本 ✅、图像输入 ✅（base64 PNG 正确识别颜色）、`reasoning_effort` ✅。
   订阅额度在此生效 —— 这是 flash 的"主场"。
2. **按量端点** `/api/paas/v4/chat/completions` + glm-5.3-flash：**HTTP 429 / 1113 余额不足**。
   即 glmvision 现用端点上 flash 吃不到订阅红利，无余额就不可用（按量计费 1/10 价也得起充）。
3. 视觉老将 `-v` 系列（5v-turbo / 4.6v-flash / 4v-flash)**不在 coding 端点的模型清单里**
   （该清单只有文本系模型），仍只在按量端点可调 ⇒ 不能把 glmvision 整体切到 coding 端点了事。

## 三、glmvision 更新建议（**未实施**，落地前按此思路改+冒烟）

现状痛点（08-27 基线）：无余额账户下每次冷调用先吃 5v-turbo 一趟 429 才落到免费档；
服务端 `_post` 单跳上游超时 180 秒 vs MCP 客户端 30 秒预算——当天两次真实调用全部
客户端超时（pm2 在线、日志确认请求已受理）。

最小改法：`describe_image` 在现有 CHAIN **之前**加一步"coding 端点 + glm-5.3-flash"，要点：

- 新增常量 `CODING_API = ".../api/coding/paas/v4/chat/completions"`，仅这一步用它；
- 该步非 200（含 429/1113/其他）一律静默落入原链，行为向后兼容；
- `_last_good` 记忆需同时记 {model, endpoint}，否则 30 分钟窗口内可能从错的入口起步；
- flash 输出上限给 4096，同现链旗舰档；
- 冒烟判据：一张本地 PNG 走 `describe_image` ≤30s 返回且内容正确，pm2 日志无异常堆栈。

收益：默认路径落在订阅额度内（≈5.3 的 1/3 耗额）、免充值、少一趟 429 空转，
且 flash 原生多模态为当前链内最强档（AA 综合指数与 Opus 4.8 持平的口径出自官方页）。
风险小：改动集中在单工具函数，原链原样保留作退路。

## 四、关联变更备忘（同期完成，详见各自台账）

- dsh 侧已于同日接入 flash 并清库（`~/.dsh/settings.yaml`：zhipu 两路由各只留
  flash + glm-5.3，默认模型与会话标题均走 flash）；developer 角色坑与复合法见
  `~/bh-workspace/agent/dsh-guide.md` §二。
