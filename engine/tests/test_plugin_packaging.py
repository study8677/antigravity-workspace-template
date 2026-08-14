"""Regression tests for Claude/Codex plugin packaging files."""

from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _engine_package_version() -> str:
    pyproject = (REPO_ROOT / "engine" / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject, flags=re.MULTILINE)
    if match is None:
        raise AssertionError("engine/pyproject.toml has no project version")
    return match.group(1)


def test_plugin_versions_are_in_sync() -> None:
    """Claude, Codex, marketplace, and engine package versions stay aligned."""
    plugin_version = _engine_package_version()
    manifest = json.loads(
        (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    codex_manifest = json.loads(
        (REPO_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    marketplace = json.loads(
        (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    engine_pyproject = (REPO_ROOT / "engine" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    engine_init = (
        REPO_ROOT / "engine" / "repobrain_engine" / "__init__.py"
    ).read_text(encoding="utf-8")

    assert manifest["version"] == plugin_version
    assert codex_manifest["version"] == plugin_version
    assert marketplace["plugins"][0]["version"] == plugin_version
    assert f'version = "{plugin_version}"' in engine_pyproject
    assert f'__version__ = "{plugin_version}"' in engine_init


def test_plugin_manifests_do_not_auto_register_mcp() -> None:
    """Default plugin install should use CLI commands, not auto-start MCP."""
    manifest = json.loads(
        (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    codex_manifest = json.loads(
        (REPO_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )

    assert "mcpServers" not in manifest
    assert "mcpServers" not in codex_manifest
    assert not (REPO_ROOT / ".mcp.json").exists()


def test_optional_mcp_example_passes_workspace_to_rb_mcp() -> None:
    config = json.loads(
        (REPO_ROOT / "docs" / "examples" / "repobrain.mcp.json").read_text(
            encoding="utf-8"
        )
    )
    server = config["mcpServers"]["repobrain"]

    assert server["command"] == "rb-mcp"
    assert server["args"] == ["--workspace", "/path/to/project"]
    assert server["env"]["WORKSPACE_PATH"] == "/path/to/project"


def test_optional_dsh_overlay_passes_workspace_to_rb_mcp() -> None:
    overlay = (REPO_ROOT / "docs" / "examples" / "repobrain.dsh.cordis.yml").read_text(
        encoding="utf-8"
    )

    assert "@deepseek-ai/dsh-mcp-client" in overlay
    assert "serverName: repobrain" in overlay
    assert "transport: stdio" in overlay
    assert "command: rb-mcp" in overlay
    assert '"--workspace"' in overlay or "--workspace" in overlay
    assert "/path/to/project" in overlay
    assert "WORKSPACE_PATH" in overlay
    assert "mcpServers" not in overlay


def test_install_docs_keep_dsh_on_the_compatible_host_path() -> None:
    install = (REPO_ROOT / "INSTALL.md").read_text(encoding="utf-8")

    assert "## DeepSeek Harness" in install
    assert "docs/examples/repobrain.dsh.cordis.yml" in install
    assert "dsh web --patch" in install
    assert "rb-ask" in install
    assert "rb-refresh" in install
    assert "/plugin marketplace add" in install
    assert "is a compatible host, not a native RepoBrain plugin" in install
    assert "rb-setup" in install
    dsh_section = install.split("## DeepSeek Harness", 1)[1].split("## Verifying", 1)[0]
    assert "mcpServers" not in dsh_section
    assert "### Codex host-runner" not in dsh_section



def test_slash_commands_run_cli_without_mcp_tools() -> None:
    ask_command = (REPO_ROOT / "commands" / "rb-ask.md").read_text(encoding="utf-8")
    refresh_command = (REPO_ROOT / "commands" / "rb-refresh.md").read_text(
        encoding="utf-8"
    )

    assert 'allowed-tools: ["Bash"]' in ask_command
    assert 'allowed-tools: ["Bash"]' in refresh_command
    assert "rb-ask" in ask_command
    assert "rb-refresh" in refresh_command
    assert "mcp__" not in ask_command
    assert "mcp__" not in refresh_command


def test_legacy_unprefixed_mcp_tool_names_do_not_reappear() -> None:
    """Repo text should not route users back to the non-plugin MCP names."""
    legacy_names = (
        "mcp__repobrain__ask_project",
        "mcp__repobrain__refresh_project",
    )
    skipped_parts = {
        ".git",
        ".pytest_cache",
        "__pycache__",
        "venv",
        ".venv",
        ".tmp-venv",
        "repobrain_workspace_template_venv",
        # Generated / local-only dirs that are never part of shipped source:
        # the knowledge base, IDE & agent state, eval artifacts, build output.
        ".repobrain",
        ".claude",
        "artifacts",
        "build",
    }
    searchable_suffixes = {".md", ".json", ".py", ".toml"}
    this_file = Path(__file__).resolve()
    hits: list[str] = []

    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.resolve() == this_file:
            continue
        if any(part in skipped_parts for part in path.parts):
            continue
        if path.suffix not in searchable_suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for legacy_name in legacy_names:
            if legacy_name in text:
                hits.append(f"{path.relative_to(REPO_ROOT)}: {legacy_name}")

    assert hits == []
