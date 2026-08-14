# Installing the RepoBrain plugin

## Claude Code

```
/plugin marketplace add study8677/repobrain
/plugin install repobrain@repobrain
/repobrain:rb-setup
/repobrain:rb-refresh
/repobrain:rb-ask "what does this project do?"
```

1. **Marketplace add** — clones the plugin manifest into Claude Code's cache.
2. **Install** — first session triggers `hooks/install_engine.py`, which installs the engine (`rb-ask`, `rb-refresh`, `rb-mcp`) and injects the `rb` CLI into the same `pipx` environment. It falls back to `pip --user` or prints manual commands if installation fails. Cross-platform (macOS / Linux / Windows).
3. **Setup** — interactive: choose your LLM provider (OpenAI / DeepSeek / Groq / 阿里灵积 / NVIDIA / Ollama), paste your API key, writes a `.env` to the current project root and ensures it's git-ignored. For local Codex users, setup can instead write `RB_HOST_RUNNER=codex` for experimental no-API-key `rb-ask`.
4. **Refresh** — runs `rb-refresh` directly and builds `.repobrain/` for the current project. The first refresh creates the project knowledge directory automatically. Full LLM refresh requires an API key; Codex host-runner mode uses scan-only refresh artifacts.
5. **Ask** — runs `rb-ask` directly and queries the refreshed project knowledge base.

MCP is optional. If you want tool-style integration in an MCP-compatible host,
register `rb-mcp --workspace <project>` separately. To let `rb-ask` consume
external MCP servers, set both `MCP_ENABLED=true` and `RB_ALLOW_MCP=true` only
for servers you trust.
An example MCP config lives at `docs/examples/repobrain.mcp.json`.

You can also add the marketplace from a local checkout:

```
/plugin marketplace add /absolute/path/to/repobrain
```

## Codex CLI

Codex CLI does not auto-run install hooks (as of April 2026), so install the engine and inject the CLI first:

```
pipx install /absolute/path/to/repobrain/engine
pipx inject --force --include-apps repobrain-engine /absolute/path/to/repobrain/cli
rb doctor --help     # verify CLI + engine availability
```

Then register and install the plugin:

```
codex plugin marketplace add /absolute/path/to/repobrain
```

Codex auto-discovers slash commands from the plugin's `commands/` directory (no manifest entry required), so the same four commands are available without the `repobrain:` prefix:

```
/rb-setup
/rb-refresh
/rb-ask "what does this project do?"
/rb-init my-new-project
```

You can also keep using the raw CLI directly: `rb-refresh --workspace <project>` and `rb-ask "question" --workspace <project>`.
If your Codex build supports MCP and you want tool-style integration, register
`rb-mcp --workspace <project>` separately in your Codex MCP configuration.

### Codex host-runner mode without an API key

If you are only using RepoBrain locally and your Codex CLI is already logged
in with ChatGPT, you can use the experimental host runner for `rb-ask`:

```
codex login status
cat >> .env <<'EOF'
RB_HOST_RUNNER=codex
RB_HOST_MODEL=gpt-5.3-codex-spark
RB_HOST_TIMEOUT_SECONDS=240
RB_HOST_MAX_CONTEXT_CHARS=60000
RB_REFRESH_SCAN_ONLY=1
EOF

rb-refresh --workspace .      # scan-only artifacts, no API key
rb-ask "what does this project do?" --workspace .
```

This mode is ask-only and depends on the user's local Codex installation and
login. It is not a hosted product backend and does not replace API-key-backed
full refresh.

## DeepSeek Harness

DeepSeek Harness (`dsh`) is a compatible host, not a native RepoBrain plugin.
It is also not the same thing as choosing DeepSeek as the `rb-setup` LLM
provider. There is no `/plugin marketplace add` path and no Cordis bundle in
this repository.

Install the engine first, the same way Codex users do:

```
pipx install /absolute/path/to/repobrain/engine
pipx inject --force --include-apps repobrain-engine /absolute/path/to/repobrain/cli
rb doctor --help
```

Then pick one of these opt-in paths:

1. **CLI via shell** — in a DSH session whose workspace is the project, run
   `rb-refresh --workspace .` and `rb-ask "what does this project do?" --workspace .`.
   DSH already loads `AGENTS.md` / `CLAUDE.md`.
2. **MCP overlay** — replace `/path/to/project` in
   [docs/examples/repobrain.dsh.cordis.yml](docs/examples/repobrain.dsh.cordis.yml)
   and launch:

```
dsh web --patch /absolute/path/to/repobrain/docs/examples/repobrain.dsh.cordis.yml
```

You can instead merge that `insert` block into `$DSH_HOME/cordis.patch.yml`.
The overlay starts `rb-mcp` over stdio. Treat it as trusted local code. Default
Claude Code and Codex plugin installs do not auto-start this server.

DSH is in developer preview; the overlay only uses the published
`@deepseek-ai/dsh-mcp-client` fields. If `rb-mcp` is missing from PATH, DSH
typically still boots and the tools stay unavailable until the engine is
installed.

## Verifying

- **General check**: run `rb doctor --workspace <project>` after installation. It should report engine, provider, knowledge freshness, and log locations without exposing the API key.
- **Claude Code**: `/repobrain:rb-ask "what does the engine do?"` should run `rb-ask` and print a routed answer.
- **Codex CLI**: `/rb-ask "what does the engine do?"` (or `rb-ask "..." --workspace <project>` from the shell) should print a routed answer.
- **DeepSeek Harness**: `rb-ask "what does the engine do?" --workspace <project>` from the DSH shell, or `ask_project` after loading the overlay, should print a routed answer.

## Available slash commands

Same four commands ship to both hosts. Claude Code namespaces them as `/repobrain:<name>`; Codex CLI surfaces them as bare `/<name>`.

| Claude Code | Codex CLI | What it does |
|---|---|---|
| `/repobrain:rb-setup` | `/rb-setup` | **First-time setup** — interactive `.env` writer (LLM provider + key + model, or local Codex host runner) |
| `/repobrain:rb-refresh [quick]` | `/rb-refresh [quick]` | Rebuild / incrementally update the project knowledge base |
| `/repobrain:rb-ask <question>` | `/rb-ask <question>` | Routed Q&A on the current codebase |
| `/repobrain:rb-init <name>` | `/rb-init <name>` | Scaffold a new multi-agent repo from this template |

The plugin also bundles the `agent-repo-init` skill (description-matched in either host), which is what `/rb-init` invokes under the hood.

## Optional MCP tools

If you manually register `rb-mcp`, the `repobrain` MCP server exposes:

- `ask_project(question)` — routed Q&A with file paths and line numbers
- `refresh_project(quick=False)` — rebuild knowledge base

Example configs:

- generic MCP host: [docs/examples/repobrain.mcp.json](docs/examples/repobrain.mcp.json)
- DeepSeek Harness overlay: [docs/examples/repobrain.dsh.cordis.yml](docs/examples/repobrain.dsh.cordis.yml)

## Uninstall

```
pipx uninstall repobrain-engine
/plugin uninstall repobrain
```

## Requirements

- Python 3.10+ on PATH (`python3` / `python`)
- `pipx` recommended (`brew install pipx`, `apt install pipx`, or `python3 -m pip install --user pipx`)
- Network access on first launch (for the auto-installer)

## Safety Boundaries

- Default local execution is intended for trusted local workspaces, not
  untrusted-code isolation.
- `RB_RETRIEVAL_MODE=compact` is the default. `full` keeps richer retrieval
  artifacts; common secrets are redacted before write, but source snippets can
  still be captured.
- MCP stdio servers inherit process environment plus configured `env` values.
  Treat enabled servers as local-permission code.

## Troubleshooting

**`rb` / `rb-ask` / `rb-refresh` not found after install**
The user-pip bin directory may not be on PATH. The installer prints the path; add it to your shell rc file (`~/.zshrc`, `~/.bashrc`, etc.).

**Optional MCP tool is not connected**
The default slash commands do not require MCP. If you manually enabled `rb-mcp`, restart the MCP host so it reloads server configuration.

**Diagnostic log**
`rb-mcp` writes startup and tool errors to `~/.claude/plugins/data/repobrain-repobrain/rb-mcp.log` unless Claude provides a plugin data directory.

**Do I need `/rb-init` before refresh?**
No. `/rb-refresh` initializes the current project's `.repobrain/` directory automatically. `/rb-init` is for scaffolding a new repository from the RepoBrain template.

**Hook timed out**
The first install allows up to 15 minutes for the engine dependency set. On a slower network, run `pipx install <plugin-root>/engine` followed by `pipx inject --force --include-apps repobrain-engine <plugin-root>/cli` before restarting.

**Codex CLI marketplace add fails or does not auto-load the plugin**
Codex's marketplace/plugin workflow varies by CLI build. If `codex plugin marketplace add <path>` rejects the repo, or if your build only registers the marketplace without installing plugins, register the MCP server directly via your local Codex CLI MCP config and load skills + commands from `<path>/skills/` and `<path>/commands/` manually.

**DeepSeek Harness overlay does not expose tools**
Confirm `rb-mcp` is on PATH, replace `/path/to/project` in the overlay, and
restart `dsh` so it reloads the patch. The overlay is opt-in; DSH does not
discover `.claude-plugin/` or `commands/*.md`. This is not a DeepSeek API key
problem — `rb-setup` choosing DeepSeek as the LLM provider does not configure
the DSH host.
