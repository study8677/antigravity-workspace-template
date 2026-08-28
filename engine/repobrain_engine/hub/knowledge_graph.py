"""Knowledge graph construction and rendering.

Extracted from ``scanner.py`` to reduce file size and improve
separation of concerns. The scanner builds a :class:`ScanReport`;
this module transforms it into a knowledge graph.

The graph includes a shared semantic layer produced by language
adapters so Python, Go, and future languages can contribute package,
import, symbol, test, and entrypoint relationships through one path.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from repobrain_engine.hub._constants import SOURCE_CODE_EXTS
from repobrain_engine.hub.semantic_index import SemanticIndex, build_semantic_index

if TYPE_CHECKING:
    from repobrain_engine.hub.language_adapters import FileSemantics, SymbolDef
    from repobrain_engine.hub.scanner import ScanReport

_DEFAULT_GRAPH_FILE_LIMIT: int | None = None
_DEFAULT_SEMANTIC_FILE_LIMIT: int | None = None


def _env_file_limit(name: str, default: int | None) -> int | None:
    """Return a configured file limit; unset, zero, or negative means unlimited."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value <= 0:
        return None
    return value


def build_knowledge_graph(root: Path, report: "ScanReport") -> dict[str, object]:
    """Build a project knowledge graph from scan metadata and shared semantics.

    Args:
        root: Project root directory.
        report: Completed scan report.

    Returns:
        JSON-serialisable graph dict with nodes, edges, and summary.
    """
    workspace_id = f"workspace:{root.resolve()}"
    nodes: list[dict[str, object]] = [
        {
            "id": workspace_id,
            "type": "workspace",
            "label": root.name or str(root),
        }
    ]
    edges: list[dict[str, str]] = []

    for lang, count in report.languages.items():
        lang_id = f"language:{lang.lower().replace(' ', '_')}"
        nodes.append({"id": lang_id, "type": "language", "label": lang, "count": count})
        edges.append({"from": workspace_id, "to": lang_id, "type": "uses_language"})

    for framework in report.frameworks:
        fw_id = f"framework:{framework.lower().replace(' ', '_').replace('/', '_')}"
        nodes.append({"id": fw_id, "type": "framework", "label": framework})
        edges.append({"from": workspace_id, "to": fw_id, "type": "uses_framework"})

    for directory in report.top_dirs:
        dir_id = f"dir:{directory}"
        nodes.append({"id": dir_id, "type": "directory", "label": directory})
        edges.append({"from": workspace_id, "to": dir_id, "type": "contains"})

    file_node_limit = _env_file_limit(
        "RB_KNOWLEDGE_GRAPH_FILE_LIMIT",
        _DEFAULT_GRAPH_FILE_LIMIT,
    )

    file_ids: set[str] = set()
    file_items = list(report.file_metadata.items())
    if file_node_limit is not None:
        file_items = file_items[:file_node_limit]
    for rel, meta in file_items:
        file_id = f"file:{rel}"
        file_ids.add(file_id)
        nodes.append(
            {
                "id": file_id,
                "type": str(meta.get("type", "file")),
                "label": rel,
                "size": int(meta.get("size", 0)),
                "mime": str(meta.get("mime", "unknown")),
            }
        )
        edges.append({"from": workspace_id, "to": file_id, "type": "contains"})

    # ── Semantic edges: adapter-driven imports, packages, and symbol definitions ──
    semantic = _extract_semantic_edges(root, report, file_ids)
    nodes.extend(semantic["nodes"])
    edges.extend(semantic["edges"])
    semantic_file_metadata = semantic["file_metadata"]
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", ""))
        if not node_id.startswith("file:"):
            continue
        rel_path = node_id[5:]
        file_semantics = semantic_file_metadata.get(rel_path)
        if not file_semantics:
            continue
        node.update(file_semantics)

    return {
        "schema": "repobrain-knowledge-graph-v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "workspace": str(root.resolve()),
        "summary": {
            "file_count": report.file_count,
            "walked_file_count": report.walked_file_count,
            "languages": report.languages,
            "frameworks": report.frameworks,
            "type_distribution": report.type_distribution,
            "semantic_files": semantic["file_count"],
            "semantic_edges": len(semantic["edges"]),
            "semantic_files_by_language": semantic["files_by_language"],
            "semantic_edges_by_type": semantic["edge_counts"],
            "semantic_adapters": semantic["adapter_counts"],
            "generic_fallback_file_count": len(semantic["generic_fallback_files"]),
            "parse_error_file_count": len(semantic["parse_error_files"]),
        },
        "diagnostics": {
            "generic_fallback_files": semantic["generic_fallback_files"],
            "parse_error_files": semantic["parse_error_files"],
        },
        "nodes": nodes,
        "edges": edges,
    }


def _extract_semantic_edges(
    root: Path,
    report: "ScanReport",
    existing_file_ids: set[str],
) -> dict[str, object]:
    """Extract adapter-driven semantic nodes and edges for source files.

    Args:
        root: Project root directory.
        report: Completed scan report used to source candidate files.
        existing_file_ids: Set of ``file:…`` node IDs already in the graph.

    Returns:
        Dict with semantic ``nodes`` and ``edges`` lists plus file count.
    """
    candidate_rel_paths = [
        rel_path
        for rel_path in sorted(report.file_metadata)
        if f"file:{rel_path}" in existing_file_ids
        and Path(rel_path).suffix.lower() in SOURCE_CODE_EXTS
    ]
    semantic_file_limit = _env_file_limit(
        "RB_SEMANTIC_FILE_LIMIT",
        _DEFAULT_SEMANTIC_FILE_LIMIT,
    )
    semantic_index = build_semantic_index(
        root,
        candidate_rel_paths=candidate_rel_paths,
        max_files=semantic_file_limit,
        skip_dirs={"data", "logs"},
    )
    return _semantic_index_to_graph(semantic_index)


def _semantic_index_to_graph(semantic_index: SemanticIndex) -> dict[str, object]:
    """Convert a semantic index into graph nodes and edges."""
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, str]] = []
    seen_modules: set[str] = set()
    seen_symbols: set[str] = set()
    files_by_language: dict[str, int] = {}
    adapter_counts: dict[str, int] = {}
    edge_counts: dict[str, int] = {}
    file_metadata: dict[str, dict[str, object]] = {}
    generic_fallback_files: list[str] = []
    parse_error_files: list[dict[str, str]] = []
    for semantics in semantic_index.files:
        file_id = f"file:{semantics.rel_path}"
        files_by_language[semantics.language] = files_by_language.get(semantics.language, 0) + 1
        adapter_counts[semantics.adapter_name] = adapter_counts.get(semantics.adapter_name, 0) + 1
        if semantics.adapter_name == "generic":
            generic_fallback_files.append(semantics.rel_path)
        if semantics.parse_error:
            parse_error_files.append(
                {
                    "file": semantics.rel_path,
                    "adapter": semantics.adapter_name,
                    "error": semantics.parse_error,
                }
            )
        file_metadata[semantics.rel_path] = {
            "language": semantics.language,
            "semantic_adapter": semantics.adapter_name,
            "semantic_package_identity": semantics.package_identity,
            "semantic_module_name": semantics.module_name,
            "semantic_import_count": len(semantics.imports),
            "semantic_symbol_count": len(semantics.symbols),
            "is_test_file": semantics.is_test_file,
            "entrypoints": list(semantics.entrypoints),
            "generic_fallback": semantics.adapter_name == "generic",
        }

        if semantics.package_identity:
            package_node_id = _ensure_module_node(
                nodes=nodes,
                seen_modules=seen_modules,
                module_name=semantics.package_identity,
                language=semantics.language,
            )
            edges.append(
                {
                    "from": file_id,
                    "to": package_node_id,
                    "type": "declares_package",
                }
            )
            _increment_edge_count(edge_counts, "declares_package")

        for imported in semantics.imports:
            module_node_id = _ensure_module_node(
                nodes=nodes,
                seen_modules=seen_modules,
                module_name=imported,
                language=semantics.language,
            )
            edges.append({"from": file_id, "to": module_node_id, "type": "imports"})
            _increment_edge_count(edge_counts, "imports")

        for symbol in semantics.symbols:
            symbol_node_id = _ensure_symbol_node(
                nodes=nodes,
                seen_symbols=seen_symbols,
                rel_path=semantics.rel_path,
                symbol=symbol,
            )
            edges.append({"from": file_id, "to": symbol_node_id, "type": "defines"})
            _increment_edge_count(edge_counts, "defines")
            if symbol.is_entrypoint:
                edges.append({"from": file_id, "to": symbol_node_id, "type": "entrypoint"})
                _increment_edge_count(edge_counts, "entrypoint")

        if semantics.is_test_file:
            for target in semantics.test_targets:
                target_node_id = _ensure_module_node(
                    nodes=nodes,
                    seen_modules=seen_modules,
                    module_name=target,
                    language=semantics.language,
                )
                edges.append({"from": file_id, "to": target_node_id, "type": "tests"})
                _increment_edge_count(edge_counts, "tests")

    return {
        "nodes": nodes,
        "edges": edges,
        "file_count": len(semantic_index.files),
        "files_by_language": dict(sorted(files_by_language.items())),
        "edge_counts": dict(sorted(edge_counts.items())),
        "adapter_counts": dict(sorted(adapter_counts.items())),
        "file_metadata": file_metadata,
        "generic_fallback_files": sorted(generic_fallback_files),
        "parse_error_files": parse_error_files,
    }


def _increment_edge_count(edge_counts: dict[str, int], edge_type: str) -> None:
    """Increment a semantic edge-type counter."""
    edge_counts[edge_type] = edge_counts.get(edge_type, 0) + 1


def _ensure_module_node(
    *,
    nodes: list[dict[str, object]],
    seen_modules: set[str],
    module_name: str,
    language: str,
) -> str:
    """Create a module/package node once and return its identifier."""
    module_id = f"module:{module_name}"
    if module_id not in seen_modules:
        seen_modules.add(module_id)
        nodes.append(
            {
                "id": module_id,
                "type": "module",
                "label": module_name,
                "language": language,
            }
        )
    return module_id


def _ensure_symbol_node(
    *,
    nodes: list[dict[str, object]],
    seen_symbols: set[str],
    rel_path: str,
    symbol: "SymbolDef",
) -> str:
    """Create a symbol node once and return its identifier."""
    symbol_label = symbol.qualified_name or symbol.name
    symbol_id = f"symbol:{rel_path}:{symbol_label}"
    if symbol_id not in seen_symbols:
        seen_symbols.add(symbol_id)
        nodes.append(
            {
                "id": symbol_id,
                "type": symbol.kind,
                "label": symbol_label,
                "lineno": symbol.line,
                "signature": symbol.signature,
                "receiver": symbol.receiver,
                "bases": list(symbol.bases),
                "entrypoint": symbol.is_entrypoint,
            }
        )
    return symbol_id


def render_knowledge_graph_markdown(graph: dict[str, object]) -> str:
    """Render a knowledge graph as Markdown for prompt/context use.

    Args:
        graph: Graph dict produced by :func:`build_knowledge_graph`.

    Returns:
        Markdown string.
    """
    summary = graph.get("summary", {})
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    lines = [
        "# Knowledge Graph",
        "",
        f"- workspace: {graph.get('workspace', '')}",
        f"- created_at_utc: {graph.get('created_at_utc', '')}",
        f"- nodes: {len(nodes) if isinstance(nodes, list) else 0}",
        f"- edges: {len(edges) if isinstance(edges, list) else 0}",
        "",
        "## Summary",
        "```json",
        json.dumps(summary, ensure_ascii=False, indent=2),
        "```",
    ]

    if isinstance(nodes, list) and nodes:
        lines.extend(["", "## Sample Nodes"])
        for node in nodes[:20]:
            if not isinstance(node, dict):
                continue
            lines.append(
                f"- {node.get('type', 'node')}: {node.get('label', node.get('id', ''))}"
            )

    if isinstance(edges, list) and edges:
        lines.extend(["", "## Sample Edges"])
        for edge in edges[:20]:
            if not isinstance(edge, dict):
                continue
            lines.append(
                f"- {edge.get('from', '')} --{edge.get('type', 'rel')}--> {edge.get('to', '')}"
            )

    return "\n".join(lines) + "\n"


def render_knowledge_graph_mermaid(graph: dict[str, object]) -> str:
    """Render a knowledge graph as Mermaid syntax.

    Args:
        graph: Graph dict produced by :func:`build_knowledge_graph`.

    Returns:
        Mermaid graph definition string.
    """
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return 'graph TD\n  n_invalid["invalid graph"]\n'

    labels: dict[str, str] = {}
    for node in nodes[:200]:
        if isinstance(node, dict):
            labels[str(node.get("id", ""))] = str(node.get("label", node.get("id", ""))).replace('"', "'")

    def _mid(raw: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in raw)
        return f"n_{safe}" if safe else "n_unknown"

    lines = ["graph TD"]
    for edge in edges[:200]:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("from", ""))
        dst = str(edge.get("to", ""))
        rel = str(edge.get("type", "rel"))
        if not src or not dst:
            continue
        src_label = labels.get(src, src)
        dst_label = labels.get(dst, dst)
        lines.append(
            f'  {_mid(src)}["{src_label}"] -->|{rel}| {_mid(dst)}["{dst_label}"]'
        )
    return "\n".join(lines) + "\n"
