"""Tests for hub.pipeline — mocked Runner."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from repobrain_engine.hub.pipeline import (
    _build_ask_context,
    _format_scan_report,
    _get_head_sha,
)
from repobrain_engine.hub.scanner import ScanReport


def test_format_scan_report_basic() -> None:
    report = ScanReport(
        root=Path("/tmp/test"),
        languages={"Python": 10, "JavaScript": 5},
        frameworks=["Python (pyproject.toml)"],
        top_dirs=["src", "tests"],
        file_count=15,
        has_tests=True,
        has_ci=True,
        has_docker=False,
        readme_snippet="# My Project",
    )
    result = _format_scan_report(report)
    assert "Python: 10" in result
    assert "JavaScript: 5" in result
    assert "pyproject.toml" in result
    assert "src, tests" in result
    assert "My Project" in result


def test_format_scan_report_empty() -> None:
    report = ScanReport(root=Path("/tmp/empty"))
    result = _format_scan_report(report)
    assert "Total files: 0" in result


def test_get_head_sha_no_git(tmp_path: Path) -> None:
    """Returns None when not in a git repo."""
    sha = _get_head_sha(tmp_path)
    assert sha is None or isinstance(sha, str)


def test_refresh_initializes_repobrain_scaffold(tmp_path: Path) -> None:
    """Refresh initialization creates project-local state idempotently."""
    from repobrain_engine.hub.refresh_pipeline import (
        _ensure_refresh_workspace_initialized,
    )

    rb_dir = _ensure_refresh_workspace_initialized(tmp_path)
    manifest = rb_dir / "manifest.json"
    original_manifest = manifest.read_text(encoding="utf-8")

    assert rb_dir == tmp_path / ".repobrain"
    assert manifest.exists()
    for dirname in (
        "agents",
        "modules",
        "graph",
        "retrieval_graphs",
        "memory",
        "decisions",
        "logs",
    ):
        assert (rb_dir / dirname).is_dir()

    _ensure_refresh_workspace_initialized(tmp_path)

    assert manifest.read_text(encoding="utf-8") == original_manifest


def test_refresh_initialization_refuses_blocking_file(tmp_path: Path) -> None:
    """Initialization fails instead of replacing user-owned files."""
    from repobrain_engine.hub.refresh_pipeline import (
        _ensure_refresh_workspace_initialized,
    )

    (tmp_path / ".repobrain").write_text("not a dir", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Project initialization failed"):
        _ensure_refresh_workspace_initialized(tmp_path)


@pytest.mark.asyncio
async def test_refresh_pipeline_creates_conventions(
    tmp_path: Path,
    monkeypatch,
    commit_workspace,
) -> None:
    """refresh_pipeline writes conventions.md."""
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    from repobrain_engine.config import reset_settings
    reset_settings()

    rb_dir = tmp_path / ".repobrain"
    rb_dir.mkdir()
    (tmp_path / "main.py").write_text("value = 1\n", encoding="utf-8")
    commit_workspace(tmp_path)

    mock_result = MagicMock()
    mock_result.final_output = "# Conventions\n\nThis is a Python project."

    # Create a mock agents module with Runner.run as AsyncMock
    mock_agents_module = MagicMock()
    mock_agents_module.Runner.run = AsyncMock(return_value=mock_result)
    mock_agents_module.Agent = MagicMock()
    mock_agents_module.set_tracing_disabled = MagicMock()

    with patch.dict("sys.modules", {"agents": mock_agents_module}):
        import importlib
        import repobrain_engine.hub.pipeline as pipeline_mod
        importlib.reload(pipeline_mod)

        await pipeline_mod.refresh_pipeline(tmp_path, quick=False)

    from repobrain_engine.hub.storage import knowledge_root

    rb_dir = knowledge_root(tmp_path)
    conventions = rb_dir / "conventions.md"
    assert conventions.exists()
    assert "Python project" in conventions.read_text(encoding="utf-8")
    assert (rb_dir / "knowledge_graph.json").exists()
    assert (rb_dir / "knowledge_graph.md").exists()
    assert (rb_dir / "knowledge_graph.mmd").exists()
    assert (rb_dir / "document_index.md").exists()
    assert (rb_dir / "data_overview.md").exists()
    assert (rb_dir / "media_manifest.md").exists()


@pytest.mark.asyncio
async def test_refresh_scan_only_can_be_enabled_from_env_file(
    tmp_path: Path,
    monkeypatch,
    commit_workspace,
) -> None:
    """No-key refresh can run in scan-only mode from project .env."""
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.delenv("RB_REFRESH_SCAN_ONLY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "RB_REFRESH_SCAN_ONLY=1\nRB_HOST_RUNNER=codex\n",
        encoding="utf-8",
    )
    (tmp_path / "main.py").write_text("value = 1\n", encoding="utf-8")
    commit_workspace(tmp_path)

    from repobrain_engine.config import reset_settings
    from repobrain_engine.hub.refresh_pipeline import refresh_pipeline

    reset_settings()

    status = await refresh_pipeline(tmp_path, quick=False)

    assert status.stages["conventions"] == "skipped"
    from repobrain_engine.hub.storage import knowledge_root

    assert (knowledge_root(tmp_path) / "scan_report.json").exists()


@pytest.mark.asyncio
async def test_ask_pipeline_returns_answer(tmp_path: Path, monkeypatch) -> None:
    """ask_pipeline returns an answer string."""
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    from repobrain_engine.config import reset_settings
    reset_settings()

    rb_dir = tmp_path / ".repobrain"
    rb_dir.mkdir()
    (rb_dir / "conventions.md").write_text("Python + FastAPI", encoding="utf-8")

    mock_result = MagicMock()
    mock_result.final_output = "This project uses FastAPI."

    mock_agents_module = MagicMock()
    mock_agents_module.Runner.run = AsyncMock(return_value=mock_result)
    mock_agents_module.Agent = MagicMock()
    mock_agents_module.set_tracing_disabled = MagicMock()

    with patch.dict("sys.modules", {"agents": mock_agents_module}):
        import importlib
        import repobrain_engine.hub.pipeline as pipeline_mod
        importlib.reload(pipeline_mod)

        answer = await pipeline_mod.ask_pipeline(tmp_path, "What framework?")

    assert "FastAPI" in answer


@pytest.mark.asyncio
async def test_ask_pipeline_uses_codex_host_runner_without_model_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """RB_HOST_RUNNER=codex bypasses the Agent SDK model path."""
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("RB_HOST_RUNNER", "codex")
    monkeypatch.setenv("RB_HOST_MODEL", "gpt-5.3-codex-spark")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    from repobrain_engine.config import reset_settings
    reset_settings()

    rb_dir = tmp_path / ".repobrain"
    rb_dir.mkdir()
    (rb_dir / "conventions.md").write_text("Python + FastAPI", encoding="utf-8")
    (rb_dir / "map.md").write_text("api: FastAPI application module", encoding="utf-8")
    agents_dir = rb_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "api.md").write_text("FastAPI agent says routes live here.", encoding="utf-8")

    async def _fake_host_runner(**kwargs):
        assert kwargs["runner"] == "codex"
        assert kwargs["model"] == "gpt-5.3-codex-spark"
        assert "FastAPI" in kwargs["context"]
        assert "FastAPI agent says" in kwargs["context"]
        return "host runner answer"

    def _unexpected_create_model(*args, **kwargs):
        raise AssertionError("create_model should not be called in host mode")

    monkeypatch.setattr(
        "repobrain_engine.hub.host_runner.run_host_runner",
        _fake_host_runner,
    )
    monkeypatch.setattr(
        "repobrain_engine.hub.agents.create_model",
        _unexpected_create_model,
    )

    from repobrain_engine.hub.ask_pipeline import ask_pipeline

    answer = await ask_pipeline(tmp_path, "What framework?")

    assert answer == "host runner answer"


@pytest.mark.asyncio
async def test_ask_pipeline_rejects_unknown_host_runner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("RB_HOST_RUNNER", "codexx")

    from repobrain_engine.config import reset_settings
    from repobrain_engine.hub.host_runner import HostRunnerError

    reset_settings()

    from repobrain_engine.hub.ask_pipeline import ask_pipeline

    with pytest.raises(HostRunnerError, match="Unsupported RB_HOST_RUNNER"):
        await ask_pipeline(tmp_path, "What framework?")


@pytest.mark.asyncio
async def test_ask_pipeline_host_runner_preserves_retrieval_first_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("RB_HOST_RUNNER", "codex")
    monkeypatch.setenv("RB_ASK_RETRIEVAL_FIRST", "2")
    (tmp_path / "app.py").write_text("def target_func():\n    return 1\n", encoding="utf-8")

    from repobrain_engine.config import reset_settings
    reset_settings()

    async def _unexpected_host_runner(**kwargs):
        raise AssertionError("host runner should be skipped by retrieval-first mode")

    monkeypatch.setattr(
        "repobrain_engine.hub.host_runner.run_host_runner",
        _unexpected_host_runner,
    )

    from repobrain_engine.hub.ask_pipeline import ask_pipeline

    answer = await ask_pipeline(tmp_path, "Where is target_func defined?")

    assert "target_func" in answer
    assert "app.py" in answer


@pytest.mark.asyncio
async def test_ask_pipeline_host_runner_failure_does_not_include_env_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("RB_HOST_RUNNER", "codex")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value")

    from repobrain_engine.config import reset_settings
    from repobrain_engine.hub.host_runner import HostRunnerError

    reset_settings()

    async def _fake_host_runner(**kwargs):
        raise HostRunnerError("Codex host runner failed: no credentials available")

    monkeypatch.setattr(
        "repobrain_engine.hub.host_runner.run_host_runner",
        _fake_host_runner,
    )

    from repobrain_engine.hub.ask_pipeline import ask_pipeline

    with pytest.raises(HostRunnerError) as excinfo:
        await ask_pipeline(tmp_path, "What framework?")

    assert "sk-test-secret-value" not in str(excinfo.value)


def test_build_ask_context_includes_root_and_memory_docs(tmp_path: Path) -> None:
    """ask context should include root docs and memory logs when present."""
    rb_dir = tmp_path / ".repobrain"
    memory_dir = rb_dir / "memory"
    (rb_dir / "decisions").mkdir(parents=True)
    memory_dir.mkdir(parents=True)

    (rb_dir / "conventions.md").write_text("Python + FastAPI", encoding="utf-8")
    (tmp_path / "CONTEXT.md").write_text("Use service layer", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(
        "Read the repobrain files first",
        encoding="utf-8",
    )
    (memory_dir / "reports.md").write_text(
        "Auth module needs cleanup",
        encoding="utf-8",
    )

    context = _build_ask_context(tmp_path)

    assert ".repobrain/conventions.md" in context
    assert "CONTEXT.md" in context
    assert "AGENTS.md" in context
    assert ".repobrain/memory/reports.md" in context
    assert "Auth module needs cleanup" in context


def test_load_project_context_includes_conventions_and_registry(tmp_path: Path) -> None:
    """_load_project_context must surface project-wide docs to the agent-md path.

    Regression guard: the new structured-facts path used to read only per-module
    agent docs, so questions answerable from conventions.md got refusal answers.
    """
    from repobrain_engine.hub.ask_pipeline import _load_project_context

    rb_dir = tmp_path / ".repobrain"
    rb_dir.mkdir()
    (rb_dir / "conventions.md").write_text(
        "# Project Conventions\n\nLint: Ruff. Format: Black.",
        encoding="utf-8",
    )
    (rb_dir / "module_registry.md").write_text(
        "# Module Registry\n\n- core: business logic\n- api: HTTP layer\n",
        encoding="utf-8",
    )

    map_content = "# Module Map\n\n## core\n- Path: src/core/\n"
    section = _load_project_context(rb_dir, map_content=map_content)

    assert "Project Context" in section
    assert "Lint: Ruff" in section
    assert "Module Registry" in section
    assert "core: business logic" in section
    assert "Module Map" in section
    assert "src/core/" in section


def test_load_project_context_returns_empty_when_no_sources(tmp_path: Path) -> None:
    """No conventions/map/registry → empty string (callers skip the section)."""
    from repobrain_engine.hub.ask_pipeline import _load_project_context

    rb_dir = tmp_path / ".repobrain"
    rb_dir.mkdir()
    assert _load_project_context(rb_dir, map_content="") == ""


def test_ask_tools_can_be_wrapped_for_answer_agent() -> None:
    """The structured-facts path binds code-exploration tools to its answer
    agents at runtime. This test guards that the wiring exists and produces
    the SDK FunctionTool objects the Agent constructor expects."""
    from pathlib import Path
    from repobrain_engine.hub.agents import _wrap_tools
    from repobrain_engine.hub.ask_tools import create_ask_tools

    tools = create_ask_tools(Path("/tmp"))
    wrapped = _wrap_tools(tools)
    # The minimal tool set the answer agent needs to verify claims and
    # enumerate cross-file (search/read/list at minimum).
    assert "search_code" in tools
    assert "read_file" in tools
    assert "list_directory" in tools
    assert len(wrapped) == len(tools)
    assert wrapped, "tool list must not be empty"
    for t in wrapped:
        assert type(t).__name__ == "FunctionTool"


def test_load_project_context_respects_total_budget(tmp_path: Path) -> None:
    """Total budget caps overall section size; per-source cap prevents one big
    file from starving the others."""
    from repobrain_engine.hub.ask_pipeline import _load_project_context

    rb_dir = tmp_path / ".repobrain"
    rb_dir.mkdir()
    big = "x" * 50_000
    (rb_dir / "conventions.md").write_text(big, encoding="utf-8")
    (rb_dir / "module_registry.md").write_text("REGISTRY_MARKER\n" + big, encoding="utf-8")

    section = _load_project_context(rb_dir, map_content="", max_chars=3_000)

    # Total stays roughly under the cap (header + per-source caps).
    assert len(section) <= 4_000
    # Conventions came first; registry should still get its share, so the marker
    # must appear because per-source cap < total budget.
    assert "REGISTRY_MARKER" in section


def test_ask_retry_classifier_handles_litellm_service_unavailable() -> None:
    """LiteLLM wraps provider 503s without always preserving the numeric code."""
    from repobrain_engine.hub.ask_pipeline import _is_retryable_ask_error

    class ServiceUnavailableError(Exception):
        pass

    exc = ServiceUnavailableError(
        "litellm.ServiceUnavailableError: OpenAIException - "
        "Service temporarily unavailable"
    )

    assert _is_retryable_ask_error(exc)


# ---------------------------------------------------------------------------
# Phase 1: config/entry/git in _format_scan_report
# ---------------------------------------------------------------------------


def test_format_scan_report_includes_config() -> None:
    """Config file contents appear in the formatted report."""
    report = ScanReport(
        root=Path("/tmp/test"),
        config_contents={"pyproject.toml": '[project]\nname = "demo"'},
    )
    result = _format_scan_report(report)
    assert "pyproject.toml" in result
    assert 'name = "demo"' in result


def test_format_scan_report_includes_entry_points() -> None:
    """Entry point snippets appear in the formatted report."""
    report = ScanReport(
        root=Path("/tmp/test"),
        entry_points={"main.py": "import sys\nprint('hello')"},
    )
    result = _format_scan_report(report)
    assert "main.py" in result
    assert "import sys" in result


def test_format_scan_report_includes_git() -> None:
    """Git summary appears in the formatted report."""
    report = ScanReport(
        root=Path("/tmp/test"),
        git_summary="Recent commits:\nabc123 fix auth\ndef456 add tests",
    )
    result = _format_scan_report(report)
    assert "fix auth" in result
    assert "add tests" in result


def test_build_module_registry_entries_humanizes_workspace_root(tmp_path: Path) -> None:
    """Workspace-root module summaries should avoid exposing the sentinel id."""
    from repobrain_engine.hub.contracts import RefreshStatus
    from repobrain_engine.hub.refresh_pipeline import _build_module_registry_entries

    (tmp_path / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")

    entries = _build_module_registry_entries(
        tmp_path,
        RefreshStatus(refresh_run_id="test-run", overall_status="success"),
    )

    assert len(entries) == 1
    assert entries[0].module == "__workspace_root__"
    assert entries[0].summary == "workspace root"
    assert entries[0].top_paths == ["main.go"]
