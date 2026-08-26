"""Tests for quick-refresh group filtering and resumable refresh."""
from __future__ import annotations

import json
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from repobrain_engine.hub.scanner import ScanReport


class _Source:
    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path


class _Group:
    def __init__(self, name: str, files: list[str]) -> None:
        self.name = name
        self.files = [_Source(path) for path in files]


class _Agent:
    def __init__(self, name: str) -> None:
        self.name = name


def _mock_agents_module(runner: AsyncMock) -> MagicMock:
    mock_agents_module = MagicMock()
    mock_agents_module.Runner.run = runner
    mock_agents_module.Agent = MagicMock()
    mock_agents_module.set_tracing_disabled = MagicMock()
    return mock_agents_module


def _patch_common_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    report: ScanReport,
    module_entries: list,
) -> None:
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    from repobrain_engine.config import reset_settings
    from repobrain_engine.hub import agents as agents_mod
    from repobrain_engine.hub import scanner
    from repobrain_engine.hub import refresh_pipeline as refresh_mod

    reset_settings()
    monkeypatch.setattr(agents_mod, "create_model", lambda settings: "test-model")
    monkeypatch.setattr(agents_mod, "build_refresh_agent", lambda model: _Agent("Conventions"))
    monkeypatch.setattr(agents_mod, "build_refresh_git_agent", lambda model, workspace: _Agent("Git"))
    monkeypatch.setattr(
        agents_mod,
        "build_refresh_module_swarm_v2",
        lambda model, workspace, modules_filter=None: module_entries,
    )
    monkeypatch.setattr(scanner, "detect_modules", lambda workspace: ["src"])
    monkeypatch.setattr(scanner, "resolve_module_path", lambda workspace, module: workspace / module)
    monkeypatch.setattr(scanner, "full_scan", lambda workspace: report)
    monkeypatch.setattr(scanner, "quick_scan", lambda workspace, since_sha: report)
    monkeypatch.setattr(scanner, "extract_structure", lambda workspace: "# Structure\n")
    monkeypatch.setattr(scanner, "build_knowledge_graph", lambda workspace, scan_report: {})
    monkeypatch.setattr(scanner, "render_knowledge_graph_markdown", lambda graph: "# Graph\n")
    monkeypatch.setattr(scanner, "render_knowledge_graph_mermaid", lambda graph: "graph TD\n")
    monkeypatch.setattr(refresh_mod, "_get_head_sha", lambda workspace: "head-current")

    async def _fake_map(*args, **kwargs):
        return "# Module Map\n"

    monkeypatch.setattr(refresh_mod, "_generate_map_md", _fake_map)


@pytest.mark.asyncio
async def test_quick_refresh_no_changes_runs_zero_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rb_dir = tmp_path / ".repobrain"
    rb_dir.mkdir()
    (rb_dir / ".last_refresh_sha").write_text("head-old", encoding="utf-8")
    report = ScanReport(root=tmp_path, changed_files=[])
    runner = AsyncMock()

    _patch_common_refresh(tmp_path, monkeypatch, report=report, module_entries=[])

    with patch.dict("sys.modules", {"agents": _mock_agents_module(runner)}):
        from repobrain_engine.hub.refresh_pipeline import _refresh_pipeline_into_generation

        status = await _refresh_pipeline_into_generation(tmp_path, quick=True)

    assert status.stages["module_docs"] == "skipped"
    assert runner.await_count == 0


@pytest.mark.asyncio
async def test_quick_refresh_single_file_reruns_only_owning_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rb_dir = tmp_path / ".repobrain"
    rb_dir.mkdir()
    (rb_dir / ".last_refresh_sha").write_text("head-old", encoding="utf-8")
    report = ScanReport(root=tmp_path, changed_files=["src/a.py"])
    module_entries = [
        (
            "src",
            [
                ("group_a", _Group("group_a", ["src/a.py"]), _Agent("RefreshModule_src_group_a")),
                ("group_b", _Group("group_b", ["src/b.py"]), _Agent("RefreshModule_src_group_b")),
            ],
        )
    ]
    runner = AsyncMock(return_value=types.SimpleNamespace(final_output="# Agent doc\n"))

    _patch_common_refresh(
        tmp_path,
        monkeypatch,
        report=report,
        module_entries=module_entries,
    )

    with patch.dict("sys.modules", {"agents": _mock_agents_module(runner)}):
        from repobrain_engine.hub.refresh_pipeline import _refresh_pipeline_into_generation

        status = await _refresh_pipeline_into_generation(tmp_path, quick=True)

    module_agent_names = [
        call.args[0].name
        for call in runner.await_args_list
        if call.args and call.args[0].name.startswith("RefreshModule_")
    ]
    assert module_agent_names == ["RefreshModule_src_group_a"]
    assert status.groups["src/group_a"] == "success"
    assert "src/group_b" not in status.groups


@pytest.mark.asyncio
async def test_refresh_resume_skips_groups_completed_at_same_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rb_dir = tmp_path / ".repobrain"
    rb_dir.mkdir()
    (rb_dir / "status.json").write_text(
        json.dumps(
            {
                "refresh_run_id": "previous",
                "overall_status": "partial",
                "head_sha": "head-current",
                "modules": {"src": "partial"},
                "groups": {"src/group_a": "success", "src/group_b": "failed"},
                "group_head_shas": {
                    "src/group_a": "head-current",
                    "src/group_b": "head-current",
                },
            }
        ),
        encoding="utf-8",
    )
    report = ScanReport(root=tmp_path)
    module_entries = [
        (
            "src",
            [
                ("group_a", _Group("group_a", ["src/a.py"]), _Agent("RefreshModule_src_group_a")),
                ("group_b", _Group("group_b", ["src/b.py"]), _Agent("RefreshModule_src_group_b")),
            ],
        )
    ]
    runner = AsyncMock(return_value=types.SimpleNamespace(final_output="# Agent doc\n"))

    _patch_common_refresh(
        tmp_path,
        monkeypatch,
        report=report,
        module_entries=module_entries,
    )

    with patch.dict("sys.modules", {"agents": _mock_agents_module(runner)}):
        from repobrain_engine.hub.refresh_pipeline import _refresh_pipeline_into_generation

        status = await _refresh_pipeline_into_generation(tmp_path, quick=False)

    module_agent_names = [
        call.args[0].name
        for call in runner.await_args_list
        if call.args and call.args[0].name.startswith("RefreshModule_")
    ]
    assert module_agent_names == ["RefreshModule_src_group_b"]
    assert status.groups["src/group_a"] == "success"
    assert status.groups["src/group_b"] == "success"
