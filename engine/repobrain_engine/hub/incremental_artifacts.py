"""Execution and deterministic artifact patching for incremental refresh."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Mapping

from repobrain_engine.hub.contracts import ChangeRecord, RefreshStatus
from repobrain_engine.hub.storage import knowledge_root


class IncrementalExecutionError(RuntimeError):
    """Raised when an approved Agent group cannot be executed safely."""


def _entry_lookup(workspace: Path, snapshot: Mapping[str, object], model: object) -> dict[str, tuple[str, object, object]]:
    from repobrain_engine.hub.agents import build_refresh_module_swarm_v2

    by_identity = {
        (str(entry.get("module", "")), str(entry.get("group_name", ""))): group_id
        for group_id, entry in (snapshot.get("groups", {}) or {}).items()
    }
    result: dict[str, tuple[str, object, object]] = {}
    for module, group_entries in build_refresh_module_swarm_v2(model, workspace):
        for group_name, group, agent in group_entries:
            group_id = by_identity.get((module, group_name))
            if group_id:
                result[group_id] = (module, group, agent)
    return result


async def execute_affected_groups(
    workspace: Path,
    snapshot: Mapping[str, object],
    affected_group_ids: list[str],
    model: object,
    status: RefreshStatus,
) -> None:
    """Run only approved groups and write their stable artifact paths."""
    from agents import Runner

    entries = _entry_lookup(workspace, snapshot, model)
    groups = snapshot.get("groups", {}) or {}
    semaphore = asyncio.Semaphore(max(1, int(os.environ.get("RB_API_CONCURRENCY", "5"))))
    execution_path = knowledge_root(workspace) / "execution.json"
    try:
        execution = json.loads(execution_path.read_text(encoding="utf-8"))
        if not isinstance(execution, dict):
            execution = {}
    except (OSError, ValueError, TypeError):
        execution = {}
    group_states = execution.setdefault("group_states", {})
    write_lock = asyncio.Lock()

    async def persist(group_id: str, state: str, reason: str = "") -> None:
        async with write_lock:
            group_states[group_id] = {"state": state, "reason": reason}
            execution_path.write_text(
                json.dumps(execution, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    async def run_one(group_id: str) -> None:
        previous = group_states.get(group_id, {})
        if isinstance(previous, dict) and previous.get("state") == "success":
            status.groups[group_id] = "success"
            return
        entry = groups.get(group_id)
        # A removed group is handled by orphan cleanup and needs no model call.
        if not isinstance(entry, dict):
            status.groups[group_id] = "success"
            await persist(group_id, "success")
            return
        runtime = entries.get(group_id)
        if runtime is None:
            await persist(group_id, "failed", "group is not executable at target HEAD")
            raise IncrementalExecutionError(f"Affected group is not executable at target HEAD: {group_id}")
        _module, _group, agent = runtime
        try:
            async with semaphore:
                result = await Runner.run(
                    agent,
                    "Analyze the pre-loaded source code and produce a comprehensive Markdown knowledge document.",
                    max_turns=3,
                )
        except Exception as exc:
            await persist(group_id, "failed", str(exc))
            raise
        content = str(result.final_output).strip()
        if not content:
            await persist(group_id, "failed", "empty knowledge output")
            raise IncrementalExecutionError(f"Affected group returned empty knowledge: {group_id}")
        out_path = knowledge_root(workspace) / str(entry["artifact_path"])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        status.groups[group_id] = "success"
        await persist(group_id, "success")

    await asyncio.gather(*(run_one(group_id) for group_id in affected_group_ids))
    _remove_orphan_agent_docs(knowledge_root(workspace), snapshot)


def _remove_orphan_agent_docs(root: Path, snapshot: Mapping[str, object]) -> None:
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return
    valid = {
        (root / str(entry.get("artifact_path", ""))).resolve()
        for entry in (snapshot.get("groups", {}) or {}).values()
        if isinstance(entry, dict) and entry.get("artifact_path")
    }
    for path in sorted(agents_dir.rglob("*.md")):
        if path.resolve() not in valid:
            path.unlink()
    for directory in sorted((path for path in agents_dir.rglob("*") if path.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass


def render_incremental_map(root: Path, snapshot: Mapping[str, object]) -> None:
    """Render deterministic map entries so unchanged groups are not regenerated."""
    entries: list[dict[str, object]] = []
    for group_id, group in sorted((snapshot.get("groups", {}) or {}).items()):
        if not isinstance(group, dict):
            continue
        artifact = root / str(group.get("artifact_path", ""))
        try:
            content = artifact.read_text(encoding="utf-8")
        except OSError:
            content = ""
        summary = next((line.strip("# ") for line in content.splitlines() if line.strip()), "")
        entries.append(
            {
                "group_id": group_id,
                "module": group.get("module", ""),
                "group_name": group.get("group_name", ""),
                "artifact_path": group.get("artifact_path", ""),
                "files": group.get("files", []),
                "summary": summary[:500],
            }
        )
    (root / "map_entries.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = ["# Module Map", ""]
    for entry in entries:
        lines.extend(
            [
                f"## {entry['module']} / {entry['group_name']}",
                f"- Group ID: `{entry['group_id']}`",
                f"- Knowledge: `{entry['artifact_path']}`",
                f"- Files: {', '.join(f'`{path}`' for path in entry['files'])}",
                f"- Summary: {entry['summary'] or '(no summary)'}",
                "",
            ]
        )
    (root / "map.md").write_text("\n".join(lines), encoding="utf-8")


def update_related_artifacts(
    workspace: Path,
    snapshot: Mapping[str, object],
    changes: list[ChangeRecord],
    artifacts: Iterable[str],
) -> None:
    """Update deterministic artifacts selected by the approved impact plan."""
    from repobrain_engine.hub.knowledge_graph import (
        build_knowledge_graph,
        render_knowledge_graph_markdown,
        render_knowledge_graph_mermaid,
    )
    from repobrain_engine.hub.refresh_pipeline import _build_non_code_indexes
    from repobrain_engine.hub.scanner import extract_structure, full_scan

    selected = set(artifacts)
    root = knowledge_root(workspace)
    if "map" in selected or "agent_docs" in selected:
        render_incremental_map(root, snapshot)
    report = None
    if selected & {"knowledge_graph", "indexes"}:
        report = full_scan(workspace)
    if "knowledge_graph" in selected and report is not None:
        target_graph = build_knowledge_graph(workspace, report)
        changed_paths = {
            path
            for change in changes
            for path in (change.path, change.old_path)
            if path
        }
        graph = _patch_knowledge_graph(
            root / "knowledge_graph.json",
            target_graph,
            changed_paths,
        )
        (root / "knowledge_graph.json").write_text(
            json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (root / "knowledge_graph.md").write_text(render_knowledge_graph_markdown(graph), encoding="utf-8")
        (root / "knowledge_graph.mmd").write_text(render_knowledge_graph_mermaid(graph), encoding="utf-8")
    if "structure" in selected:
        (root / "structure.md").write_text(extract_structure(workspace), encoding="utf-8")
    if "indexes" in selected and report is not None:
        docs, data, media = _build_non_code_indexes(report)
        (root / "document_index.md").write_text(docs, encoding="utf-8")
        (root / "data_overview.md").write_text(data, encoding="utf-8")
        (root / "media_manifest.md").write_text(media, encoding="utf-8")
    if "conventions" in selected:
        _append_convention_change_entry(root, changes)


def _patch_knowledge_graph(
    current_path: Path,
    target_graph: Mapping[str, object],
    changed_paths: set[str],
) -> dict[str, object]:
    """Patch changed file/symbol subgraphs while preserving unrelated nodes."""
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return dict(target_graph)
    if not isinstance(current, dict):
        return dict(target_graph)

    def changed_node(node_id: str) -> bool:
        for path in changed_paths:
            if node_id == f"file:{path}" or node_id.startswith(f"symbol:{path}:"):
                return True
        return False

    current_nodes = [node for node in current.get("nodes", []) if isinstance(node, dict)]
    target_nodes = [node for node in target_graph.get("nodes", []) if isinstance(node, dict)]
    current_edges = [edge for edge in current.get("edges", []) if isinstance(edge, dict)]
    target_edges = [edge for edge in target_graph.get("edges", []) if isinstance(edge, dict)]

    # Global/module metadata is cheap and deterministic; file and symbol nodes
    # are the knowledge-bearing units patched only for changed paths.
    preserved_nodes = {
        str(node.get("id", "")): node
        for node in current_nodes
        if str(node.get("id", "")).startswith(("file:", "symbol:"))
        and not changed_node(str(node.get("id", "")))
    }
    target_by_id = {str(node.get("id", "")): node for node in target_nodes}
    merged_nodes: dict[str, dict[str, object]] = {
        node_id: node for node_id, node in target_by_id.items()
        if not node_id.startswith(("file:", "symbol:"))
    }
    merged_nodes.update(preserved_nodes)
    for node_id, node in target_by_id.items():
        if changed_node(node_id):
            merged_nodes[node_id] = node

    preserved_edges = [
        edge
        for edge in current_edges
        if not changed_node(str(edge.get("from", "")))
        and not changed_node(str(edge.get("to", "")))
        and str(edge.get("type", "")) not in {"uses_language", "uses_framework", "contains"}
    ]
    target_patch_edges = [
        edge
        for edge in target_edges
        if changed_node(str(edge.get("from", "")))
        or changed_node(str(edge.get("to", "")))
        or str(edge.get("type", "")) in {"uses_language", "uses_framework", "contains"}
    ]
    edge_map: dict[str, dict[str, object]] = {}
    for edge in [*preserved_edges, *target_patch_edges]:
        key = json.dumps(edge, sort_keys=True, ensure_ascii=False)
        edge_map[key] = edge

    result = dict(target_graph)
    result["nodes"] = [merged_nodes[key] for key in sorted(merged_nodes)]
    result["edges"] = [edge_map[key] for key in sorted(edge_map)]
    return result


def _append_convention_change_entry(root: Path, changes: list[ChangeRecord]) -> None:
    """Record only convention-relevant committed changes without rewriting old entries."""
    path = root / "convention_entries.json"
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            entries = []
    except (OSError, ValueError, TypeError):
        baseline = ""
        try:
            baseline = (root / "conventions.md").read_text(encoding="utf-8")
        except OSError:
            pass
        entries = [{"id": "baseline", "content": baseline, "evidence_files": []}]
    relevant = sorted({change.path for change in changes})
    entry_id = "commit:" + hashlib.sha256("\n".join(relevant).encode("utf-8")).hexdigest()[:12]
    entries = [entry for entry in entries if entry.get("id") != entry_id]
    entries.append(
        {
            "id": entry_id,
            "content": "Configuration evidence changed; re-check conventions backed by: " + ", ".join(relevant),
            "evidence_files": relevant,
        }
    )
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rendered = ["# Project Conventions", ""]
    for entry in entries:
        content = str(entry.get("content", "")).strip()
        if content:
            rendered.append(content)
            rendered.append("")
    (root / "conventions.md").write_text("\n".join(rendered), encoding="utf-8")
