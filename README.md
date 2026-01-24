# 🪐 Google Antigravity Workspace Template

**Production-grade starter kit for autonomous AI agents on Google Antigravity.**

Language: [English](/docs/en/) | [中文（仓库主页）](README_CN.md) | [中文文档](/docs/zh/) | [Español](/docs/es/)

![License](https://img.shields.io/badge/License-MIT-green)
![Gemini](https://img.shields.io/badge/AI-Gemini_2.0_Flash-blue)
![Architecture](https://img.shields.io/badge/Architecture-Event_Driven-purple)
![Memory](https://img.shields.io/badge/Context-Infinite-orange)

## 🌟 Project Intent

In a world full of AI IDEs, I want enterprise-grade architecture to be as simple as **Clone → Rename → Prompt**.

This project leverages IDE context awareness (via `.cursorrules` and `.antigravity/rules.md`) to pre-embed a complete **cognitive architecture** in the repo.

When you open this project, your IDE stops being just an editor—it becomes an **industry-savvy architect**.

**First principles:**

- Minimize repetition: the repo should encode defaults so setup is nearly zero.
- Make intent explicit: capture architecture, context, and workflows in files, not tribal knowledge.
- Treat the IDE as a teammate: contextual rules turn the editor into a proactive architect, not a passive tool.

### Why do we need a thinking scaffold?

While building with Google Antigravity or Cursor, I found a pain point:

**The IDE and models are powerful, but the empty project is too weak.**

Every new project repeats the same boring setup:

- "Should my code live in `src` or `app`?"
- "How do I define utilities so Gemini recognizes them?"
- "How do I help the AI remember prior context?"

This repetition wastes creative energy. My ideal workflow is: **after a git clone, the IDE already knows what to do.**

So I built this project: **Antigravity Workspace Template**.

## ⚡ Quick Start

### Automated Installation (Recommended)

**Linux / macOS:**
```bash
# 1. Clone the template
git clone https://github.com/study8677/antigravity-workspace-template.git my-project
cd my-project

# 2. Run the installer
chmod +x install.sh
./install.sh

# 3. Configure your API keys
nano .env

# 4. Run the agent
source venv/bin/activate
python src/agent.py
```

**Windows:**
```cmd
# 1. Clone the template
git clone https://github.com/study8677/antigravity-workspace-template.git my-project
cd my-project

# 2. Run the installer
install.bat

# 3. Configure your API keys (notepad .env)

# 4. Run the agent
python src/agent.py
```

### Manual Installation

```bash
# 1. Clone the template
git clone https://github.com/study8677/antigravity-workspace-template.git my-project
cd my-project

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure your API keys
cp .env.example .env  # (if available) or create .env manually
nano .env

# 5. Run the agent
python src/agent.py
```

**That's it!** The IDE auto-loads configuration via `.cursorrules` + `.antigravity/rules.md`. You're ready to prompt.

## 🎯 What Is This?

This is **not** another LangChain wrapper. It's a minimal, transparent workspace for building AI agents that:

- 🧠 Have infinite memory (recursive summarization)
- 🛠️ Auto-discover tools from `src/tools/`
- 📚 Auto-inject context from `.context/`
- 🔌 Connect to MCP servers seamlessly
- 🤖 Coordinate multiple specialist agents
- 📦 Save outputs as artifacts (plans, logs, evidence)

**Clone → Rename → Prompt. That's the workflow.**

## 🚀 Key Features

| Feature | Description |
|---------|-------------|
| 🧠 **Infinite Memory** | Recursive summarization compresses context automatically |
| 🧠 **True Thinking** | "Deep Think" step using Chain-of-Thought prompts before acting |
| 🎓 **Skills System** | Modular capabilities as folders (`src/skills/`) with auto-loading |
| 🛠️ **Universal Tools** | Drop Python functions in `src/tools/` → auto-discovered |
| 📚 **Auto Context** | Add files to `.context/` → auto-injected into prompts |
| 🔌 **MCP Support** | Connect GitHub, databases, filesystems, custom servers |
| 🤖 **Swarm Agents** | Multi-agent orchestration with Router-Worker pattern |
| ⚡ **Gemini Native** | Optimized for Gemini 2.0 Flash |
| 🌐 **LLM Agnostic** | Use OpenAI, Azure, Ollama, or any OpenAI-compatible API |
| 📂 **Artifact-First** | Every task produces plans, logs, and evidence |
| 🔒 **Sandbox Execution** | Configurable code execution environments (local by default) |

## 📚 Documentation

**Full documentation available in `/docs/en/`:**

- **[Quick Start](docs/en/QUICK_START.md)** — Installation & deployment
- **[Philosophy](docs/en/PHILOSOPHY.md)** — Core concepts & architecture
- **[Zero-Config](docs/en/ZERO_CONFIG.md)** — Auto tool & context loading
- **[MCP Integration](docs/en/MCP_INTEGRATION.md)** — External tool connectivity
- **[Swarm Protocol](docs/en/SWARM_PROTOCOL.md)** — Multi-agent coordination
- **[Roadmap](docs/en/ROADMAP.md)** — Future phases & vision

### Sandbox Configuration (Zero-Config by default)

The sandbox lets the agent execute generated Python code safely and consistently. It defaults to a local subprocess with isolation and limits.

- `SANDBOX_TYPE`: `local` (default) | `docker` (opt-in) | `e2b` (future)
- `SANDBOX_TIMEOUT_SEC`: maximum execution time in seconds (default `30`)
- `SANDBOX_MAX_OUTPUT_KB`: truncate stdout/stderr to limit size (default `10`)

Docker (opt-in) extra variables:
- `DOCKER_IMAGE` (default `python:3.11-slim`)
- `DOCKER_NETWORK_ENABLED` (`false` by default)
- `DOCKER_CPU_LIMIT` (default `0.5` cores)
- `DOCKER_MEMORY_LIMIT` (default `256m`)

Example:

```bash
export SANDBOX_TYPE=local
export SANDBOX_TIMEOUT_SEC=30
export SANDBOX_MAX_OUTPUT_KB=10
# Docker mode
# export SANDBOX_TYPE=docker
# export DOCKER_IMAGE=python:3.11-slim
# export DOCKER_NETWORK_ENABLED=false
# export DOCKER_CPU_LIMIT=0.5
# export DOCKER_MEMORY_LIMIT=256m
```

## 🏗️ Project Structure

```
src/
├── agent.py           # Main agent loop
├── memory.py          # JSON memory manager
├── mcp_client.py      # MCP integration
├── swarm.py           # Multi-agent orchestration
├── agents/            # Specialist agents
├── tools/             # Your custom tools
└── skills/            # Modular skills (Zero-Config)

.context/             # Knowledge base (auto-injected)
.antigravity/         # Antigravity rules
artifacts/            # Outputs & evidence
```

## 💡 Example: Build a Tool in 30 Seconds

```python
# src/tools/my_tool.py
def analyze_sentiment(text: str) -> str:
    """Analyzes the sentiment of given text."""
    return "positive" if len(text) > 10 else "neutral"
```

**Restart agent.** Done! The tool is now available.

## 🔌 MCP Integration

Connect to external tools:

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

Agent automatically discovers and uses all MCP tools.

## 🤖 Multi-Agent Swarm

Decompose complex tasks:

```python
from src.swarm import SwarmOrchestrator

swarm = SwarmOrchestrator()
result = swarm.execute("Build and review a calculator")
```

The swarm automatically:
- 📤 Routes to Coder, Reviewer, Researcher agents
- 🧩 Synthesizes results
- 📂 Saves artifacts

## ✅ What's Complete

- ✅ Phase 1-7: Foundation, DevOps, Memory, Tools, Swarm, Discovery
- ✅ Phase 8: MCP Integration (fully implemented)
- 🚀 Phase 9: Enterprise Core (in progress)

## 🆕 Recent Updates

- Added **True Thinking**: The agent now performs a real "Deep Think" step (Chain-of-Thought) before every action, generating a structured plan.
- Added **Skills System**: New `src/skills/` directory allows for modular, folder-based agent capabilities (Docs + Code).
- Added local OpenAI-compatible backend support (e.g., Ollama) when no Google API key is provided.
- Fixed `.env` loading so runs from the `src/` folder still read the project-root config.
- CLI entrypoints (`agent.py` and `src/agent.py`) now accept tasks via arguments `AGENT_TASK`.

See [Roadmap](docs/en/ROADMAP.md) for details.

## 🤝 Contributing

Ideas are contributions too! Open an [issue](https://github.com/study8677/antigravity-workspace-template/issues) to:
- Report bugs
- Suggest features
- Propose architecture (Phase 9)

Or submit a PR to improve docs or code.

## 👥 Contributors

- [@devalexanderdaza](https://github.com/devalexanderdaza) — First contributor. Implemented demo tools, enhanced agent functionality, proposed the "Agent OS" roadmap, and completed MCP integration.
- [@Subham-KRLX](https://github.com/Subham-KRLX) — Added dynamic tools and context loading (Fixes #4) and the multi-agent cluster protocol (Fixes #6).

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=study8677/antigravity-workspace-template&type=Date)](https://star-history.com/#study8677/antigravity-workspace-template&Date)

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.

---

**[Explore Full Documentation →](docs/en/)**
