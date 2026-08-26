"""Tests for non-blocking ask freshness and health notices."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from repobrain_engine.hub.ask_pipeline import _build_workspace_health_notices


def _write_repobrain(tmp_path: Path, *, sha: str | None = "abc123") -> Path:
    rb_dir = tmp_path / ".repobrain"
    rb_dir.mkdir()
    if sha is not None:
        (rb_dir / ".last_refresh_sha").write_text(sha, encoding="utf-8")
    return rb_dir


def test_ask_fresh_workspace_has_no_notice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_repobrain(tmp_path)

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="0\n", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)

    assert _build_workspace_health_notices(tmp_path) == []


def test_ask_stale_workspace_reports_commit_lag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_repobrain(tmp_path)

    def _fake_run(*args, **kwargs):
        assert args[0] == ["git", "rev-list", "--count", "abc123..HEAD"]
        return subprocess.CompletedProcess(args[0], 0, stdout="3\n", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)

    notices = _build_workspace_health_notices(tmp_path)

    assert notices == [
        "⚠ Knowledge base is 3 commit(s) behind HEAD -- consider running rb-refresh --quick."
    ]


def test_ask_missing_refresh_sha_silently_skips_freshness_check(
    tmp_path: Path,
) -> None:
    _write_repobrain(tmp_path, sha=None)

    assert _build_workspace_health_notices(tmp_path) == []


def test_ask_non_git_workspace_silently_skips_freshness_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_repobrain(tmp_path)

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 128, stdout="", stderr="fatal")

    monkeypatch.setattr("subprocess.run", _fake_run)

    assert _build_workspace_health_notices(tmp_path) == []


def test_ask_partial_status_reports_degraded_modules(tmp_path: Path) -> None:
    rb_dir = _write_repobrain(tmp_path, sha=None)
    (rb_dir / "status.json").write_text(
        json.dumps(
            {
                "refresh_run_id": "run",
                "overall_status": "partial",
                "modules": {
                    "api": "success",
                    "cli": "partial",
                    "worker": "failed",
                },
            }
        ),
        encoding="utf-8",
    )

    notices = _build_workspace_health_notices(tmp_path)

    assert notices == [
        "⚠ Knowledge base has partial/failed module knowledge for: cli, worker."
    ]


@pytest.mark.asyncio
async def test_ask_host_runner_prepends_workspace_health_notice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("RB_HOST_RUNNER", "codex")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    rb_dir = _write_repobrain(tmp_path)
    (rb_dir / "map.md").write_text("api: docs", encoding="utf-8")
    agents_dir = rb_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "api.md").write_text("agent docs", encoding="utf-8")

    from repobrain_engine.config import reset_settings

    reset_settings()

    async def _fake_host_runner(**kwargs):
        return "host answer"

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="1\n", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)

    from repobrain_engine.hub import ask_pipeline as ask_mod

    monkeypatch.setattr(ask_mod, "_ask_with_host_runner", lambda *args, **kwargs: _fake_host_runner())

    answer = await ask_mod.ask_pipeline(tmp_path, "What changed?")

    assert answer.startswith(
        "⚠ Knowledge base is 1 commit(s) behind HEAD -- consider running rb-refresh --quick.\n"
    )
    assert answer.endswith("host answer")


# ---------------------------------------------------------------------------
# Manual-refresh reminder: rb-ask never mutates knowledge
# ---------------------------------------------------------------------------


class _AutoRefreshSettings:
    """Minimal settings stub exposing only the auto-refresh knobs."""

    def __init__(self, mode: str = "stale", lag: int = 20) -> None:
        self.RB_ASK_AUTO_REFRESH = mode
        self.RB_ASK_AUTO_REFRESH_LAG = lag


def _write_full_kb(tmp_path: Path, *, sha: str | None = "abc123") -> None:
    """Write artifacts that make _structured_artifacts_available() true."""
    rb_dir = _write_repobrain(tmp_path, sha=sha)
    (rb_dir / "map.md").write_text("api: docs", encoding="utf-8")
    agents_dir = rb_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "api.md").write_text("agent docs", encoding="utf-8")


def test_auto_refresh_off_never_triggers(tmp_path: Path) -> None:
    from repobrain_engine.hub.ask_pipeline import _should_auto_refresh

    # No KB at all, but mode is off → still no refresh.
    assert _should_auto_refresh(tmp_path, _AutoRefreshSettings(mode="off")) is None


def test_auto_refresh_first_run_triggers_when_kb_missing(tmp_path: Path) -> None:
    from repobrain_engine.hub.ask_pipeline import _should_auto_refresh

    reason = _should_auto_refresh(tmp_path, _AutoRefreshSettings(mode="first-only"))
    assert reason == "no knowledge base found"


def test_legacy_first_only_now_warns_on_any_committed_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from repobrain_engine.hub.ask_pipeline import _should_auto_refresh

    _write_full_kb(tmp_path)

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="999\n", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)

    assert _should_auto_refresh(tmp_path, _AutoRefreshSettings(mode="first-only")) == (
        "knowledge base is 999 commits behind HEAD"
    )


def test_auto_refresh_stale_triggers_past_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from repobrain_engine.hub.ask_pipeline import _should_auto_refresh

    _write_full_kb(tmp_path)

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="25\n", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)

    reason = _should_auto_refresh(tmp_path, _AutoRefreshSettings(mode="stale", lag=20))
    assert reason == "knowledge base is 25 commits behind HEAD"


def test_manual_notice_ignores_legacy_lag_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from repobrain_engine.hub.ask_pipeline import _should_auto_refresh

    _write_full_kb(tmp_path)

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="5\n", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)

    assert _should_auto_refresh(tmp_path, _AutoRefreshSettings(mode="stale", lag=20)) == (
        "knowledge base is 5 commits behind HEAD"
    )


@pytest.mark.asyncio
async def test_refresh_reminder_never_invokes_refresh_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ask emits a reminder but never executes refresh."""
    import repobrain_engine.hub.refresh_pipeline as refresh_mod
    from repobrain_engine.hub import ask_pipeline as ask_mod

    calls: list[tuple[Path, bool]] = []

    async def _fake_refresh(workspace, quick: bool = False, **kwargs):
        calls.append((workspace, quick))

    monkeypatch.setattr(refresh_mod, "refresh_pipeline", _fake_refresh)

    # No KB → first-run trigger regardless of mode.
    await ask_mod._maybe_auto_refresh(tmp_path, _AutoRefreshSettings(mode="stale"))

    assert calls == []


@pytest.mark.asyncio
async def test_refresh_reminder_does_not_touch_refresh_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old refresh function is unreachable from the reminder path."""
    import repobrain_engine.hub.refresh_pipeline as refresh_mod
    from repobrain_engine.hub import ask_pipeline as ask_mod

    async def _boom(workspace, quick: bool = False, **kwargs):
        raise RuntimeError("refresh exploded")

    monkeypatch.setattr(refresh_mod, "refresh_pipeline", _boom)

    # Should return normally despite the refresh error.
    await ask_mod._maybe_auto_refresh(tmp_path, _AutoRefreshSettings(mode="first-only"))


@pytest.mark.asyncio
async def test_refresh_reminder_has_no_reentrancy_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reminder-only behavior has no mutable reentrancy guard."""
    import repobrain_engine.hub.refresh_pipeline as refresh_mod
    from repobrain_engine.hub import ask_pipeline as ask_mod

    called = False

    async def _fake_refresh(workspace, quick: bool = False, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(refresh_mod, "refresh_pipeline", _fake_refresh)
    await ask_mod._maybe_auto_refresh(tmp_path, _AutoRefreshSettings(mode="first-only"))

    assert called is False
