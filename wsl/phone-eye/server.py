"""fleet wrapper — phone-eye 舰队成员壳。

单一事实源在 ~/bh-workspace/app/phone-eye/server.py(独立可分发版; 2026-08-27
随槽位治理迁入 app 槽=增益产品线, infra 只留止损基建);
本壳只做两件事: 挂到 huamcp HTTP 传输 + 默认指向舰队视觉成员(8102)。
"""
import os
import pathlib
import sys

# 导航到独立版 server.py
import importlib.util

_HERE = pathlib.Path(__file__).resolve().parent
_CORE = _HERE.parents[3] / "app" / "phone-eye" / "server.py"
if not _CORE.is_file():
    raise SystemExit(f"phone-eye 舰队壳: 找不到独立版真身 {_CORE} (应在本机 app/phone-eye/, GitHub: boheastill/phone-eye)")
# 按路径加载为 phone_eye_core —— 本壳自身也叫 server, 直接 `import server`
# 在本壳被当作 server 模块导入时(fleet.sh test 的 import 冒烟)会递归命中自己。
_spec = importlib.util.spec_from_file_location("phone_eye_core", _CORE)
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)

for _p in _HERE.parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break

os.environ.setdefault("PHONE_EYE_VISION_URL", "http://127.0.0.1:8102/mcp")
os.environ.setdefault("ANDROID_SERIAL", "192.168.31.41:5555")  # 手机 Wi-Fi adb

import huamcp  # noqa: E402

mcp = huamcp.server(__file__)

# 复注册独立版的工具(同一函数对象, 描述同源)
for name in ("phone_look", "phone_tap", "phone_swipe", "phone_type", "phone_screenshot"):
    fn = getattr(core, name)
    mcp.tool()(fn)

if __name__ == "__main__":
    huamcp.run(mcp)
