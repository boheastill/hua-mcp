# phone-eye (舰队成员, 端口 8122)

> **产品页与真身已独立可分发**: [~/bh-workspace/infra/phone-eye](../../phone-eye)
> (GitHub: boheastill/phone-eye)。本目录只是舰队接线壳。

## 本目录里有什么

- `server.py` — 薄壳: 按路径加载独立版 `infra/phone-eye/server.py`, 把它的 5 个工具
  (`phone_look` / `phone_tap` / `phone_swipe` / `phone_type` / `phone_screenshot`)
  复注册到 huamcp HTTP 传输上。改工具实现去独立仓库, 别在这里改。
- `mcp.json` / `run.sh` / `requirements.txt(.lock)` — 舰队标准元数据与启动器。
- `ENGINEERING.md` — 工程实录(对内)。

## 默认环境变量(壳里 setdefault)

| 变量 | 默认 | 说明 |
|---|---|---|
| `PHONE_EYE_VISION_URL` | `http://127.0.0.1:8102/mcp` | 视觉后端(舰队 glmvision); 隐私场景可指本地模型 |
| `ANDROID_SERIAL` | `192.168.31.41:5555` | 手机 Wi-Fi adb 直连; IP 变了改这里(pm2 --update-env) |

## 已知边界(踩坑实录见 ENGINEERING.md)

- 壳依赖本机存在 `~/bh-workspace/infra/phone-eye/` 检出(相对路径导航); 缺失时启动即报错退出。
- `phone_type` 仅 ASCII(adb 限制); 中文走设备剪贴板。
- MIUI 长会话后 `screencap` 偶发空输出 → 重试或重启手机。
