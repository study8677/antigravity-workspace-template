## Context

RepoBrain's product boundary is `rb-refresh`, `rb-ask`, and `.repobrain/`.
Claude Code and Codex CLI have native slash-command plugins because that is
the most ergonomic path on those hosts. DeepSeek Harness already speaks
shell and MCP. Its first-party plugin format is a TypeScript Cordis module
loaded from `cordis.yml`, which does not consume `.claude-plugin/` or
`commands/*.md`.

## Goals / Non-Goals

- Goals:
  - Give DSH users one obvious opt-in path that reuses `rb-mcp` and the CLI.
  - Keep MCP off by default.
  - Distinguish DSH-the-host from DeepSeek-the-LLM-provider in `rb-setup`.
- Non-Goals:
  - A third host-specific plugin runtime.
  - Auto-starting `rb-mcp` from Claude or Codex manifests.

## Decisions

- Decision: treat DeepSeek Harness like Cursor/Windsurf (compatible host),
  not like Claude/Codex (native plugin).
  - Alternatives considered: native Cordis bundle now. Rejected because the
    host is in developer preview and the portable contract already exists.
- Decision: ship a `cordis.yml` overlay example with an explicit
  `/path/to/project` placeholder, matching `docs/examples/repobrain.mcp.json`.
  - Alternatives considered: `!!js process.cwd()`. Rejected; implicit cwd is
    easy to mis-launch from the wrong directory.
- Decision: document the overlay in `INSTALL.md`, not as a top-level README
  install command.
- Decision: do not write Claude-style `mcp__repobrain__*` tool names in repo
  text. Existing packaging tests forbid those strings so docs keep routing
  users to CLI commands; describe DSH namespacing as
  `mcp__<serverName>__<rawName>` instead.

## Risks / Trade-offs

- DSH overlay schema may drift while the host is in preview → keep the
  example small and point at the official `@deepseek-ai/dsh-mcp-client`
  fields only.
- Users may confuse DeepSeek LLM setup with DSH host setup → INSTALL must
  say they are different.
- Overlay is trusted local stdio → restate the existing MCP permission
  warning.

## Migration Plan

Additive docs and an example file. No runtime default changes. Rollback is
delete the example and the INSTALL section.

## Open Questions

- None for this change. Native Cordis packaging is a later topic.
