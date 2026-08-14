## ADDED Requirements

### Requirement: Optional DeepSeek Harness Overlay
The repository SHALL document DeepSeek Harness as a compatible host that
reuses the existing CLI and `rb-mcp` contracts. The overlay MUST remain
opt-in. Default Claude Code and Codex CLI plugin manifests MUST NOT
auto-start MCP.

#### Scenario: Overlay example registers rb-mcp
- **WHEN** a user opens `docs/examples/repobrain.dsh.cordis.yml`
- **THEN** the file inserts `@deepseek-ai/dsh-mcp-client`
- **AND** the command is `rb-mcp`
- **AND** the args include `--workspace` and a project path placeholder
- **AND** `WORKSPACE_PATH` is set to the same project path

#### Scenario: Overlay is not the default plugin install
- **WHEN** a user installs the Claude Code or Codex CLI plugin
- **THEN** the plugin manifests do not declare `mcpServers`
- **AND** no repo-root `.mcp.json` is shipped
- **AND** DeepSeek Harness is not presented as a marketplace plugin install

#### Scenario: CLI works without the overlay
- **WHEN** a DeepSeek Harness user has `rb-ask` and `rb-refresh` on PATH
- **THEN** install docs tell them they can run those commands in the DSH
  shell without loading the MCP overlay
- **AND** the docs distinguish this host path from choosing DeepSeek as the
  `rb-setup` LLM provider
