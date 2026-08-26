"""context7 MCP — Upstash Context7(免费远程) 的本地中继。

上游透传工具: resolve-library-id(找库) / get-library-docs(按版本拉最新文档+代码示例)。
免费端点无需鉴权(auth_required=False); 若日后配了 API key 提高速率上限:
  环境变量 CONTEXT7_API_KEY 或 ~/.context7/key.txt, 中继自动带上, 免重启。
"""
import pathlib
import sys

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

app = huamcp.relay(
    __file__,
    "https://mcp.context7.com/mcp",
    auth_env="CONTEXT7_API_KEY",
    key_paths=("~/.context7/key.txt",),
    auth_required=False,
)

if __name__ == "__main__":
    huamcp.run_relay(app, __file__)
