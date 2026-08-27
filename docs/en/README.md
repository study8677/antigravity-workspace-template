# 📚 RepoBrain Documentation

Welcome to the documentation for **RepoBrain** — a cross-IDE repository
knowledge engine for grounded codebase Q&A.

## 🎯 Quick Navigation

### Getting Started
- **[Quick Start Guide](QUICK_START.md)** — Installation, local development, and first steps
- **[Project Philosophy](PHILOSOPHY.md)** — Product thesis and support boundaries

### Core Features
- **[Zero-Config Features](ZERO_CONFIG.md)** — Automatic tool and context discovery
- **[MCP Integration](MCP_INTEGRATION.md)** — Connect to external tools and data sources
- **[Sandbox Execution](SANDBOX.md)** — Trusted-local boundary and Microsandbox opt-in
- **[Multi-Agent Swarm](SWARM_PROTOCOL.md)** — Orchestrate specialist agents for complex tasks

### Planning & Vision
- **[Development Roadmap](ROADMAP.md)** — Current progress and future plans through Phase 9

## 🌟 Key Features

### 🧠 Repository Knowledge Base
`rb-refresh` builds `.repobrain/` so AI tools can reason over a fresh model of
the repository.

### 🛠️ Routed Codebase Q&A
`rb-ask` routes questions to the right module context and answers with file
evidence.

### 🎓 Native Plugin Channels
Claude Code and Codex CLI get slash commands for setup, refresh, ask, and
workspace bootstrapping.

### 🔌 Compatible Integrations
Other IDEs can use shared context files, raw CLI commands, or the optional MCP
server.

## 🚀 Common Tasks

### I want to...

| Task | Documentation |
|------|----------------|
| Get started with RepoBrain | [Quick Start](QUICK_START.md) |
| Build a custom tool | [Zero-Config Features](ZERO_CONFIG.md) |
| Initialize a new project from this template | [Zero-Config Features](ZERO_CONFIG.md) |
| Connect to an MCP server | [MCP Integration](MCP_INTEGRATION.md) |
| Use multiple agents | [Multi-Agent Swarm](SWARM_PROTOCOL.md) |
| Understand the architecture | [Project Philosophy](PHILOSOPHY.md) |
| See what's coming | [Development Roadmap](ROADMAP.md) |
| Query project context | `rb-ask "question"` / `rb-refresh` |

## 📊 Project Structure

```
.
├── cli/                         # rb CLI, templates, offline helpers
├── engine/repobrain_engine/    # Knowledge engine, hub, MCP server, sandbox
├── commands/                    # Shared slash-command definitions
├── skills/                      # Plugin-facing skills
├── docs/                        # Documentation in multiple languages
├── artifacts/                   # Plans, reports, and benchmark outputs
├── memory/                      # Markdown interaction memory
└── .repobrain/                # Generated knowledge base in target repos
```

## 🎓 Documentation by Role

### For Developers
1. Start with [Quick Start](QUICK_START.md)
2. Learn [Zero-Config tool discovery](ZERO_CONFIG.md)
3. Explore the [swarm protocol](SWARM_PROTOCOL.md)

### For DevOps/Deployment
1. Read [Quick Start](QUICK_START.md) Docker section
2. Check [Development Roadmap](ROADMAP.md) Phase 9 (Enterprise Core)
3. Configure MCP servers in [MCP Integration](MCP_INTEGRATION.md)

### For Architects
1. Understand [Project Philosophy](PHILOSOPHY.md)
2. Study [Multi-Agent Swarm](SWARM_PROTOCOL.md) architecture
3. Review [Development Roadmap](ROADMAP.md) vision

### For Contributors
1. Read [Project Philosophy](PHILOSOPHY.md)
2. Read the repository root `CONTRIBUTING.md`
3. Open an issue to propose ideas

## 🔗 External Resources

- 🌐 [RepoBrain Official Docs](https://docs.repobrain.dev/)
- 📘 [MCP Protocol Specification](https://modelcontextprotocol.io/)
- 🐍 [Python Documentation](https://docs.python.org/3/)
- 🐳 [Docker Documentation](https://docs.docker.com/)
- 🧪 [Pytest Documentation](https://docs.pytest.org/)

## ❓ FAQ

**Q: Which LLM providers are supported?**  
A: Run `rb-setup` and choose one of the OpenAI-compatible providers it offers: OpenAI, DeepSeek, Groq, DashScope, NVIDIA NIM, Ollama, or a custom endpoint. The command writes `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `OPENAI_MODEL`.

**Q: How do I add a custom tool?**  
A: Drop a Python file in `engine/repobrain_engine/tools/` with your functions. No registration needed! See [Zero-Config Features](ZERO_CONFIG.md).

**Q: How do I initialize a fresh project from this template?**  
A: Use the `agent-repo-init` skill in `quick` or `full` mode, or run `skills/agent-repo-init/scripts/init_project.py`. See [Zero-Config Features](ZERO_CONFIG.md).

**Q: How do I deploy the MCP server?**  
A: Use Docker or run `rb-mcp --workspace <project>`. See [Quick Start](QUICK_START.md) Docker section.

**Q: Can I use multiple agents?**  
A: Yes! Use the swarm system. See [Multi-Agent Swarm](SWARM_PROTOCOL.md).

**Q: How do I add context/knowledge?**
A: Create files in `.context/` directory. They're automatically loaded! See [Zero-Config Features](ZERO_CONFIG.md).

**Q: What is the Knowledge Hub?**
A: The Knowledge Hub (`rb-ask`, `rb-refresh`, `rb report`, `rb log-decision`) maintains project context in `.repobrain/`, making all AI IDEs smarter. See the main [README](../../README.md).

**Q: What languages does module detection support?**
A: Python, TypeScript/JavaScript, Go, Rust, Java, Kotlin, Swift, C/C++, and C#. The scanner uses a unified extension list to detect modules across all supported languages.

**Q: What are structured facts?**
A: Since April 2026, `rb-refresh` produces structured JSON claims with source evidence (file path + line range) per module. `rb-ask` verifies these claims against live source before answering, reducing hallucination and improving traceability.

## 🤝 Contributing

We welcome contributions at all levels:

### Report Issues
Found a bug? [Open an issue](https://github.com/study8677/repobrain/issues)

### Suggest Ideas
Have an architectural idea? Ideas are contributions too!  
[Propose your thought](https://github.com/study8677/repobrain/issues/new)

### Submit Code
Ready to code? Check the [Roadmap](ROADMAP.md) Phase 9 for open areas.

### Improve Docs
See a typo or unclear section? Submit a PR to improve the docs!

## 📞 Support

- 📖 **Documentation**: You're reading it! (or check [README.md](../../README.md))
- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/study8677/repobrain/issues)
- 💡 **Feature Requests**: [GitHub Discussions](https://github.com/study8677/repobrain/discussions)
- 👥 **Community**: [Star the repo](https://github.com/study8677/repobrain) to stay updated

## 👥 Contributors

- [@devalexanderdaza](https://github.com/devalexanderdaza) — First contributor. Implemented demo tools, enhanced agent functionality, helped shape the early roadmap and completed MCP integration.
- [@Subham-KRLX](https://github.com/Subham-KRLX) — Added dynamic tools and context loading (Fixes #4) and the multi-agent cluster protocol (Fixes #6).
- [@SunkenCost](https://github.com/SunkenCost) — Added `rb clean` command and `__main__` entry-point guard (#37).
- [@aravindhbalaji04](https://github.com/aravindhbalaji04) — Unified instruction surface around `AGENTS.md` (#41).
- [@xiaolai](https://github.com/xiaolai) — Provided [NLPM](https://github.com/xiaolai/nlpm-for-claude) audit feedback that improved skill frontmatter and dependency hygiene (#51, #52, #53).

## 📄 License

This project is licensed under the **MIT License**. See [LICENSE](../../LICENSE) for details.

---

**Latest Update:** August 2026
**Current Architecture:** Generative knowledge hub + local host-runner + incremental agent-group refresh + structured evidence verification

Friendly Link: [LINUX DO](https://linux.do/)
