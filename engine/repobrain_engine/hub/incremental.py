"""Committed-diff, Agent-group incremental refresh.

Git establishes what changed.  RepoBrain builds a bounded group candidate graph
and two independent, tool-free agents decide which groups are actually affected.
Only an approved plan is executed and promoted as a new storage generation.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from repobrain_engine.hub._constants import SOURCE_CODE_EXTS
from repobrain_engine.hub.contracts import (
    ChangeRecord,
    FailureRecord,
    ImpactCandidate,
    ImpactDecision,
    ImpactPlan,
    ImpactVerification,
    RefreshStatus,
)
from repobrain_engine.hub.storage import (
    active_generation_root,
    control_root,
    create_generation,
    knowledge_root,
    new_generation_id,
    promote_generation,
    read_current_pointer,
    remove_generation,
    use_knowledge_root,
    write_run_record,
)


SNAPSHOT_SCHEMA_VERSION = 1
GROUPING_VERSION = "functional-groups-v1"
IMPACT_SCHEMA_VERSION = 1
_ALLOWED_ARTIFACTS = {
    "agent_docs",
    "knowledge_graph",
    "map",
    "structure",
    "indexes",
    "conventions",
    "git_insights",
}


class IncrementalRefreshError(RuntimeError):
    """Base class for actionable incremental-refresh failures."""


class DirtyWorktreeError(IncrementalRefreshError):
    """Raised when committed-only refresh would read dirty source files."""


class MissingBaselineError(IncrementalRefreshError):
    """Raised when quick refresh has no generation snapshot to compare."""


def _run_git(workspace: Path, args: list[str], *, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(workspace),
        capture_output=True,
        text=text,
        check=False,
    )


def get_head_sha(workspace: Path) -> str:
    """Return HEAD or raise an actionable error."""
    result = _run_git(workspace, ["rev-parse", "HEAD"])
    if result.returncode != 0:
        raise IncrementalRefreshError("RepoBrain incremental refresh requires a Git repository with a commit.")
    return result.stdout.strip()


def ensure_clean_worktree(workspace: Path) -> None:
    """Require a clean committed source tree, excluding RepoBrain outputs."""
    result = _run_git(
        workspace,
        [
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            ".",
            ":(exclude).repobrain",
            ":(exclude).repobrain/**",
        ],
    )
    if result.returncode != 0:
        raise IncrementalRefreshError(result.stderr.strip() or "Unable to inspect Git worktree state.")
    dirty = [line for line in result.stdout.splitlines() if line.strip()]
    if dirty:
        sample = "; ".join(dirty[:8])
        raise DirtyWorktreeError(
            "RepoBrain committed-only refresh requires a clean worktree. "
            f"Commit, stash, or remove these changes first: {sample}"
        )


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned or "group"


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def _stable_group_id(module: str, group_name: str, files: Iterable[str]) -> str:
    identity = "\n".join(sorted(files))
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
    return f"{_safe_id(module)}::{_safe_id(group_name)}::{suffix}"


def _artifact_path(module: str, group_name: str, group_count: int) -> str:
    if group_count == 1:
        return f"agents/{_safe_id(module)}.md"
    return f"agents/{_safe_id(module)}/{_safe_id(group_name)}.md"


def _load_snapshot_from_root(root: Path | None) -> dict[str, object] | None:
    if root is None:
        return None
    path = root / "snapshot.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        return None
    return payload


def load_active_snapshot(workspace: Path) -> dict[str, object] | None:
    """Load the active generation's committed-source snapshot."""
    return _load_snapshot_from_root(active_generation_root(workspace))


def _group_inventory(workspace: Path, previous: Mapping[str, object] | None = None) -> dict[str, object]:
    """Build stable Agent groups and typed group dependency edges."""
    from repobrain_engine.hub.module_grouping import group_files, load_module_files
    from repobrain_engine.hub.scanner import detect_modules, resolve_module_path

    previous_groups = dict((previous or {}).get("groups", {}) or {})
    unused_previous = set(previous_groups)
    raw_groups: list[tuple[str, object]] = []
    for module in detect_modules(workspace):
        files = load_module_files(resolve_module_path(workspace, module), workspace)
        for group in group_files(files, workspace):
            raw_groups.append((module, group))

    module_counts: dict[str, int] = defaultdict(int)
    for module, _group in raw_groups:
        module_counts[module] += 1

    groups: dict[str, dict[str, object]] = {}
    file_to_group: dict[str, str] = {}
    group_objects: dict[str, object] = {}
    for module, group in raw_groups:
        paths = sorted(source.rel_path for source in group.files)
        group_id: str | None = None

        # Preserve exact prior identity first, then match by file overlap for
        # rename/split-safe continuity.
        for prior_id in sorted(unused_previous):
            prior = previous_groups.get(prior_id, {})
            if prior.get("module") == module and prior.get("group_name") == group.name:
                group_id = prior_id
                break
        if group_id is None:
            current_set = set(paths)
            best: tuple[float, str] | None = None
            for prior_id in sorted(unused_previous):
                prior = previous_groups.get(prior_id, {})
                if prior.get("module") != module:
                    continue
                prior_set = set(prior.get("files", []) or [])
                union = current_set | prior_set
                score = len(current_set & prior_set) / len(union) if union else 0.0
                if score > 0 and (best is None or score > best[0]):
                    best = (score, prior_id)
            if best is not None:
                group_id = best[1]
        if group_id is None:
            group_id = _stable_group_id(module, group.name, paths)
        unused_previous.discard(group_id)

        artifact = _artifact_path(module, group.name, module_counts[module])
        groups[group_id] = {
            "group_id": group_id,
            "module": module,
            "group_name": group.name,
            "files": paths,
            "artifact_path": artifact,
        }
        group_objects[group_id] = group
        for path in paths:
            file_to_group[path] = group_id

    provided_to_groups: dict[str, set[str]] = defaultdict(set)
    symbol_providers: dict[str, set[str]] = defaultdict(set)
    reference_tokens: dict[str, set[str]] = defaultdict(set)
    for group_id, group in group_objects.items():
        for source in group.files:
            provided = set(getattr(source.semantics, "provided_modules", []) or [])
            for value in (
                getattr(source, "package_identity", None),
                getattr(source.semantics, "module_name", None),
            ):
                if value:
                    provided.add(str(value))
            for name in provided:
                provided_to_groups[str(name)].add(group_id)
                reference_tokens[group_id].add(str(name))
            for symbol in getattr(source.semantics, "symbols", []) or []:
                if len(symbol.name) >= 4:
                    symbol_providers[symbol.name].add(group_id)
            reference_tokens[group_id].update(getattr(source, "imports_modules", []) or [])
            reference_tokens[group_id].update(
                re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", source.content)
            )

    dependencies: dict[str, set[str]] = defaultdict(set)
    edge_reasons: dict[str, list[str]] = defaultdict(list)
    edge_types: dict[str, set[str]] = defaultdict(set)
    for group_id, group in group_objects.items():
        for source in group.files:
            imports = set(getattr(source, "imports_modules", []) or [])
            test_targets = set(getattr(source.semantics, "test_targets", []) or [])
            imports.update(test_targets)
            for imported in imports:
                for target_group in provided_to_groups.get(str(imported), set()):
                    if target_group == group_id:
                        continue
                    dependencies[group_id].add(target_group)
                    edge_reasons[f"{group_id}->{target_group}"].append(
                        f"{source.rel_path} references {imported}"
                    )
                    edge_types[f"{group_id}->{target_group}"].add(
                        "tests" if imported in test_targets else "imports"
                    )
            identifiers = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b", source.content))
            for identifier in identifiers:
                for target_group in symbol_providers.get(identifier, set()):
                    if target_group == group_id:
                        continue
                    dependencies[group_id].add(target_group)
                    edge_reasons[f"{group_id}->{target_group}"].append(
                        f"{source.rel_path} references symbol {identifier}"
                    )
                    edge_types[f"{group_id}->{target_group}"].add("symbol_reference")

    reverse: dict[str, set[str]] = defaultdict(set)
    for source_group, target_groups in dependencies.items():
        for target_group in target_groups:
            reverse[target_group].add(source_group)

    return {
        "groups": groups,
        "file_to_group": file_to_group,
        "dependencies": {key: sorted(value) for key, value in dependencies.items()},
        "reverse_dependencies": {key: sorted(value) for key, value in reverse.items()},
        "edge_reasons": {key: sorted(set(value)) for key, value in edge_reasons.items()},
        "edge_types": {key: sorted(value) for key, value in edge_types.items()},
        "token_to_groups": {
            token: sorted(group_ids)
            for token, group_ids in _invert_reference_tokens(reference_tokens).items()
        },
        "_group_objects": group_objects,
    }


def _invert_reference_tokens(reference_tokens: Mapping[str, set[str]]) -> dict[str, set[str]]:
    inverted: dict[str, set[str]] = defaultdict(set)
    for group_id, tokens in reference_tokens.items():
        for token in tokens:
            normalized = str(token).strip()
            if normalized:
                inverted[normalized].add(group_id)
    return inverted


def build_workspace_snapshot(
    workspace: Path,
    head_sha: str,
    *,
    previous: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the committed-source snapshot used by later quick refreshes."""
    inventory = _group_inventory(workspace, previous)
    groups = dict(inventory["groups"])
    # Git blob ids cover every committed file (including docs/config/data) and
    # are content-addressed. Group hashes below retain SHA-256 source hashes for
    # Agent cache identity.
    file_hashes = _committed_blob_hashes(workspace, head_sha)
    group_hashes: dict[str, str] = {}
    for group_id, entry in groups.items():
        hashed_lines: list[str] = []
        for rel_path in entry.get("files", []):
            path = workspace / rel_path
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            digest = _content_hash(content)
            hashed_lines.append(f"{rel_path}\0{digest}")
        group_hashes[group_id] = _content_hash("\n".join(sorted(hashed_lines)))
    merkle_root = _content_hash(
        "\n".join(f"{path}\0{digest}" for path, digest in sorted(file_hashes.items()))
    )
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "grouping_version": GROUPING_VERSION,
        "head_sha": head_sha,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "merkle_root": merkle_root,
        "file_hashes": file_hashes,
        "group_hashes": group_hashes,
        "groups": groups,
        "file_to_group": inventory["file_to_group"],
        "dependencies": inventory["dependencies"],
        "reverse_dependencies": inventory["reverse_dependencies"],
        "edge_reasons": inventory["edge_reasons"],
        "edge_types": inventory["edge_types"],
        "token_to_groups": inventory["token_to_groups"],
    }


def _committed_blob_hashes(workspace: Path, head_sha: str) -> dict[str, str]:
    """Return content-addressed Git blob ids for the committed workspace tree."""
    result = _run_git(workspace, ["ls-tree", "-r", "-z", head_sha], text=False)
    if result.returncode != 0:
        raise IncrementalRefreshError(os.fsdecode(result.stderr or b"").strip() or "git ls-tree failed")
    hashes: dict[str, str] = {}
    for record in result.stdout.split(b"\0"):
        if not record or b"\t" not in record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        fields = metadata.split()
        if len(fields) < 3 or fields[1] != b"blob":
            continue
        path = os.fsdecode(raw_path)
        if path == ".repobrain" or path.startswith(".repobrain/"):
            continue
        hashes[path] = os.fsdecode(fields[2])
    return hashes


def save_snapshot(root: Path, snapshot: Mapping[str, object]) -> Path:
    """Persist a snapshot in a generation."""
    path = root / "snapshot.json"
    path.write_text(json.dumps(dict(snapshot), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _git_blob(workspace: Path, revision: str, path: str) -> str | None:
    result = _run_git(workspace, ["show", f"{revision}:{path}"])
    return result.stdout if result.returncode == 0 else None


def _semantic_summary(workspace: Path, rel_path: str, content: str | None) -> tuple[list[str], str, list[str]]:
    if content is None or Path(rel_path).suffix.lower() not in SOURCE_CODE_EXTS:
        return [], "", []
    from repobrain_engine.hub.semantic_index import analyze_source_file

    semantics = analyze_source_file(
        workspace,
        workspace / rel_path,
        rel_path=rel_path,
        content=content,
    )
    symbols = sorted(f"{symbol.kind}:{symbol.name}" for symbol in semantics.symbols)
    return symbols, semantics.signature_summary, sorted(set(semantics.imports))


def _semantic_noop_hint(old: str | None, new: str | None, old_sig: str, new_sig: str) -> bool:
    if old is None or new is None or old_sig != new_sig:
        return False

    def normalized(content: str) -> str:
        lines: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "//", "/*", "*", "*/")):
                continue
            lines.append(re.sub(r"\s+", "", stripped))
        return "".join(lines)

    return normalized(old) == normalized(new)


def build_change_set(workspace: Path, baseline_head: str, target_head: str) -> list[ChangeRecord]:
    """Build rename-aware, semantic change records for two committed trees."""
    result = _run_git(
        workspace,
        [
            "diff",
            "--name-status",
            "-z",
            "-M",
            baseline_head,
            target_head,
            "--",
            ".",
            ":(exclude).repobrain",
            ":(exclude).repobrain/**",
        ],
        text=False,
    )
    if result.returncode != 0:
        stderr = os.fsdecode(result.stderr or b"").strip()
        raise IncrementalRefreshError(stderr or "Unable to compare baseline commit to HEAD.")
    fields = [os.fsdecode(part) for part in result.stdout.split(b"\0") if part]
    records: list[tuple[str, str | None, str]] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        code = status[0]
        if code in {"R", "C"}:
            if index + 1 >= len(fields):
                raise IncrementalRefreshError("Malformed rename record from git diff.")
            old_path, new_path = fields[index], fields[index + 1]
            index += 2
            records.append(("renamed", old_path, new_path))
        else:
            if index >= len(fields):
                raise IncrementalRefreshError("Malformed path record from git diff.")
            path = fields[index]
            index += 1
            kind = {"A": "added", "D": "deleted", "M": "modified"}.get(code, "modified")
            records.append((kind, None, path))

    changes: list[ChangeRecord] = []
    for change_type, old_path, path in records:
        before_path = old_path or path
        old_content = None if change_type == "added" else _git_blob(workspace, baseline_head, before_path)
        new_content = None if change_type == "deleted" else _git_blob(workspace, target_head, path)
        old_symbols, old_sig, old_imports = _semantic_summary(workspace, before_path, old_content)
        new_symbols, new_sig, new_imports = _semantic_summary(workspace, path, new_content)
        patch_result = _run_git(
            workspace,
            ["diff", "--no-ext-diff", "--unified=3", "-M", baseline_head, target_head, "--", before_path, path],
        )
        patch = patch_result.stdout[:20_000] if patch_result.returncode == 0 else ""
        changes.append(
            ChangeRecord(
                path=path,
                old_path=old_path,
                change_type=change_type,
                patch=patch,
                old_symbols=old_symbols,
                new_symbols=new_symbols,
                signature_changed=old_sig != new_sig,
                imports_added=sorted(set(new_imports) - set(old_imports)),
                imports_removed=sorted(set(old_imports) - set(new_imports)),
                semantic_noop_hint=_semantic_noop_hint(old_content, new_content, old_sig, new_sig),
            )
        )
    return changes


from repobrain_engine.hub.impact import (
    build_impact_plan,
    build_initial_candidates,
    run_impact_planner,
    run_impact_verifier,
)
from repobrain_engine.hub.incremental_artifacts import (
    _remove_orphan_agent_docs,
    execute_affected_groups,
    render_incremental_map,
    update_related_artifacts,
)


def _status_for_unresolved(
    *,
    run_id: str,
    head_sha: str,
    reason: str,
    baseline_generation: str | None = None,
) -> RefreshStatus:
    status = RefreshStatus(
        refresh_run_id=run_id,
        overall_status="unresolved",
        head_sha=head_sha,
        target_head=head_sha,
        baseline_generation=baseline_generation,
    )
    status.stages["impact_plan"] = "unresolved"
    status.failures.append(FailureRecord(stage="impact_plan", reason=reason))
    return status


def _find_resumable_generation(
    workspace: Path,
    *,
    target_head: str,
    baseline_generation: str,
) -> Path | None:
    generations = control_root(workspace) / "generations"
    if not generations.is_dir():
        return None
    for candidate in sorted((path for path in generations.iterdir() if path.is_dir()), reverse=True):
        resume_path = candidate / "resume.json"
        try:
            payload = json.loads(resume_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("target_head") == target_head
            and payload.get("baseline_generation") == baseline_generation
        ):
            return candidate
    return None


async def _resume_failed_generation(
    workspace: Path,
    *,
    generation_root: Path,
    model: object | None,
) -> RefreshStatus:
    """Resume only failed/pending affected groups in an existing staging generation."""
    plan = ImpactPlan.model_validate_json((generation_root / "impact_plan.json").read_text(encoding="utf-8"))
    snapshot = _load_snapshot_from_root(generation_root)
    if snapshot is None:
        raise IncrementalRefreshError("Resumable generation is missing snapshot.json.")
    try:
        status = RefreshStatus.model_validate_json((generation_root / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        status = RefreshStatus(
            refresh_run_id=plan.run_id,
            overall_status="partial",
            head_sha=plan.target_head,
            target_head=plan.target_head,
            baseline_generation=plan.baseline_generation,
            impact_round=plan.round,
            affected_groups=plan.affected_group_ids,
            unaffected_groups=plan.unaffected_group_ids,
        )
    if model is None:
        from repobrain_engine.config import get_settings
        from repobrain_engine.hub.agents import create_model

        model = create_model(get_settings())
    with use_knowledge_root(generation_root):
        await execute_affected_groups(
            workspace,
            snapshot,
            plan.affected_group_ids,
            model,
            status,
        )
        update_related_artifacts(workspace, snapshot, plan.changes, plan.artifacts)
        status.overall_status = "success"
        status.stages.update(
            {
                "diff": "success",
                "impact_plan": "success",
                "module_docs": "success" if plan.affected_group_ids else "skipped",
                "artifacts": "success" if plan.artifacts else "skipped",
            }
        )
        (generation_root / "status.json").write_text(
            json.dumps(status.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if get_head_sha(workspace) != plan.target_head:
        remove_generation(generation_root)
        raise IncrementalRefreshError("HEAD changed while resuming incremental refresh.")
    promote_generation(
        workspace,
        generation=generation_root.name,
        head_sha=plan.target_head,
        merkle_root=str(snapshot.get("merkle_root", "")),
    )
    (generation_root / "resume.json").unlink(missing_ok=True)
    return status


async def incremental_refresh(
    workspace: Path,
    *,
    model: object | None = None,
    failed_only: bool = False,
) -> RefreshStatus:
    """Run the committed-diff impact loop and atomically promote on success."""
    workspace = workspace.expanduser().resolve()
    ensure_clean_worktree(workspace)
    target_head = get_head_sha(workspace)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    pointer = read_current_pointer(workspace)
    baseline = load_active_snapshot(workspace)
    if pointer is None or baseline is None:
        status = _status_for_unresolved(
            run_id=run_id,
            head_sha=target_head,
            reason="No generation baseline exists. Run `rb-refresh` once before `--quick`.",
        )
        status.impact_plan_path = str(
            write_run_record(workspace, run_id, status.model_dump(mode="json"))
        )
        return status

    baseline_head = str(baseline.get("head_sha", ""))
    baseline_generation = str(pointer.get("generation", ""))
    if failed_only:
        resumable = _find_resumable_generation(
            workspace,
            target_head=target_head,
            baseline_generation=baseline_generation,
        )
        if resumable is not None:
            return await _resume_failed_generation(
                workspace,
                generation_root=resumable,
                model=model,
            )
    if baseline_head == target_head:
        return RefreshStatus(
            refresh_run_id=run_id,
            overall_status="success",
            head_sha=target_head,
            target_head=target_head,
            baseline_generation=baseline_generation,
            stages={"diff": "skipped", "impact_plan": "skipped", "module_docs": "skipped"},
        )

    changes = build_change_set(workspace, baseline_head, target_head)
    target = build_workspace_snapshot(workspace, target_head, previous=baseline)
    if model is None:
        from repobrain_engine.config import get_settings
        from repobrain_engine.hub.agents import create_model

        model = create_model(get_settings())
    max_rounds = max(1, int(os.environ.get("RB_IMPACT_MAX_ROUNDS", "3")))
    plan = await build_impact_plan(
        run_id=run_id,
        baseline_generation=baseline_generation,
        baseline=baseline,
        target=target,
        changes=changes,
        model=model,
        max_rounds=max_rounds,
    )
    plan_path = write_run_record(workspace, run_id, plan.model_dump(mode="json"))
    if plan.unresolved_group_ids:
        status = _status_for_unresolved(
            run_id=run_id,
            head_sha=target_head,
            reason="ImpactPlanner and ImpactVerifier did not converge.",
            baseline_generation=baseline_generation,
        )
        status.impact_round = plan.round
        status.affected_groups = plan.affected_group_ids
        status.unaffected_groups = plan.unaffected_group_ids
        status.unresolved_groups = plan.unresolved_group_ids
        status.impact_plan_path = str(plan_path)
        return status

    generation = new_generation_id(target_head)
    generation_root = create_generation(workspace, generation, clone_active=True)
    status = RefreshStatus(
        refresh_run_id=run_id,
        overall_status="success",
        head_sha=target_head,
        target_head=target_head,
        baseline_generation=baseline_generation,
        impact_round=plan.round,
        affected_groups=plan.affected_group_ids,
        unaffected_groups=plan.unaffected_group_ids,
        impact_plan_path=str(plan_path),
    )
    try:
        with use_knowledge_root(generation_root):
            # The cloned active generation may contain the prior run's
            # execution journal. A new target commit always starts a fresh
            # journal; only --failed-only reuses one in-place.
            (generation_root / "execution.json").unlink(missing_ok=True)
            save_snapshot(generation_root, target)
            (generation_root / "impact_plan.json").write_text(
                plan.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
            )
            (generation_root / "resume.json").write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "baseline_generation": baseline_generation,
                        "target_head": target_head,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (generation_root / "status.json").write_text(
                json.dumps(status.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            await execute_affected_groups(
                workspace,
                target,
                plan.affected_group_ids,
                model,
                status,
            )
            update_related_artifacts(workspace, target, changes, plan.artifacts)
            status.stages.update(
                {
                    "diff": "success",
                    "impact_plan": "success",
                    "module_docs": "success" if plan.affected_group_ids else "skipped",
                    "artifacts": "success" if plan.artifacts else "skipped",
                }
            )
            (generation_root / "status.json").write_text(
                json.dumps(status.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        # A commit arriving during refresh invalidates the whole candidate.
        if get_head_sha(workspace) != target_head:
            raise IncrementalRefreshError("HEAD changed during refresh; run `rb-refresh --quick` again.")
        promote_generation(
            workspace,
            generation=generation,
            head_sha=target_head,
            merkle_root=str(target.get("merkle_root", "")),
        )
        (generation_root / "resume.json").unlink(missing_ok=True)
        return status
    except Exception:
        # Keep staging + execution.json for --failed-only. It is never visible
        # because current.json still points at the prior generation.
        raise


def initialize_full_generation_metadata(
    workspace: Path,
    generation_root: Path,
    head_sha: str,
    status: RefreshStatus,
) -> dict[str, object]:
    """Finalize a successful full refresh as the first incremental baseline."""
    snapshot = build_workspace_snapshot(workspace, head_sha)
    save_snapshot(generation_root, snapshot)
    render_incremental_map(generation_root, snapshot)
    status.baseline_generation = generation_root.name
    status.target_head = head_sha
    (generation_root / "status.json").write_text(
        json.dumps(status.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return snapshot
