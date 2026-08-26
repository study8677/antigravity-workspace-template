"""Tests for generation-backed, RepoBrain-judged incremental refresh."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from repobrain_engine.hub.contracts import ImpactDecision, ImpactVerification
from repobrain_engine.hub.incremental import (
    _remove_orphan_agent_docs,
    DirtyWorktreeError,
    build_change_set,
    build_workspace_snapshot,
    ensure_clean_worktree,
    incremental_refresh,
    save_snapshot,
)
from repobrain_engine.hub.impact import build_impact_plan, build_initial_candidates
from repobrain_engine.hub.storage import (
    create_generation,
    knowledge_root,
    promote_generation,
    read_current_pointer,
    use_knowledge_root,
)


def _git(workspace: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(workspace: Path) -> str:
    _git(workspace, "init", "-q")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "Test")
    src = workspace / "src"
    src.mkdir()
    (src / "service.py").write_text("def value() -> int:\n    return 1\n", encoding="utf-8")
    (src / "other.py").write_text("def other() -> int:\n    return 2\n", encoding="utf-8")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "baseline")
    return _git(workspace, "rev-parse", "HEAD")


def _install_baseline(workspace: Path, head: str) -> dict[str, object]:
    generation = f"baseline-{head[:8]}"
    root = create_generation(workspace, generation, clone_active=False)
    snapshot = build_workspace_snapshot(workspace, head)
    save_snapshot(root, snapshot)
    for entry in snapshot["groups"].values():
        artifact = root / entry["artifact_path"]
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(f"# {entry['group_name']}\n", encoding="utf-8")
    promote_generation(
        workspace,
        generation=generation,
        head_sha=head,
        merkle_root=str(snapshot["merkle_root"]),
    )
    return snapshot


def test_generation_pointer_controls_reader_root(tmp_path: Path) -> None:
    head = _init_repo(tmp_path)
    snapshot = _install_baseline(tmp_path, head)

    pointer = read_current_pointer(tmp_path)
    assert pointer is not None
    assert knowledge_root(tmp_path).name == pointer["generation"]
    assert json.loads((knowledge_root(tmp_path) / "snapshot.json").read_text())["merkle_root"] == snapshot["merkle_root"]


def test_dirty_worktree_is_rejected_but_repobrain_outputs_are_ignored(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / ".repobrain").mkdir()
    (tmp_path / ".repobrain" / "local.json").write_text("{}", encoding="utf-8")
    ensure_clean_worktree(tmp_path)

    (tmp_path / "src" / "service.py").write_text("changed\n", encoding="utf-8")
    with pytest.raises(DirtyWorktreeError):
        ensure_clean_worktree(tmp_path)


def test_change_set_uses_commits_and_detects_signature_change(tmp_path: Path) -> None:
    baseline = _init_repo(tmp_path)
    path = tmp_path / "src" / "service.py"
    path.write_text("def value(flag: bool) -> int:\n    return 2 if flag else 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "change signature")
    target = _git(tmp_path, "rev-parse", "HEAD")

    changes = build_change_set(tmp_path, baseline, target)

    assert [change.path for change in changes] == ["src/service.py"]
    assert changes[0].signature_changed is True
    assert "def value(flag: bool)" in changes[0].patch


def test_multi_group_artifacts_never_create_single_file_shadow(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    test_file = tmp_path / "src" / "test_service.py"
    test_file.write_text("def test_value():\n    assert True\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "add tests group")
    snapshot = build_workspace_snapshot(tmp_path, _git(tmp_path, "rev-parse", "HEAD"))
    artifacts = {entry["artifact_path"] for entry in snapshot["groups"].values()}
    assert "agents/src.md" not in artifacts
    assert any(path.startswith("agents/src/") for path in artifacts)

    generation = tmp_path / "generation"
    for artifact in artifacts:
        path = generation / artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("knowledge", encoding="utf-8")
    shadow = generation / "agents" / "src.md"
    shadow.write_text("stale shadow", encoding="utf-8")

    _remove_orphan_agent_docs(generation, snapshot)

    assert not shadow.exists()
    assert all((generation / artifact).exists() for artifact in artifacts)


def test_non_source_config_token_selects_consuming_group() -> None:
    change = {
        "path": "deploy/app.env",
        "change_type": "modified",
        "patch": "+FEATURE_ENABLED=true",
    }
    snapshot = {
        "groups": {
            "api": {"module": "api", "group_name": "main", "files": ["api/app.py"]},
        },
        "file_to_group": {},
        "token_to_groups": {"FEATURE_ENABLED": ["api"]},
        "reverse_dependencies": {},
        "edge_reasons": {},
    }
    from repobrain_engine.hub.contracts import ChangeRecord

    candidates, _ = build_initial_candidates([ChangeRecord.model_validate(change)], snapshot, snapshot)

    assert list(candidates) == ["api"]


@pytest.mark.asyncio
async def test_public_impact_expands_reverse_dependencies_layer_by_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = {
        name: {"module": name, "group_name": "main", "files": [f"{name}.py"]}
        for name in ("a", "b", "c")
    }
    snapshot = {
        "head_sha": "target",
        "groups": groups,
        "file_to_group": {"a.py": "a"},
        "token_to_groups": {},
        "reverse_dependencies": {"a": ["b"], "b": ["c"]},
        "edge_reasons": {"b->a": ["b imports a"], "c->b": ["c imports b"]},
    }
    from repobrain_engine.hub.contracts import ChangeRecord

    change = ChangeRecord(path="a.py", change_type="modified", patch="public API changed")

    async def planner(changes, candidates, model, **kwargs):
        return [
            ImpactDecision(
                group_id=candidate.group_id,
                decision="affected",
                reason="public contract dependency",
                evidence=["public API changed"],
                impact_path=["diff:a.py", f"group:{candidate.group_id}"],
                propagate=True,
            )
            for candidate in candidates
        ]

    async def verifier(changes, candidates, decisions, model):
        return ImpactVerification(decisions=decisions, approved=True)

    monkeypatch.setattr("repobrain_engine.hub.impact.run_impact_planner", planner)
    monkeypatch.setattr("repobrain_engine.hub.impact.run_impact_verifier", verifier)

    plan = await build_impact_plan(
        run_id="run",
        baseline_generation="base",
        baseline={**snapshot, "head_sha": "base"},
        target=snapshot,
        changes=[change],
        model=object(),
        max_rounds=3,
    )

    assert plan.affected_group_ids == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_quick_requires_full_generation_baseline(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    status = await incremental_refresh(tmp_path, model=object())

    assert status.overall_status == "unresolved"
    assert status.exit_code == 2
    assert read_current_pointer(tmp_path) is None


@pytest.mark.asyncio
async def test_only_approved_group_executes_and_promotes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_head = _init_repo(tmp_path)
    baseline = _install_baseline(tmp_path, baseline_head)
    changed = tmp_path / "src" / "service.py"
    changed.write_text("def value() -> int:\n    return 3\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "change implementation")
    target_head = _git(tmp_path, "rev-parse", "HEAD")
    owner = baseline["file_to_group"]["src/service.py"]
    executed: list[str] = []
    (knowledge_root(tmp_path) / "execution.json").write_text(
        json.dumps({"group_states": {owner: {"state": "success"}}}),
        encoding="utf-8",
    )

    async def fake_planner(changes, candidates, model, **kwargs):
        return [
            ImpactDecision(
                group_id=candidate.group_id,
                decision="affected" if candidate.group_id == owner else "unaffected",
                reason="direct implementation owner" if candidate.group_id == owner else "no semantic dependency",
                evidence=["src/service.py changed"],
                impact_path=["diff:src/service.py", f"group:{candidate.group_id}"],
                propagate=False,
            )
            for candidate in candidates
        ]

    async def fake_verifier(changes, candidates, decisions, model):
        return ImpactVerification(decisions=decisions, approved=True, reason="complete")

    async def fake_execute(workspace, snapshot, affected_group_ids, model, status):
        assert not (knowledge_root(workspace) / "execution.json").exists()
        executed.extend(affected_group_ids)
        for group_id in affected_group_ids:
            status.groups[group_id] = "success"

    monkeypatch.setattr("repobrain_engine.hub.impact.run_impact_planner", fake_planner)
    monkeypatch.setattr("repobrain_engine.hub.impact.run_impact_verifier", fake_verifier)
    monkeypatch.setattr("repobrain_engine.hub.incremental.execute_affected_groups", fake_execute)
    monkeypatch.setattr("repobrain_engine.hub.incremental.update_related_artifacts", lambda *args, **kwargs: None)

    status = await incremental_refresh(tmp_path, model=object())

    assert status.overall_status == "success"
    assert executed == [owner]
    assert read_current_pointer(tmp_path)["head_sha"] == target_head


@pytest.mark.asyncio
async def test_three_conflicting_rounds_leave_active_generation_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_head = _init_repo(tmp_path)
    _install_baseline(tmp_path, baseline_head)
    changed = tmp_path / "src" / "service.py"
    changed.write_text("def value() -> int:\n    return 4\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "conflicting impact")
    original_pointer = read_current_pointer(tmp_path)
    rounds = 0

    async def fake_planner(changes, candidates, model, **kwargs):
        nonlocal rounds
        rounds += 1
        return [
            ImpactDecision(
                group_id=candidate.group_id,
                decision="affected",
                reason="planner says affected",
                evidence=["diff"],
                impact_path=["diff", f"group:{candidate.group_id}"],
            )
            for candidate in candidates
        ]

    async def fake_verifier(changes, candidates, decisions, model):
        return ImpactVerification(
            decisions=[
                ImpactDecision(
                    group_id=decision.group_id,
                    decision="unaffected",
                    reason="verifier disagrees",
                )
                for decision in decisions
            ],
            approved=False,
            reason="conflict",
        )

    monkeypatch.setattr("repobrain_engine.hub.impact.run_impact_planner", fake_planner)
    monkeypatch.setattr("repobrain_engine.hub.impact.run_impact_verifier", fake_verifier)

    status = await incremental_refresh(tmp_path, model=object())

    assert rounds == 3
    assert status.overall_status == "unresolved"
    assert status.unresolved_groups
    assert read_current_pointer(tmp_path) == original_pointer


@pytest.mark.asyncio
async def test_semantic_noop_can_promote_with_zero_group_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_head = _init_repo(tmp_path)
    _install_baseline(tmp_path, baseline_head)
    path = tmp_path / "src" / "service.py"
    path.write_text("# explanation\ndef value() -> int:\n    return 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "comment only")

    async def fake_planner(changes, candidates, model, **kwargs):
        assert changes[0].semantic_noop_hint is True
        return [
            ImpactDecision(
                group_id=candidate.group_id,
                decision="unaffected",
                reason="comment-only change",
                evidence=["semantic signature unchanged"],
            )
            for candidate in candidates
        ]

    async def fake_verifier(changes, candidates, decisions, model):
        return ImpactVerification(decisions=decisions, approved=True, reason="no impact")

    async def should_not_execute(*args, **kwargs):
        assert not args[2]

    monkeypatch.setattr("repobrain_engine.hub.impact.run_impact_planner", fake_planner)
    monkeypatch.setattr("repobrain_engine.hub.impact.run_impact_verifier", fake_verifier)
    monkeypatch.setattr("repobrain_engine.hub.incremental.execute_affected_groups", should_not_execute)
    monkeypatch.setattr("repobrain_engine.hub.incremental.update_related_artifacts", lambda *args, **kwargs: None)

    status = await incremental_refresh(tmp_path, model=object())

    assert status.overall_status == "success"
    assert status.affected_groups == []


@pytest.mark.asyncio
async def test_failed_only_resumes_unpromoted_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_head = _init_repo(tmp_path)
    baseline = _install_baseline(tmp_path, baseline_head)
    path = tmp_path / "src" / "service.py"
    path.write_text("def value() -> int:\n    return 9\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "resumable change")
    owner = baseline["file_to_group"]["src/service.py"]

    async def fake_planner(changes, candidates, model, **kwargs):
        return [
            ImpactDecision(
                group_id=candidate.group_id,
                decision="affected" if candidate.group_id == owner else "unaffected",
                reason="owner" if candidate.group_id == owner else "unrelated",
                evidence=["diff"],
                impact_path=["diff", f"group:{candidate.group_id}"],
            )
            for candidate in candidates
        ]

    async def fake_verifier(changes, candidates, decisions, model):
        return ImpactVerification(decisions=decisions, approved=True)

    attempts = 0

    async def flaky_execute(workspace, snapshot, affected_group_ids, model, status):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("provider failed")
        for group_id in affected_group_ids:
            status.groups[group_id] = "success"

    monkeypatch.setattr("repobrain_engine.hub.impact.run_impact_planner", fake_planner)
    monkeypatch.setattr("repobrain_engine.hub.impact.run_impact_verifier", fake_verifier)
    monkeypatch.setattr("repobrain_engine.hub.incremental.execute_affected_groups", flaky_execute)
    monkeypatch.setattr("repobrain_engine.hub.incremental.update_related_artifacts", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="provider failed"):
        await incremental_refresh(tmp_path, model=object())
    old_pointer = read_current_pointer(tmp_path)

    status = await incremental_refresh(tmp_path, model=object(), failed_only=True)

    assert status.overall_status == "success"
    assert attempts == 2
    assert read_current_pointer(tmp_path) != old_pointer
