"""Graph Retrieval Skill tools.

This skill provides graph-based retrieval as a tool abstraction layer.
It consumes .repobrain/graph/nodes.jsonl and edges.jsonl, then returns
LLM-friendly semantic triples plus source-backed evidence.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from repobrain_engine.hub._utils import is_safe_path
from repobrain_engine.hub.storage import knowledge_root


def _workspace_root() -> Path:
    """Resolve the trusted workspace root from env var or current directory."""
    env = os.environ.get("WORKSPACE_PATH", "").strip()
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


def _resolve_workspace(workspace: str | None = None) -> Path:
    """Resolve and validate workspace path from explicit arg, env var, or cwd.

    Args:
        workspace: Optional workspace path override.

    Returns:
        A canonical workspace path constrained to the trusted workspace root.

    Raises:
        ValueError: If the provided workspace escapes the trusted workspace root.
    """
    root = _workspace_root()
    candidate = Path(workspace).resolve() if workspace else root
    if not is_safe_path(root, candidate):
        raise ValueError(
            "workspace must be inside the current project workspace"
        )
    return candidate


def _read_jsonl(path: Path, max_rows: int | None = None) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if isinstance(max_rows, int) and max_rows > 0:
        lines = lines[-max_rows:]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^0-9A-Za-z_\u4e00-\u9fff]+", text.lower()) if t}


def _node_text(node: dict[str, Any]) -> str:
    node_data = node.get("node", {})
    if not isinstance(node_data, dict):
        return ""
    return " ".join(
        [
            str(node_data.get("id", "")),
            str(node_data.get("type", "")),
            str(node_data.get("label", "")),
            str(node.get("tool_name", "")),
        ]
    )


def _edge_text(edge: dict[str, Any]) -> str:
    edge_data = edge.get("edge", {})
    if not isinstance(edge_data, dict):
        return ""
    return " ".join(
        [
            str(edge_data.get("from", "")),
            str(edge_data.get("to", "")),
            str(edge_data.get("type", "")),
            str(edge.get("tool_name", "")),
        ]
    )


def _read_knowledge_graph_rows(workspace: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read fallback graph rows from ``knowledge_graph.json``.

    Args:
        workspace: Workspace root path.

    Returns:
        Tuple of ``(nodes_rows, edges_rows)`` in normalized JSONL-like format.
    """
    knowledge_graph_path = knowledge_root(workspace) / "knowledge_graph.json"
    if not knowledge_graph_path.exists() or not knowledge_graph_path.is_file():
        return [], []

    try:
        graph = json.loads(knowledge_graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], []

    if not isinstance(graph, dict):
        return [], []

    retrieval_id = str(graph.get("created_at_utc", "")) or "refresh-knowledge-graph"
    tool_name = "refresh_pipeline"

    nodes_rows: list[dict[str, Any]] = []
    raw_nodes = graph.get("nodes", [])
    if isinstance(raw_nodes, list):
        for node in raw_nodes:
            if not isinstance(node, dict):
                continue
            nodes_rows.append(
                {
                    "schema": "repobrain-graph-node-v1",
                    "retrieval_id": retrieval_id,
                    "tool_name": tool_name,
                    "node": node,
                }
            )

    edges_rows: list[dict[str, Any]] = []
    raw_edges = graph.get("edges", [])
    if isinstance(raw_edges, list):
        for edge in raw_edges:
            if not isinstance(edge, dict):
                continue
            edges_rows.append(
                {
                    "schema": "repobrain-graph-edge-v1",
                    "retrieval_id": retrieval_id,
                    "tool_name": tool_name,
                    "edge": edge,
                }
            )

    return nodes_rows, edges_rows


def query_graph(query: str, max_hops: int = 2, workspace: str = ".") -> dict[str, Any]:
    """Retrieve a relevant semantic subgraph for a user query.

    Returns a tool-friendly structure:
    - summary: short semantic explanation
    - triples: LLM-friendly triples [subject, predicate, object]
    - evidence: retrieval ids + tool names for replayability
    - nodes/edges: selected subgraph payload
    """
    ws = _resolve_workspace(workspace)
    graph_dir = knowledge_root(ws) / "graph"
    max_rows = int(os.environ.get("RB_GRAPH_QUERY_MAX_ROWS", "2000"))
    max_rows = max(100, max_rows)
    nodes_rows = _read_jsonl(graph_dir / "nodes.jsonl", max_rows=max_rows)
    edges_rows = _read_jsonl(graph_dir / "edges.jsonl", max_rows=max_rows)
    if not nodes_rows and not edges_rows:
        nodes_rows, edges_rows = _read_knowledge_graph_rows(ws)

    if not query.strip():
        return {
            "summary": "Query is empty.",
            "triples": [],
            "evidence": [],
            "nodes": [],
            "edges": [],
        }

    if not nodes_rows and not edges_rows:
        return {
            "summary": "No graph store found. Run refresh or retrieval tools first.",
            "triples": [],
            "evidence": [],
            "nodes": [],
            "edges": [],
        }

    q_tokens = _tokens(query)
    scored_nodes: list[tuple[int, dict[str, Any]]] = []
    for row in nodes_rows:
        text = _node_text(row)
        score = len(q_tokens & _tokens(text))
        if score > 0:
            scored_nodes.append((score, row))

    scored_edges: list[tuple[int, dict[str, Any]]] = []
    for row in edges_rows:
        text = _edge_text(row)
        score = len(q_tokens & _tokens(text))
        if score > 0:
            scored_edges.append((score, row))

    scored_nodes.sort(key=lambda x: x[0], reverse=True)
    scored_edges.sort(key=lambda x: x[0], reverse=True)

    seed_node_ids: set[str] = set()
    selected_node_rows = [r for _, r in scored_nodes[:40]]
    selected_edge_rows = [r for _, r in scored_edges[:80]]

    for row in selected_node_rows:
        n = row.get("node", {})
        if isinstance(n, dict):
            nid = str(n.get("id", ""))
            if nid:
                seed_node_ids.add(nid)

    for row in selected_edge_rows:
        e = row.get("edge", {})
        if isinstance(e, dict):
            f = str(e.get("from", ""))
            t = str(e.get("to", ""))
            if f:
                seed_node_ids.add(f)
            if t:
                seed_node_ids.add(t)

    id_to_node: dict[str, dict[str, Any]] = {}
    for row in nodes_rows:
        n = row.get("node", {})
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id", ""))
        if nid and nid not in id_to_node:
            id_to_node[nid] = row

    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in edges_rows:
        e = row.get("edge", {})
        if not isinstance(e, dict):
            continue
        f = str(e.get("from", ""))
        t = str(e.get("to", ""))
        if f:
            adjacency[f].append(row)
        if t:
            adjacency[t].append(row)

    max_hops = max(1, min(max_hops, 4))
    visited_nodes: set[str] = set(seed_node_ids)
    visited_edges: set[tuple[str, str, str]] = set()
    q = deque([(nid, 0) for nid in seed_node_ids])

    while q:
        nid, depth = q.popleft()
        if depth >= max_hops:
            continue
        for edge_row in adjacency.get(nid, []):
            e = edge_row.get("edge", {})
            if not isinstance(e, dict):
                continue
            f = str(e.get("from", ""))
            t = str(e.get("to", ""))
            rel = str(e.get("type", "rel"))
            visited_edges.add((f, rel, t))
            for nxt in (f, t):
                if nxt and nxt not in visited_nodes:
                    visited_nodes.add(nxt)
                    q.append((nxt, depth + 1))

    final_nodes = [id_to_node[nid] for nid in sorted(visited_nodes) if nid in id_to_node]

    triples: list[list[str]] = []
    for f, rel, t in sorted(visited_edges):
        s_label = str(id_to_node.get(f, {}).get("node", {}).get("label", f))
        o_label = str(id_to_node.get(t, {}).get("node", {}).get("label", t))
        triples.append([s_label, rel, o_label])

    evidence: list[dict[str, str]] = []
    seen_ev: set[tuple[str, str]] = set()
    for row in final_nodes:
        rid = str(row.get("retrieval_id", ""))
        tool = str(row.get("tool_name", ""))
        key = (rid, tool)
        if rid and tool and key not in seen_ev:
            evidence.append({"retrieval_id": rid, "tool_name": tool})
            seen_ev.add(key)

    if triples:
        summary = (
            f"Found {len(triples)} semantic relation(s) across {len(final_nodes)} node record(s). "
            f"Primary relation: {triples[0][0]} {triples[0][1]} {triples[0][2]}"
        )
    else:
        summary = (
            f"Found {len(final_nodes)} relevant node record(s) but no explicit relation edges matched the query."
        )

    return {
        "summary": summary,
        "triples": triples[:120],
        "evidence": evidence[:80],
        "nodes": final_nodes[:200],
        "edges": [
            {"from": f, "type": rel, "to": t}
            for f, rel, t in sorted(visited_edges)
        ][:200],
    }
