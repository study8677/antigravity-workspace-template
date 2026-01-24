# 🪐 Google Antigravity Workspace Template

**用于在 Google Antigravity 上构建自主 AI 代理的生产级入门套件。**

语言: [English](/docs/en/) | [中文（仓库主页）](README_CN.md) | [中文文档](/docs/zh/) | [Español](/docs/es/)

![License](https://img.shields.io/badge/License-MIT-green)
![Gemini](https://img.shields.io/badge/AI-Gemini_2.0_Flash-blue)
![Architecture](https://img.shields.io/badge/Architecture-Event_Driven-purple)
![Memory](https://img.shields.io/badge/Context-Infinite-orange)

## 🌟 项目初衷

在 AI IDE 如此丰富的今天，我希望企业级架构可以像 **Clone → Rename → Prompt** 一样简单。

本项目利用 IDE 的上下文感知能力（通过 `.cursorrules` 和 `.antigravity/rules.md`），在仓库中预埋了一套完整的 **认知架构**。

当你打开这个项目时，IDE 不再只是编辑器，而是一位**懂行的架构师**。

**第一性原理：**

- **减少重复**：让仓库内置默认值，降低上手成本。
- **显式表达意图**：把架构、上下文和工作流写进文件，而不是口口相传。
- **把 IDE 当队友**：借助上下文规则，让编辑器成为主动的架构师，而不是被动工具。

### 为什么需要一个“有思想”的脚手架？

在使用 Google Antigravity 或 Cursor 开发时，我发现了一个痛点：

**IDE 和模型都很强，但空项目太弱。**

每个新项目都要重复同样的枯燥配置：

- “代码该放在 `src` 还是 `app`？”
- “工具函数怎么写才能让 Gemini 识别？”
- “怎样让 AI 记住上下文？”

这种重复消耗创造力。理想的工作流是：**git clone 之后，IDE 已经知道该做什么。**

所以我做了这个项目：**Antigravity Workspace Template**。

## ⚡ 快速开始

### 自动安装（推荐）

**Linux / macOS：**
```bash
# 1. 克隆模板
git clone https://github.com/study8677/antigravity-workspace-template.git my-project
cd my-project

# 2. 运行安装脚本
chmod +x install.sh
./install.sh

# 3. 配置 API 密钥
nano .env

# 4. 运行 Agent
source venv/bin/activate
python src/agent.py
```

**Windows：**
```cmd
# 1. 克隆模板
git clone https://github.com/study8677/antigravity-workspace-template.git my-project
cd my-project

# 2. 运行安装脚本
install.bat

# 3. 配置 API 密钥（notepad .env）

# 4. 运行 Agent
python src/agent.py
```

### 手动安装

```bash
# 1. 克隆模板
git clone https://github.com/study8677/antigravity-workspace-template.git my-project
cd my-project

# 2. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置 API 密钥
cp .env.example .env  #（如有）或手动创建 .env
nano .env

# 5. 运行 Agent
python src/agent.py
```

**就这么简单！** IDE 会通过 `.cursorrules` + `.antigravity/rules.md` 自动加载配置，你可以直接开始提示。

## 🎯 这是什么？

这并不是另一个 LangChain 封装。它是一个极简、透明的工作区，用于构建能够：

- 🧠 拥有无限记忆（递归摘要）
- 🛠️ 从 `src/tools/` 自动发现工具
- 📚 从 `.context/` 自动注入上下文
- 🔌 无缝连接 MCP 服务器
- 🤖 协调多个专家型 Agent
- 📦 将输出保存为 Artifact（计划、日志、证据）

**Clone → Rename → Prompt，即是工作流。**

## 🚀 关键特性

| 特性 | 描述 |
|---------|-------------|
| 🧠 **无限记忆** | 递归摘要自动压缩上下文 |
| 🧠 **真实思考 (True Thinking)** | 行动前使用思维链 (CoT) 进行“深度思考”，生成执行计划 |
| 🎓 **技能系统 (Skills System)** | 模块化能力系统：`src/skills/` 下的文件夹自动加载 |
| 🛠️ **通用工具** | 将 Python 函数放入 `src/tools/` 即可自动发现 |
| 📚 **自动上下文** | 向 `.context/` 添加文件即可自动注入提示 |
| 🔌 **MCP 支持** | 连接 GitHub、数据库、文件系统、自定义服务器 |
| 🤖 **Swarm Agent** | Router-Worker 模式的多 Agent 编排 |
| ⚡ **Gemini 原生** | 为 Gemini 2.0 Flash 做了优化 |
| 🌐 **LLM 无关** | 支持 OpenAI、Azure、Ollama 或任何兼容 OpenAI 的 API |
| 📂 **Artifact-First** | 每个任务都会生成计划、日志和证据 |

## 📚 文档

**完整文档位于 `/docs/en/`：**

- **[Quick Start](docs/en/QUICK_START.md)** — 安装与部署
- **[Philosophy](docs/en/PHILOSOPHY.md)** — 核心理念与架构
- **[Zero-Config](docs/en/ZERO_CONFIG.md)** — 自动工具与上下文加载
- **[MCP Integration](docs/en/MCP_INTEGRATION.md)** — 外部工具连接
- **[Swarm Protocol](docs/en/SWARM_PROTOCOL.md)** — 多 Agent 协调
- **[Roadmap](docs/en/ROADMAP.md)** — 未来规划与愿景

## 🏗️ 项目结构

```
src/
├── agent.py           # Agent 主循环
├── memory.py          # JSON 记忆管理
├── mcp_client.py      # MCP 集成
├── swarm.py           # 多 Agent 编排
├── agents/            # 专家型 Agent
├── tools/             # 自定义工具
└── skills/            # 模块化技能（零配置）

.context/             # 知识库（自动注入）
.antigravity/         # Antigravity 规则
artifacts/            # 输出与证据
```

## 💡 30 秒创建一个工具

```python
# src/tools/my_tool.py
def analyze_sentiment(text: str) -> str:
    """Analyzes the sentiment of given text."""
    return "positive" if len(text) > 10 else "neutral"
```

**重启 Agent。** 完成！工具已可用。

## 🔌 MCP 集成

连接外部工具：

```json
{
  "servers": [
    {
      "name": "github",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "enabled": true
    }
  ]
}
```

Agent 会自动发现并使用所有 MCP 工具。

## 🤖 多 Agent Swarm

分解复杂任务：

```python
from src.swarm import SwarmOrchestrator

swarm = SwarmOrchestrator()
result = swarm.execute("构建并审查一个计算器")
```

Swarm 会自动：
- 📤 路由到 Coder、Reviewer、Researcher Agent
- 🧩 综合结果
- 📂 保存 Artifact

## ✅ 已完成内容

- ✅ 阶段 1-7：基础、DevOps、记忆、工具、Swarm、发现
- ✅ 阶段 8：MCP 集成（已完全实现）
- 🚀 阶段 9：企业核心（进行中）

详见 [Roadmap](docs/en/ROADMAP.md)。

## 🆕 最近更新

- 新增 **真实思考 (True Thinking)**：Agent 现在会在每次行动前执行真正的“深度思考”（CoT），生成结构化计划。
- 新增 **技能系统 (Skills System)**：新的 `src/skills/` 目录支持基于文件夹的模块化能力（文档+代码）。
- 支持本地 OpenAI 兼容后端（如 Ollama），在没有 Google Key 时可直接用本地模型。
- 修复 `.env` 读取路径，从 `src/` 运行也能读取项目根目录配置。
- 入口脚本支持通过参数或 `AGENT_TASK` 指定任务。

## 🤝 贡献

创意也是贡献！欢迎在 [issue](https://github.com/study8677/antigravity-workspace-template/issues) 中：
- 报告 bug
- 提出功能建议
- 提交架构方案（阶段 9）

或提交 PR 改进文档或代码。

## 👥 贡献者

- [@devalexanderdaza](https://github.com/devalexanderdaza) — 首位贡献者。实现了演示工具、增强了 Agent 功能、提出了 “Agent OS” 路线图，并完成 MCP 集成。
- [@Subham-KRLX](https://github.com/Subham-KRLX) — 添加了动态工具与上下文加载（修复 #4），以及多 Agent 集群协议（修复 #6）。

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=study8677/antigravity-workspace-template&type=Date)](https://star-history.com/#study8677/antigravity-workspace-template&Date)

## 📄 许可证

MIT License. 详见 [LICENSE](LICENSE)。

---

**[查看完整文档 →](docs/en/)**
