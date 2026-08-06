# 📚 RepoBrain 工作区文档（中文）

欢迎来到 **RepoBrain** 中文文档。它是一个跨 IDE 的代码库知识引擎，
用于构建可移植、基于证据的 repository knowledge layer，并支持带源码证据的代码库问答。

## 🎯 快速导航

### 入门
- **[快速开始](QUICK_START.md)** — 安装、本地开发、运行示例
- **[项目理念](PHILOSOPHY.md)** — 核心理念与 Artifact-First 协议

### 核心特性
- **[零配置特性](ZERO_CONFIG.md)** — 自动发现工具与上下文
- **[MCP 集成](MCP_INTEGRATION.md)** — 连接外部工具与数据源
- **[Sandbox 执行](SANDBOX.md)** — 本地可信执行边界与 Microsandbox opt-in
- **[多 Agent Swarm](SWARM_PROTOCOL.md)** — Router-Worker 协作流程

### 规划与愿景
- **[开发路线图](ROADMAP.md)** — Phase 1-9 的进展与计划

## 🌟 亮点特性

### 🧠 无限记忆引擎
递归摘要自动压缩历史上下文，缓解上下文窗口限制。

### 🛠️ 通用工具协议
遵循通用 ReAct 模式；在 `repobrain_engine/tools/` 放入 Python 函数即被自动注册为工具。

### 🎓 基于 Skill 的项目初始化
使用内置 `agent-repo-init` skill 可以从当前模板快速初始化干净的新仓库。
支持 `quick` 与 `full` 两种模式，并提供可移植脚本 `skills/agent-repo-init/scripts/init_project.py`。

### ⚡️ 多模型支持
通过 `rb-setup` 选择并写入 OpenAI-compatible endpoint（OpenAI、OrcaRouter、DeepSeek、Groq、DashScope、NVIDIA NIM、Ollama 或自定义端点）。

### 🔌 外部 LLM 支持
通过内置 `call_openai_chat` 工具可调用任意 OpenAI 兼容 API（OpenAI、Azure、Ollama 等）。

## 🚀 常见任务

| 目标 | 文档 |
|------|------|
| 体验与运行 | [快速开始](QUICK_START.md) |
| 编写自定义工具 | [零配置特性](ZERO_CONFIG.md) |
| 从当前模板初始化新项目 | [零配置特性](ZERO_CONFIG.md) |
| 连接 MCP 服务器 | [MCP 集成](MCP_INTEGRATION.md) |
| 启用多 Agent | [多 Agent Swarm](SWARM_PROTOCOL.md) |
| 理解架构 | [项目理念](PHILOSOPHY.md) |
| 查看规划 | [开发路线图](ROADMAP.md) |
| 查询项目上下文 | `rb-ask "问题"` / `rb-refresh` |

## 📊 项目结构

```
.
├── .repobrain/        # 🛸 生成的代码库知识库
├── .context/            # 📚 可选的额外上下文
├── artifacts/           # 📂 Agent 输出（计划、日志、证据）
├── repobrain_engine/  # 🧠 Agent 源码
│   ├── hub/             # 知识中枢（扫描器、Agent、管道）
│   ├── mcp_server.py    # rb-mcp 服务端
│   ├── memory.py        # Markdown 记忆管理
│   ├── mcp_client.py    # MCP 集成
│   ├── swarm.py         # 多 Agent 编排
│   ├── agents/          # 专家型 Agent
│   ├── tools/           # 工具实现
│   └── sandbox/         # local / microsandbox 代码执行
├── tests/               # ✅ 测试套件
├── scripts/             # 🧪 辅助脚本
├── docker-compose.yml   # 本地开发栈
├── README.md            # 项目主页
└── pyproject.toml       # Python 依赖
```

## 🎓 按角色阅读

### 开发者
1) 先读 [快速开始](QUICK_START.md)
2) 理解 [零配置特性](ZERO_CONFIG.md)
3) 了解 [Swarm 协议](SWARM_PROTOCOL.md)

### DevOps/部署
1) 阅读 [快速开始](QUICK_START.md) 的 Docker 部分
2) 查看 [开发路线图](ROADMAP.md) 的 Phase 9（Enterprise Core）
3) 在 [MCP 集成](MCP_INTEGRATION.md) 配置外部服务器

### 架构师
1) 理解 [项目理念](PHILOSOPHY.md)
2) 学习 [多 Agent Swarm](SWARM_PROTOCOL.md) 架构
3) 复盘 [开发路线图](ROADMAP.md) 愿景

### 贡献者
1) 阅读 [项目理念](PHILOSOPHY.md)
2) 查看 [开发路线图](ROADMAP.md) Phase 9 的开放议题
3) 提交 Issue/PR 讨论想法或实现

## 🔗 外部资源

- 🌐 [RepoBrain 官方文档](https://docs.repobrain.dev/)
- 📘 [MCP 协议规范](https://modelcontextprotocol.io/)
- 🐍 [Python 文档](https://docs.python.org/3/)
- 🐳 [Docker 文档](https://docs.docker.com/)
- 🧪 [Pytest 文档](https://docs.pytest.org/)

## ❓ 常见问题

**Q: 支持哪些 LLM provider？**
A: 运行 `rb-setup`，选择 OpenAI、OrcaRouter、DeepSeek、Groq、DashScope、NVIDIA NIM、Ollama 或自定义 OpenAI-compatible endpoint。命令会写入 `.env` 中的 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`。

**Q: 如何添加自定义工具？**
A: 将 Python 文件放进 `repobrain_engine/tools/`，无需额外注册，见 [零配置特性](ZERO_CONFIG.md)。

**Q: 如何基于模板初始化一个新项目？**
A: 使用 `agent-repo-init` 的 `quick/full` 模式，或直接运行 `skills/agent-repo-init/scripts/init_project.py`，见 [零配置特性](ZERO_CONFIG.md)。

**Q: 如何部署到生产？**
A: 使用 Docker，参考 [快速开始](QUICK_START.md) Docker 部分。

**Q: 是否支持多 Agent？**
A: 支持，使用 Swarm 系统，见 [多 Agent Swarm](SWARM_PROTOCOL.md)。

**Q: 如何添加知识/上下文？**
A: 在 `.context/` 创建文件会被自动加载，详见 [零配置特性](ZERO_CONFIG.md)。

**Q: 什么是知识中枢？**
A: 知识中枢（`rb-ask`、`rb-refresh`、`rb report`、`rb log-decision`）在 `.repobrain/` 中维护项目上下文，让所有 AI IDE 更智能。详见主 [README](../../README.md)。

**Q: 模块检测支持哪些语言？**
A: Python、TypeScript/JavaScript、Go、Rust、Java、Kotlin、Swift、C/C++、C#。扫描器使用统一的扩展名列表跨语言检测模块。

**Q: 什么是结构化 facts？**
A: 自 2026 年 4 月起，`rb-refresh` 为每个模块生成结构化 JSON 声明（claims），附带源码证据（文件路径 + 行范围）。`rb-ask` 在回答前先对照源码验证这些声明，降低幻觉率并提高可追溯性。

## 🤝 贡献

- 报告问题或想法：[GitHub Issues](https://github.com/study8677/repobrain/issues)
- 提交代码或改进文档：优先关注 [开发路线图](ROADMAP.md) Phase 9 的议题
- 欢迎通过 PR 修复错别字、补充示例

## 📞 支持

- 📖 文档：当前页面或主仓库 `README.md`
- 🐛 Bug：GitHub Issues
- 💡 Feature：GitHub Discussions
- 👥 社区：给仓库加星以获取更新

## 👥 贡献者

- [@devalexanderdaza](https://github.com/devalexanderdaza) — 初始贡献者，完成 demo 工具、Agent 功能增强、MCP 集成与早期路线设计。
- [@Subham-KRLX](https://github.com/Subham-KRLX) — 增加动态工具/上下文加载（Fixes #4）与多 Agent 集群协议（Fixes #6）。
- [@SunkenCost](https://github.com/SunkenCost) — 新增 `rb clean` 清理命令与 `__main__` 入口保护（#37）。
- [@aravindhbalaji04](https://github.com/aravindhbalaji04) — 统一指令层围绕 `AGENTS.md`（#41）。
- [@xiaolai](https://github.com/xiaolai) — 提供 [NLPM](https://github.com/xiaolai/nlpm-for-claude) 审计反馈，帮助改进 skill frontmatter 与依赖版本卫生（#51、#52、#53）。

## 📄 许可证

MIT License，详见仓库根目录 `LICENSE`。

---

**最后更新：2026 年 4 月**
**当前版本：Phase 10（知识中枢）✅ —— 结构化证据管道 + 多语言模块支持**

祝构建愉快！🚀

友情链接：[LINUX DO](https://linux.do/)
