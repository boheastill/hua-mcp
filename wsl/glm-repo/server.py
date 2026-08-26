"""GLM repo MCP — 智谱编程套餐专属「开源仓库」(zread, 基于 zread.ai) 的本地中继。

上游透传工具: search_doc(搜仓库知识文档/issue/pr) / get_repo_structure(目录结构) /
read_file(读仓库内文件)。仅支持 zread.ai 收录的公开 GitHub 仓库(owner/repo)。
调用计入智谱账户 MCP 额度(积分系数 ×1.2)。
Key 读取: GLM_API_KEY 环境变量 → ~/.glm/key.txt(与 glmvision 同一把, 已实测可过套餐 MCP 鉴权)。
"""
import pathlib
import sys

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

app = huamcp.relay(__file__, "https://open.bigmodel.cn/api/mcp/zread/mcp")

if __name__ == "__main__":
    huamcp.run_relay(app, __file__)
