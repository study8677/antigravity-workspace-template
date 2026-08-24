"""CLI entry points for RepoBrain Engine.

Provides:
- rb-ask "question"   → ask the multi-agent cluster
- rb-refresh          → refresh the knowledge base (module agents self-learn)
- rb-mcp              → MCP server (see hub/mcp_server.py)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Sequence


def _parse_args(
    parser: argparse.ArgumentParser,
    argv: Sequence[str] | None,
) -> argparse.Namespace:
    """Parse CLI arguments from an explicit argv list or sys.argv.

    Args:
        parser: Configured argument parser.
        argv: Optional explicit argv list without the executable name.

    Returns:
        Parsed argument namespace.
    """
    if argv is None:
        return parser.parse_args()
    return parser.parse_args(list(argv))


def _run_ask_pipeline(workspace: Path, question: str) -> str:
    """Run the ask pipeline for CLI entry points."""
    import asyncio
    from repobrain_engine.hub.pipeline import ask_pipeline

    return asyncio.run(ask_pipeline(workspace, question))


def _split_answer_sections(answer_text: str) -> dict[str, object]:
    """Split a rendered answer into ``{answer, sources, limitations}``.

    The pipeline returns a single Markdown string. The host-runner path
    appends ``Sources:`` / ``Limitations:`` blocks (see
    :meth:`HostRunnerAnswer.to_markdown`); the LLM/structured paths return
    free-form prose with no such headers. This best-effort splitter peels off
    those trailing blocks when present so programmatic callers get structured
    fields, and otherwise leaves the whole text as ``answer`` with empty lists.

    Args:
        answer_text: The rendered answer string from ``ask_pipeline``.

    Returns:
        A dict with ``answer`` (str), ``sources`` (list[str]), and
        ``limitations`` (list[str]).
    """
    sources: list[str] = []
    limitations: list[str] = []

    # Match a trailing "Limitations:" block, then a trailing "Sources:" block.
    # Order matters: strip Limitations (which follows Sources) first so the
    # Sources regex then sees a clean tail.
    def _pop_block(text: str, header: str) -> tuple[str, list[str]]:
        pattern = re.compile(
            rf"\n\n{re.escape(header)}:\n((?:- .*(?:\n|$))+)\Z"
        )
        match = pattern.search(text)
        if not match:
            return text, []
        items = [
            line[2:].strip()
            for line in match.group(1).splitlines()
            if line.startswith("- ")
        ]
        return text[: match.start()], [item for item in items if item]

    remaining, limitations = _pop_block(answer_text, "Limitations")
    remaining, sources = _pop_block(remaining, "Sources")

    return {
        "answer": remaining.strip(),
        "sources": sources,
        "limitations": limitations,
    }


def _emit_ask_json(workspace: Path, question: str, answer_text: str) -> None:
    """Print the ask result as a stable JSON envelope on stdout.

    Guarantees a machine-parseable object so LLM tool wrappers never have to
    scrape human-formatted text:

        {"answer": ..., "sources": [...], "limitations": [...],
         "workspace": ..., "question": ...}
    """
    payload = _split_answer_sections(answer_text)
    payload["workspace"] = str(workspace)
    payload["question"] = question
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _run_refresh_pipeline(workspace: Path, *, quick: bool, failed_only: bool):
    """Run the refresh pipeline for CLI entry points."""
    import asyncio
    from repobrain_engine.hub.pipeline import refresh_pipeline

    return asyncio.run(
        refresh_pipeline(
            workspace=workspace,
            quick=quick,
            failed_only=failed_only,
        )
    )


def _diagnostic_log_path() -> Path:
    """Return the MCP diagnostic log path for actionable CLI errors."""
    try:
        from repobrain_engine.hub.mcp_server import _mcp_log_path

        return _mcp_log_path()
    except Exception:
        data_dir = os.environ.get("CLAUDE_PLUGIN_DATA_DIR", "").strip()
        if data_dir:
            base = Path(data_dir).expanduser()
        else:
            base = Path.home() / ".claude" / "plugins" / "data" / "repobrain-repobrain"
        return base / "rb-mcp.log"


def _debug_mode_enabled() -> bool:
    """Return whether full tracebacks should be printed."""
    value = os.environ.get("DEBUG_MODE", "")
    if value.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    try:
        from repobrain_engine.config import settings

        return bool(settings.DEBUG_MODE)
    except Exception:
        return False


def _one_line_message(exc: BaseException) -> str:
    """Return an exception message without embedded newlines."""
    message = str(exc).replace("\n", " ").replace("\r", " ").strip()
    return message or exc.__class__.__name__


def _suggestion_for_exception(exc: BaseException) -> str:
    """Return a short actionable suggestion for a CLI failure."""
    name = exc.__class__.__name__.lower()
    message = _one_line_message(exc).lower()
    if "timeout" in name or "timeout" in message or "timed out" in message:
        return "Try increasing RB_ASK_TIMEOUT_SECONDS or rerun rb doctor."
    if "connection" in name or "connect" in message or "provider" in message:
        return "Run rb doctor to check provider connectivity."
    if "permission" in name or "permission" in message:
        return "Check workspace file permissions, then rerun rb doctor."
    return "Run rb doctor for environment and knowledge-base diagnostics."


def _handle_unexpected_cli_exception(exc: Exception) -> None:
    """Print a compact actionable error, then optional debug traceback."""
    print(
        "Error: "
        f"{exc.__class__.__name__}: {_one_line_message(exc)}. "
        f"{_suggestion_for_exception(exc)} "
        f"Diagnostic log: {_diagnostic_log_path()}",
        file=sys.stderr,
    )
    if _debug_mode_enabled():
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    sys.exit(1)


def ask_main(argv: Sequence[str] | None = None) -> None:
    """Entry point for ``rb-ask``.

    Args:
        argv: Optional explicit argv list without the executable name.
    """

    parser = argparse.ArgumentParser(
        prog="rb-ask",
        description="Ask the RepoBrain multi-agent cluster a question",
    )
    parser.add_argument("question", help="Natural language question about the project")
    parser.add_argument("--workspace", default=".", help="Project root (default: cwd)")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON envelope "
        "{answer, sources, limitations, workspace, question} instead of "
        "human-formatted text. Errors are also emitted as JSON on stderr. "
        "Use this when an LLM or script calls rb-ask programmatically.",
    )
    args = _parse_args(parser, argv)

    workspace = Path(args.workspace).resolve()
    os.environ["WORKSPACE_PATH"] = str(workspace)

    try:
        answer_text = _run_ask_pipeline(workspace, args.question)
        if args.json:
            _emit_ask_json(workspace, args.question, answer_text)
        else:
            print(answer_text)
    except KeyboardInterrupt:
        sys.exit(130)
    except ValueError as exc:
        if args.json:
            print(
                json.dumps({"error": str(exc)}, ensure_ascii=False),
                file=sys.stderr,
            )
        else:
            print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 - CLI boundary formats unknown failures
        if args.json:
            print(
                json.dumps(
                    {"error": f"{exc.__class__.__name__}: {_one_line_message(exc)}"},
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            sys.exit(1)
        _handle_unexpected_cli_exception(exc)


def refresh_main(argv: Sequence[str] | None = None) -> None:
    """Entry point for ``rb-refresh``.

    Args:
        argv: Optional explicit argv list without the executable name.
    """

    parser = argparse.ArgumentParser(
        prog="rb-refresh",
        description="Refresh the RepoBrain knowledge base",
    )
    parser.add_argument("--workspace", default=".", help="Project root (default: cwd)")
    parser.add_argument("--quick", action="store_true", help="Only scan changed files")
    parser.add_argument("--failed-only", action="store_true", help="Only re-run modules that failed in the previous refresh")
    args = _parse_args(parser, argv)

    workspace = Path(args.workspace).resolve()
    os.environ["WORKSPACE_PATH"] = str(workspace)

    try:
        status = _run_refresh_pipeline(
            workspace=workspace,
            quick=args.quick,
            failed_only=args.failed_only,
        )
        if getattr(status, "exit_code", 0) != 0:
            sys.exit(int(status.exit_code))
    except KeyboardInterrupt:
        sys.exit(130)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 - CLI boundary formats unknown failures
        _handle_unexpected_cli_exception(exc)


def mcp_main(argv: Sequence[str] | None = None) -> None:
    """Entry point for ``rb-mcp``.

    Args:
        argv: Optional explicit argv list without the executable name.
    """
    from repobrain_engine.hub.mcp_server import main as mcp_server_main

    if argv is None:
        mcp_server_main()
        return

    original_argv = sys.argv[:]
    try:
        sys.argv = ["rb-mcp", *list(argv)]
        mcp_server_main()
    finally:
        sys.argv = original_argv


def _dispatch_main(argv: Sequence[str] | None, prog: str) -> None:
    """Dispatch a subcommand-oriented module entrypoint.

    Args:
        argv: Optional explicit argv list without the executable name.
        prog: Program name shown in argparse help.
    """
    parser = argparse.ArgumentParser(
        prog=prog,
        description="RepoBrain engine command dispatcher",
    )
    parser.add_argument(
        "command",
        choices=("ask", "refresh", "mcp"),
        help="Engine command to run",
    )
    parsed, remainder = parser.parse_known_args(
        sys.argv[1:] if argv is None else list(argv)
    )

    if parsed.command == "ask":
        ask_main(remainder)
        return
    if parsed.command == "refresh":
        refresh_main(remainder)
        return
    mcp_main(remainder)


def engine_main(argv: Sequence[str] | None = None) -> None:
    """Entry point for ``python -m repobrain_engine``.

    Args:
        argv: Optional explicit argv list without the executable name.
    """
    _dispatch_main(argv, "repobrain_engine")


def hub_main(argv: Sequence[str] | None = None) -> None:
    """Entry point for ``python -m repobrain_engine.hub``.

    Args:
        argv: Optional explicit argv list without the executable name.
    """
    _dispatch_main(argv, "repobrain_engine.hub")
