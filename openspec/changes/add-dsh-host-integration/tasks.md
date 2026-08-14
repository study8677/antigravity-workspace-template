## 1. Overlay example

- [x] 1.1 Add `docs/examples/repobrain.dsh.cordis.yml` that inserts
      `@deepseek-ai/dsh-mcp-client` with `rb-mcp --workspace /path/to/project`
- [x] 1.2 Keep the overlay opt-in; do not add `mcpServers` to plugin manifests

## 2. Install and positioning docs

- [x] 2.1 Add a DeepSeek Harness section to `INSTALL.md` covering engine
      install, CLI-via-shell, and the overlay `--patch` path
- [x] 2.2 Point the optional MCP section at both host examples
- [x] 2.3 List DeepSeek Harness under compatible hosts, not native plugins
- [x] 2.4 Add one delivery-channel sentence in philosophy docs

## 3. Contract tests

- [x] 3.1 Assert the DSH overlay uses `rb-mcp` and a workspace path
- [x] 3.2 Keep the existing "plugin manifests do not auto-register MCP" test
- [x] 3.3 Extend `scripts/check_repo_contract.py` so INSTALL keeps the
      overlay example and the opt-in MCP warning
