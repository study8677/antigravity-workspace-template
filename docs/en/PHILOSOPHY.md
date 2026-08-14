# Project Philosophy

## The Product Thesis

AI coding tools are strongest when they can ask focused questions against a
fresh model of the repository instead of rereading the whole tree on every task.
RepoBrain is that repository knowledge layer.

The core workflow is deliberately small:

1. `rb-refresh` scans the workspace and builds `.repobrain/` knowledge
   artifacts.
2. `rb-ask` routes a question to the right module context and answers with
   source evidence.
3. Plugins, CLI commands, context files, and MCP expose the same knowledge to
   different AI development environments.

## Design Principles

### One Knowledge Base, Many Hosts

The generated `.repobrain/` directory is portable project state. Claude Code,
Codex CLI, Cursor, Windsurf, Gemini CLI, Cline, Aider, DeepSeek Harness, and
other hosts should all benefit from the same repository model instead of
maintaining separate context systems.

### Grounded Answers Beat Broad Context

Large prompt dumps are easy to create and hard to trust. RepoBrain favors
routed answers backed by module-level knowledge, source paths, line evidence,
and optional graph context.

### Plugins Are Delivery Channels

Claude Code and Codex CLI receive native slash commands because that is the most
ergonomic path for those hosts. Other hosts that already speak shell or MCP,
including DeepSeek Harness, reuse the CLI and optional `rb-mcp` overlay instead
of a third native plugin package. The product boundary remains the knowledge
engine: `rb-refresh`, `rb-ask`, and the artifacts they produce.

### Compatibility Without Vendor Lock-In

The setup flow writes an OpenAI-compatible `.env` contract:
`OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `OPENAI_MODEL`. That keeps the engine
portable across OpenAI, DeepSeek, Groq, DashScope, NVIDIA NIM, Ollama, and custom
providers without making any one model the product default.

## What Belongs Here

RepoBrain should prioritize:

- better repository scanning and module grouping
- better grounded Q&A and evidence validation
- clear install paths for native plugin users
- stable CLI and MCP contracts
- documentation and CI checks that keep the product story consistent

Features that turn the repository into a generic agent operating system,
workflow manager, or unrelated scaffold should be kept separate unless they make
the repository knowledge engine measurably better.

---

**Next:** [Quick Start Guide](QUICK_START.md) | [Full Index](README.md)
