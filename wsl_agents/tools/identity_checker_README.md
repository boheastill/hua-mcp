# Model Identity Checker MCP Server

一个专门用于检测当前运行模型身份的 MCP 服务器。

## 背景

当 AI 代理（如 Claude Code）运行时，它们通常依赖训练数据中的默认身份信息。然而，实际运行环境可能使用不同的模型（例如，通过小米 MiMo API 代理运行 Claude Code）。

这个 MCP 服务器提供工具，让 AI 代理能够：
1. 检查实际的环境变量配置
2. 分析 API 端点指向哪个提供商
3. 检测运行时环境特征
4. 综合分析得出最可能的模型身份

## 工具列表

### 1. `check_model_identity`
检查环境变量中的模型配置，返回：
- 检测到的模型名称
- 检测到的提供商
- API 端点
- 证据列表
- 摘要信息

### 2. `check_runtime_environment`
检查运行时环境，包括：
- 系统信息（平台、架构等）
- 环境变量（Shell、用户等）
- Claude Code 特定信息
- 容器化检测

### 3. `check_api_connectivity`
测试与配置的 API 端点的连接性，验证实际使用的服务。

### 4. `get_model_config`
获取模型配置（非敏感部分），用于调试。

### 5. `analyze_model_characteristics`
综合分析模型特征，基于多个证据点给出：
- 最可能的模型家族
- 置信度评分
- 推理过程
- 反面证据

## 使用方法

### 作为 MCP 服务器运行

```bash
# 安装依赖
uv pip install mcp requests pydantic

# 运行服务器
uv run server.py
```

### 在 Claude Code 中配置

在项目根目录创建 `.mcp.json` 文件：

```json
{
  "mcpServers": {
    "model-identity-checker": {
      "command": "uv",
      "args": ["run", "C:/Users/bohea/Documents/vibe-code/mcp/server.py"],
      "env": {}
    }
  }
}
```

### 测试工具

```bash
uv run test_mcp.py
```

### 优化点（已实现）

1. **实际 API 调用验证** - 通过 DNS 解析和连接测试验证端点真实性
2. **多源证据收集** - 环境变量 + API 验证 + 运行时环境
3. **置信度评分** - 基于证据数量计算置信度
4. **综合判断** - `comprehensive_identity_check` 工具整合所有信息

## 检测点

### 环境变量检测
- `ANTHROPIC_MODEL` - 模型名称
- `ANTHROPIC_BASE_URL` - API 端点
- `MIMO_API_KEY` - 小米 MiMo 密钥
- `ANTHROPIC_AUTH_TOKEN` - Anthropic 密钥

### API 端点分析
- `xiaomimimo.com` → 小米 MiMo
- `anthropic.com` → Anthropic Claude
- `openai.com` → OpenAI

### 模型名称分析
- 包含 `mimo` → 小米 MiMo
- 包含 `claude` → Anthropic Claude
- 包含 `gpt` → OpenAI GPT

## 示例输出

```json
{
  "detected_model": "mimo-v2.5-pro[1m]",
  "detected_provider": "Xiaomi MiMo",
  "api_endpoint": "https://api.xiaomimimo.com/anthropic",
  "evidence": [
    "API endpoint contains 'mimo': https://api.xiaomimimo.com/anthropic",
    "Model name contains 'mimo': mimo-v2.5-pro[1m]",
    "MIMO_API_KEY is set - indicates Xiaomi MiMo provider"
  ],
  "summary": "Running mimo-v2.5-pro[1m] via Xiaomi MiMo"
}
```

## 设计理念

这个 MCP 服务器的设计理念是：
1. **证据优先** - 基于实际配置而非假设
2. **多源验证** - 从多个角度收集证据
3. **透明推理** - 展示推理过程和证据
4. **自我诊断** - 让 AI 代理能够了解自己的运行环境

## 注意事项

- 敏感信息（API 密钥）会被自动脱敏
- 某些检测可能因环境限制而失败
- 建议结合多个工具的结果进行综合判断

## 许可证

MIT
