# Change: Document DeepSeek Harness as an opt-in CLI/MCP host

## Why

DeepSeek Harness (`dsh`) is a new coding-agent host with an official MCP
client. RepoBrain already exposes the same knowledge layer through CLI and
`rb-mcp`. The missing piece is a copyable overlay and install path, not a
third native plugin package. Cordis plugin APIs are still in developer
preview, so a TypeScript bundle would add a new packaging surface before the
host contract is stable.

## What Changes

- Add an opt-in DeepSeek Harness overlay example that registers `rb-mcp`
  through `@deepseek-ai/dsh-mcp-client`.
- Document DeepSeek Harness in `INSTALL.md` as a compatible host: install the
  engine, then use CLI via shell or the MCP overlay. This is not a Claude
  Code / Codex marketplace plugin.
- Keep default Claude and Codex plugin manifests free of auto-started MCP.
- Lock the overlay contract with packaging tests and the repo contract check.
- Name DeepSeek Harness in the compatible-host matrix, not the native-plugin
  row.

## Non-Goals

- No native Cordis / npm `dsh.bundle` package.
- No `ctx.tools` or `ctx.commands` TypeScript wrapper.
- No install hook that auto-installs the Python engine inside `dsh`.
- No README host badge that implies first-class plugin parity.
- No change to `.claude-plugin/` or `.codex-plugin/` version sync.
- Follow-up topic `add-dsh-native-plugin` stays closed until the Cordis
  plugin API is stable and a native command surface is clearly more
  ergonomic than CLI + MCP.

## Impact

- Affected specs: `deployment` (added optional host overlay)
- Affected code:
  - `docs/examples/repobrain.dsh.cordis.yml`
  - `INSTALL.md`
  - `README.md`, `README_CN.md`, `README_ES.md` (compatible-host lists)
  - `docs/*/PHILOSOPHY.md` (delivery-channel sentence)
  - `engine/tests/test_plugin_packaging.py`
  - `scripts/check_repo_contract.py`
