"""Refresh pipeline — scan the project and generate knowledge artifacts.

Extracted from ``pipeline.py`` to separate the refresh and ask
workflows into dedicated modules.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repobrain_engine.hub._constants import (
    AGENT_MD_FALLBACK_MARKER,
    AGENT_MD_FALLBACK_SENTINEL,
    SOURCE_CODE_EXTS,
    WORKSPACE_ROOT_MODULE_ID,
)
from repobrain_engine.hub.contracts import (
    EvidenceSpan,
    FailureRecord,
    GroupFactsDocument,
    ModuleClaim,
    ModuleFactsDocument,
    ModuleRegistryEntry,
    RefreshStatus,
)
from repobrain_engine.hub.storage import knowledge_root

logger = logging.getLogger(__name__)

_REPOBRAIN_MANIFEST_VERSION = 1
_REFRESH_INIT_DIRS = (
    "agents",
    "modules",
    "graph",
    "retrieval_graphs",
    "memory",
    "decisions",
    "logs",
)


def _ensure_refresh_workspace_initialized(workspace: Path) -> Path:
    """Create the refresh-owned workspace scaffold without overwriting data.

    Refresh owns the project-local ``.repobrain/`` knowledge directory. It
    should be safe to run on a clean project and safe to re-run on an existing
    project. If a required path is blocked by a regular file, fail before any
    destructive action instead of replacing user data.

    Args:
        workspace: Project root directory.

    Returns:
        Path to the ``.repobrain`` directory.

    Raises:
        RuntimeError: If the workspace cannot be initialized safely.
    """
    workspace = workspace.expanduser().resolve()
    if not workspace.exists() or not workspace.is_dir():
        raise RuntimeError(
            "Project initialization failed: workspace does not exist or is not a "
            f"directory: {workspace}"
        )

    rb_dir = knowledge_root(workspace)
    if rb_dir.exists() and not rb_dir.is_dir():
        raise RuntimeError(
            "Project initialization failed: .repobrain exists but is not a "
            f"directory: {rb_dir}. Move or remove that file, then rerun refresh."
        )
    rb_dir.mkdir(parents=True, exist_ok=True)

    for dirname in _REFRESH_INIT_DIRS:
        child = rb_dir / dirname
        if child.exists() and not child.is_dir():
            raise RuntimeError(
                "Project initialization failed: expected a directory at "
                f"{child}, but found a file. Move or remove that file, then "
                "rerun refresh."
            )
        child.mkdir(parents=True, exist_ok=True)

    manifest_path = rb_dir / "manifest.json"
    if manifest_path.exists() and not manifest_path.is_file():
        raise RuntimeError(
            "Project initialization failed: .repobrain/manifest.json exists "
            "but is not a file. Move or repair it, then rerun refresh."
        )
    if not manifest_path.exists():
        manifest = {
            "schema_version": _REPOBRAIN_MANIFEST_VERSION,
            "workspace": str(workspace),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "managed_by": "repobrain-refresh",
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return rb_dir

def _get_retry_config(max_retries: int | None = None, base_delay: float | None = None) -> tuple[int, float]:
    """Read retry configuration from environment variables.

    Args:
        max_retries: Override for max retries (uses env var if None).
        base_delay: Override for base delay in seconds (uses env var if None).

    Returns:
        Tuple of (max_retries, base_delay).
    """
    if max_retries is None:
        try:
            max_retries = max(0, int(os.environ.get("RB_REFRESH_RETRY_COUNT", "3")))
        except (ValueError, TypeError):
            max_retries = 3
    if base_delay is None:
        try:
            base_delay = max(0.0, float(os.environ.get("RB_REFRESH_RETRY_DELAY", "1.0")))
        except (ValueError, TypeError):
            base_delay = 1.0
    return max_retries, base_delay


def _is_retryable_error(exc: Exception) -> bool:
    """Check if an exception qualifies for retry.

    Retries on timeout, network errors, rate limits, and 5xx server errors.

    Args:
        exc: The exception to inspect.

    Returns:
        True if the error is retryable.
    """
    # A bare asyncio wait_for timeout has an empty str() and means OUR own
    # per-attempt deadline elapsed — the model is slow/stalling, not
    # transiently failing. Retrying the same full-length attempt just
    # multiplies wall-clock by (retries + 1) for the same outcome, which is
    # what made refresh appear to hang. Treat a *bare* timeout as NON-retryable
    # so the step falls back immediately. A provider-side timeout that carries
    # a message (e.g. "gateway time-out"/"504") falls through to the keyword
    # check below and stays retryable.
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) and not str(exc).strip():
        return False
    msg = str(exc).lower()
    retryable_keywords = (
        "timeout",
        "gateway time-out",
        "504",
        "connection",
        "network",
        "unreachable",
        "refused",
        "rate limit",
        "ratelimit",
        "429",
        "502",
        "503",
        "500",
        "service unavailable",
        "bad gateway",
        "internal server error",
    )
    return any(kw in msg for kw in retryable_keywords)


async def _run_with_retry(
    coro_fn,
    *args,
    max_retries: int | None = None,
    base_delay: float | None = None,
    timeout: float | None = None,
    context: str = "",
    **kwargs,
):
    """Run an async coroutine with retry and exponential backoff.

    Args:
        coro_fn: Async callable to execute.
        *args: Positional arguments for ``coro_fn``.
        max_retries: Maximum retry attempts (overrides env var).
        base_delay: Initial delay between retries in seconds (overrides env var).
        timeout: Per-attempt timeout in seconds (None or <=0 for no timeout).
        context: Human-readable context string for logging.
        **kwargs: Keyword arguments for ``coro_fn``.

    Returns:
        Result of ``coro_fn``.
    Raises:
        The last exception if all retries are exhausted.
    """
    max_retries, base_delay = _get_retry_config(max_retries, base_delay)
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            if timeout is not None and timeout > 0:
                return await asyncio.wait_for(coro_fn(*args, **kwargs), timeout=timeout)
            return await coro_fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            # Last attempt failed, re-raise
            if attempt >= max_retries:
                raise
            # Non-retryable error, re-raise immediately
            if not _is_retryable_error(exc):
                raise
            # Calculate delay (exponential backoff)
            delay = base_delay * (2 ** attempt)
            label = f" ({context})" if context else ""
            # Clean newlines from error message to prevent log format issues
            raw_msg = str(exc).replace('\n', ' ').replace('\r', '')[:150]
            error_msg = raw_msg or type(exc).__name__
            print(
                f"  ⚠ Attempt {attempt + 1} failed{label}: {error_msg}. Retrying in {delay}s...",
                file=sys.stderr,
            )
            await asyncio.sleep(delay)
    # Unreachable - loop always returns or raises



async def _refresh_pipeline_into_generation(
    workspace: Path,
    quick: bool = False,
    failed_only: bool = False,
) -> RefreshStatus:
    """Scan project and update .repobrain/conventions.md.

    Args:
        workspace: Project root directory.
        quick: If True, only scan files changed since last refresh.
        failed_only: If True, only re-run modules that failed or were
            partial in the previous refresh.

    Returns:
        Structured refresh status, including stage and module health.
    """
    from repobrain_engine.hub.scanner import (
        build_knowledge_graph,
        extract_structure,
        full_scan,
        quick_scan,
        render_knowledge_graph_markdown,
        render_knowledge_graph_mermaid,
    )
    from repobrain_engine.config import get_settings

    settings = get_settings()
    scan_only_raw = os.environ.get("RB_REFRESH_SCAN_ONLY")
    if scan_only_raw is None:
        refresh_scan_only = bool(settings.RB_REFRESH_SCAN_ONLY)
    else:
        refresh_scan_only = scan_only_raw.strip().lower() in {"1", "true", "yes"}
    model: "str | object | None" = None

    module_docs_changed = False
    host_runner_mode = False
    if not refresh_scan_only:
        from agents import set_tracing_disabled
        from repobrain_engine.hub.agents import create_model
        from repobrain_engine.hub.host_runner import is_host_runner_model

        set_tracing_disabled(True)
        model = create_model(settings)
        # When no API key is configured, create_model returns a HostRunnerModel
        # (local CLI). It can only drive tool-free, single-turn, no-handoff
        # agents, so tool-using / handoff refresh stages fall back gracefully.
        host_runner_mode = is_host_runner_model(model)
        if host_runner_mode:
            print(
                f"[0/3] No API key configured; using local host runner "
                f"'{settings.RB_HOST_RUNNER}' for LLM stages. Tool-using and "
                "handoff stages (conventions, git insights) will use "
                "deterministic fallbacks.",
                file=sys.stderr,
            )

    rb_dir = _ensure_refresh_workspace_initialized(workspace)
    sha_file = rb_dir / ".last_refresh_sha"
    current_sha = _get_head_sha(workspace)
    previous_status = _load_previous_refresh_status(rb_dir)
    refresh_status = RefreshStatus(
        refresh_run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
        overall_status="success",
        head_sha=current_sha,
    )

    scan_timeout = os.environ.get("RB_SCAN_TIMEOUT_SECONDS", "0")
    scan_max_files = os.environ.get("RB_SCAN_MAX_FILES", "unlimited")
    scan_sample_files = os.environ.get("RB_SCAN_SAMPLE_FILES", "(default)")
    scan_verbose = os.environ.get("RB_SCAN_VERBOSE", "1")
    print(
        (
            "[1/3] Scan config: "
            f"timeout={scan_timeout}, "
            f"max_files={scan_max_files}, "
            f"sample_files={scan_sample_files}, "
            f"verbose={scan_verbose}, "
            f"quick={quick}"
        ),
        file=sys.stderr,
    )

    print("[1/3] Scanning project...", file=sys.stderr)

    used_quick_scan = quick and sha_file.exists()
    if used_quick_scan:
        since_sha = sha_file.read_text(encoding="utf-8").strip()
        report = quick_scan(workspace, since_sha)
    else:
        report = full_scan(workspace)

    print("[1/3] Scan stage finished; preparing scan report...", file=sys.stderr)

    scan_report_path = rb_dir / "scan_report.json"
    scan_payload = _build_scan_payload(report)
    print("[1/3] Scan payload built; writing scan_report.json...", file=sys.stderr)
    scan_report_path.write_text(
        json.dumps(scan_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    refresh_status.stages["scan"] = "success"

    print(
        (
            "[1/3] Scan summary: "
            f"files={report.file_count}, "
            f"walked={getattr(report, 'walked_file_count', 0)}, "
            f"elapsed={getattr(report, 'scan_elapsed_seconds', 0.0):.2f}s, "
            f"timed_out={getattr(report, 'timed_out', False)}, "
            f"reason={getattr(report, 'scan_stopped_reason', '') or 'completed'}"
        ),
        file=sys.stderr,
    )
    samples = getattr(report, "scanned_file_samples", [])
    if samples:
        print("[1/3] Retrieved file samples:", file=sys.stderr)
        for rel in samples[:20]:
            print(f"  - {rel}", file=sys.stderr)
    print(f"[1/3] Scan report: {scan_report_path}", file=sys.stderr)

    conventions_content = ""
    quick_changed_files = list(getattr(report, "changed_files", []) or [])
    quick_has_no_changes = used_quick_scan and not quick_changed_files

    if quick_has_no_changes:
        print("[2/3] Quick mode: no changed files; preserving conventions.md.", file=sys.stderr)
        refresh_status.stages["conventions"] = "skipped"
    elif not refresh_scan_only:
        from repobrain_engine.hub.agents import (
            build_refresh_agent,
            build_single_turn_convention_agent,
        )

        prompt = _format_scan_report(report)

        # The default conventions swarm uses agent handoffs, which a host
        # runner cannot drive. In host-runner mode, collapse it into a single
        # tool-free, single-turn agent instead.
        if host_runner_mode:
            agent = build_single_turn_convention_agent(model)
        else:
            agent = build_refresh_agent(model or "")
        try:
            from agents import Runner
        except ImportError:
            raise ImportError(
                "OpenAI Agent SDK not found. Install: pip install repobrain-engine"
            ) from None

        print("[2/3] Analyzing with multi-agent swarm...", file=sys.stderr)

        # Conventions is a 3-hop handoff swarm (ScanAnalyst → ArchitectureReviewer
        # → ConventionWriter), so it needs ~3x a single call. Default is generous
        # enough for slow reasoning models; fast models finish well under it.
        refresh_timeout = float(os.environ.get("RB_REFRESH_AGENT_TIMEOUT_SECONDS", "300"))
        try:
            result = await _run_with_retry(
                Runner.run, agent, prompt,
                timeout=refresh_timeout,
                context="Conventions swarm",
            )
            conventions_content = result.final_output
            refresh_status.stages["conventions"] = "success"
        except Exception as exc:
            exc_msg = str(exc) or type(exc).__name__
            print(f"  ⚠ Conventions swarm failed: {exc_msg}. Using fallback.", file=sys.stderr)
            conventions_content = _build_fallback_conventions(report)
            _mark_stage_failure(
                refresh_status,
                stage="conventions",
                reason=str(exc),
                partial=True,
            )
    else:
        print("[2/3] Scan-only mode enabled; skipping LLM analysis.", file=sys.stderr)
        conventions_content = _build_fallback_conventions(report)
        refresh_status.stages["conventions"] = "skipped"

    if quick_has_no_changes:
        print("[3/8] Quick mode: keeping existing conventions.md.", file=sys.stderr)
    else:
        print("[3/8] Writing conventions.md...", file=sys.stderr)
        (rb_dir / "conventions.md").write_text(conventions_content, encoding="utf-8")

    # In quick mode the ScanReport only contains changed files, so
    # rebuilding structure / knowledge-graph / non-code indexes from it
    # would overwrite the full artifacts with near-empty content.
    # Skip these stages and keep the previous full-refresh output.
    if not quick:
        print("[4/8] Generating structure.md...", file=sys.stderr)
        structure_content = extract_structure(workspace)
        (rb_dir / "structure.md").write_text(structure_content, encoding="utf-8")
        refresh_status.stages["structure"] = "success"

        print("[5/8] Building knowledge graph artifacts...", file=sys.stderr)
        graph = build_knowledge_graph(workspace, report)
        (rb_dir / "knowledge_graph.json").write_text(
            json.dumps(graph, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _export_normalized_graph_store(rb_dir, graph)
        (rb_dir / "knowledge_graph.md").write_text(
            render_knowledge_graph_markdown(graph),
            encoding="utf-8",
        )
        (rb_dir / "knowledge_graph.mmd").write_text(
            render_knowledge_graph_mermaid(graph),
            encoding="utf-8",
        )
        refresh_status.stages["knowledge_graph"] = "success"

        print("[6/8] Writing document/data/media indexes...", file=sys.stderr)
        doc_index, data_overview, media_manifest = _build_non_code_indexes(report)
        (rb_dir / "document_index.md").write_text(doc_index, encoding="utf-8")
        (rb_dir / "data_overview.md").write_text(data_overview, encoding="utf-8")
        (rb_dir / "media_manifest.md").write_text(media_manifest, encoding="utf-8")
        refresh_status.stages["indexes"] = "success"
    else:
        print("[4-6/8] Quick mode: keeping existing structure/graph/index artifacts.", file=sys.stderr)
        refresh_status.stages["structure"] = "skipped"
        refresh_status.stages["knowledge_graph"] = "skipped"
        refresh_status.stages["indexes"] = "skipped"

    modules_filter: list[str] | None = None
    if failed_only:
        status_path = rb_dir / "status.json"
        if status_path.is_file():
            try:
                prev_status_raw = json.loads(status_path.read_text(encoding="utf-8"))
                prev_modules = prev_status_raw.get("modules", {})
                modules_filter = [
                    mod for mod, state in prev_modules.items()
                    if state in ("failed", "partial")
                ]
                if modules_filter:
                    print(
                        f"[7/8] Failed-only mode: re-running {len(modules_filter)} "
                        f"failed/partial modules...",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "[7/8] Failed-only mode: no failed/partial modules found. "
                        "Skipping module agents.",
                        file=sys.stderr,
                    )
            except Exception as exc:
                print(
                    f"  ⚠ Failed to load previous status: {exc}. "
                    "Running all modules.",
                    file=sys.stderr,
                )
        else:
            print(
                "[7/8] Failed-only mode: no previous status found. "
                "Running all modules.",
                file=sys.stderr,
            )

    if not refresh_scan_only:
        from repobrain_engine.hub.agents import (
            build_refresh_module_swarm_v2,
            build_refresh_git_agent,
        )
        from repobrain_engine.hub.scanner import detect_modules

        try:
            from agents import Runner
        except ImportError:
            raise ImportError(
                "OpenAI Agent SDK not found. Install: pip install repobrain-engine"
            ) from None

        module_timeout = float(os.environ.get("RB_MODULE_AGENT_TIMEOUT_SECONDS", "300"))

        # Skip module agents when failed-only mode has no modules to process
        if modules_filter is not None and not modules_filter:
            print("[7/8] No failed/partial modules to re-run. Skipping module agents.", file=sys.stderr)
            refresh_status.stages["module_docs"] = "skipped"
        elif quick_has_no_changes:
            print("  → 0 module groups affected", file=sys.stderr)
            print("[7/8] No module groups to run. Skipping module agents.", file=sys.stderr)
            refresh_status.stages["module_docs"] = "skipped"
            _write_refresh_status(rb_dir, refresh_status)
        else:
            print("[7/8] Module agents learning codebase...", file=sys.stderr)

            module_entries = build_refresh_module_swarm_v2(
                model, workspace, modules_filter=modules_filter
            )
            expected_modules = detect_modules(workspace)
            if modules_filter is not None:
                expected_modules = [m for m in expected_modules if m in modules_filter]

            affected_group_count: int | None = None
            if used_quick_scan:
                module_entries, affected_group_count = _filter_module_entries_for_changed_files(
                    workspace=workspace,
                    module_entries=module_entries,
                    changed_files=quick_changed_files,
                )
                affected_modules = {mod for mod, _ in module_entries}
                expected_modules = [m for m in expected_modules if m in affected_modules]
                if affected_group_count == 0:
                    print("  → 0 module groups affected", file=sys.stderr)

            module_entries = _filter_completed_groups_for_head(
                module_entries=module_entries,
                previous_status=previous_status,
                current_sha=current_sha,
                refresh_status=refresh_status,
            )
            expected_modules = [m for m in expected_modules if any(e[0] == m for e in module_entries)]

            mod_concurrency = int(os.environ.get("RB_REFRESH_CONCURRENCY", "8"))
            _mod_sem = asyncio.Semaphore(mod_concurrency)
            # Global API call semaphore: limits total concurrent LLM calls
            # across ALL modules and groups to avoid rate-limiting.
            api_concurrency = int(os.environ.get("RB_API_CONCURRENCY", "5"))
            _api_sem = asyncio.Semaphore(api_concurrency)
            status_write_lock = asyncio.Lock()
            agents_dir = rb_dir / "agents"
            agents_dir.mkdir(parents=True, exist_ok=True)
            # Keep legacy modules dir for backward compat (will be removed in Phase 5)
            modules_dir = rb_dir / "modules"
            modules_dir.mkdir(parents=True, exist_ok=True)

            async def _run_module(entry: tuple) -> tuple[str, str]:
                """Run one module's group agents and persist agent.md artifacts.

                For single-group modules: writes ``agents/{module}.md``.
                For multi-group modules: writes ``agents/{module}/group_N.md``
                (one per group, no merging).

                Args:
                    entry: Tuple of module name and group agent entries.

                Returns:
                    Module identifier and resulting health state.
                """
                async with _mod_sem:
                    mod_name, group_entries = entry
                    num_groups = len(group_entries)
                    print(
                        f"  → RefreshModule_{mod_name} ({num_groups} groups)...",
                        file=sys.stderr,
                    )

                    async def _run_sub(
                        group_name: str,
                        group,
                        sagent: object,
                    ) -> tuple[str, str | None, str | None]:
                        """Run one group agent and collect its Markdown output.

                        Args:
                            group_name: Group identifier within the module.
                            group: Module grouping object with pre-loaded files.
                            sagent: Agent instance for the group.

                        Returns:
                            Tuple of group name, Markdown output, and optional
                            failure reason.
                        """
                        try:
                            async with _api_sem:
                                res = await _run_with_retry(
                                    Runner.run,
                                    sagent,
                                    "Analyze the pre-loaded source code and produce a comprehensive Markdown knowledge document.",
                                    max_turns=3,
                                    timeout=module_timeout,
                                    context=f"{mod_name}/{group_name}",
                                )
                            md_output = str(res.final_output).strip()
                            if not md_output:
                                async with status_write_lock:
                                    _mark_group_completion(
                                        refresh_status,
                                        module=mod_name,
                                        group_name=group_name,
                                        state="failed",
                                        head_sha=current_sha,
                                    )
                                    _write_refresh_status(rb_dir, refresh_status)
                                return group_name, None, "empty output"
                            print(f"    ✓ {mod_name}/{group_name}", file=sys.stderr)
                            async with status_write_lock:
                                _mark_group_completion(
                                    refresh_status,
                                    module=mod_name,
                                    group_name=group_name,
                                    state="success",
                                    head_sha=current_sha,
                                )
                                _write_refresh_status(rb_dir, refresh_status)
                            return group_name, md_output, None
                        except Exception as exc:
                            failure_reason = str(exc)
                            print(f"    ⚠ {mod_name}/{group_name} failed: {failure_reason}", file=sys.stderr)
                            # Build a minimal fallback from file listing
                            fallback = _build_agent_md_fallback(mod_name, group_name, group)
                            async with status_write_lock:
                                _mark_group_completion(
                                    refresh_status,
                                    module=mod_name,
                                    group_name=group_name,
                                    state="partial",
                                    head_sha=current_sha,
                                )
                                _write_refresh_status(rb_dir, refresh_status)
                            return group_name, fallback, failure_reason

                    sub_results = await asyncio.gather(
                        *[_run_sub(gn, grp, sa) for gn, grp, sa in group_entries]
                    )

                    successes: list[tuple[str, str]] = []
                    for group_name, md_output, failure_reason in sub_results:
                        if md_output is None:
                            _mark_module_failure(
                                refresh_status,
                                module=mod_name,
                                group_name=group_name,
                                reason=failure_reason or "group returned no output",
                                state="failed",
                            )
                            continue
                        successes.append((group_name, md_output))
                        if failure_reason:
                            _mark_module_failure(
                                refresh_status,
                                module=mod_name,
                                group_name=group_name,
                                reason=failure_reason,
                                state="partial",
                            )

                    if not successes:
                        refresh_status.modules[mod_name] = "failed"
                        print(f"  ⚠ RefreshModule_{mod_name} produced no output", file=sys.stderr)
                        return mod_name, "failed"

                    # Write agent.md artifacts
                    _write_agent_md_artifacts(
                        agents_dir=agents_dir,
                        module=mod_name,
                        group_outputs=successes,
                    )
                    module_state = "success"
                    if any(reason is not None for _, _, reason in sub_results):
                        module_state = "partial"
                    refresh_status.modules[mod_name] = module_state
                    if current_sha:
                        refresh_status.module_head_shas[mod_name] = current_sha
                    _write_refresh_status(rb_dir, refresh_status)
                    print(f"  ✓ RefreshModule_{mod_name} done ({module_state})", file=sys.stderr)
                    return mod_name, module_state

            if not module_entries:
                print("[7/8] No module groups to run. Skipping module agents.", file=sys.stderr)
                refresh_status.stages["module_docs"] = "skipped"
                _write_refresh_status(rb_dir, refresh_status)
                module_results = []
            else:
                print(
                    f"  ▶ Running {len(module_entries)} modules "
                    f"(module_concurrency={mod_concurrency}, api_concurrency={api_concurrency})...",
                    file=sys.stderr,
                )
                module_results = await asyncio.gather(*[_run_module(e) for e in module_entries])
                module_docs_changed = True
            seen_modules = {name for name, _ in module_results}
            for module_name in expected_modules:
                if module_name in seen_modules:
                    continue
                refresh_status.modules[module_name] = "failed"
                _mark_module_failure(
                    refresh_status,
                    module=module_name,
                    group_name=None,
                    reason="module produced no group agents",
                    state="failed",
                )

            refresh_status.stages["module_docs"] = _aggregate_states(
                list(refresh_status.modules.values()),
                skipped_state="skipped",
            )

        if used_quick_scan and not module_docs_changed:
            print("[7/8] Quick mode: no module changes; skipping git insights.", file=sys.stderr)
            refresh_status.stages["git_insights"] = "skipped"
        else:
            print("  → RefreshGitAgent analyzing git history...", file=sys.stderr)
            if host_runner_mode:
                # The git agent relies on tools (git_log/git_diff/…), which a
                # host runner cannot invoke. Write the pre-extracted git data
                # deterministically instead of driving a tool-using agent.
                try:
                    _write_host_runner_git_insights(workspace)
                    print(
                        "  ✓ Wrote deterministic git insights (host-runner mode).",
                        file=sys.stderr,
                    )
                    refresh_status.stages["git_insights"] = "partial"
                except Exception as exc:
                    print(f"  ⚠ Git insights fallback failed: {exc}", file=sys.stderr)
                    _mark_stage_failure(
                        refresh_status,
                        stage="git_insights",
                        reason=str(exc),
                        partial=True,
                    )
            else:
                try:
                    git_agent = build_refresh_git_agent(model, workspace)
                    await _run_with_retry(
                        Runner.run,
                        git_agent,
                        "Analyze the project's git history and write your git insights document.",
                        max_turns=25,
                        timeout=module_timeout,
                        context="Git agent",
                    )
                    refresh_status.stages["git_insights"] = "success"
                except Exception as exc:
                    print(f"  ⚠ RefreshGitAgent failed: {exc}", file=sys.stderr)
                    _mark_stage_failure(
                        refresh_status,
                        stage="git_insights",
                        reason=str(exc),
                        partial=True,
                    )
    else:
        print("[7/8] Scan-only mode: module agents skipped.", file=sys.stderr)
        refresh_status.stages["module_docs"] = "skipped"
        refresh_status.stages["git_insights"] = "skipped"

    # -- Step 8: Generate map.md via Map Agent --
    if not refresh_scan_only and (not used_quick_scan or module_docs_changed):
        print("[8/8] Generating map.md via Map Agent...", file=sys.stderr)
        try:
            map_content = await _generate_map_md(workspace, model or "")
            (rb_dir / "map.md").write_text(map_content, encoding="utf-8")
            print("  ✓ map.md generated", file=sys.stderr)
            refresh_status.stages["module_registry"] = "success"

            # Also generate legacy module_registry for backward compat
            try:
                registry_entries = _build_module_registry_entries(workspace, refresh_status)
                (rb_dir / "module_registry.json").write_text(
                    json.dumps([entry.model_dump(mode="json") for entry in registry_entries], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                (rb_dir / "module_registry.md").write_text(
                    _render_module_registry_markdown(registry_entries),
                    encoding="utf-8",
                )
            except Exception:
                pass  # Legacy registry is best-effort
        except Exception as exc:
            print(f"  ⚠ Map Agent failed: {exc}. Using fallback.", file=sys.stderr)
            # Fallback: build map.md from file listing
            fallback_map = _build_fallback_map_md(workspace)
            (rb_dir / "map.md").write_text(fallback_map, encoding="utf-8")
            # Also try legacy registry
            try:
                registry_entries = _build_module_registry_entries(workspace, refresh_status)
                (rb_dir / "module_registry.json").write_text(
                    json.dumps([entry.model_dump(mode="json") for entry in registry_entries], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                (rb_dir / "module_registry.md").write_text(
                    _render_module_registry_markdown(registry_entries),
                    encoding="utf-8",
                )
            except Exception:
                pass
            _mark_stage_failure(
                refresh_status,
                stage="module_registry",
                reason=str(exc),
                partial=True,
            )
    else:
        if refresh_scan_only:
            print("[8/8] Scan-only mode: map generation skipped.", file=sys.stderr)
        else:
            print("[8/8] Quick mode: no module groups changed; keeping existing map.md.", file=sys.stderr)
        refresh_status.stages["module_registry"] = "skipped"

    if current_sha:
        sha_file.write_text(current_sha, encoding="utf-8")

    refresh_status.overall_status = _aggregate_states(
        list(refresh_status.stages.values()) + list(refresh_status.modules.values()),
        skipped_state="success",
    )
    _write_refresh_status(rb_dir, refresh_status)

    _print_artifact_status(
        rb_dir / "conventions.md",
        refresh_status.stages.get("conventions", "success"),
    )
    _print_artifact_status(
        rb_dir / "structure.md",
        refresh_status.stages.get("structure", "success"),
    )
    _print_artifact_status(
        rb_dir / "knowledge_graph.json",
        refresh_status.stages.get("knowledge_graph", "success"),
    )
    _print_artifact_status(
        rb_dir / "knowledge_graph.md",
        refresh_status.stages.get("knowledge_graph", "success"),
    )
    _print_artifact_status(
        rb_dir / "knowledge_graph.mmd",
        refresh_status.stages.get("knowledge_graph", "success"),
    )
    _print_artifact_status(
        rb_dir / "document_index.md",
        refresh_status.stages.get("indexes", "success"),
    )
    _print_artifact_status(
        rb_dir / "data_overview.md",
        refresh_status.stages.get("indexes", "success"),
    )
    _print_artifact_status(
        rb_dir / "media_manifest.md",
        refresh_status.stages.get("indexes", "success"),
    )
    _print_artifact_status(
        rb_dir / "module_registry.json",
        refresh_status.stages.get("module_registry", "success"),
    )
    _print_artifact_status(
        rb_dir / "module_registry.md",
        refresh_status.stages.get("module_registry", "success"),
    )
    agents_out_dir = rb_dir / "agents"
    if agents_out_dir.exists():
        agent_md_count = len(list(agents_out_dir.glob("*.md")))
        agent_dir_count = len([d for d in agents_out_dir.iterdir() if d.is_dir()])
        status_label = "Preserved" if refresh_status.stages.get("module_docs") == "skipped" else "Updated"
        print(f"{status_label} {agents_out_dir} ({agent_md_count} agent docs, {agent_dir_count} multi-group modules)")
    modules_dir = rb_dir / "modules"
    if modules_dir.exists():
        mod_count = len(list(modules_dir.glob("*.md")))
        facts_count = len(list(modules_dir.glob("*.facts.json")))
        if refresh_status.stages.get("module_registry") == "skipped":
            print(f"Preserved {modules_dir} ({mod_count} module docs, {facts_count} facts files)")
        else:
            print(f"Updated {modules_dir} ({mod_count} module docs, {facts_count} facts files)")
    print(
        f"Refresh status: {refresh_status.overall_status} "
        f"(exit code {refresh_status.exit_code})",
    )
    return refresh_status


async def _refresh_pipeline_generation_entry(
    workspace: Path,
    quick: bool = False,
    failed_only: bool = False,
) -> RefreshStatus:
    """Refresh knowledge through an atomically promoted generation.

    Full refresh builds the committed baseline.  Quick refresh delegates to
    RepoBrain's bounded ImpactPlanner/ImpactVerifier loop and never falls back
    to a full rebuild.
    """
    from repobrain_engine.hub.incremental import (
        ensure_clean_worktree,
        get_head_sha,
        incremental_refresh,
        initialize_full_generation_metadata,
    )
    from repobrain_engine.hub.storage import (
        create_generation,
        new_generation_id,
        promote_generation,
        remove_generation,
        use_knowledge_root,
    )

    workspace = workspace.expanduser().resolve()
    ensure_clean_worktree(workspace)
    if quick:
        return await incremental_refresh(
            workspace,
            failed_only=failed_only,
        )

    head_sha = get_head_sha(workspace)
    generation = new_generation_id(head_sha)
    generation_root = create_generation(
        workspace,
        generation,
        clone_active=False,
    )
    try:
        with use_knowledge_root(generation_root):
            status = await _refresh_pipeline_into_generation(
                workspace,
                quick=False,
                failed_only=failed_only,
            )
            if status.overall_status != "success":
                remove_generation(generation_root)
                return status
            snapshot = initialize_full_generation_metadata(
                workspace,
                generation_root,
                head_sha,
                status,
            )
        if get_head_sha(workspace) != head_sha:
            raise RuntimeError("HEAD changed during full refresh; no generation was promoted.")
        promote_generation(
            workspace,
            generation=generation,
            head_sha=head_sha,
            merkle_root=str(snapshot.get("merkle_root", "")),
        )
        return status
    except Exception:
        remove_generation(generation_root)
        raise


async def refresh_pipeline(
    workspace: Path,
    quick: bool = False,
    failed_only: bool = False,
) -> RefreshStatus:
    """Serialize and execute a generation-backed refresh."""
    from repobrain_engine.hub.storage import refresh_lock

    with refresh_lock(workspace):
        return await _refresh_pipeline_generation_entry(
            workspace,
            quick=quick,
            failed_only=failed_only,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mark_stage_failure(
    status: RefreshStatus,
    stage: str,
    reason: str,
    partial: bool,
) -> None:
    """Record a stage-level failure on the refresh status object.

    Args:
        status: Mutable refresh status object.
        stage: Stage identifier.
        reason: Human-readable failure reason.
        partial: Whether the stage is degraded instead of fully failed.
    """
    next_state = "partial" if partial else "failed"
    current_state = status.stages.get(stage)
    status.stages[stage] = _combine_states(current_state, next_state)
    status.failures.append(
        FailureRecord(
            stage=stage,
            reason=reason,
        )
    )


def _print_artifact_status(path: Path, stage_state: str) -> None:
    """Print whether a refresh artifact was updated or preserved.

    Args:
        path: Artifact path to report.
        stage_state: Stage state associated with the artifact.
    """
    if not path.exists():
        return
    if stage_state == "skipped":
        print(f"Preserved {path}")
        return
    print(f"Updated {path}")


def _mark_module_failure(
    status: RefreshStatus,
    module: str,
    group_name: str | None,
    reason: str,
    state: str,
) -> None:
    """Record a module- or group-level failure.

    Args:
        status: Mutable refresh status object.
        module: Module identifier.
        group_name: Optional group identifier.
        reason: Human-readable failure reason.
        state: Failure state, usually ``partial`` or ``failed``.
    """
    current_state = status.modules.get(module)
    status.modules[module] = _combine_states(current_state, state)
    status.failures.append(
        FailureRecord(
            stage="module_docs",
            module=module,
            group=group_name,
            reason=reason,
        )
    )


def _combine_states(
    current: str | None,
    new: str | None,
) -> str:
    """Combine two refresh states, keeping the more severe value.

    Args:
        current: Existing state, if any.
        new: Candidate next state.

    Returns:
        The more severe state.
    """
    priority = {
        None: 0,
        "skipped": 1,
        "success": 2,
        "partial": 3,
        "unresolved": 4,
        "failed": 5,
    }
    left = current if current in priority else "success"
    right = new if new in priority else "success"
    return left if priority[left] >= priority[right] else right


def _aggregate_states(
    states: list[str],
    skipped_state: str = "success",
) -> str:
    """Aggregate a list of refresh states into a single health status.

    Args:
        states: Stage or module states.
        skipped_state: Replacement state to use for ``skipped`` entries.

    Returns:
        Aggregate state.
    """
    normalized = [
        skipped_state if state == "skipped" else state
        for state in states
        if state
    ]
    if not normalized:
        return skipped_state
    if "failed" in normalized:
        return "failed"
    if "unresolved" in normalized:
        return "unresolved"
    if "partial" in normalized:
        return "partial"
    if "success" in normalized:
        return "success"
    return skipped_state


def _write_refresh_status(rb_dir: Path, status: RefreshStatus) -> None:
    """Persist refresh status to ``.repobrain/status.json``.

    Args:
        rb_dir: RepoBrain output directory.
        status: Refresh status document to serialize.
    """
    status_path = rb_dir / "status.json"
    status_path.write_text(
        json.dumps(status.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_previous_refresh_status(rb_dir: Path) -> dict[str, object]:
    """Load a previous status.json payload without requiring new fields."""
    status_path = rb_dir / "status.json"
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _group_key(module: str, group_name: str) -> str:
    """Return the stable status key for a module group."""
    return f"{module}/{group_name}"


def _mark_group_completion(
    status: RefreshStatus,
    *,
    module: str,
    group_name: str,
    state: str,
    head_sha: str | None,
) -> None:
    """Record completion state for a single module group."""
    key = _group_key(module, group_name)
    status.groups[key] = state
    if head_sha:
        status.head_sha = head_sha
        status.group_head_shas[key] = head_sha


def _previous_module_success_at_head(
    previous_status: dict[str, object],
    module: str,
    current_sha: str | None,
) -> bool:
    """Return whether a module already succeeded at the current HEAD."""
    if not current_sha:
        return False
    modules = previous_status.get("modules")
    if not isinstance(modules, dict) or modules.get(module) != "success":
        return False
    module_head_shas = previous_status.get("module_head_shas")
    if isinstance(module_head_shas, dict):
        return module_head_shas.get(module) == current_sha
    return previous_status.get("head_sha") == current_sha


def _previous_group_success_at_head(
    previous_status: dict[str, object],
    module: str,
    group_name: str,
    current_sha: str | None,
) -> bool:
    """Return whether a group already succeeded at the current HEAD."""
    if not current_sha:
        return False
    key = _group_key(module, group_name)
    groups = previous_status.get("groups")
    if isinstance(groups, dict):
        if groups.get(key) != "success":
            return False
        group_head_shas = previous_status.get("group_head_shas")
        if isinstance(group_head_shas, dict):
            return group_head_shas.get(key) == current_sha
        return previous_status.get("head_sha") == current_sha
    return _previous_module_success_at_head(previous_status, module, current_sha)


def _filter_completed_groups_for_head(
    *,
    module_entries: list,
    previous_status: dict[str, object],
    current_sha: str | None,
    refresh_status: RefreshStatus,
) -> list:
    """Remove groups already completed successfully at the same HEAD."""
    if not current_sha or not previous_status:
        return module_entries

    filtered_entries: list = []
    for module, group_entries in module_entries:
        remaining_groups: list = []
        skipped_groups = 0
        for group_name, group, agent in group_entries:
            if _previous_group_success_at_head(
                previous_status,
                module,
                group_name,
                current_sha,
            ):
                skipped_groups += 1
                _mark_group_completion(
                    refresh_status,
                    module=module,
                    group_name=group_name,
                    state="success",
                    head_sha=current_sha,
                )
                continue
            remaining_groups.append((group_name, group, agent))
        if remaining_groups:
            filtered_entries.append((module, remaining_groups))
        elif skipped_groups:
            refresh_status.modules[module] = "success"
            refresh_status.module_head_shas[module] = current_sha
    return filtered_entries


def _filter_module_entries_for_changed_files(
    *,
    workspace: Path,
    module_entries: list,
    changed_files: list[str],
) -> tuple[list, int]:
    """Keep only module groups affected by quick-scan changed files."""
    changed = {path.replace("\\", "/").strip() for path in changed_files if path.strip()}
    if not changed:
        return [], 0

    filtered_entries: list = []
    affected_count = 0
    for module, group_entries in module_entries:
        module_path_prefix = _module_path_prefix(workspace, module)
        module_has_unmatched_change = any(
            module_path_prefix
            and (rel == module_path_prefix or rel.startswith(f"{module_path_prefix}/"))
            for rel in changed
        )
        kept_groups: list = []
        matched_any_group = False
        for group_name, group, agent in group_entries:
            group_files = {
                getattr(source_file, "rel_path", "").replace("\\", "/")
                for source_file in getattr(group, "files", [])
            }
            if group_files & changed:
                matched_any_group = True
                kept_groups.append((group_name, group, agent))
        if module_has_unmatched_change and not matched_any_group:
            kept_groups = list(group_entries)
        if kept_groups:
            affected_count += len(kept_groups)
            filtered_entries.append((module, kept_groups))
    return filtered_entries, affected_count


def _module_path_prefix(workspace: Path, module: str) -> str | None:
    """Resolve a module id to a workspace-relative path prefix."""
    try:
        from repobrain_engine.hub.scanner import resolve_module_path

        module_path = resolve_module_path(workspace, module)
        rel_path = module_path.relative_to(workspace).as_posix()
    except Exception:
        return module if module else None
    return "" if rel_path == "." else rel_path


def _extract_json_payload(output: object) -> dict[str, object]:
    """Extract the first JSON object from a model output payload.

    Args:
        output: Raw agent output.

    Returns:
        Parsed JSON object.

    Raises:
        ValueError: If no JSON object can be extracted.
    """
    if isinstance(output, dict):
        return output
    text = str(output).strip()
    if not text:
        raise ValueError("group facts output is empty")

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("group facts output does not contain JSON")
    return json.loads(text[start : end + 1])


def _parse_group_facts_output(
    output: object,
    module: str,
    group_name: str,
) -> GroupFactsDocument:
    """Parse model output into a structured group facts document.

    Args:
        output: Raw model output.
        module: Owning module identifier.
        group_name: Group identifier.

    Returns:
        Parsed and normalized group facts document.
    """
    payload = _extract_json_payload(output)
    payload["module"] = module
    payload["group_name"] = group_name
    document = GroupFactsDocument.model_validate(payload)
    normalized_claims: list[ModuleClaim] = []
    for claim in document.claims:
        claim.claim_id = _sanitize_claim_id(
            claim.claim_id or f"{module}.{group_name}.{claim.claim_type}"
        )
        claim.source_files = _dedupe_strings(claim.source_files or document.source_files)
        claim.evidence = _dedupe_evidence(claim.evidence)
        normalized_claims.append(claim)
    document.claims = normalized_claims
    document.source_files = _dedupe_strings(document.source_files)
    return document


def _build_group_facts_fallback(
    module: str,
    group_name: str,
    group,
) -> GroupFactsDocument:
    """Build deterministic fallback facts for a failed group agent.

    Args:
        module: Module identifier.
        group_name: Group identifier.
        group: File grouping object from ``module_grouping``.

    Returns:
        Deterministic group facts document.
    """
    source_files = [source_file.rel_path for source_file in group.files]
    claims: list[ModuleClaim] = []
    for source_file in group.files:
        claims.extend(_extract_symbol_claims(source_file))
    return GroupFactsDocument(
        module=module,
        group_name=group_name,
        source_files=_dedupe_strings(source_files),
        claims=claims[:18],
    )


def _extract_symbol_claims(source_file) -> list[ModuleClaim]:
    """Extract lightweight fallback claims from a source file.

    Args:
        source_file: Source file object from ``module_grouping``.

    Returns:
        Structured claims for top-level definitions and dependencies.
    """
    suffix = Path(source_file.rel_path).suffix.lower()
    if suffix == ".py":
        return _extract_python_symbol_claims(source_file)
    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        return _extract_js_symbol_claims(source_file)
    return []


def _extract_python_symbol_claims(source_file) -> list[ModuleClaim]:
    """Extract fallback claims from a Python source file.

    .. deprecated::
        Legacy function kept for backward compatibility with existing
        ``modules/*.facts.json`` artifacts. New refresh pipeline uses
        LLM-based analysis (``agents/*.md``) instead.

    Args:
        source_file: Source file object from ``module_grouping``.

    Returns:
        Claims derived from top-level definitions and imports.
    """
    import ast  # noqa: F811 — lazy import for legacy path only
    claims: list[ModuleClaim] = []
    rel_path = source_file.rel_path
    lines = source_file.content.splitlines()
    try:
        tree = ast.parse(source_file.content, filename=rel_path)
    except SyntaxError:
        return claims

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbol_name = node.name
            start_line = int(getattr(node, "lineno", 1))
            end_line = int(getattr(node, "end_lineno", start_line))
            claims.append(
                ModuleClaim(
                    claim_id=_sanitize_claim_id(f"{rel_path}.{symbol_name}.definition"),
                    claim_type="symbol_definition",
                    statement=f"`{symbol_name}` is defined in `{rel_path}`.",
                    importance="low",
                    source_files=[rel_path],
                    evidence=[
                        EvidenceSpan(
                            file=rel_path,
                            start_line=start_line,
                            end_line=end_line,
                            excerpt=_slice_excerpt(lines, start_line, end_line),
                        )
                    ],
                )
            )
        elif isinstance(node, ast.Import):
            for alias in node.names[:3]:
                imported_name = alias.name
                claims.append(
                    ModuleClaim(
                        claim_id=_sanitize_claim_id(f"{rel_path}.{imported_name}.dependency"),
                        claim_type="dependency",
                        statement=f"`{rel_path}` imports `{imported_name}`.",
                        importance="low",
                        source_files=[rel_path],
                        evidence=[
                            EvidenceSpan(
                                file=rel_path,
                                start_line=int(getattr(node, "lineno", 1)),
                                end_line=int(
                                    getattr(node, "end_lineno", getattr(node, "lineno", 1))
                                ),
                                excerpt=_slice_excerpt(
                                    lines,
                                    int(getattr(node, "lineno", 1)),
                                    int(
                                        getattr(
                                            node,
                                            "end_lineno",
                                            getattr(node, "lineno", 1),
                                        )
                                    ),
                                ),
                            )
                        ],
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            imported_from = node.module or "."
            claims.append(
                ModuleClaim(
                    claim_id=_sanitize_claim_id(f"{rel_path}.{imported_from}.dependency"),
                    claim_type="dependency",
                    statement=f"`{rel_path}` depends on `{imported_from}`.",
                    importance="low",
                    source_files=[rel_path],
                    evidence=[
                        EvidenceSpan(
                            file=rel_path,
                            start_line=int(getattr(node, "lineno", 1)),
                            end_line=int(
                                getattr(node, "end_lineno", getattr(node, "lineno", 1))
                            ),
                            excerpt=_slice_excerpt(
                                lines,
                                int(getattr(node, "lineno", 1)),
                                int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                            ),
                        )
                    ],
                )
            )
    return claims


def _extract_js_symbol_claims(source_file) -> list[ModuleClaim]:
    """Extract fallback claims from a JS/TS source file.

    Args:
        source_file: Source file object from ``module_grouping``.

    Returns:
        Claims derived from exports and imports.
    """
    claims: list[ModuleClaim] = []
    rel_path = source_file.rel_path
    lines = source_file.content.splitlines()

    export_patterns = [
        re.compile(r"^\s*export\s+(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\s*export\s+class\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\s*export\s+(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\s*export\s+default\s+function\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\s*export\s+default\s+class\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ]
    import_pattern = re.compile(r"""^\s*import\s+.+?\s+from\s+['"](.+?)['"]""")

    for line_no, line in enumerate(lines, start=1):
        for pattern in export_patterns:
            match = pattern.search(line)
            if not match:
                continue
            symbol_name = match.group(1)
            claims.append(
                ModuleClaim(
                    claim_id=_sanitize_claim_id(f"{rel_path}.{symbol_name}.definition"),
                    claim_type="symbol_definition",
                    statement=f"`{symbol_name}` is exported from `{rel_path}`.",
                    importance="low",
                    source_files=[rel_path],
                    evidence=[
                        EvidenceSpan(
                            file=rel_path,
                            start_line=line_no,
                            end_line=line_no,
                            excerpt=line.strip(),
                        )
                    ],
                )
            )
            break

        import_match = import_pattern.search(line)
        if import_match:
            imported_from = import_match.group(1)
            claims.append(
                ModuleClaim(
                    claim_id=_sanitize_claim_id(f"{rel_path}.{imported_from}.dependency"),
                    claim_type="dependency",
                    statement=f"`{rel_path}` imports `{imported_from}`.",
                    importance="low",
                    source_files=[rel_path],
                    evidence=[
                        EvidenceSpan(
                            file=rel_path,
                            start_line=line_no,
                            end_line=line_no,
                            excerpt=line.strip(),
                        )
                    ],
                )
            )
    return claims


def _sanitize_claim_id(raw_claim_id: str) -> str:
    """Normalize claim identifiers for stable merging.

    Args:
        raw_claim_id: Proposed claim identifier.

    Returns:
        Sanitized identifier safe for JSON merging.
    """
    normalized = raw_claim_id.strip().lower()
    normalized = re.sub(r"[^a-z0-9._-]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("._") or "claim"


def _slice_excerpt(
    lines: list[str],
    start_line: int,
    end_line: int,
) -> str:
    """Slice a bounded excerpt from source lines.

    Args:
        lines: Source file split into lines.
        start_line: Inclusive 1-based start line.
        end_line: Inclusive 1-based end line.

    Returns:
        Joined excerpt string.
    """
    bounded_end = min(len(lines), max(start_line, end_line))
    bounded_start = max(1, start_line)
    window_end = min(bounded_end, bounded_start + 19)
    return "\n".join(lines[bounded_start - 1 : window_end]).strip()


def _merge_group_facts(
    module: str,
    group_docs: list[GroupFactsDocument],
) -> ModuleFactsDocument:
    """Merge multiple group fact documents into one module artifact.

    Args:
        module: Module identifier.
        group_docs: Facts extracted from module groups.

    Returns:
        Deterministic merged module facts document.
    """
    merged_claims: dict[str, ModuleClaim] = {}
    all_source_files: list[str] = []
    groups: list[str] = []

    for document in group_docs:
        groups.append(document.group_name)
        all_source_files.extend(document.source_files)
        for claim in document.claims:
            claim_id = _sanitize_claim_id(claim.claim_id)
            if claim_id not in merged_claims:
                merged_claims[claim_id] = claim.model_copy(deep=True)
                merged_claims[claim_id].claim_id = claim_id
                continue

            existing = merged_claims[claim_id]
            existing.importance = _max_importance(existing.importance, claim.importance)
            existing.source_files = _dedupe_strings(existing.source_files + claim.source_files)
            existing.evidence = _dedupe_evidence(existing.evidence + claim.evidence)
            if len(claim.statement) > len(existing.statement):
                existing.statement = claim.statement
            if claim.claim_type != existing.claim_type and existing.claim_type == "symbol_definition":
                existing.claim_type = claim.claim_type

    ordered_claims = sorted(
        merged_claims.values(),
        key=lambda claim: (
            -_importance_rank(claim.importance),
            claim.claim_type,
            claim.claim_id,
        ),
    )
    return ModuleFactsDocument(
        module=module,
        groups=_dedupe_strings(groups),
        source_files=_dedupe_strings(all_source_files),
        claims=ordered_claims,
    )


def _importance_rank(importance: str) -> int:
    """Rank claim importance for sorting and merging.

    Args:
        importance: Claim importance label.

    Returns:
        Higher value means higher importance.
    """
    ranking = {"high": 3, "medium": 2, "low": 1}
    return ranking.get(importance, 1)


def _max_importance(left: str, right: str) -> str:
    """Return the more important of two claim importance levels.

    Args:
        left: First importance label.
        right: Second importance label.

    Returns:
        Higher-priority importance label.
    """
    return left if _importance_rank(left) >= _importance_rank(right) else right


def _dedupe_strings(items: list[str]) -> list[str]:
    """Deduplicate strings while preserving order.

    Args:
        items: Candidate strings.

    Returns:
        Deduplicated strings.
    """
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _dedupe_evidence(evidence: list[EvidenceSpan]) -> list[EvidenceSpan]:
    """Deduplicate evidence spans while preserving order.

    Args:
        evidence: Candidate evidence spans.

    Returns:
        Deduplicated evidence spans.
    """
    seen: set[tuple[str, int, int, str]] = set()
    result: list[EvidenceSpan] = []
    for item in evidence:
        key = (item.file, item.start_line, item.end_line, item.excerpt)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _write_agent_md_artifacts(
    agents_dir: Path,
    module: str,
    group_outputs: list[tuple[str, str]],
) -> None:
    """Write agent.md Markdown artifacts for a module.

    For single-group modules: writes ``agents/{module}.md``.
    For multi-group modules: writes ``agents/{module}/group_name.md``
    (one per group, no merging — each is a standalone knowledge document).

    Args:
        agents_dir: The ``.repobrain/agents`` directory.
        module: Module identifier.
        group_outputs: List of ``(group_name, markdown_content)`` tuples.
    """
    if len(group_outputs) == 1:
        # Single group → single file
        _group_name, md_content = group_outputs[0]
        out_path = agents_dir / f"{module}.md"
        out_path.write_text(md_content, encoding="utf-8")
    else:
        # Multiple groups → directory with one file per group
        mod_dir = agents_dir / module
        mod_dir.mkdir(parents=True, exist_ok=True)
        for group_name, md_content in group_outputs:
            safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", group_name)
            out_path = mod_dir / f"{safe_name}.md"
            out_path.write_text(md_content, encoding="utf-8")


def _write_host_runner_git_insights(workspace: Path) -> Path:
    """Write a deterministic git insights doc for host-runner mode.

    The normal git stage drives a tool-using agent (git_log/git_diff/…),
    which a :class:`HostRunnerModel` cannot invoke. This writes the
    pre-extracted git data straight to ``.repobrain/modules/_git_insights.md``
    — the same artifact the agent would have produced — so downstream Q&A
    still has git context, just without LLM narration.

    Args:
        workspace: Project root directory.

    Returns:
        Path to the written git insights document.
    """
    from repobrain_engine.hub.scanner import extract_git_insights

    git_data = extract_git_insights(workspace)
    modules_dir = knowledge_root(workspace) / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)
    doc_path = modules_dir / "_git_insights.md"
    content = (
        "# Git Insights\n\n"
        "_Generated in host-runner mode without an API key. This is the "
        "pre-extracted git data; no LLM narration was applied._\n\n"
        f"{git_data.strip()}\n"
    )
    doc_path.write_text(content, encoding="utf-8")
    return doc_path


def _build_agent_md_fallback(
    module: str,
    group_name: str,
    group,
) -> str:
    """Build a minimal fallback agent.md when the LLM fails.

    Lists source files with basic metadata (path, language, line count).

    Args:
        module: Module identifier.
        group_name: Group identifier.
        group: File grouping object from ``module_grouping``.

    Returns:
        Markdown string with file listing.
    """
    lines = [
        AGENT_MD_FALLBACK_MARKER,
        f"# Module: {module} — Group: {group_name}",
        "",
        AGENT_MD_FALLBACK_SENTINEL,
        "",
        "## Source Files",
        "",
    ]
    for source_file in group.files:
        line_count = source_file.content.count("\n") + 1
        lines.append(
            f"- `{source_file.rel_path}` ({source_file.language}, {line_count} lines)"
        )
    return "\n".join(lines) + "\n"


def _write_module_artifacts(
    modules_dir: Path,
    document: ModuleFactsDocument,
) -> None:
    """Write deterministic JSON and Markdown artifacts for a module.

    Args:
        modules_dir: Module artifact directory.
        document: Module facts to persist.
    """
    facts_path = modules_dir / f"{document.module}.facts.json"
    markdown_path = modules_dir / f"{document.module}.md"
    facts_path.write_text(
        json.dumps(document.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(
        _render_module_markdown(document),
        encoding="utf-8",
    )


def _render_module_markdown(document: ModuleFactsDocument) -> str:
    """Render a human-readable Markdown view of module facts.

    Args:
        document: Module facts document.

    Returns:
        Markdown summary for human inspection.
    """
    lines = [
        f"# Module: {document.module}",
        "",
        f"- Groups: {', '.join(document.groups) if document.groups else '(none)'}",
        f"- Source files: {len(document.source_files)}",
        f"- Claims: {len(document.claims)}",
        f"- Generated at: {document.generated_at}",
        "",
    ]
    if document.source_files:
        lines.append("## Source Files")
        lines.append("")
        for rel_path in document.source_files[:20]:
            lines.append(f"- `{rel_path}`")
        if len(document.source_files) > 20:
            lines.append(f"- ... ({len(document.source_files) - 20} more)")
        lines.append("")

    claim_groups: dict[str, list[ModuleClaim]] = {}
    for claim in document.claims:
        claim_groups.setdefault(claim.claim_type, []).append(claim)

    for claim_type in sorted(claim_groups):
        lines.append(f"## {claim_type.replace('_', ' ').title()}")
        lines.append("")
        for claim in claim_groups[claim_type]:
            lines.append(f"- [{claim.importance}] {claim.statement}")
            for evidence in claim.evidence[:2]:
                lines.append(
                    f"  - Evidence: `{evidence.file}:{evidence.start_line}-{evidence.end_line}`"
                )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _build_module_registry_entries(
    workspace: Path,
    status: RefreshStatus,
) -> list[ModuleRegistryEntry]:
    """Build lightweight module routing entries from facts artifacts.

    Args:
        workspace: Project root directory.
        status: Refresh status document for module health.

    Returns:
        Sorted module registry entries.
    """
    from repobrain_engine.hub.scanner import (
        detect_modules,
        list_root_module_files,
        resolve_module_path,
    )

    modules_dir = knowledge_root(workspace) / "modules"
    entries: list[ModuleRegistryEntry] = []
    for module_name in detect_modules(workspace):
        facts_path = modules_dir / f"{module_name}.facts.json"
        if facts_path.is_file():
            document = ModuleFactsDocument.model_validate_json(
                facts_path.read_text(encoding="utf-8")
            )
            keywords = _extract_registry_keywords(document)
            top_paths = document.source_files[:8]
            summary = _build_registry_summary(document)
        else:
            module_path = resolve_module_path(workspace, module_name)
            if module_name == WORKSPACE_ROOT_MODULE_ID:
                top_paths = [path.name for path in list_root_module_files(workspace)[:8]]
            else:
                top_paths = _list_module_files(module_path).splitlines()[:8]
            keywords = _tokenize_text(_module_display_name(module_name))
            if module_name == WORKSPACE_ROOT_MODULE_ID:
                for rel_path in top_paths:
                    keywords.extend(_tokenize_text(rel_path.replace(".", " ")))
            summary = _module_display_name(module_name)

        entries.append(
            ModuleRegistryEntry(
                module=module_name,
                keywords=keywords[:12],
                top_paths=[
                    path.removeprefix("- ").strip()
                    for path in top_paths
                    if path.strip()
                ],
                status=status.modules.get(module_name, "failed"),
                summary=summary,
            )
        )
    return sorted(entries, key=lambda entry: entry.module)


def _extract_registry_keywords(document: ModuleFactsDocument) -> list[str]:
    """Extract routing keywords from a module facts document.

    Args:
        document: Module facts document.

    Returns:
        Deduplicated routing keywords.
    """
    keywords: list[str] = []
    keywords.extend(_tokenize_text(_module_display_name(document.module)))
    for claim in document.claims[:20]:
        keywords.append(claim.claim_type.replace("_", " "))
        keywords.extend(_tokenize_text(claim.statement))
    for rel_path in document.source_files[:10]:
        keywords.extend(_tokenize_text(rel_path.replace("/", " ").replace(".", " ")))
    return _dedupe_strings(keywords)


def _build_registry_summary(document: ModuleFactsDocument) -> str:
    """Build a short human-readable module summary from top claims.

    Args:
        document: Module facts document.

    Returns:
        Short summary sentence.
    """
    top_claims = sorted(
        document.claims,
        key=lambda claim: (-_importance_rank(claim.importance), claim.claim_id),
    )[:2]
    if not top_claims:
        return _module_display_name(document.module)
    return " ".join(claim.statement for claim in top_claims)


def _render_module_registry_markdown(entries: list[ModuleRegistryEntry]) -> str:
    """Render registry entries into a compact Markdown overview.

    Args:
        entries: Machine-readable registry entries.

    Returns:
        Human-readable Markdown registry.
    """
    lines = ["# Module Registry", ""]
    for entry in entries:
        tags = ", ".join(entry.keywords[:8]) if entry.keywords else entry.summary
        lines.append(f"- **{_module_display_name(entry.module)}** ({entry.status}): {tags}")
        if entry.summary:
            lines.append(f"  Summary: {entry.summary}")
    return "\n".join(lines).strip() + "\n"


def _module_display_name(module_name: str) -> str:
    """Return a human-readable module label for docs and routing summaries.

    Args:
        module_name: Internal module identifier.

    Returns:
        Display-safe module label.
    """
    if module_name == WORKSPACE_ROOT_MODULE_ID:
        return "workspace root"
    return module_name.replace("_", " ")


def _tokenize_text(text: str) -> list[str]:
    """Tokenize free-form text into routing-friendly lowercase keywords.

    Args:
        text: Input text.

    Returns:
        Lowercase keyword tokens with lightweight stop-word filtering.
    """
    stop_words = {
        "the", "and", "for", "with", "from", "this", "that",
        "into", "uses", "used", "module", "project", "file",
        "files", "code", "data", "path", "paths", "json",
        "python", "function", "class",
    }
    tokens = re.findall(r"[a-zA-Z0-9_]{3,}", text.lower())
    return [token for token in tokens if token not in stop_words]

def _format_scan_report(report) -> str:
    """Format a ScanReport into a prompt string."""
    lines = [f"Project root: {report.root}"]

    if report.languages:
        lines.append("\nLanguages (file count):")
        for lang, count in list(report.languages.items())[:10]:
            lines.append(f"  - {lang}: {count}")

    if report.frameworks:
        lines.append("\nFrameworks/Tools detected:")
        for fw in report.frameworks:
            lines.append(f"  - {fw}")

    if report.top_dirs:
        lines.append(f"\nTop-level directories: {', '.join(report.top_dirs)}")

    lines.append(f"\nTotal files: {report.file_count}")
    lines.append(f"Scan elapsed seconds: {getattr(report, 'scan_elapsed_seconds', 0.0):.2f}")
    lines.append(f"Scan timed out: {getattr(report, 'timed_out', False)}")
    if getattr(report, "scan_stopped_reason", ""):
        lines.append(f"Scan stop reason: {report.scan_stopped_reason}")
    lines.append(f"Has tests: {report.has_tests}")
    lines.append(f"Has CI: {report.has_ci}")
    lines.append(f"Has Docker: {report.has_docker}")
    if getattr(report, "type_distribution", None):
        lines.append("\nFile types:")
        for ftype, count in report.type_distribution.items():
            lines.append(f"  - {ftype}: {count}")
    lines.append(f"Unreadable files: {getattr(report, 'unreadable_files', 0)}")
    lines.append(f"Oversized files: {getattr(report, 'oversized_files', 0)}")

    if report.readme_snippet:
        lines.append(f"\nREADME excerpt:\n{report.readme_snippet}")

    samples = getattr(report, "scanned_file_samples", [])
    if samples:
        lines.append("\nScanned file samples:")
        for rel in samples[:30]:
            lines.append(f"  - {rel}")

    if getattr(report, "config_contents", None):
        lines.append("\n--- Configuration files (actual content) ---")
        for name, content in report.config_contents.items():
            lines.append(f"\n### {name}\n```\n{content}\n```")

    if getattr(report, "entry_points", None):
        lines.append("\n--- Entry point files (first lines) ---")
        for name, content in report.entry_points.items():
            lines.append(f"\n### {name}\n```\n{content}\n```")

    git_summary = getattr(report, "git_summary", "")
    if git_summary:
        lines.append(f"\n--- Git activity ---\n{git_summary}")

    return "\n".join(lines)


def _export_normalized_graph_store(rb_dir: Path, graph: dict[str, Any]) -> None:
    """Export knowledge graph into normalized JSONL graph store files.

    Args:
        rb_dir: The ``.repobrain`` directory path.
        graph: The in-memory knowledge graph payload.
    """
    graph_dir = rb_dir / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(edges, list):
        edges = []

    retrieval_id = str(graph.get("created_at_utc", "")) or "refresh-knowledge-graph"
    tool_name = "refresh_pipeline"

    nodes_lines: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nodes_lines.append(
            json.dumps(
                {
                    "schema": "repobrain-graph-node-v1",
                    "retrieval_id": retrieval_id,
                    "tool_name": tool_name,
                    "node": node,
                },
                ensure_ascii=False,
            )
        )
    (graph_dir / "nodes.jsonl").write_text(
        ("\n".join(nodes_lines) + "\n") if nodes_lines else "",
        encoding="utf-8",
    )

    edges_lines: list[str] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        edges_lines.append(
            json.dumps(
                {
                    "schema": "repobrain-graph-edge-v1",
                    "retrieval_id": retrieval_id,
                    "tool_name": tool_name,
                    "edge": edge,
                },
                ensure_ascii=False,
            )
        )
    (graph_dir / "edges.jsonl").write_text(
        ("\n".join(edges_lines) + "\n") if edges_lines else "",
        encoding="utf-8",
    )


def _get_head_sha(workspace: Path) -> str | None:
    """Get the current HEAD commit SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(workspace),
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def _build_non_code_indexes(report) -> tuple[str, str, str]:
    """Build document/data/media markdown indexes from scan metadata."""
    docs: list[str] = []
    data: list[str] = []
    media: list[str] = []
    for rel, meta in getattr(report, "file_metadata", {}).items():
        ftype = str(meta.get("type", "other"))
        size = int(meta.get("size", 0))
        mime = str(meta.get("mime", "unknown"))
        line = f"- {rel} ({size} bytes, {mime})"
        if ftype == "documentation":
            docs.append(line)
        elif ftype == "data":
            data.append(line)
        elif ftype == "media":
            media.append(line)

    def _render(title: str, items: list[str]) -> str:
        if not items:
            return f"# {title}\n\n(none)\n"
        body = "\n".join(items[:200])
        if len(items) > 200:
            body += f"\n- ... ({len(items) - 200} more)"
        return f"# {title}\n\n{body}\n"

    return (
        _render("Document Index", docs),
        _render("Data Overview", data),
        _render("Media Manifest", media),
    )


def _compute_affected_modules(
    report,
    module_ids: list[str],
) -> set[str] | None:
    """Determine which modules were touched by changed files in a quick scan.

    Returns ``None`` if the impact cannot be determined (e.g. no file
    metadata), in which case the caller should run all modules.

    Args:
        report: ScanReport from quick_scan.
        module_ids: List of known module identifiers.

    Returns:
        Set of affected module identifiers, or None.
    """
    metadata = getattr(report, "file_metadata", None)
    samples = getattr(report, "scanned_file_samples", None)
    changed_paths = list(metadata.keys()) if metadata else (samples or [])
    if not changed_paths:
        return None

    affected: set[str] = set()
    for rel_path in changed_paths:
        parts = rel_path.replace("\\", "/").split("/")
        if not parts:
            continue
        # Match against module IDs — check both simple ("cli") and
        # two-level ("engine_hub") patterns.
        top = parts[0]
        for mid in module_ids:
            if mid == top:
                affected.add(mid)
            elif mid.startswith(f"{top}_") and len(parts) > 1:
                # Two-level: "engine_hub" matches "engine/repobrain_engine/hub/..."
                # Heuristic: if any path component matches the suffix, it's affected.
                suffix = mid.split("_", 1)[1]
                if suffix in parts:
                    affected.add(mid)
    return affected


def _build_scan_payload(report) -> dict[str, object]:
    """Build a JSON-serializable scan payload for traceability."""
    return {
        "root": str(getattr(report, "root", "")),
        "file_count": int(getattr(report, "file_count", 0)),
        "walked_file_count": int(getattr(report, "walked_file_count", 0)),
        "languages": dict(getattr(report, "languages", {}) or {}),
        "frameworks": list(getattr(report, "frameworks", []) or []),
        "type_distribution": dict(getattr(report, "type_distribution", {}) or {}),
        "timed_out": bool(getattr(report, "timed_out", False)),
        "scan_elapsed_seconds": float(getattr(report, "scan_elapsed_seconds", 0.0)),
        "scan_stopped_reason": str(getattr(report, "scan_stopped_reason", "") or ""),
        "scanned_file_samples": list(getattr(report, "scanned_file_samples", []) or []),
        "changed_files": list(getattr(report, "changed_files", []) or []),
        "unreadable_files": int(getattr(report, "unreadable_files", 0)),
        "oversized_files": int(getattr(report, "oversized_files", 0)),
        "binary_files": int(getattr(report, "binary_files", 0)),
    }


async def _generate_map_md(workspace: Path, model: str) -> str:
    """Generate map.md by feeding agent.md files to a Map Agent.

    Reads all ``agents/*.md`` files and passes them to a Map Agent LLM
    that produces a concise routing index.  If the total content exceeds
    a reasonable context size, groups are fed to multiple Map Agents and
    their outputs are concatenated.

    Args:
        workspace: Project root directory.
        model: LLM model identifier.

    Returns:
        Markdown content for map.md.
    """
    from repobrain_engine.hub.agents import build_map_agent

    try:
        from agents import Runner
    except ImportError:
        raise ImportError(
            "OpenAI Agent SDK not found. Install: pip install repobrain-engine"
        ) from None

    agents_dir = knowledge_root(workspace) / "agents"
    if not agents_dir.exists():
        return _build_fallback_map_md(workspace)

    # Collect all agent.md content
    agent_docs: list[tuple[str, str]] = []
    for item in sorted(agents_dir.iterdir()):
        if item.is_file() and item.suffix == ".md":
            module_name = item.stem
            try:
                content = item.read_text(encoding="utf-8")
                agent_docs.append((module_name, content))
            except OSError:
                continue
        elif item.is_dir():
            # Multi-group module
            module_name = item.name
            for md_file in sorted(item.glob("*.md")):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    agent_docs.append((f"{module_name}/{md_file.stem}", content))
                except OSError:
                    continue

    if not agent_docs:
        return _build_fallback_map_md(workspace)

    # Split agent docs into context-sized batches.
    # Each batch gets its own Map Agent call; results are concatenated.
    max_batch_chars = int(os.environ.get("RB_MAP_BATCH_CHARS", "30000"))
    max_doc_chars = 20_000  # truncate individual docs to keep batches balanced

    batches: list[list[str]] = []
    current_batch: list[str] = []
    current_chars = 0

    for name, content in agent_docs:
        header = f"\n---\n## Agent: {name}\n"
        truncated = content[:max_doc_chars] if len(content) > max_doc_chars else content
        part = header + truncated
        if current_batch and current_chars + len(part) > max_batch_chars:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(part)
        current_chars += len(part)

    if current_batch:
        batches.append(current_batch)

    map_agent = build_map_agent(model)
    map_timeout = float(os.environ.get("RB_MAP_AGENT_TIMEOUT_SECONDS", "300"))

    async def _run_map_batch(batch: list[str], batch_idx: int) -> str:
        prompt = "Create a map.md from these module knowledge documents:\n" + "\n".join(batch)
        result = await _run_with_retry(
            Runner.run, map_agent, prompt,
            timeout=map_timeout,
            context=f"Map agent batch {batch_idx}",
        )
        return str(result.final_output).strip()

    if len(batches) == 1:
        return await _run_map_batch(batches[0], 0)

    # Multiple batches → parallel Map Agent calls → concatenate
    print(
        f"  → Map Agent: {len(agent_docs)} docs split into {len(batches)} batches",
        file=sys.stderr,
    )
    partial_maps = await asyncio.gather(
        *[_run_map_batch(batch, i) for i, batch in enumerate(batches)]
    )
    # Concatenate: keep the first header, strip duplicate headers from subsequent
    combined_parts: list[str] = []
    for i, partial in enumerate(partial_maps):
        if i == 0:
            combined_parts.append(partial)
        else:
            # Strip leading "# Module Map" header from subsequent batches
            lines = partial.splitlines()
            start = 0
            for j, line in enumerate(lines):
                if line.strip().startswith("## "):
                    start = j
                    break
            combined_parts.append("\n".join(lines[start:]))

    return "\n\n".join(combined_parts)


def _build_fallback_map_md(workspace: Path) -> str:
    """Build a basic map.md without LLM, from agent.md file listing.

    Args:
        workspace: Project root directory.

    Returns:
        Markdown content for a fallback map.
    """
    from repobrain_engine.hub.scanner import detect_modules, resolve_module_path

    modules = detect_modules(workspace)
    if not modules:
        return "# Module Map\n\n(No modules detected)\n"

    lines = ["# Module Map\n"]
    agents_dir = knowledge_root(workspace) / "agents"

    for mod in modules:
        mod_path = resolve_module_path(workspace, mod)
        try:
            rel_dir = str(mod_path.relative_to(workspace))
        except ValueError:
            rel_dir = mod

        lines.append(f"## {mod}")
        lines.append(f"**Path:** `{rel_dir}/`")

        # Check if agent.md exists for a brief summary
        agent_md = agents_dir / f"{mod}.md" if agents_dir.exists() else None
        if agent_md and agent_md.is_file():
            try:
                first_lines = agent_md.read_text(encoding="utf-8").splitlines()[:3]
                desc = " ".join(line.strip("#").strip() for line in first_lines if line.strip())
                if desc:
                    lines.append(f"**Description:** {desc[:200]}")
            except OSError:
                pass

        lines.append("")

    return "\n".join(lines)


async def _generate_module_registry(workspace: Path, model: str) -> str:
    """Call LLM to generate a module registry from all available knowledge.

    Reads structure.md (always available) and modules/*.md (if generated),
    then asks the LLM to produce a concise 2-3 sentence description per module.

    Args:
        workspace: Project root directory.
        model: LLM model identifier.

    Returns:
        Markdown content for module_registry.md.
    """
    from repobrain_engine.hub.scanner import detect_modules

    rb_dir = knowledge_root(workspace)
    modules = detect_modules(workspace)

    # -- Collect per-module evidence --
    from repobrain_engine.hub.scanner import resolve_module_path

    # Read structure.md once
    structure = ""
    structure_file = rb_dir / "structure.md"
    if structure_file.is_file():
        try:
            structure = structure_file.read_text(encoding="utf-8")
        except OSError:
            pass

    module_evidence: list[str] = []
    for mod in modules:
        parts: list[str] = [f"### Module: {mod}"]

        # Source 1: module knowledge doc (best quality, from RefreshModuleAgent)
        mod_doc = rb_dir / "modules" / f"{mod}.md"
        if mod_doc.is_file():
            try:
                content = mod_doc.read_text(encoding="utf-8")
                # Take first 800 chars — usually contains purpose + key files
                parts.append(f"**Deep knowledge (excerpt):**\n{content[:800]}")
            except OSError:
                pass

        # Source 2: structure.md section (AST-extracted)
        # Use resolve_module_path for accurate directory matching
        mod_path = resolve_module_path(workspace, mod)
        rel_dir = str(mod_path.relative_to(workspace)) + "/"
        if structure:
            section = _extract_module_section(structure, mod, rel_dir)
            if section:
                parts.append(f"**Code structure:**\n{section[:1200]}")

        # Source 3: fallback — list actual files if structure.md had no section
        if len(parts) == 1:  # Only has the header, no evidence yet
            file_listing = _list_module_files(mod_path)
            if file_listing:
                parts.append(f"**Files in module:**\n{file_listing[:1200]}")

        module_evidence.append("\n".join(parts))

    # -- Build LLM prompt --
    evidence_text = "\n\n---\n\n".join(module_evidence)

    # Include conventions.md for overall context
    conventions = ""
    conv_file = rb_dir / "conventions.md"
    if conv_file.is_file():
        try:
            conventions = conv_file.read_text(encoding="utf-8")[:2000]
        except OSError:
            pass

    prompt = f"""\
You are a senior software architect. Based on the evidence below, write an
**ultra-compact Module Registry** — a tag-line index for a Router agent.

FORMAT — one line per module, NO exceptions:
- **module_name**: 5-10 keyword tags (comma-separated)

The Router reads the ENTIRE registry to decide which module expert to
consult. Keep it SHORT so it always fits in context. Focus on what
TOPICS and QUESTIONS each module can answer.

GOOD example:
- **extensions_telegram**: Telegram bot, polling, message handlers, voice, grammY
- **src_gateway**: WebSocket server, device auth, TLS, protocol, REST API

BAD example (too long):
- **extensions_telegram**: The Telegram integration provides complete bot infrastructure including inbound message processing...

Output ONLY the Markdown registry. Start with `# Module Registry`.

---

## Project Overview
{conventions}

---

## Module Evidence

{evidence_text}
"""

    # -- Single LLM call --
    from agents import Agent, Runner

    registry_agent = Agent(
        name="RegistryWriter",
        instructions="Output only the requested Markdown. No commentary.",
        model=model,
    )

    registry_timeout = float(os.environ.get("RB_REGISTRY_TIMEOUT_SECONDS", "120"))
    result = await _run_with_retry(
        Runner.run, registry_agent, prompt,
        timeout=registry_timeout,
        context="Registry agent",
    )

    return result.final_output


def _extract_module_section(structure_text: str, module_id: str, rel_dir: str = "") -> str:
    """Extract lines from structure.md relevant to a module.

    Matches both ``## dir/`` section headers and ``### dir/file.py`` file
    entries whose path starts with the module's resolved directory.

    Args:
        structure_text: Full content of structure.md.
        module_id: Module identifier (e.g. "src_tools", "frontend").
        rel_dir: Resolved relative directory path (e.g. "src/opencmo/tools/").

    Returns:
        Extracted section text, or empty string.
    """
    # Build prefixes to match
    prefixes: list[str] = [f"{module_id}/"]
    if rel_dir:
        prefixes.append(rel_dir)
        prefixes.append(rel_dir.rstrip("/"))
    if "_" in module_id:
        parts = module_id.split("_", 1)
        prefixes.append(f"{parts[0]}/{parts[1]}/")

    def _line_matches(line: str) -> bool:
        # Match ## or ### headers that contain a matching path
        stripped = line.lstrip("#").strip()
        return any(stripped.startswith(p) or stripped.startswith(p.rstrip("/")) for p in prefixes)

    lines = structure_text.splitlines()
    result: list[str] = []
    collecting = False

    for line in lines:
        if line.startswith("## ") or line.startswith("### "):
            if _line_matches(line):
                collecting = True
                result.append(line)
                continue
            elif collecting and line.startswith("## "):
                # New top-level section that doesn't match → stop
                if not _line_matches(line):
                    collecting = False
                    continue
        if collecting:
            result.append(line)

    return "\n".join(result[:80])  # Cap at 80 lines per module


def _list_module_files(mod_path: Path) -> str:
    """List source files in a module directory for evidence.

    Args:
        mod_path: Absolute path to the module directory.

    Returns:
        Newline-separated list of relative file paths, or empty string.
    """
    if not mod_path.is_dir():
        return ""
    files: list[str] = []
    try:
        for f in sorted(mod_path.rglob("*")):
            if (
                f.is_file()
                and f.suffix.lower() in SOURCE_CODE_EXTS
                and "__pycache__" not in str(f)
            ):
                files.append(f"- {f.relative_to(mod_path)}")
    except OSError:
        pass
    return "\n".join(files[:50])


def _build_fallback_registry(workspace: Path) -> str:
    """Build a basic module registry without LLM, from structure.md.

    Used when the LLM call fails. Extracts file listings per module
    and uses them as rough descriptions.

    Args:
        workspace: Project root directory.

    Returns:
        Markdown content for a fallback registry, or empty string.
    """
    from repobrain_engine.hub.scanner import (
        detect_modules,
        list_root_module_files,
        resolve_module_path,
    )

    rb_dir = knowledge_root(workspace)
    modules = detect_modules(workspace)
    if not modules:
        return ""

    structure_file = rb_dir / "structure.md"
    structure = ""
    if structure_file.is_file():
        try:
            structure = structure_file.read_text(encoding="utf-8")
        except OSError:
            pass

    lines: list[str] = ["# Module Registry\n"]
    modules_dir = rb_dir / "modules"
    for mod in modules:
        module_path = resolve_module_path(workspace, mod)
        rel_dir = ""
        if mod != WORKSPACE_ROOT_MODULE_ID:
            rel_dir = str(module_path.relative_to(workspace)) + "/"

        # Source 1: module knowledge doc — extract heading keywords
        tags: list[str] = []
        mod_doc = modules_dir / f"{mod}.md"
        if mod_doc.is_file():
            try:
                doc_text = mod_doc.read_text(encoding="utf-8")[:1500]
                for line in doc_text.splitlines():
                    line_s = line.strip()
                    # Extract ## and ### headings as tags
                    if line_s.startswith("## ") or line_s.startswith("### "):
                        heading = line_s.lstrip("#").strip().lower()
                        # Skip generic headings
                        if heading not in (
                            "overview", "summary", "key files", "main files",
                            "architecture", "design patterns", "file locations",
                            "key dependencies", "dependencies",
                        ):
                            tags.append(heading)
            except OSError:
                pass

        # Source 2: structure.md — extract key filenames
        if not tags:
            section = _extract_module_section(structure, mod, rel_dir) if structure else ""
            for line in section.splitlines():
                line_s = line.strip()
                if line_s.startswith("### "):
                    fname = line_s[4:].strip().rsplit("/", 1)[-1]
                    stem = fname.rsplit(".", 1)[0] if "." in fname else fname
                    if stem not in ("index", "__init__", "main", "test", "utils", "types"):
                        tags.append(stem)
        if not tags and mod == WORKSPACE_ROOT_MODULE_ID:
            for path in list_root_module_files(workspace):
                tags.extend(_tokenize_text(path.name.replace(".", " ")))

        # Deduplicate and limit to 8 tags
        seen: set[str] = set()
        unique_tags: list[str] = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                unique_tags.append(t)
            if len(unique_tags) >= 8:
                break
        tag_str = ", ".join(unique_tags) if unique_tags else _module_display_name(mod)
        lines.append(f"- **{_module_display_name(mod)}**: {tag_str}")

    return "\n".join(lines)


def _build_fallback_conventions(report) -> str:
    """Build minimal conventions content when refresh runs in scan-only mode."""
    languages = ", ".join(report.languages.keys()) if getattr(report, "languages", None) else "unknown"
    frameworks = ", ".join(report.frameworks) if getattr(report, "frameworks", None) else "none"
    return (
        "# Project Conventions (Scan-Only)\n\n"
        "This file was generated in scan-only mode without LLM analysis.\n\n"
        f"- Languages: {languages}\n"
        f"- Frameworks: {frameworks}\n"
        f"- File count: {getattr(report, 'file_count', 0)}\n"
        f"- Scan elapsed: {getattr(report, 'scan_elapsed_seconds', 0.0):.2f}s\n"
        f"- Timed out: {getattr(report, 'timed_out', False)}\n"
        f"- Stop reason: {getattr(report, 'scan_stopped_reason', '') or 'completed'}\n"
    )
