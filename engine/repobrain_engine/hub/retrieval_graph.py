"""Retrieval graph persistence layer.

Extracted from ``ask_tools.py`` to separate the retrieval-graph
recording/storage concern from the tool implementations themselves.

Depending on mode, each tool invocation can emit a lossless graph record that is:
1. Written as JSON + Markdown + Mermaid to ``.repobrain/retrieval_graphs/``
2. Appended to the persistent graph store (JSONL) in ``.repobrain/graph/``

Recording behavior is controlled by ``RB_RETRIEVAL_MODE``:
- ``off``: disable retrieval graph recording entirely
- ``compact``: append JSONL graph store + latest markdown only (default)
- ``full``: write all retrieval artifacts and graph store updates
"""
from __future__ import annotations

import functools
import inspect
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from repobrain_engine.hub._utils import env_int
from repobrain_engine.hub.storage import knowledge_root


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RETRIEVAL_MODE_DEFAULT = "compact"
_RETRIEVAL_MODE_VALUES = {"off", "compact", "full"}
_SECRET_PATTERNS = (
    (
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|PASS))\s*=\s*([^\s,;]+)"
        ),
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
_SECRET_KEY_RE = re.compile(r"(?i)(api_?key|token|secret|password|pass|authorization)")


def _get_retrieval_mode() -> str:
    """Return the normalized retrieval recording mode."""
    raw_mode = os.environ.get("RB_RETRIEVAL_MODE", _RETRIEVAL_MODE_DEFAULT)
    mode = raw_mode.strip().lower()
    if mode in _RETRIEVAL_MODE_VALUES:
        return mode
    return _RETRIEVAL_MODE_DEFAULT


def _redact_secrets(value: object) -> str:
    """Redact common credentials before retrieval data is written to disk."""
    text = str(value)
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _redact_jsonable(value: object) -> object:
    """Redact common credentials from a JSON-serializable payload."""
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            redacted[key_text] = (
                "<redacted>"
                if _SECRET_KEY_RE.search(key_text)
                else _redact_jsonable(item)
            )
        return redacted
    if isinstance(value, (list, tuple, set)):
        return [_redact_jsonable(v) for v in value]
    if isinstance(value, str):
        return _redact_secrets(value)
    return value


def _trim_file_to_last_lines(path: Path, max_lines: int) -> None:
    """Keep only the most recent N lines in a text file."""
    if max_lines <= 0 or not path.exists() or not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    if len(lines) <= (max_lines * 2):
        return
    trimmed = "\n".join(lines[-max_lines:]) + "\n"
    try:
        path.write_text(trimmed, encoding="utf-8")
    except OSError:
        return


def _prune_retrieval_artifacts(out_dir: Path, max_retrievals: int) -> None:
    """Keep only the latest retrieval graph artifact groups (.json/.md/.mmd)."""
    if max_retrievals <= 0 or not out_dir.exists() or not out_dir.is_dir():
        return

    json_files = sorted(out_dir.glob("*.json"))
    if len(json_files) <= max_retrievals:
        return

    stale = json_files[: len(json_files) - max_retrievals]
    for jf in stale:
        base = jf.with_suffix("")
        for suffix in (".json", ".md", ".mmd"):
            target = base.with_suffix(suffix)
            try:
                if target.exists():
                    target.unlink()
            except OSError:
                continue


def jsonable(value: object) -> object:
    """Convert arbitrary Python values into JSON-serializable structures.

    Args:
        value: Any Python value.

    Returns:
        A JSON-safe equivalent.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    return repr(value)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_retrieval_graph_markdown(graph: dict[str, object]) -> str:
    """Render retrieval graph as markdown while preserving full raw payload."""
    lines = [
        "# Retrieval Knowledge Graph",
        "",
        f"- schema: {graph.get('schema', 'unknown')}",
        f"- retrieval_id: {graph.get('retrieval_id', 'unknown')}",
        f"- tool_name: {graph.get('tool_name', 'unknown')}",
        f"- created_at_utc: {graph.get('created_at_utc', 'unknown')}",
        "",
        "## Raw Input (Lossless)",
        "```json",
        json.dumps(graph.get("raw_input", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Raw Output (Lossless)",
        "```text",
        str(graph.get("raw_output", "")),
        "```",
        "",
        "## Graph Data",
        "```json",
        json.dumps(
            {
                "nodes": graph.get("nodes", []),
                "edges": graph.get("edges", []),
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
    ]
    return "\n".join(lines)


def render_retrieval_graph_mermaid(graph: dict[str, object]) -> str:
    """Render retrieval graph as Mermaid syntax for visualization."""
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return "graph TD\n  A[invalid graph]"

    labels: dict[str, str] = {}
    for n in nodes:
        if isinstance(n, dict):
            nid = str(n.get("id", ""))
            lbl = str(n.get("label", nid)).replace('"', "'")
            if nid:
                labels[nid] = lbl

    lines = ["graph TD"]

    def _mid(raw: str) -> str:
        safe = re.sub(r"[^0-9A-Za-z_]", "_", raw)
        return f"n_{safe}"

    for e in edges:
        if not isinstance(e, dict):
            continue
        src = str(e.get("from", ""))
        dst = str(e.get("to", ""))
        etype = str(e.get("type", "rel"))
        if not src or not dst:
            continue
        lines.append(
            f'  {_mid(src)}["{labels.get(src, src)}"] -->|{etype}| {_mid(dst)}["{labels.get(dst, dst)}"]'
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def record_retrieval_graph(
    workspace: Path,
    tool_name: str,
    raw_input: dict[str, object],
    raw_output: str,
) -> None:
    """Persist one lossless graph artifact per tool retrieval call."""
    mode = _get_retrieval_mode()
    if mode == "off":
        return

    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    retrieval_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}"

    project_id = "project:workspace"
    tool_id = f"tool:{tool_name}"
    output_id = f"output:{retrieval_id}"
    nodes: list[dict[str, str]] = [
        {
            "id": project_id,
            "type": "project",
            "label": workspace.name or str(workspace),
        },
        {
            "id": tool_id,
            "type": "tool",
            "label": tool_name,
        },
        {
            "id": output_id,
            "type": "output",
            "label": f"output_of_{tool_name}",
        },
    ]
    edges: list[dict[str, str]] = [
        {"from": project_id, "to": tool_id, "type": "invokes"},
        {"from": tool_id, "to": output_id, "type": "produces"},
    ]

    redacted_input = _redact_jsonable(jsonable(raw_input))
    redacted_output = _redact_secrets(raw_output)

    if isinstance(redacted_input, dict):
        graph_raw_input = redacted_input
    else:
        graph_raw_input = {"value": redacted_input}

    for key, value in graph_raw_input.items():
        input_id = f"input:{retrieval_id}:{key}"
        nodes.append(
            {
                "id": input_id,
                "type": "input",
                "label": f"{key}={value!r}",
            }
        )
        edges.append({"from": tool_id, "to": input_id, "type": "uses_input"})

    graph = {
        "schema": "repobrain-retrieval-kg-v1",
        "retrieval_id": retrieval_id,
        "created_at_utc": created_at,
        "workspace": str(workspace),
        "tool_name": tool_name,
        "raw_input": graph_raw_input,
        "raw_output": redacted_output,
        "nodes": nodes,
        "edges": edges,
    }

    if mode == "full":
        out_dir = knowledge_root(workspace) / "retrieval_graphs"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_tool = re.sub(r"[^0-9A-Za-z_-]", "_", tool_name)
        base = out_dir / f"{safe_tool}_{retrieval_id}"

        (base.with_suffix(".json")).write_text(
            json.dumps(graph, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (base.with_suffix(".md")).write_text(
            render_retrieval_graph_markdown(graph),
            encoding="utf-8",
        )
        (base.with_suffix(".mmd")).write_text(
            render_retrieval_graph_mermaid(graph),
            encoding="utf-8",
        )

        max_artifacts = env_int("RB_RETRIEVAL_ARTIFACT_MAX_FILES", 300, minimum=1)
        _prune_retrieval_artifacts(out_dir, max_artifacts)

    _append_knowledge_graph_store(workspace, graph)


def _append_knowledge_graph_store(workspace: Path, graph: dict[str, object]) -> None:
    """Append retrieval graph nodes/edges into normalized graph store files.

    This is the persistent graph layer consumed by Graph Skill.
    """
    graph_dir = knowledge_root(workspace) / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)

    nodes_file = graph_dir / "nodes.jsonl"
    edges_file = graph_dir / "edges.jsonl"
    latest_file = graph_dir / "latest_graph_context.md"
    max_rows = env_int("RB_GRAPH_STORE_MAX_ROWS", 3000, minimum=1)

    retrieval_id = str(graph.get("retrieval_id", ""))
    tool_name = str(graph.get("tool_name", "unknown"))
    raw_input = jsonable(graph.get("raw_input", {}))
    raw_output = str(graph.get("raw_output", ""))

    nodes = graph.get("nodes", [])
    if isinstance(nodes, list):
        with nodes_file.open("a", encoding="utf-8") as fh:
            for n in nodes:
                if not isinstance(n, dict):
                    continue
                record = {
                    "schema": "repobrain-graph-node-v1",
                    "retrieval_id": retrieval_id,
                    "tool_name": tool_name,
                    "node": n,
                }
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        _trim_file_to_last_lines(nodes_file, max_rows)

    edges = graph.get("edges", [])
    if isinstance(edges, list):
        with edges_file.open("a", encoding="utf-8") as fh:
            for e in edges:
                if not isinstance(e, dict):
                    continue
                record = {
                    "schema": "repobrain-graph-edge-v1",
                    "retrieval_id": retrieval_id,
                    "tool_name": tool_name,
                    "edge": e,
                }
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        _trim_file_to_last_lines(edges_file, max_rows)

    latest_lines = [
        "# Latest Graph Context",
        "",
        f"- retrieval_id: {retrieval_id}",
        f"- tool_name: {tool_name}",
        "",
        "## Raw Input",
        "```json",
        json.dumps(raw_input, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Raw Output",
        "```text",
        raw_output,
        "```",
        "",
        "## Graph Store Files",
        f"- {nodes_file}",
        f"- {edges_file}",
    ]
    latest_file.write_text("\n".join(latest_lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tool wrapping
# ---------------------------------------------------------------------------

def wrap_retrieval_tools(workspace: Path, tools: dict[str, Callable]) -> dict[str, Callable]:
    """Wrap each tool so every call emits one lossless retrieval graph.

    Args:
        workspace: Project root directory.
        tools: Dict of tool name → callable.

    Returns:
        New dict with the same keys but wrapped callables.
    """
    if _get_retrieval_mode() == "off":
        return tools

    wrapped_tools: dict[str, Callable] = {}
    for tool_name, fn in tools.items():
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def _wrapped(*args, __fn=fn, __sig=sig, __tool_name=tool_name, **kwargs):
            bound = __sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            raw_input_dict = {k: jsonable(v) for k, v in bound.arguments.items()}
            try:
                result = __fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                record_retrieval_graph(workspace, __tool_name, raw_input_dict, f"ERROR: {exc}")
                raise

            raw_output = result if isinstance(result, str) else repr(result)
            record_retrieval_graph(workspace, __tool_name, raw_input_dict, raw_output)
            return result

        _wrapped.__signature__ = sig
        wrapped_tools[tool_name] = _wrapped
    return wrapped_tools
