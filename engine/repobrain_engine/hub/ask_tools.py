"""Code exploration tools for the Ask Swarm agents.

These tools let the ask-pipeline agents search, read, and inspect
the user's project at query time — turning ``rb ask`` from
"guess from metadata" into "answer with code evidence".

All tools are scoped to a *workspace* directory that is captured
via :func:`create_ask_tools`.  Path-traversal outside the workspace
is rejected.

Retrieval-graph persistence has been extracted to
:mod:`repobrain_engine.hub.retrieval_graph`.
"""
from __future__ import annotations

import fnmatch
import mimetypes
import os
import re
import subprocess
from pathlib import Path
from typing import Callable

from repobrain_engine.hub._constants import SKIP_DIRS
from repobrain_engine.hub._utils import is_safe_path, should_skip_dir
from repobrain_engine.hub.retrieval_graph import wrap_retrieval_tools
from repobrain_engine.hub.storage import knowledge_root

# Maximum search results returned by search_code.
_MAX_SEARCH_RESULTS = 50
# Maximum lines returned by read_file.
_MAX_READ_LINES = 200


# ---------------------------------------------------------------------------
# Tool factory — returns workspace-bound tool functions
# ---------------------------------------------------------------------------


def create_ask_tools(workspace: Path) -> dict[str, Callable]:
    """Create code-exploration tools bound to *workspace*.

    Returns a dict of ``{tool_name: callable}`` ready to be wrapped
    with the OpenAI Agent SDK ``function_tool`` decorator.

    Args:
        workspace: Absolute path to the user's project root.

    Returns:
        Dict mapping tool name to its implementation function.
    """
    ws = workspace.resolve()

    # ── search_code ───────────────────────────────────────────────

    def search_code(query: str, file_pattern: str = "*") -> str:
        """Search project source files for a text pattern.

        Args:
            query: Text or regex pattern to search for.
            file_pattern: Glob pattern to filter files (e.g. "*.py").

        Returns:
            Matching lines formatted as ``file:line: content``.
        """
        if not query:
            return "Error: query must not be empty."

        matches: list[str] = []
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = re.compile(re.escape(query), re.IGNORECASE)

        for dirpath_str, dirnames, filenames in os.walk(ws):
            dirnames[:] = [
                d for d in dirnames if not should_skip_dir(d)
            ]
            for fname in filenames:
                if file_pattern != "*" and not fnmatch.fnmatch(fname, file_pattern):
                    continue
                fpath = Path(dirpath_str) / fname
                try:
                    rel = fpath.relative_to(ws)
                except ValueError:
                    continue
                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for lineno, line in enumerate(text.splitlines(), 1):
                    if pattern.search(line):
                        matches.append(f"{rel}:{lineno}: {line.rstrip()}")
                        if len(matches) >= _MAX_SEARCH_RESULTS:
                            break
                if len(matches) >= _MAX_SEARCH_RESULTS:
                    break
            if len(matches) >= _MAX_SEARCH_RESULTS:
                break

        if not matches:
            return f"No results found for '{query}'."
        header = f"Found {len(matches)} result(s):\n"
        return header + "\n".join(matches)

    # ── read_file ─────────────────────────────────────────────────

    def read_file(file_path: str, start_line: int = 1, end_line: int = 100) -> str:
        """Read a file from the project, returning numbered lines.

        Args:
            file_path: Relative path from the project root.
            start_line: First line to return (1-based, default 1).
            end_line: Last line to return (default 100).

        Returns:
            Numbered source lines, or an error message.
        """
        target = (ws / file_path).resolve()
        if not is_safe_path(ws, target):
            return f"Error: path '{file_path}' is outside the project."
        if not target.is_file():
            return f"Error: '{file_path}' does not exist or is not a file."

        start_line = max(1, start_line)
        end_line = min(end_line, start_line + _MAX_READ_LINES - 1)

        try:
            all_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return f"Error reading '{file_path}': {exc}"

        selected = all_lines[start_line - 1 : end_line]
        numbered = [
            f"{start_line + i:>5}  {line}"
            for i, line in enumerate(selected)
        ]
        header = f"--- {file_path} (lines {start_line}-{start_line + len(selected) - 1} of {len(all_lines)}) ---\n"
        return header + "\n".join(numbered)

    # ── list_directory ────────────────────────────────────────────

    def list_directory(path: str = ".") -> str:
        """List the contents of a project directory.

        Args:
            path: Relative directory path from the project root.

        Returns:
            A formatted listing of files and subdirectories.
        """
        target = (ws / path).resolve()
        if not is_safe_path(ws, target):
            return f"Error: path '{path}' is outside the project."
        if not target.is_dir():
            return f"Error: '{path}' is not a directory."

        entries: list[str] = []
        try:
            for item in sorted(target.iterdir()):
                if should_skip_dir(item.name):
                    continue
                if item.is_dir():
                    entries.append(f"  {item.name}/")
                else:
                    size = item.stat().st_size
                    entries.append(f"  {item.name}  ({size} bytes)")
        except OSError as exc:
            return f"Error listing '{path}': {exc}"

        if not entries:
            return f"Directory '{path}' is empty."
        header = f"Contents of {path}/:\n"
        return header + "\n".join(entries)

    # ── read_file_metadata ────────────────────────────────────────

    def read_file_metadata(file_path: str) -> str:
        """Read lightweight metadata for a file without loading full content.

        Args:
            file_path: Relative path from the project root.

        Returns:
            Size/mime/binary flags and file system times.
        """
        target = (ws / file_path).resolve()
        if not is_safe_path(ws, target):
            return f"Error: path '{file_path}' is outside the project."
        if not target.exists() or not target.is_file():
            return f"Error: '{file_path}' does not exist or is not a file."

        try:
            st = target.stat()
            mime, _ = mimetypes.guess_type(target.name)
            binary = False
            try:
                with target.open("rb") as fh:
                    binary = b"\x00" in fh.read(2048)
            except OSError:
                pass
        except OSError as exc:
            return f"Error reading metadata '{file_path}': {exc}"

        return (
            f"Metadata for {file_path}:\n"
            f"- size_bytes: {st.st_size}\n"
            f"- mime: {mime or 'unknown'}\n"
            f"- is_binary: {binary}\n"
            f"- modified_ts: {st.st_mtime:.0f}"
        )

    # ── search_by_type ────────────────────────────────────────────

    def search_by_type(file_type: str, limit: int = 50) -> str:
        """Find files by high-level type: code/documentation/data/media/binary.

        Args:
            file_type: Target file type.
            limit: Maximum number of paths returned (max 200).

        Returns:
            Matching relative paths.
        """
        category = file_type.strip().lower()
        if category not in {"code", "documentation", "data", "media", "binary"}:
            return "Error: file_type must be one of code/documentation/data/media/binary."

        limit = max(1, min(limit, 200))
        ext_map = {
            "documentation": {".md", ".rst", ".txt", ".adoc", ".pdf"},
            "data": {".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".xml", ".sql", ".db", ".sqlite", ".parquet"},
            "media": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".mp3", ".wav", ".ogg", ".mp4", ".mov", ".avi", ".mkv"},
        }

        matches: list[str] = []
        for dirpath_str, dirnames, filenames in os.walk(ws):
            dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
            for fname in filenames:
                fpath = Path(dirpath_str) / fname
                try:
                    rel = fpath.relative_to(ws)
                except ValueError:
                    continue
                ext = fpath.suffix.lower()

                if category == "code":
                    hit = ext in {
                        ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs", ".cpp", ".c", ".swift", ".dart", ".lua", ".sh", ".html", ".css", ".scss", ".sql",
                    }
                elif category in ext_map:
                    hit = ext in ext_map[category]
                else:
                    try:
                        with fpath.open("rb") as fh:
                            hit = b"\x00" in fh.read(2048)
                    except OSError:
                        hit = False

                if hit:
                    matches.append(rel.as_posix())
                    if len(matches) >= limit:
                        break
            if len(matches) >= limit:
                break

        if not matches:
            return f"No files found for type '{category}'."
        return f"Found {len(matches)} file(s) for type '{category}':\n" + "\n".join(matches)

    # ── summarize_directory ───────────────────────────────────────

    def summarize_directory(path: str = ".") -> str:
        """Summarize a directory by file counts and total size per extension."""
        target = (ws / path).resolve()
        if not is_safe_path(ws, target):
            return f"Error: path '{path}' is outside the project."
        if not target.is_dir():
            return f"Error: '{path}' is not a directory."

        counts: dict[str, int] = {}
        sizes: dict[str, int] = {}
        total_files = 0
        for dirpath_str, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
            for fname in filenames:
                fpath = Path(dirpath_str) / fname
                ext = fpath.suffix.lower() or "(no-ext)"
                try:
                    sz = fpath.stat().st_size
                except OSError:
                    sz = 0
                counts[ext] = counts.get(ext, 0) + 1
                sizes[ext] = sizes.get(ext, 0) + sz
                total_files += 1

        lines = [f"Directory summary for {path}:", f"- total_files: {total_files}"]
        for ext, c in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:20]:
            lines.append(f"- {ext}: {c} file(s), {sizes.get(ext, 0)} bytes")
        return "\n".join(lines)

    # ── read_binary_stub ──────────────────────────────────────────

    def read_binary_stub(file_path: str, preview_bytes: int = 64) -> str:
        """Read a safe hex preview of a binary file.

        Args:
            file_path: Relative path from workspace.
            preview_bytes: Number of bytes to preview (max 256).
        """
        target = (ws / file_path).resolve()
        if not is_safe_path(ws, target):
            return f"Error: path '{file_path}' is outside the project."
        if not target.exists() or not target.is_file():
            return f"Error: '{file_path}' does not exist or is not a file."

        n = max(16, min(preview_bytes, 256))
        try:
            data = target.read_bytes()[:n]
        except OSError as exc:
            return f"Error reading '{file_path}': {exc}"

        hex_preview = data.hex(" ")
        return (
            f"Binary stub for {file_path}:\n"
            f"- preview_bytes: {len(data)}\n"
            f"- hex: {hex_preview}"
        )

    # ── git_file_history ──────────────────────────────────────────

    def git_file_history(file_path: str, limit: int = 10) -> str:
        """Show the recent git commit history for a specific file.

        Args:
            file_path: Relative path from the project root.
            limit: Maximum number of commits to show (default 10).

        Returns:
            Recent commits touching this file.
        """
        target = (ws / file_path).resolve()
        if not is_safe_path(ws, target):
            return f"Error: path '{file_path}' is outside the project."

        limit = min(limit, 20)
        try:
            result = subprocess.run(
                [
                    "git", "log",
                    f"--max-count={limit}",
                    "--format=%h %ai %s",
                    "--",
                    file_path,
                ],
                capture_output=True,
                text=True,
                cwd=str(ws),
                check=False,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return f"No git history found for '{file_path}'."
            return f"Git history for {file_path}:\n{result.stdout.strip()}"
        except FileNotFoundError:
            return "Git is not available."

    tools: dict[str, Callable] = {
        "search_code": search_code,
        "read_file": read_file,
        "list_directory": list_directory,
        "git_file_history": git_file_history,
        "read_file_metadata": read_file_metadata,
        "search_by_type": search_by_type,
        "summarize_directory": summarize_directory,
        "read_binary_stub": read_binary_stub,
    }

    # Every retrieval call emits a lossless graph artifact.
    return wrap_retrieval_tools(ws, tools)


# ---------------------------------------------------------------------------
# Git tools — deeper git analysis for GitAgent
# ---------------------------------------------------------------------------


def create_git_tools(workspace: Path) -> dict[str, Callable]:
    """Create git-focused tools for the GitAgent.

    Args:
        workspace: Absolute path to the user's project root.

    Returns:
        Dict mapping tool name to its implementation function.
    """
    ws = workspace.resolve()

    def git_log(limit: int = 20, path: str = "") -> str:
        """Show recent git commit history, optionally filtered by path.

        Args:
            limit: Maximum number of commits to show (default 20, max 50).
            path: Optional relative path to filter commits by.

        Returns:
            Formatted commit history.
        """
        limit = min(max(1, limit), 50)
        cmd = [
            "git", "log",
            f"--max-count={limit}",
            "--format=%h %ai %an | %s",
        ]
        if path:
            target = (ws / path).resolve()
            if not is_safe_path(ws, target):
                return f"Error: path '{path}' is outside the project."
            cmd.extend(["--", path])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=str(ws), check=False,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return "No git history found."
            return f"Git log ({limit} commits):\n{result.stdout.strip()}"
        except FileNotFoundError:
            return "Git is not available."

    def git_diff(commit_hash: str) -> str:
        """Show the diff of a specific commit.

        Args:
            commit_hash: Short or full git commit hash.

        Returns:
            The diff output for the commit, truncated to 3000 chars.
        """
        try:
            result = subprocess.run(
                ["git", "diff", f"{commit_hash}~1", commit_hash, "--stat"],
                capture_output=True, text=True,
                cwd=str(ws), check=False,
            )
            stat = result.stdout.strip() if result.returncode == 0 else ""

            result = subprocess.run(
                ["git", "diff", f"{commit_hash}~1", commit_hash],
                capture_output=True, text=True,
                cwd=str(ws), check=False,
            )
            if result.returncode != 0:
                return f"Error: could not get diff for '{commit_hash}'."

            diff = result.stdout.strip()
            header = f"Diff for {commit_hash}:\n\n{stat}\n\n"
            if len(diff) > 3000:
                diff = diff[:3000] + "\n... (truncated)"
            return header + diff
        except FileNotFoundError:
            return "Git is not available."

    def git_blame(file_path: str, start_line: int = 1, end_line: int = 50) -> str:
        """Show git blame for a range of lines in a file.

        Args:
            file_path: Relative path from the project root.
            start_line: First line to blame (1-based, default 1).
            end_line: Last line to blame (default 50).

        Returns:
            Blame output with author, date, and line content.
        """
        target = (ws / file_path).resolve()
        if not is_safe_path(ws, target):
            return f"Error: path '{file_path}' is outside the project."
        if not target.is_file():
            return f"Error: '{file_path}' does not exist."

        start_line = max(1, start_line)
        end_line = max(start_line, min(end_line, start_line + 100))

        try:
            result = subprocess.run(
                [
                    "git", "blame",
                    f"-L{start_line},{end_line}",
                    "--date=short",
                    "--", file_path,
                ],
                capture_output=True, text=True,
                cwd=str(ws), check=False,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return f"No blame info for '{file_path}'."
            return f"Blame for {file_path} (lines {start_line}-{end_line}):\n{result.stdout.strip()}"
        except FileNotFoundError:
            return "Git is not available."

    tools = {
        "git_log": git_log,
        "git_diff": git_diff,
        "git_blame": git_blame,
    }

    return wrap_retrieval_tools(ws, tools)


# ---------------------------------------------------------------------------
# Write tools — used by RefreshModuleAgents during refresh to persist docs
# ---------------------------------------------------------------------------


def create_write_tools(workspace: Path, module_name: str) -> dict[str, Callable]:
    """Create tools for a RefreshModuleAgent to write its knowledge doc.

    Args:
        workspace: Absolute path to the user's project root.
        module_name: Name of the module this agent is responsible for.

    Returns:
        Dict with a single ``write_module_doc`` tool.
    """
    ws = workspace.resolve()
    modules_dir = knowledge_root(ws) / "modules"

    def write_module_doc(content: str) -> str:
        """Write the module knowledge document.

        Args:
            content: Full Markdown content of the knowledge document.

        Returns:
            Confirmation message.
        """
        modules_dir.mkdir(parents=True, exist_ok=True)
        doc_path = modules_dir / f"{module_name}.md"
        doc_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {doc_path.relative_to(ws)}"

    return {
        "write_module_doc": write_module_doc,
    }


def create_git_write_tools(workspace: Path) -> dict[str, Callable]:
    """Create tools for the RefreshGitAgent to write its knowledge doc.

    Args:
        workspace: Absolute path to the user's project root.

    Returns:
        Dict with a single ``write_git_doc`` tool.
    """
    ws = workspace.resolve()
    modules_dir = knowledge_root(ws) / "modules"

    def write_git_doc(content: str) -> str:
        """Write the git insights knowledge document.

        Args:
            content: Full Markdown content of the git knowledge document.

        Returns:
            Confirmation message.
        """
        modules_dir.mkdir(parents=True, exist_ok=True)
        doc_path = modules_dir / "_git_insights.md"
        doc_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {doc_path.relative_to(ws)}"

    return {
        "write_git_doc": write_git_doc,
    }
