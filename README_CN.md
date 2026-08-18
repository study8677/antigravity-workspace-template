<div align="center">

<img src="docs/assets/logo.svg" alt="RepoBrain" width="200"/>

# RepoBrain（仓库大脑）

### 跨 IDE 的代码库知识引擎，面向带源码证据的 repository Q&A。

<sub>原名 <b>Antigravity Workspace Template</b> —— 同一个项目，全新的名字。</sub>

`rb-refresh` 构建可移植知识层；`rb-ask` 将问题路由到正确模块上下文并返回源码证据。
插件、CLI 与 MCP 都只是围绕这条主流程的交付渠道。

语言: [English](README.md) | **中文** | [Español](README_ES.md)

[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org/)
[![CI](https://img.shields.io/github/actions/workflow/status/study8677/repobrain/test.yml?style=for-the-badge&label=CI)](https://github.com/study8677/repobrain/actions)
[![DeepWiki](https://img.shields.io/badge/DeepWiki-Docs-blue?style=for-the-badge&logo=gitbook&logoColor=white)](https://deepwiki.com/study8677/repobrain)
[![NLPM](https://img.shields.io/badge/NLPM-audited-7C3AED?style=for-the-badge)](https://github.com/xiaolai/nlpm-for-claude)

<br/>

<img src="https://img.shields.io/badge/Cursor-✓-000000?style=flat-square" alt="Cursor"/>
<img src="https://img.shields.io/badge/Claude_Code-✓-D97757?style=flat-square" alt="Claude Code"/>
<img src="https://img.shields.io/badge/Windsurf-✓-06B6D4?style=flat-square" alt="Windsurf"/>
<img src="https://img.shields.io/badge/Gemini_CLI-✓-4285F4?style=flat-square" alt="Gemini CLI"/>
<img src="https://img.shields.io/badge/VS_Code_+_Copilot-✓-007ACC?style=flat-square" alt="VS Code"/>
<img src="https://img.shields.io/badge/Codex-✓-412991?style=flat-square" alt="Codex"/>
<img src="https://img.shields.io/badge/Cline-✓-FF6B6B?style=flat-square" alt="Cline"/>
<img src="https://img.shields.io/badge/Aider-✓-8B5CF6?style=flat-square" alt="Aider"/>

<br/><br/>

<img src="docs/assets/demo.gif" alt="rb-ask 演示 — 向代码库提问,答案带文件路径和行号" width="800"/>

</div>

<br/>

<div align="center">
<img src="docs/assets/before_after.svg" alt="Before vs After RepoBrain" width="800"/>
</div>

<br/>

## 为什么选择 RepoBrain？

> AI Agent 的能力上限 = **它能读到的上下文质量。**

引擎是核心：`rb-refresh` 部署多智能体集群自主阅读代码——每个模块分配专属 Agent 生成知识文档。`rb-ask` 将问题路由到对应 Agent，答案有据可查，带文件路径和行号。

**与其给 Claude Code / Codex 一个仓库 `grep` 让它自己找，不如给它一个仓库版本的 ChatGPT。**

**与 Codex CLI 和 Claude Code 在三个真实 Python 仓库（`fastapi`、`requests`、`sqlmodel`）上做了 36 道题的三方对决——RepoBrain 事实题 99%、审计题 97%，事实题速度比 Codex 快 2.1×。** [查看对比](#三方对决repobrain-vs-codex-cli-vs-claude-code2026-05-09)

```
传统做法：                           RepoBrain 做法：
  CLAUDE.md = 5000 行文档              Claude Code 调用 ask_project("auth 怎么工作的？")
  Agent 全部读入，大半遗忘              Router → ModuleAgent 读真实源码，返回精准答案
  幻觉率居高不下                       有据可查，带文件路径和行号
```

| 痛点 | 没有 RepoBrain | 有 RepoBrain |
|:----|:----------------|:--------------|
| Agent 忘记代码风格 | 反复纠正同样的问题 | 读取 `.repobrain/conventions.md` —— 一次到位 |
| 接手新代码库 | Agent 只能猜测架构 | `rb-refresh` → ModuleAgent 自主学习每个模块 |
| 切换 IDE | 每个 IDE 规则不同 | 一个 `.repobrain/` 目录 —— 所有 IDE 共享 |
| 问"X 怎么实现的？" | Agent 胡乱翻文件 | `ask_project` MCP → Router 精准路由到负责模块的 Agent |

架构是**文件 + 实时问答引擎**，而非插件。跨 IDE、跨 LLM、零平台锁定。

---

## 斜杠命令

同一套四个斜杠命令同时支持 **Claude Code** 和 **Codex CLI**。Claude 使用 `/repobrain:<name>` 命名空间；Codex 自动发现 `commands/` 目录并暴露裸 `/<name>` 形式。两边一套流程，无需切换思路。

| Claude Code | Codex CLI | 用途 |
|---|---|---|
| `/repobrain:rb-setup` | `/rb-setup` | 首次配置 —— 选择 LLM 提供商，写入 `.env` |
| `/repobrain:rb-refresh [quick]` | `/rb-refresh [quick]` | 构建 / 增量刷新项目知识库 |
| `/repobrain:rb-ask <问题>` | `/rb-ask <问题>` | 当前代码库的路由问答 |
| `/repobrain:rb-init <名字>` | `/rb-init <名字>` | 基于本模板创建新的多智能体仓库 |

典型首次会话：**rb-setup → rb-refresh → rb-ask**。详细说明见下。

### `rb-setup` —— 首次配置

每个项目跑**一次**，在安装插件后立即执行。交互式选择 LLM 提供商（OpenAI / DeepSeek / Groq / 阿里灵积 / NVIDIA NIM / Ollama 本地 / 任意 OpenAI 兼容端点），然后在项目根目录写入 `.env`，包含 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`、`RB_ASK_TIMEOUT_SECONDS`。也可以选择本地 Codex host-runner 实验模式，让无 API key 的 `rb-ask` 通过本机 `codex login` 运行。命令会把 `.env` 加入 `.gitignore`。如果已经有可用的 `.env` 可跳过。

```
# Claude Code
/repobrain:rb-setup

# Codex CLI
/rb-setup
```

### `rb-refresh` —— 构建 / 刷新知识库

部署多智能体集群阅读代码：每个模块由专属 Agent 生成知识文档（`.repobrain/agents/*.md`），并由 Map Agent 产出 `map.md` 路由索引。在安装后、重要代码改动后、或 `rb-ask` 出现陈旧答复时运行。首次 refresh 会自动创建 `.repobrain/` 目录，无需单独初始化。传 `quick` 做增量更新，传 `failed-only` 仅重跑上次失败的模块。

```
# Claude Code
/repobrain:rb-refresh
/repobrain:rb-refresh quick

# Codex CLI
/rb-refresh
/rb-refresh quick
```

耗时：小仓库几分钟，大仓库更久。需要先完成 `rb-setup`。完整 LLM refresh 仍需要 API key / OpenAI-compatible provider；本地 host-runner 模式下可用 `RB_REFRESH_SCAN_ONLY=1 rb-refresh --workspace .` 生成本地扫描知识产物。

### `rb-ask` —— 路由问答

**插件存在的主要原因**。把问题路由到合适的 ModuleAgent（必要时也调 GitAgent），返回有据可查的答案，附带文件路径和行号。**优先使用它**而非手动 grep / 读文件 —— 更快也更准。适合的问题形态：「X 在哪里定义/处理？」、「Y 为什么这样设计？」、「认证流程是怎样的？」、「哪些地方依赖模块 Z？」。

```
# Claude Code
/repobrain:rb-ask "认证逻辑是怎么实现的？"

# Codex CLI
/rb-ask "认证逻辑是怎么实现的？"
```

需要已有知识库 —— 如果出现"无索引"或空答复，先跑 `rb-refresh`。

### `rb-init` —— 新仓库脚手架

基于 RepoBrain 模板创建**新**项目。两种模式：`quick`（快速脚手架、干净副本）和 `full`（在 quick 基础上加运行时 profile、`.env`、mission 文件、沙箱配置、可选 `git init`）。用于**开新仓库** —— 在已有项目上跑 `rb-refresh` 之前**不需要**先执行它。

```
# Claude Code
/repobrain:rb-init my-agent
/repobrain:rb-init my-agent full

# Codex CLI
/rb-init my-agent
/rb-init my-agent full
```

> 插件还附带 `agent-repo-init` skill（与 `rb-init` 共用同一份后端——Codex / Claude 也能按描述匹配触发）以及可选的 `rb-mcp` MCP 服务（`ask_project` + `refresh_project`）用于工具式集成。

---

## 快速开始

**方案 A —— Claude Code / Codex CLI 插件安装**
```bash
# Claude Code（首次会话由 SessionStart hook 自动安装 rb CLI + Python 引擎）
/plugin marketplace add study8677/repobrain
/plugin install repobrain@repobrain
/repobrain:rb-setup            # 交互式：选 LLM 提供商、贴 API key，自动写 .env
/repobrain:rb-refresh          # 直接运行 rb-refresh；首次 refresh 会自动创建 .repobrain/
/repobrain:rb-ask "这个项目是怎么工作的？"  # 直接运行 rb-ask

# Codex CLI（需手动先装引擎；Codex 暂不支持自动 hook）
pipx install "git+https://github.com/study8677/repobrain.git#subdirectory=engine"
pipx inject --force --include-apps repobrain-engine "git+https://github.com/study8677/repobrain.git#subdirectory=cli"
codex plugin marketplace add study8677/repobrain
/rb-setup                        # Codex 内同样的命令，无 repobrain: 前缀
/rb-refresh
/rb-ask "这个项目是怎么工作的？"
```

Codex CLI 通过 `codex plugin marketplace add` 注册插件后，会自动从插件的 `commands/` 目录发现斜杠命令，因此同样四个命令在 Codex 内不带 `repobrain:` 前缀（`/rb-setup`、`/rb-refresh`、`/rb-ask`、`/rb-init`）。也可以继续用裸 CLI（`rb-refresh --workspace .`、`rb-ask "..." --workspace .`）；安装或配置异常时运行 `rb doctor --workspace .`。如果 Codex 版本支持 MCP 并希望工具式集成，再单独注册 `rb-mcp --workspace <project>`。

安装并 setup 后，两个平台均提供 `rb-ask <问题>`、`rb-refresh`、`rb-init <名字>` 斜杠命令。MCP 仍可选，可通过 `rb-mcp` 暴露 `ask_project` + `refresh_project`；示例配置见 [docs/examples/repobrain.mcp.json](docs/examples/repobrain.mcp.json)。详见 [INSTALL.md](INSTALL.md)。

**方案 B —— 手动安装：通过 pip 安装引擎 + CLI**
```bash
# 1. 安装引擎 + CLI
pip install "git+https://github.com/study8677/repobrain.git#subdirectory=cli"
pip install "git+https://github.com/study8677/repobrain.git#subdirectory=engine"

# 2. 配置 .env（任意 OpenAI 兼容 API）
cd my-project
cat > .env <<EOF
OPENAI_BASE_URL=https://your-endpoint/v1
OPENAI_API_KEY=your-key
OPENAI_MODEL=your-model
RB_ASK_TIMEOUT_SECONDS=120
EOF

# 3. 构建知识库（ModuleAgent 自主学习每个模块）
rb-refresh --workspace .

# 4. 提问
rb-ask "这个项目的认证逻辑是怎么实现的？"

# 5.（可选）注册为 Claude Code 的 MCP 服务器
claude mcp add repobrain rb-mcp -- --workspace $(pwd)
```

**方案 C —— 仅注入上下文文件（任意 IDE，无需 LLM）**
```bash
pip install git+https://github.com/study8677/repobrain.git#subdirectory=cli
rb init my-project && cd my-project
# IDE 入口文件会引导到 AGENTS.md；动态项目上下文在 .repobrain/
```

---

## 功能一览

```
  rb init             将上下文文件注入任意项目（--force 可覆盖已有文件）
       │
       ▼
  .repobrain/       共享知识库 —— 所有 IDE 从这里读取
       │
       ├──► rb-refresh     动态多智能体自主学习 → 生成模块知识文档 + 结构图
       ├──► rb-ask         Router → ModuleAgent 路由问答，实时代码证据
       └──► rb-mcp         可选 MCP 服务端 → IDE 工具集成
```

**动态多智能体集群** —— `rb-refresh` 时，引擎使用**智能功能分组**：基于 import 关系、目录共位、文件名前缀将文件聚类。源码直接预加载进 agent 上下文（无需工具调用），构建产物自动过滤。每个 sub-agent 分析约 30K tokens 的聚焦代码，只需 1 次 LLM 调用，输出**全面的 Markdown 知识文档**（`agents/*.md`）。大模块由多个 sub-agent 并行分析——每个输出独立 agent.md（不合并、不压缩）。**Map Agent** 读取所有 agent 文档生成 `map.md` 路由索引。`rb-ask` 时，Router 读取 `map.md` 选择相关模块，将 agent 文档喂给 answer agent。**完全语言无关** —— 模块检测使用纯目录结构，代码分析完全由 LLM 完成。支持任何编程语言。

**GitAgent** —— 专门分析 git 历史的 Agent，了解「谁改了什么、为什么改」。

**NLPM 审计反馈** —— 本仓库受益于 [xiaolai](https://github.com/xiaolai) 的 [NLPM](https://github.com/xiaolai/nlpm-for-claude)，它是面向 Claude Code 插件、skills 和 agent 定义的自然语言编程 linter。它的审计帮助发现了 skill frontmatter 和依赖版本卫生方面的真实改进点。

---

## CLI 命令

| 命令 | 功能 | 需要 LLM？ |
|:-----|:-----|:----------:|
| `rb init <dir>` | 注入认知架构模板 | 否 |
| `rb init <dir> --force` | 重新注入，覆盖已有文件 | 否 |
| `rb refresh --workspace <dir>` | CLI 便捷包装，调用知识库 refresh 流程 | 是 |
| `rb ask "问题" --workspace <dir>` | CLI 便捷包装，调用路由式项目问答流程 | 是，或本地 Codex host runner |
| `rb-refresh` | 多智能体自主学习代码库，生成模块知识文档 + `conventions.md` + `structure.md` | 是 |
| `rb-ask "问题"` | Router → ModuleAgent/GitAgent 路由问答 | 是，或本地 Codex host runner |
| `rb-mcp --workspace <dir>` | **启动 MCP 服务器** —— 向 Claude Code 暴露 `ask_project` + `refresh_project` 工具 | 是 |
| `rb report "内容"` | 记录发现到 `.repobrain/memory/` | 否 |
| `rb log-decision "决策" "原因"` | 记录架构决策 | 否 |

`rb ask` / `rb refresh` 需要同时安装 `cli/` 和 `engine/`。`rb-ask` / `rb-refresh` 是只安装 engine 也可用的入口。

---

## 两个包，一套工作流

```
repobrain/
├── cli/                     # rb CLI — 轻量，pip 可安装
│   └── templates/           # .cursorrules, CLAUDE.md, .repobrain/, ...
└── engine/                  # 多智能体引擎 + 知识中枢
    └── repobrain_engine/
        ├── _cli_entry.py    # rb-ask / rb-refresh 入口
        ├── config.py        # Pydantic 配置
        ├── hub/             # ★ 核心：多智能体集群
        │   ├── agents.py    #   Router + ModuleAgent + GitAgent
        │   ├── contracts.py #   Pydantic 模型：claims、证据、刷新状态
        │   ├── ask_pipeline.py    # agent.md 路由问答
        │   ├── refresh_pipeline.py # LLM 驱动刷新 → agents/*.md + map.md
        │   ├── ask_tools.py #   代码探索工具
        │   ├── scanner.py   #   多语言项目扫描
        │   ├── module_grouping.py # 智能功能分组
        │   └── mcp_server.py#   MCP 服务端 (rb-mcp)
        ├── mcp_client.py    # MCP 消费端（连接外部工具）
        ├── memory.py        # 持久交互记忆
        ├── tools/           # MCP 查询工具 + 扩展工具
        ├── skills/          # 技能加载器
        └── sandbox/         # 代码执行（local / microsandbox）
```

**CLI**（`pip install .../cli`）—— 零 LLM 依赖。注入模板，离线记录报告和决策。

**Engine**（`pip install .../engine`）—— 代码库知识运行时。驱动 `rb-ask`、`rb-refresh`、`rb-mcp`。使用 `rb-setup` 写入的 OpenAI-compatible endpoint（OpenAI、DeepSeek、Groq、DashScope、NVIDIA NIM、Ollama 或自定义端点）。实验性本地模式可设置 `RB_HOST_RUNNER=codex`，让 `rb-ask` 使用用户本机 `codex login`，不走 API key；这个能力只面向个人本地使用，不作为托管产品后端承诺。

**新增 skill 封装更新：**
- `engine/repobrain_engine/skills/graph-retrieval/` —— 面向结构与调用路径推理的图谱检索工具。
- `engine/repobrain_engine/skills/knowledge-layer/` —— 面向项目语义上下文整合的知识层工具。

```bash
# 安装两者获取完整体验
pip install "git+https://...#subdirectory=cli"
pip install "git+https://...#subdirectory=engine"
```

---

## 工作原理

### 1. `rb init` — 注入上下文文件

```bash
rb init my-project
# 已经初始化过？用 --force 覆盖：
rb init my-project --force
```

创建 `AGENTS.md`（权威行为规则）、IDE 引导文件（`.cursorrules`、`CLAUDE.md`、`.windsurfrules`、`.clinerules`、`.github/copilot-instructions.md`）以及 `.repobrain/` 动态上下文文件。

### 2. `rb-refresh` — 多智能体自主学习

```bash
rb-refresh --workspace my-project
```

**8 步流程：**
1. 扫描代码库（语言、框架、结构）
2. 多 Agent 管道生成 `conventions.md`
3. 生成 `structure.md` —— 语言无关的文件树（含行数统计）
4. 构建知识图谱（`knowledge_graph.json` + mermaid）
5. 写入文档/数据/媒体索引
6. **LLM 全量代码分析** —— 基于 import 图 + 目录 + 前缀分组，代码预加载进 context（每组约 30K tokens），自动过滤构建产物。每个 sub-agent 读取完整源码，输出**全面的 Markdown 知识文档**（`agents/*.md`）。大模块生成多个 agent 文档（每组一个，不合并）。全局 API 并发控制防止限流。**完全语言无关** —— 支持任何编程语言。
7. **RefreshGitAgent** 分析 git 历史，生成 `_git_insights.md`
8. **Map Agent** 读取所有 agent 文档 → 生成 `map.md`（模块路由索引，含描述和关键词）

### 3. `rb-ask` — Router 路由问答

```bash
rb-ask "这个项目的认证逻辑是怎么实现的？"
```

Ask 管道采用**语义路径**：Router 读取 `map.md` → 选择模块 → 读取 `agents/*.md` → LLM 回答并引用代码。多个 agent 文档由并行 LLM 读取，然后由 Synthesizer 合并答案。

若 agent 文档尚未生成，则回退到传统的 Router → ModuleAgent/GitAgent swarm 路径。

---

## IDE 兼容性

架构编码在**文件**中 —— 任何能读项目文件的 Agent 都能受益：

| IDE | 配置文件 |
|:----|:---------|
| Cursor | `.cursorrules` |
| Claude Code | `CLAUDE.md` |
| Windsurf | `.windsurfrules` |
| VS Code + Copilot | `.github/copilot-instructions.md` |
| Gemini CLI / Codex / DeepSeek Harness | `AGENTS.md` |
| Cline | `.clinerules` |
| Google Antigravity | `.repobrain/rules.md` |

均由 `rb init` 生成：`AGENTS.md` 是唯一行为规则源，IDE 专属文件是轻量引导层，`.repobrain/` 保存共享的动态项目上下文。

---

## 进阶功能

<details>
<summary><b>MCP 服务器 — 给 Claude Code 一个代码库专属 ChatGPT</b></summary>

Claude Code 不再需要读数百个文档文件——它可以直接调用 `ask_project` 工具，背后是动态多智能体集群：Router 将问题路由到对应 ModuleAgent，返回带文件路径和行号的精准答案。

**配置步骤：**

```bash
# 安装引擎
pip install "git+https://github.com/study8677/repobrain.git#subdirectory=engine"

# 先刷新知识库（ModuleAgent 自主学习每个模块）
rb-refresh --workspace /path/to/project

# 注册为 Claude Code 的 MCP 服务器
claude mcp add repobrain rb-mcp -- --workspace /path/to/project
```

**向 Claude Code 暴露的工具：**

| 工具 | 功能 |
|:-----|:-----|
| `ask_project(question)` | Router → ModuleAgent/GitAgent 回答代码库问题。返回文件路径 + 行号。 |
| `refresh_project(quick?)` | 重大改动后重建知识库。ModuleAgent 重新学习代码。 |

</details>

<details>
<summary><b>动态多智能体集群</b> — 模块级自学习 + 智能路由</summary>

引擎的核心是**按代码模块动态创建的 Agent 集群**：

```
 rb-refresh：                                rb-ask：

 对每个模块：                                Router（读 map.md）
 ┌ 按 import 图分组文件                        └── 读 agents/*.md → LLM 回答
 ├ 每组预加载约 30K tokens
 ├ 自动过滤构建产物
 ├ Sub-agent → Markdown agent 文档
 ├ agents/{module}.md（或 /group_N.md）
 └ Map Agent → map.md
```

**核心创新：**
- **LLM 即分析器**：不使用 AST 解析或正则 —— 源码直接喂给 LLM 分析。开箱即用支持任何编程语言。
- **智能分组**：基于 import 关系、目录共位、文件名前缀分组。构建产物自动过滤。字符硬限（800K）防止上下文溢出。
- **零信息损失**：大模块生成多个 `agent.md`（每组一个）—— 不合并、不压缩。`rb-ask` 时多个 agent 文档由并行 LLM 读取，然后 Synthesizer 合并答案。
- **全局 API 并发控制**：`RB_API_CONCURRENCY` 限制所有模块的同时 LLM 调用数，防止限流。
- **语言无关模块检测**：纯目录结构 —— 不需要 `__init__.py` 或任何语言特定标记。

```bash
# 模块 Agent 自主学习代码库
rb-refresh

# 仅扫描上次刷新后变更的文件
rb-refresh --quick

# Router 智能路由到对应模块 Agent
rb-ask "这个项目用了什么测试模式？"

# 记录发现和决策（无需 LLM）
rb report "认证模块需要重构"
rb log-decision "使用 PostgreSQL" "团队有丰富经验"
```

使用 `rb-setup` 选择并写入的 OpenAI-compatible endpoint。基于 OpenAI Agent SDK + LiteLLM。
</details>

<details>
<summary><b>MCP 集成</b> — 连接外部工具（GitHub、数据库、文件系统）</summary>

```json
// mcp_servers.json
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

设置 `MCP_ENABLED=true` 让配置的 server 对 engine 可见；只有希望 `rb-ask`
自动连接外部 server 且信任这些 server 时，才设置 `RB_ALLOW_MCP=true`。
Stdio MCP server 会继承进程环境变量和配置中的 `env` 值，因此应把它们视为拥有本地权限的代码。
详见 [MCP 文档](docs/zh/MCP_INTEGRATION.md)。
</details>

<details>
<summary><b>MCP 集成（消费端）</b> — 让 Agent 调用外部工具</summary>

`MCPClientManager` 让你的 Agent 能连接外部 MCP 服务器（GitHub、数据库等），自动发现并注册工具。

```json
// mcp_servers.json
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

设置 `MCP_ENABLED=true` 让配置的 server 对 engine 可见；只有希望 `rb-ask`
自动连接外部 server 且信任这些 server 时，才设置 `RB_ALLOW_MCP=true`。
Stdio MCP server 会继承进程环境变量和配置中的 `env` 值，因此应把它们视为拥有本地权限的代码。
</details>

<details>
<summary><b>沙盒执行</b> — 可配置的代码执行环境</summary>

| 变量 | 默认值 | 选项 |
|:-----|:------|:-----|
| `SANDBOX_TYPE` | `local` | `local` · `microsandbox` |
| `SANDBOX_TIMEOUT_SEC` | `30` | 秒 |
| `RB_RETRIEVAL_MODE` | `compact` | `off` · `compact` · `full` |

默认 sandbox 只面向可信本地 workspace，不是执行不可信代码的隔离边界。
Retrieval graph 写盘前会脱敏常见 secret，但 `full` 模式仍可能保留源码片段。
详见 [沙盒文档](docs/zh/SANDBOX.md)。
</details>

---

## 三方对决：RepoBrain vs Codex CLI vs Claude Code（2026-05-09）

在三个真实 Python 仓库（`fastapi/fastapi`、`psf/requests`、`fastapi/sqlmodel`）上对三个工具问**同样的 36 道题**，按难度分三档。三家都用 `gpt-5.5` + 高推理强度；Codex 和 Claude 拥有完整源码读权限。评分由 Codex 担任，4 轴 0-3 规则，所有声明都对源码核验。

| 题型 | RepoBrain | Codex CLI | Claude Code |
|:---|:---:|:---:|:---:|
| 15 道事实查找 | **179/180 (99%)** | 179/180 (99%) | 178/180 (99%) |
| 12 道综合题（项目/架构 tour） | 116/144 (81%) | **144/144 (100%)** | 136/144 (94%) |
| 9 道审计/安全 | **105/108 (97%)** | 104/108 (96%) | 98/108 (91%) |

**事实题 + 审计题合计 24 题：RepoBrain 284/288，Codex 283/288，Claude 276/288。** RepoBrain **微弱反超**——而且**每道题都比 Codex 跑得更快**。

**延迟**（同一代理下每题平均墙钟）：

| 题型 | RepoBrain | Codex | Claude |
|:---|:---:|:---:|:---:|
| 事实 | **56s** | 119s | 42s |
| 审计 | 160s | 177s | **100s** |

RepoBrain 在事实题上**比 Codex 快 2.1x**，在审计题上跟 Codex 速度持平，但正确率持平或略胜。Claude 在审计上最快但正确率落后 7 个百分点。

**仓库里两个引擎修复带来的提升**（本分支已提交）：

1. `_ask_with_agent_md` 现在把项目级文档（`conventions.md`、`module_registry.md`、`map.md`、`structure.md`）注入答案 prompt——杜绝了"module knowledge 不包含项目约定"那种假性拒答。
2. structured-facts 路径的 AnswerAgent / Reader 都绑上了 `search_code` / `read_file` / `list_directory` / `read_file_metadata` / `search_by_type` 等运行时工具——LLM 现在能直接 grep+读源码，不再靠 paraphrase。

完整报告（数据、方法、每题分数、注意事项）：[`artifacts/benchmark-2026-05-09/REPORT.md`](artifacts/benchmark-2026-05-09/REPORT.md)。

---

## 文档

| | |
|:--|:--|
| 🇬🇧 English | **[`docs/en/`](docs/en/)** |
| 🇨🇳 中文 | **[`docs/zh/`](docs/zh/)** |
| 🇪🇸 Español | **[`docs/es/`](docs/es/)** |

---

## 贡献

创意也是贡献！欢迎在 [issue](https://github.com/study8677/repobrain/issues) 中报告 bug、提出建议或提交架构方案。

## 贡献者

<table>
  <tr>
    <td align="center" width="20%">
      <a href="https://github.com/Lling0000">
        <img src="https://github.com/Lling0000.png" width="80" /><br/>
        <b>⭐ Lling0000</b>
      </a><br/>
      <sub><b>主要贡献者</b> · 创意建议 · 项目管理员 · 项目构想与反馈</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/h13181278389">
        <img src="https://github.com/h13181278389.png" width="80" /><br/>
        <b>h13181278389</b>
      </a><br/>
      <sub><b>核心贡献者</b> · 感谢你对 RepoBrain 的支持、反馈与贡献</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/flyw1015">
        <img src="https://github.com/flyw1015.png" width="80" /><br/>
        <b>flyw1015</b>
      </a><br/>
      <sub><b>核心贡献者</b> · 感谢你对 RepoBrain 的支持、反馈与贡献</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/devalexanderdaza">
        <img src="https://github.com/devalexanderdaza.png" width="80" /><br/>
        <b>Alexander Daza</b>
      </a><br/>
      <sub>沙盒 MVP · OpenSpec 工作流 · 技术分析文档 · PHILOSOPHY</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/chenyi">
        <img src="https://github.com/chenyi.png" width="80" /><br/>
        <b>Chen Yi</b>
      </a><br/>
      <sub>首个 CLI 原型 · 753 行重构 · DummyClient 提取 · 快速开始文档</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="20%">
      <a href="https://github.com/Subham-KRLX">
        <img src="https://github.com/Subham-KRLX.png" width="80" /><br/>
        <b>Subham Sangwan</b>
      </a><br/>
      <sub>动态工具与上下文加载 (#4) · 多 Agent Swarm 协议 (#3)</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/shuofengzhang">
        <img src="https://github.com/shuofengzhang.png" width="80" /><br/>
        <b>shuofengzhang</b>
      </a><br/>
      <sub>记忆上下文窗口修复 · MCP 关闭优雅处理 (#28)</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/goodmorning10">
        <img src="https://github.com/goodmorning10.png" width="80" /><br/>
        <b>goodmorning10</b>
      </a><br/>
      <sub>增强 <code>rb ask</code> 上下文加载 — 新增 CONTEXT.md、AGENTS.md 和 memory/*.md 作为上下文来源 (#29)</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/abhigyanpatwari">
        <img src="https://github.com/abhigyanpatwari.png" width="80" /><br/>
        <b>Abhigyan Patwari</b>
      </a><br/>
      <sub>代码知识图谱原生集成到 <code>rb ask</code>，提供符号搜索、调用图和影响分析</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/BBear0115">
        <img src="https://github.com/BBear0115.png" width="80" /><br/>
        <b>BBear0115</b>
      </a><br/>
      <sub>技能封装与知识图谱检索增强 · 多语言 README 同步更新 (#30)</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="20%">
      <a href="https://github.com/SunkenCost">
        <img src="https://github.com/SunkenCost.png" width="80" /><br/>
        <b>SunkenCost</b>
      </a><br/>
      <sub><code>rb clean</code> 清理命令 · <code>__main__</code> 入口保护 (#37)</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/aravindhbalaji04">
        <img src="https://github.com/aravindhbalaji04.png" width="80" /><br/>
        <b>Aravindh Balaji</b>
      </a><br/>
      <sub>统一指令层围绕 <code>AGENTS.md</code> (#41)</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="20%">
      <a href="https://github.com/xiaolai">
        <img src="https://github.com/xiaolai.png" width="80" /><br/>
        <b>xiaolai</b>
      </a><br/>
      <sub><a href="https://github.com/xiaolai/nlpm-for-claude">NLPM</a> 审计反馈 · Skill frontmatter 修复 · 依赖版本卫生审查 (#51, #52, #53)</sub>
    </td>
  </tr>
</table>

## Star History

[![Star History Chart](https://star-history.dera.page/svg?repos=study8677/repobrain&type=Date)](https://star-history.dera.page/#study8677/repobrain&Date)

## 许可证

MIT License. 详见 [LICENSE](LICENSE)。

---

<div align="center">

**[📚 查看完整文档 →](docs/zh/)**

*为 AI 原生开发时代而构建*

友情链接：[LINUX DO](https://linux.do/)

</div>
