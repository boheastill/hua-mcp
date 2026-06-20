# md2pdf 使用指南

## 生成 PDF

MCP 协议调用（推荐）：

```python
import json, base64, requests

s = requests.Session()
init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "agent", "version": "1.0"}}}
r = s.post("http://localhost:8110/mcp", json=init, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}, timeout=10)
session_id = r.headers.get("mcp-session-id")

call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "md_to_pdf", "arguments": {"markdown": md_content, "title": "Title", "subtitle": "Subtitle", "author": "Bohea Still", "lang": "zh"}}}
r = s.post("http://localhost:8110/mcp", json=call, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "mcp-session-id": session_id}, timeout=60)
# 解析 SSE 响应，提取 pdf_base64，base64 解码后写入文件
```

REST 接口：

```bash
curl -X POST http://localhost:8110/pdf -H "Content-Type: application/json" \
  -d '{"md": "# Title\n\nContent"}' -o output.pdf
```

## 参数

| 参数 | 说明 | 必填 |
|------|------|------|
| markdown | Markdown 内容 | 是 |
| title | 文档标题（大字，左对齐） | 否 |
| subtitle | 副标题（标题下方） | 否 |
| author | 署名（正文末尾：下划线 + 居中） | 否 |
| lang | 语言，"en" 或 "zh" | 否 |

## 模板特性

- 标题左对齐，署名右对齐（头部 meta-info）
- 深色表头 + 斑马纹表格
- 深色代码块（#1E293B）
- Mermaid 图表自动渲染为 SVG（max-height 500px）
- 正文末尾：下划线 + 居中署名

## 启动方式

```bash
# 正确启动（需要 Nix 环境提供 Node.js + Chromium）
cd wsl/md2pdf && bash run.sh

# 错误启动（mermaid 不会渲染）
python server.py  # 缺少 node，mmdc 静默降级为纯文本
```

## 已知限制

- Mermaid 渲染需要 Nix 环境，通过 `run.sh` 启动
- PM2 管理的进程需 `pm2 kill` 才能彻底停止
- Nix PATH 不传给子进程，run.sh 需显式 export
- Chromium headless PDF 不支持 `position: fixed`
