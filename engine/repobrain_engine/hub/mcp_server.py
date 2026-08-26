"""RepoBrain Knowledge Hub — MCP Server.

Exposes `ask_project` and `refresh_project` as MCP tools so that
Claude Code (and any MCP-compatible AI IDE) can query the project
knowledge base without doing its own grep/file search.

Usage (stdio transport):
    python -m repobrain_engine.hub.mcp_server --workspace /path/to/project

Or via the installed entry-point:
    rb-mcp --workspace /path/to/project

Then configure in Claude Code's MCP settings (~/.claude/mcp.json):
    {
      "mcpServers": {
        "repobrain": {
          "command": "rb-mcp",
          "args": ["--workspace", "/path/to/your/project"]
        }
      }
    }
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP


_SECRET_PATTERNS = (
    (
        re.compile(r"(?i)\b([A-Z0-9_]*API_KEY)\s*=\s*([^\s,;]+)"),
        r"\1=<redacted>",
    ),
    (
        re.compile(r"(?i)(Authorization\s*:\s*)(?:Bearer\s+)?([^\s,;]+)"),
        r"\1<redacted>",
    ),
    (re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._~+/=-]+)"), "Bearer <redacted>"),
    (re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9._-]{6,}"), "sk-<redacted>"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{6,}"), "AIza<redacted>"),
)


def _redact_secrets(value: object) -> str:
    """Redact common API key and authorization token patterns."""
    text = str(value)
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _package_version() -> str:
    """Return the installed engine package version when available."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("repobrain-engine")
    except Exception:
        try:
            from repobrain_engine import __version__

            return __version__
        except Exception:
            return "unknown"


def _mcp_log_path() -> Path:
    """Return the user-visible log path for rb-mcp startup/tool errors."""
    data_dir = os.environ.get("CLAUDE_PLUGIN_DATA_DIR", "").strip()
    if data_dir:
        base = Path(data_dir).expanduser()
    else:
        base = Path.home() / ".claude" / "plugins" / "data" / "repobrain-repobrain"
    base.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(base, 0o700)
    except OSError:
        pass
    return base / "rb-mcp.log"


def _log_mcp_event(message: str) -> Path:
    """Append a small diagnostic event without including environment values."""
    log_path = _mcp_log_path()
    timestamp = datetime.now(timezone.utc).isoformat()
    clean = _redact_secrets(message).replace("\n", " ").replace("\r", " ")
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.chmod(log_path, 0o600)
    except OSError:
        pass
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} {clean}\n")
    return log_path


def _format_tool_error(tool_name: str, exc: Exception) -> str:
    """Return a user-actionable MCP tool error."""
    message = _redact_secrets(str(exc) or exc.__class__.__name__)
    log_path = _log_mcp_event(f"{tool_name} failed: {exc.__class__.__name__}: {message}")

    if "No LLM configured" in message:
        return (
            "Error: No LLM configured for this project. Run "
            "`/repobrain:rb-setup` (Claude Code) or `/rb-setup` (Codex CLI), "
            "restart the host once so rb-mcp reloads the project environment, "
            "then rerun this command."
        )
    if "Project initialization failed" in message:
        return f"Error: {message}"
    return (
        f"Error: {tool_name} failed: {message}\n"
        f"Diagnostic log: {log_path}"
    )


def _resolve_workspace(workspace: str | None) -> Path:
    """Resolve workspace path from argument, env, or upward-scan from cwd.

    Resolution order:
      1. --workspace argument (if usable)
      2. WORKSPACE_PATH env var (if usable)
      3. Walk up from cwd looking for a `.env` or `.git` marker — the
         common signature of a project root. This rescues cases where an
         MCP host doesn't substitute variables and spawns the server from
         a non-project cwd (cache dir, /, etc.).
      4. cwd as last resort.

    Treats values containing un-expanded `${...}` placeholders as missing.
    """
    def _usable(v: str | None) -> bool:
        return bool(v) and "${" not in v

    if _usable(workspace):
        resolved = Path(workspace).resolve()
        print(f"[rb-mcp] workspace from --arg: {resolved}", file=sys.stderr)
        return resolved
    env = os.environ.get("WORKSPACE_PATH", "")
    if _usable(env):
        resolved = Path(env).resolve()
        print(f"[rb-mcp] workspace from WORKSPACE_PATH env: {resolved}", file=sys.stderr)
        return resolved

    cwd = Path.cwd().resolve()
    for d in [cwd, *cwd.parents]:
        if (d / ".env").is_file() or (d / ".git").exists():
            print(
                f"[rb-mcp] workspace auto-detected by scanning up from cwd ({cwd}): {d}",
                file=sys.stderr,
            )
            return d
    print(f"[rb-mcp] workspace fallback to cwd (no .env/.git found upward): {cwd}", file=sys.stderr)
    return cwd


# Active workspace is module-level so MCP roots can upgrade it on the first
# tool call after the protocol handshake completes. Initialized by serve().
_active_workspace: Path | None = None
_roots_attempted = False


def _root_uri_to_path(uri: str) -> Path | None:
    """Convert an MCP file:// root URI to a filesystem Path."""
    from urllib.parse import unquote, urlparse

    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    raw = unquote(parsed.path or "")
    if not raw:
        return None
    return Path(raw).resolve()


async def _maybe_upgrade_via_roots(ctx) -> None:
    """If the MCP client supports the `roots` protocol, prefer its root.

    MCP clients (Claude Code, Cursor, etc.) typically advertise the open
    project as a workspace root. Asking the client directly is the most
    reliable workspace source — better than args (host may not substitute
    variables), better than env (same), better than cwd-scan (may pick a
    nested git repo or miss entirely).

    Idempotent: only attempts once per process. On success, updates
    `_active_workspace`, sets WORKSPACE_PATH env var, and resets the
    cached Settings so the new project's `.env` is read on next access.
    """
    global _active_workspace, _roots_attempted
    if _roots_attempted:
        return
    _roots_attempted = True

    try:
        result = await ctx.request_context.session.list_roots()
    except Exception as exc:  # noqa: BLE001 — client may not support roots
        print(f"[rb-mcp] MCP roots/list unavailable ({exc.__class__.__name__}): keeping workspace = {_active_workspace}", file=sys.stderr)
        return

    if not result.roots:
        print(f"[rb-mcp] MCP roots/list returned empty list: keeping workspace = {_active_workspace}", file=sys.stderr)
        return

    new_workspace = _root_uri_to_path(str(result.roots[0].uri))
    if new_workspace is None or not new_workspace.exists():
        print(f"[rb-mcp] MCP roots/list returned unusable URI {result.roots[0].uri!r}: keeping workspace = {_active_workspace}", file=sys.stderr)
        return

    if new_workspace == _active_workspace:
        print(f"[rb-mcp] MCP roots confirmed workspace = {_active_workspace}", file=sys.stderr)
        return

    print(f"[rb-mcp] upgrading workspace via MCP roots: {_active_workspace} → {new_workspace}", file=sys.stderr)
    _active_workspace = new_workspace
    os.environ["WORKSPACE_PATH"] = str(new_workspace)
    try:
        from repobrain_engine.config import reset_settings

        reset_settings()
    except Exception:  # noqa: BLE001
        pass


def serve(workspace: Path) -> None:
    """Start the MCP server on stdio.

    Args:
        workspace: Initial workspace guess from CLI/env/cwd-scan. Will be
            upgraded to the MCP client's reported root on the first tool call
            if the client supports the `roots` protocol.
    """
    global _active_workspace
    _active_workspace = workspace
    _log_mcp_event(f"starting rb-mcp workspace={workspace}")

    mcp = FastMCP(
        "RepoBrain Knowledge Hub",
        instructions=(
            "Use ask_project to answer any question about the codebase — "
            "where code lives, why decisions were made, how things work. "
            "Use refresh_project to rebuild the project knowledge base after "
            "significant changes. Prefer ask_project over manual file search."
        ),
    )

    @mcp.tool()
    async def ask_project(question: str, ctx: Context) -> str:
        """Answer a question about the project using the knowledge hub.

        Searches the codebase, reads actual source files, checks git history,
        and synthesizes a grounded answer with file paths and line numbers.
        Use this instead of manual grep or file reading.

        Args:
            question: Natural language question about the project, e.g.
                "Where is the authentication logic?",
                "Why was the JWT migration done?",
                "What does the Scanner class do?"

        Returns:
            Grounded answer with file paths, line numbers, and context.
        """
        await _maybe_upgrade_via_roots(ctx)
        from repobrain_engine.hub.pipeline import ask_pipeline

        try:
            return await ask_pipeline(_active_workspace, question)
        except Exception as exc:  # noqa: BLE001
            return _format_tool_error("ask_project", exc)

    @mcp.tool()
    async def refresh_project(quick: bool = False, ctx: Context = None) -> str:
        """Rebuild the project knowledge base (.repobrain/conventions.md and structure.md).

        Run this after significant code changes to keep the knowledge base
        up to date. Use quick=True to let RepoBrain judge and update only
        Agent groups affected by committed changes since the active generation.

        Args:
            quick: If True, run the bounded ImpactPlanner/ImpactVerifier loop.

        Returns:
            Confirmation message with updated file paths.
        """
        if ctx is not None:
            await _maybe_upgrade_via_roots(ctx)
        from repobrain_engine.hub.pipeline import refresh_pipeline

        try:
            status = await refresh_pipeline(_active_workspace, quick=quick)
            if status.overall_status == "unresolved":
                return (
                    "Knowledge base was not changed: incremental impact remains unresolved.\n"
                    f"Plan: {status.impact_plan_path or '(not written)'}"
                )
            from repobrain_engine.hub.storage import knowledge_root

            rb_dir = knowledge_root(_active_workspace)
            return (
                f"Knowledge base updated:\n"
                f"  {rb_dir / 'conventions.md'}\n"
                f"  {rb_dir / 'structure.md'}"
            )
        except Exception as exc:  # noqa: BLE001
            return _format_tool_error("refresh_project", exc)

    mcp.run(transport="stdio")


def main() -> None:
    """Entry point for rb-mcp CLI command."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="rb-mcp",
        description="RepoBrain Knowledge Hub MCP server (stdio transport)",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="Project root directory (default: WORKSPACE_PATH env or cwd)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_package_version()}",
    )
    args = parser.parse_args()

    try:
        workspace = _resolve_workspace(args.workspace)

        if not workspace.exists():
            raise RuntimeError(f"workspace does not exist: {workspace}")

        # Set env so pipeline picks up the workspace
        os.environ["WORKSPACE_PATH"] = str(workspace)

        serve(workspace)
    except Exception as exc:  # noqa: BLE001
        message = _redact_secrets(str(exc) or exc.__class__.__name__)
        log_path = _log_mcp_event(f"fatal startup error: {exc.__class__.__name__}: {message}")
        print(f"Error: rb-mcp failed to start: {message}", file=sys.stderr)
        print(f"Diagnostic log: {log_path}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
