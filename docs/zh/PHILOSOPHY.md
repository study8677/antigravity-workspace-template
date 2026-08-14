# 项目理念

## 产品主张

AI 编程工具最需要的不是一次性塞满整个仓库，而是能围绕当前问题读取一个新鲜、
可验证的仓库模型。RepoBrain 就是这层 repository knowledge layer。

核心工作流刻意保持很小：

1. `rb-refresh` 扫描 workspace，构建 `.repobrain/` 知识产物。
2. `rb-ask` 将问题路由到正确模块上下文，并用源码证据回答。
3. 插件、CLI、上下文文件与 MCP 把同一层知识暴露给不同 AI 开发环境。

## 设计原则

### 一份知识库，多种宿主

生成的 `.repobrain/` 是可移植项目状态。Claude Code、Codex CLI、Cursor、
Windsurf、Gemini CLI、Cline、Aider、DeepSeek Harness 和其他宿主都应该读取同一份仓库模型，
而不是各自维护割裂的上下文系统。

### 有证据的回答优于宽泛上下文

大段 prompt 很容易创建，但很难信任。RepoBrain 偏向模块级知识、源码路径、
行号证据和可选图谱上下文支撑的路由式回答。

### 插件只是交付渠道

Claude Code 与 Codex CLI 有原生 slash commands，是因为这对这些宿主最顺手。
已经能跑 shell 或 MCP 的宿主（包括 DeepSeek Harness）复用 CLI 和可选的
`rb-mcp` overlay，而不是再做第三套原生插件包。产品边界仍然是知识引擎：
`rb-refresh`、`rb-ask`，以及它们生成的产物。

### 兼容而不锁定供应商

`rb-setup` 写入 OpenAI-compatible `.env` 契约：`OPENAI_BASE_URL`、
`OPENAI_API_KEY`、`OPENAI_MODEL`。这样可以覆盖 OpenAI、DeepSeek、Groq、
DashScope、NVIDIA NIM、Ollama 和自定义 provider，而不把任何一个模型写成产品默认值。

## 什么应该留在这里

RepoBrain 应优先改进：

- 更好的仓库扫描和模块分组
- 更可靠的带证据问答和事实验证
- 原生插件用户的清晰安装路径
- 稳定的 CLI 与 MCP 契约
- 让产品叙事保持一致的文档和 CI 检查

把仓库变成泛用 agent OS、工作流管理器或无关 scaffold 的功能，除非能明确提升
repository knowledge engine，否则应拆到产品边界之外。

---

**下一步：** [快速开始](QUICK_START.md) | [文档索引](README.md)
