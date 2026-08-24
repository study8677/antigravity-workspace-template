"""Ask pipeline — answer questions about the project.

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
from pathlib import Path

from repobrain_engine.hub._constants import (
    AGENT_MD_FALLBACK_MARKER,
    AGENT_MD_FALLBACK_SENTINEL,
    SKIP_DIRS,
)
from repobrain_engine.hub.contracts import (
    ClaimVerification,
    ModuleClaim,
    ModuleFactsDocument,
    ModuleRegistryEntry,
    RefreshStatus,
    VerificationResult,
    WorkerEvidence,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents import Agent
    from agents.result import RunResultStreaming

logger = logging.getLogger(__name__)


def _get_ask_retry_config() -> tuple[int, float]:
    """Return retry settings for transient ask-time model failures."""
    try:
        max_retries = max(0, int(os.environ.get("RB_ASK_RETRY_COUNT", "3")))
    except (TypeError, ValueError):
        max_retries = 3
    try:
        base_delay = max(0.0, float(os.environ.get("RB_ASK_RETRY_DELAY", "5.0")))
    except (TypeError, ValueError):
        base_delay = 5.0
    return max_retries, base_delay


def _is_retryable_ask_error(exc: Exception) -> bool:
    """Return true for transient model/provider failures.

    Delegates to the shared classifier in ``_providers`` so the same-provider
    retry path and the cross-provider failover path agree on what counts as
    transient.
    """
    from repobrain_engine.hub._providers import is_retryable_provider_error

    return is_retryable_provider_error(exc)


async def _run_with_optional_stream(
    agent: "Agent",
    prompt: str,
    max_turns: int = 50,
    timeout: float | None = None,
    stream_enabled: bool = False,
    progress_label: str | None = None,
) -> str:
    """Execute agent with optional streaming support."""
    from agents import Runner

    async def _run_once() -> str:
        if not stream_enabled:
            if timeout and timeout > 0:
                result = await asyncio.wait_for(
                    Runner.run(agent, prompt, max_turns=max_turns),
                    timeout=timeout,
                )
            else:
                result = await Runner.run(agent, prompt, max_turns=max_turns)
            return str(result.final_output)

        stream_result = Runner.run_streamed(agent, prompt, max_turns=max_turns)
        try:
            if timeout and timeout > 0:
                return await asyncio.wait_for(
                    _consume_stream_events(stream_result, progress_label),
                    timeout=timeout,
                )
            return await _consume_stream_events(stream_result, progress_label)
        except Exception:
            stream_result.cancel()
            raise

    max_retries, base_delay = _get_ask_retry_config()
    for attempt in range(max_retries + 1):
        try:
            return await _run_once()
        except Exception as exc:
            if attempt >= max_retries or not _is_retryable_ask_error(exc):
                raise
            delay = base_delay * (2 ** attempt)
            label = f" ({progress_label})" if progress_label else ""
            raw_msg = str(exc).replace("\n", " ").replace("\r", "")[:150]
            error_msg = raw_msg or type(exc).__name__
            print(
                f"  ⚠ Ask attempt {attempt + 1} failed{label}: "
                f"{error_msg}. Retrying in {delay}s...",
                file=sys.stderr,
            )
            await asyncio.sleep(delay)

    raise RuntimeError("unreachable ask retry state")


async def _consume_stream_events(
    stream_result: "RunResultStreaming",
    progress_label: str | None = None,
) -> str:
    """Consume streaming events and return final output."""
    from agents.item_helpers import ItemHelpers

    if progress_label:
        print(f"[stream] {progress_label}", file=sys.stderr, flush=True)

    async for event in stream_result.stream_events():
        # Skip raw response events (token-level - too verbose)
        if event.type == "raw_response_event":
            continue

        # Track agent changes
        elif event.type == "agent_updated_stream_event":
            print(
                f"[stream] → Agent: {event.new_agent.name}",
                file=sys.stderr,
                flush=True,
            )

        # Handle generated items
        elif event.type == "run_item_stream_event":
            item = event.item

            if item.type == "tool_call_item":
                print("[stream] ⚙ Calling tool...", file=sys.stderr, flush=True)

            elif item.type == "tool_call_output_item":
                output_preview = str(getattr(item, 'output', ''))[:100]
                print(
                    f"[stream] ⚙ Tool output: {output_preview}...",
                    file=sys.stderr,
                    flush=True,
                )

            elif item.type == "message_output_item":
                content = ItemHelpers.text_message_output(item)
                if content:
                    preview = content[:200] if len(content) > 200 else content
                    if len(content) > 200:
                        preview += "..."
                    print(
                        f"[stream] 📝 {preview}",
                        file=sys.stderr,
                        flush=True,
                    )

    return str(stream_result.final_output)


async def ask_pipeline(workspace: Path, question: str) -> str:
    """Answer a question about the project.

    Args:
        workspace: Project root directory.
        question: Natural language question.

    Returns:
        Answer string.

    Notes:
        MCP servers are only auto-connected when both ``MCP_ENABLED=true`` and
        ``RB_ALLOW_MCP=true`` are set in the runtime environment.

        When ``RB_LLM_FALLBACKS`` configures backup providers, a sustained
        provider outage on the active endpoint transparently fails over to
        the next provider and re-runs the answer. With no fallbacks the call
        is unchanged.
    """
    from repobrain_engine.config import get_settings
    from repobrain_engine.hub.host_runner import (
        SUPPORTED_HOST_RUNNERS,
        HostRunnerError,
        is_host_runner_enabled,
        normalize_host_runner_name,
    )

    settings = get_settings()
    host_runner = normalize_host_runner_name(settings.RB_HOST_RUNNER)
    if host_runner:
        if not is_host_runner_enabled(host_runner):
            supported = ", ".join(sorted(SUPPORTED_HOST_RUNNERS))
            raise HostRunnerError(
                f"Unsupported RB_HOST_RUNNER={settings.RB_HOST_RUNNER!r}. "
                f"Supported values: {supported}."
            )
        answer = await _ask_with_host_runner(workspace, question, settings)
        return _prepend_workspace_health_notices(workspace, answer)

    from repobrain_engine.hub._providers import (
        get_provider_chain,
        run_with_provider_failover,
    )

    providers = get_provider_chain(settings)

    async def _once() -> str:
        return await _ask_pipeline_once(workspace, question)

    answer = await run_with_provider_failover(
        _once,
        providers=providers,
        is_retryable=_is_retryable_ask_error,
        label="ask",
    )
    return _prepend_workspace_health_notices(workspace, answer)


async def _ask_pipeline_once(workspace: Path, question: str) -> str:
    """Run one ask attempt: structured path first, then legacy swarm."""
    from agents import set_tracing_disabled

    set_tracing_disabled(True)

    structured_enabled = os.environ.get("RB_ASK_FORCE_LEGACY", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }
    if structured_enabled and _structured_artifacts_available(workspace):
        print("[1/4] Loading structured module facts...", file=sys.stderr)
        structured_answer = await _ask_with_structured_facts(workspace, question)
        if structured_answer is not None:
            return structured_answer
        print("[1/4] Structured facts were insufficient; falling back to legacy swarm.", file=sys.stderr)

    return await _ask_with_legacy_swarm(workspace, question)


async def _ask_with_host_runner(workspace: Path, question: str, settings) -> str:
    """Run an explicit local host runner instead of the Agent SDK provider path."""
    from repobrain_engine.hub.host_runner import run_host_runner

    retrieval_mode = os.environ.get("RB_ASK_RETRIEVAL_FIRST", "1").strip().lower()
    retrieval_evidence: str | None = None
    if retrieval_mode in {"1", "true", "yes", "2"}:
        retrieval_evidence = _build_retrieval_semantic_answer(workspace, question)
        if retrieval_evidence and retrieval_mode == "2":
            print("[1/2] Retrieval-first answer hit; skipping host runner.", file=sys.stderr)
            return retrieval_evidence

    print("[1/2] Gathering project context for local host runner...", file=sys.stderr)
    context_parts = [_build_ask_context(workspace, question)]
    agent_context = _build_host_runner_agent_context(workspace, question)
    if agent_context:
        context_parts.append(agent_context)
    context = "\n\n".join(part for part in context_parts if part.strip())
    graph_context = _build_graph_skill_context(workspace, question) if _is_structure_query(question) else None

    print(
        f"[2/2] Asking local host runner '{settings.RB_HOST_RUNNER}'...",
        file=sys.stderr,
    )
    return await run_host_runner(
        runner=settings.RB_HOST_RUNNER,
        workspace=workspace,
        question=question,
        context=context,
        retrieval_evidence=retrieval_evidence,
        graph_context=graph_context,
        model=settings.RB_HOST_MODEL,
        command=settings.RB_HOST_COMMAND,
        output_mode=settings.RB_HOST_OUTPUT_MODE,
        timeout_seconds=settings.RB_HOST_TIMEOUT_SECONDS,
        max_context_chars=settings.RB_HOST_MAX_CONTEXT_CHARS,
    )


def _build_host_runner_agent_context(workspace: Path, question: str) -> str:
    """Build compact map.md/agent.md context for local host runners."""
    rb_dir = workspace / ".repobrain"
    agents_dir = rb_dir / "agents"
    parts: list[str] = []

    map_path = rb_dir / "map.md"
    if map_path.is_file():
        try:
            map_text = map_path.read_text(encoding="utf-8")[:20_000]
            parts.append("## .repobrain/map.md\n\n" + map_text)
        except OSError:
            pass

    if not agents_dir.is_dir():
        return "\n\n".join(parts)

    question_tokens = set(_question_tokens(question))
    scored_docs: list[tuple[int, str, str]] = []
    for label, path in _iter_agent_docs(agents_dir):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        searchable = f"{label}\n{content[:4000]}".lower()
        score = sum(1 for token in question_tokens if token in searchable)
        if label.lower() in question.lower():
            score += 5
        scored_docs.append((score, label, content))

    scored_docs.sort(key=lambda item: (-item[0], item[1]))
    selected = [item for item in scored_docs if item[0] > 0][:3]
    if not selected:
        selected = scored_docs[:2]

    for _, label, content in selected:
        marker = ""
        if _is_fallback_doc(content):
            marker = "\n\n[Note: this is a fallback file-list document, not full LLM analysis.]"
        parts.append(f"## .repobrain/agents/{label}\n{marker}\n\n{content[:25_000]}")

    if parts:
        return "## RepoBrain Agent Knowledge\n\n" + "\n\n".join(parts)
    return ""


def _iter_agent_docs(agents_dir: Path) -> list[tuple[str, Path]]:
    """Return readable agent.md document labels and paths."""
    docs: list[tuple[str, Path]] = []
    for item in sorted(agents_dir.iterdir(), key=lambda path: path.name):
        if item.is_file() and item.suffix == ".md":
            docs.append((item.name, item))
        elif item.is_dir() and not item.name.startswith("."):
            for md_file in sorted(item.glob("*.md")):
                docs.append((f"{item.name}/{md_file.name}", md_file))
    return docs


async def _ask_with_legacy_swarm(workspace: Path, question: str) -> str:
    """Run the legacy multi-agent ask workflow.

    Args:
        workspace: Project root directory.
        question: Natural language question about the project.

    Returns:
        Answer string from the reviewer swarm.
    """

    from repobrain_engine.config import get_settings
    from repobrain_engine.hub.agents import build_reviewer_agent, create_model

    settings = get_settings()
    model = create_model(settings)

    print("[1/3] Gathering project context...", file=sys.stderr)

    # Retrieval-assisted: gather code evidence and feed it to the LLM
    # as additional context rather than returning it directly.  Set
    # RB_ASK_RETRIEVAL_FIRST=2 to restore the old "return immediately" mode.
    retrieval_mode = os.environ.get("RB_ASK_RETRIEVAL_FIRST", "1").strip().lower()
    retrieval_evidence: str | None = None
    if retrieval_mode in {"1", "true", "yes", "2"}:
        retrieval_evidence = _build_retrieval_semantic_answer(workspace, question)
        if retrieval_evidence and retrieval_mode == "2":
            # Legacy mode: return retrieval result directly without LLM.
            print("[2/3] Retrieval-first answer hit; skipping LLM.", file=sys.stderr)
            return retrieval_evidence

    context = _build_ask_context(workspace, question)
    graph_skill_context = None
    if _is_structure_query(question):
        graph_skill_context = _build_graph_skill_context(workspace, question)

    prompt_parts = [f"Project context:\n{context}"]
    if retrieval_evidence:
        prompt_parts.append(f"Code evidence (from retrieval):\n{retrieval_evidence}")
    if graph_skill_context:
        prompt_parts.append(graph_skill_context)
    prompt_parts.append(f"Question: {question}")
    prompt = "\n\n".join(prompt_parts)

    mcp_tools: dict | None = None
    mcp_manager = None
    mcp_runtime_opt_in = os.environ.get("RB_ALLOW_MCP", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if settings.MCP_ENABLED and mcp_runtime_opt_in:
        print("[…] Connecting to MCP servers...", file=sys.stderr)
        try:
            from repobrain_engine.mcp_client import MCPClientManager

            mcp_manager = MCPClientManager()
            await mcp_manager.initialize()
            mcp_tools = mcp_manager.get_all_tools_as_callables()
            if mcp_tools:
                logger.info("MCP tools loaded: %s", list(mcp_tools.keys()))
            else:
                logger.info("MCP enabled but no tools discovered")
        except Exception as exc:
            logger.warning("MCP initialization failed: %s", exc)
            print(f"  ⚠ MCP init failed: {exc}", file=sys.stderr)
            mcp_manager = None
    elif settings.MCP_ENABLED:
        logger.info(
            "MCP is enabled in settings but RB_ALLOW_MCP is not set; skipping MCP server autoconnection"
        )

    agent = build_reviewer_agent(model, workspace=workspace, mcp_tools=mcp_tools)
    try:
        from agents import Runner
    except ImportError:
        raise ImportError(
            "OpenAI Agent SDK not found. Install: pip install repobrain-engine"
        ) from None

    print("[2/3] Analyzing with multi-agent swarm...", file=sys.stderr)

    ask_timeout = float(os.environ.get("RB_ASK_TIMEOUT_SECONDS", "240"))
    try:
        try:
            result_text = await _run_with_optional_stream(
                agent=agent,
                prompt=prompt,
                max_turns=50,
                timeout=ask_timeout if ask_timeout > 0 else None,
                stream_enabled=settings.STREAM_ENABLED,
                progress_label="Analyzing with multi-agent swarm...",
            )
        finally:
            if mcp_manager is not None:
                try:
                    await mcp_manager.shutdown()
                except Exception as exc:
                    logger.warning("MCP shutdown error: %s", exc)
    except TimeoutError:
        return _build_timeout_fallback_answer(workspace, question)

    print("[3/3] Synthesizing answer...", file=sys.stderr)

    return result_text


# ---------------------------------------------------------------------------
# Structured facts path
# ---------------------------------------------------------------------------

def _structured_artifacts_available(workspace: Path) -> bool:
    """Return whether structured refresh artifacts exist.

    Checks for the new agent.md-based format first (``map.md`` +
    ``agents/``), then falls back to the legacy JSON facts format.

    Args:
        workspace: Project root directory.

    Returns:
        True when routing and knowledge artifacts exist.
    """
    rb_dir = workspace / ".repobrain"

    # New format: map.md + agents/ directory
    agents_dir = rb_dir / "agents"
    if (rb_dir / "map.md").is_file() and agents_dir.is_dir():
        has_agents = (
            any(agents_dir.glob("*.md"))
            or any(d.is_dir() for d in agents_dir.iterdir() if not d.name.startswith("."))
        )
        if has_agents:
            return True

    # Legacy format: module_registry.json + modules/*.facts.json
    modules_dir = rb_dir / "modules"
    return (
        (rb_dir / "module_registry.json").is_file()
        and (rb_dir / "status.json").is_file()
        and modules_dir.is_dir()
        and any(modules_dir.glob("*.facts.json"))
    )


def _prepend_workspace_health_notices(workspace: Path, answer: str) -> str:
    """Add non-blocking workspace health notices before an ask answer."""
    notices = _build_workspace_health_notices(workspace)
    if not notices:
        return answer
    return "\n".join(notices + [answer])


def _build_workspace_health_notices(workspace: Path) -> list[str]:
    """Return staleness/degradation notices for existing knowledge artifacts."""
    notices: list[str] = []
    behind_count = _get_refresh_commit_lag(workspace)
    if behind_count and behind_count > 0:
        notices.append(
            "⚠ Knowledge base is "
            f"{behind_count} commit(s) behind HEAD -- consider running "
            "rb-refresh --quick."
        )

    degraded_modules = _load_degraded_status_modules(workspace)
    if degraded_modules:
        notices.append(
            "⚠ Knowledge base has partial/failed module knowledge for: "
            f"{', '.join(degraded_modules)}."
        )
    return notices


def _get_refresh_commit_lag(workspace: Path) -> int | None:
    """Return commits between last refresh SHA and HEAD, or None on failure."""
    sha_path = workspace / ".repobrain" / ".last_refresh_sha"
    try:
        last_sha = sha_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not last_sha:
        return None

    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"{last_sha}..HEAD"],
            capture_output=True,
            text=True,
            cwd=str(workspace),
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except (TypeError, ValueError):
        return None


def _load_degraded_status_modules(workspace: Path) -> list[str]:
    """Return modules marked partial/failed in status.json, if readable."""
    status_path = workspace / ".repobrain" / "status.json"
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    modules = payload.get("modules")
    if not isinstance(modules, dict):
        return []
    degraded = [
        str(module)
        for module, state in modules.items()
        if state in {"partial", "failed"}
    ]
    return sorted(degraded)


async def _ask_with_structured_facts(workspace: Path, question: str) -> str | None:
    """Answer a question using agent.md knowledge documents.

    Uses map.md to route the question to relevant modules, then reads
    their agent.md files and lets LLM(s) answer from that context.

    For single agent.md → one LLM call.
    For multiple agent.md → parallel LLM calls → synthesizer LLM.

    Falls back to legacy JSON facts if the new format is not available.

    Args:
        workspace: Project root directory.
        question: Natural language question.

    Returns:
        Answer string, or ``None`` if the agent.md path cannot answer.
    """
    rb_dir = workspace / ".repobrain"

    # Check for new agent.md format
    if (rb_dir / "map.md").is_file() and (rb_dir / "agents").is_dir():
        answer = await _ask_with_agent_md(workspace, question)
        if answer is not None:
            return answer

    # Fall back to legacy JSON facts path
    return await _ask_with_legacy_facts(workspace, question)


def _parse_router_output(output: str) -> list[str]:
    """Parse the Router agent's structured output.

    Expected format::

        MODULES: module1, module2

    Falls back to treating each line as a module name if the format
    is not recognized (backward compatible with old Router output).

    Args:
        output: Raw Router agent output text.

    Returns:
        List of raw module names.
    """
    modules: list[str] = []

    for line in output.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("MODULES:"):
            raw = stripped[len("MODULES:"):].strip()
            modules = [m.strip().strip("`*") for m in raw.split(",") if m.strip()]

    # Fallback: if no MODULES: line found, treat each line as a module name
    if not modules:
        modules = [
            line.strip().strip("- *`#")
            for line in output.strip().splitlines()
            if line.strip()
        ]

    return modules


def _match_to_known_modules(
    raw_names: list[str],
    known: set[str],
) -> list[str]:
    """Match LLM-output module names to known module identifiers.

    Tries exact match first, then case-insensitive, then substring
    containment. Deduplicates and preserves order.

    Args:
        raw_names: Raw module name strings from LLM output.
        known: Set of known module identifiers from agents/ directory.

    Returns:
        Matched module identifiers (up to 3).
    """
    matched: list[str] = []
    seen: set[str] = set()
    known_lower = {k.lower(): k for k in known}

    for raw in raw_names:
        if len(matched) >= 3:
            break
        # Clean: strip markdown artifacts, parenthetical notes, etc.
        clean = re.sub(r"\s*\(.*?\)\s*", "", raw).strip().strip("- *`#:.")
        if not clean:
            continue

        # 1. Exact match
        if clean in known and clean not in seen:
            matched.append(clean)
            seen.add(clean)
            continue

        # 2. Case-insensitive match
        lower = clean.lower()
        if lower in known_lower and known_lower[lower] not in seen:
            matched.append(known_lower[lower])
            seen.add(known_lower[lower])
            continue

        # 3. Substring: find known modules whose name is contained
        #    in the raw output or vice versa
        for k in sorted(known, key=len, reverse=True):
            if k in seen:
                continue
            if k.lower() in lower or lower in k.lower():
                matched.append(k)
                seen.add(k)
                break

    return matched


def _load_project_context(
    rb_dir: Path,
    map_content: str = "",
    max_chars: int | None = None,
) -> str:
    """Load project-level docs (conventions, registry, map, etc.) into a single
    labelled section to be injected alongside per-module knowledge.

    Returns an empty string if no sources are present (callers should still
    inject the section conditionally so the prompt stays clean).

    Sources are read in priority order; each source has a per-source cap and
    the function stops once the total budget is exhausted. ``map_content`` is
    accepted directly so the caller can reuse the already-read map.md instead
    of re-reading it from disk.
    """
    if max_chars is None:
        try:
            max_chars = int(os.environ.get("RB_ASK_PROJECT_CTX_MAX_CHARS", "15000"))
        except ValueError:
            max_chars = 15000
    if max_chars <= 0:
        return ""

    per_source_cap = max(1000, max_chars // 3)
    budget = max_chars
    parts: list[str] = []

    def _push(label: str, content: str) -> None:
        nonlocal budget
        if budget <= 0 or not content or not content.strip():
            return
        chunk = content[: min(per_source_cap, budget)]
        parts.append(f"### {label}\n{chunk}")
        budget -= len(chunk)

    file_sources: list[tuple[str, Path]] = [
        ("Project Conventions (.repobrain/conventions.md)", rb_dir / "conventions.md"),
        ("Document Index (.repobrain/document_index.md)", rb_dir / "document_index.md"),
    ]
    for label, path in file_sources:
        if budget <= 0:
            break
        if not path.is_file():
            continue
        try:
            _push(label, path.read_text(encoding="utf-8"))
        except OSError:
            continue

    if budget > 0 and map_content.strip():
        _push("Module Map (.repobrain/map.md)", map_content)

    file_sources_after_map: list[tuple[str, Path]] = [
        ("Module Registry (.repobrain/module_registry.md)", rb_dir / "module_registry.md"),
        ("Project Structure (.repobrain/structure.md)", rb_dir / "structure.md"),
    ]
    for label, path in file_sources_after_map:
        if budget <= 0:
            break
        if not path.is_file():
            continue
        try:
            _push(label, path.read_text(encoding="utf-8"))
        except OSError:
            continue

    if not parts:
        return ""
    return "## Project Context (project-wide reference docs)\n\n" + "\n\n".join(parts)


def _is_fallback_doc(content: str) -> bool:
    """True if an agent.md is an auto-generated refresh fallback (a bare file
    listing written when a module's LLM analysis failed), not real knowledge."""
    return AGENT_MD_FALLBACK_MARKER in content or AGENT_MD_FALLBACK_SENTINEL in content


def _prepend_degradation_banner(
    answer: str | None, degraded_modules: list[str]
) -> str | None:
    """Prefix a visible warning when some answered modules had only fallback
    (un-analyzed) knowledge, so an answer is never presented as fully grounded."""
    if not answer or not degraded_modules:
        return answer
    mods = ", ".join(degraded_modules)
    banner = (
        f"> ⚠ Incomplete knowledge for module(s): {mods}. These were not fully "
        "analyzed in the last refresh, so the answer may be unreliable for them — "
        "run `rb-refresh --failed-only` to fix.\n\n"
    )
    return banner + answer


async def _ask_with_agent_md(workspace: Path, question: str) -> str | None:
    """Answer a question by routing through map.md → agent.md files.

    Args:
        workspace: Project root directory.
        question: Natural language question.

    Returns:
        Answer string, or ``None`` if insufficient.
    """
    from repobrain_engine.config import get_settings
    from repobrain_engine.hub.agents import create_model

    settings = get_settings()
    model = create_model(settings)

    try:
        from agents import Agent, Runner
    except ImportError:
        return None

    rb_dir = workspace / ".repobrain"

    # Build code-exploration tools once so the AnswerAgent / Reader agents
    # below can grep, read, and list inside the workspace at answer time
    # (verifying KG claims and enumerating across files when the question
    # demands it). This is the difference between an LLM that paraphrases
    # the KG and one that actually inspects the source.
    answer_tools_wrapped: list = []
    try:
        from repobrain_engine.hub.agents import _wrap_tools
        from repobrain_engine.hub.ask_tools import create_ask_tools
        answer_tools_wrapped = _wrap_tools(create_ask_tools(workspace))
    except Exception as exc:
        logger.warning("Could not bind ask tools to answer agents: %s", exc)
        answer_tools_wrapped = []

    # Step 1: Read map.md and select modules
    try:
        map_content = (rb_dir / "map.md").read_text(encoding="utf-8")
    except OSError:
        return None

    print("[2/4] Routing question via map.md...", file=sys.stderr)

    router_prompt = f"""\
You are a routing agent for a codebase Q&A system.

Given the question and module map below, select the 1-3 modules most relevant
to this question.

Output format (strict):
MODULES: module1, module2

Question: {question}

Module Map:
{map_content}
"""
    router_agent = Agent(
        name="QuickRouter",
        instructions="Output ONLY in the exact format: MODULES: module1, module2. No other text.",
        model=model,
    )
    ask_timeout = float(os.environ.get("RB_ASK_TIMEOUT_SECONDS", "240"))
    try:
        router_output = await _run_with_optional_stream(
            agent=router_agent,
            prompt=router_prompt,
            max_turns=1,
            timeout=ask_timeout if ask_timeout > 0 else None,
            stream_enabled=settings.STREAM_ENABLED,
            progress_label="Routing question via map.md...",
        )
    except Exception as exc:
        logger.warning("ask: router agent failed: %s", exc)
        return None

    # Parse Router output: MODULES line
    raw_modules = _parse_router_output(router_output)

    # Collect known module names from agents/ directory
    agents_dir = rb_dir / "agents"
    known_modules: set[str] = set()
    if agents_dir.is_dir():
        for item in agents_dir.iterdir():
            if item.is_file() and item.suffix == ".md":
                known_modules.add(item.stem)
            elif item.is_dir() and not item.name.startswith("."):
                known_modules.add(item.name)

    selected_modules = _match_to_known_modules(raw_modules, known_modules)
    if not selected_modules:
        logger.warning(
            "ask: router output matched no known modules (raw=%s)", raw_modules
        )
        return None

    print(
        f"[2/4] Selected modules: {', '.join(selected_modules)}",
        file=sys.stderr,
    )

    # Step 2: Read agent.md for selected modules
    module_knowledge: list[tuple[str, str]] = []
    for mod_name in selected_modules:
        # Try single file
        single_md = agents_dir / f"{mod_name}.md"
        if single_md.is_file():
            try:
                content = single_md.read_text(encoding="utf-8")
                module_knowledge.append((mod_name, content))
            except OSError:
                continue
        # Try multi-group directory
        elif (agents_dir / mod_name).is_dir():
            for md_file in sorted((agents_dir / mod_name).glob("*.md")):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    module_knowledge.append((f"{mod_name}/{md_file.stem}", content))
                except OSError:
                    continue

    if not module_knowledge:
        logger.warning(
            "ask: selected modules had no readable agent docs: %s", selected_modules
        )
        return None

    # Detect modules whose knowledge doc is an auto-generated refresh fallback
    # (a bare file listing, not real analysis) so it is never silently served
    # to the user as factual, grounded knowledge.
    degraded_modules = [
        name for name, content in module_knowledge if _is_fallback_doc(content)
    ]
    if degraded_modules:
        logger.warning(
            "ask: %d selected module doc(s) are refresh fallbacks (no LLM "
            "analysis): %s",
            len(degraded_modules),
            ", ".join(degraded_modules),
        )

    # Step 2.5: Load project-level docs so the synthesizer can answer
    # project-wide questions (conventions, CI, dependencies, module
    # relationships) even when per-module agent docs don't carry them.
    project_context = _load_project_context(rb_dir, map_content=map_content)
    project_section = ""
    if project_context:
        project_section = f"""

{project_context}

NOTE: Use the project context above for project-wide questions about conventions,
tooling, lint/format/type-check, CI, docs, dependencies, supported environments,
or how modules relate to each other. If the project context already answers the
question, answer from it even if the per-module knowledge does not."""

    if degraded_modules:
        project_section += (
            "\n\nIMPORTANT: The knowledge for these module(s) is an auto-generated "
            "fallback — a bare file listing, NOT real analysis: "
            f"{', '.join(degraded_modules)}. Do not present that file list as findings. "
            "Use the code-inspection tools to read the listed files directly; if you "
            "cannot ground the answer in real source, say the module knowledge is "
            "incomplete."
        )

    # Step 3: Answer from agent.md content
    print(f"[3/4] Reading {len(module_knowledge)} agent docs...", file=sys.stderr)
    ask_api_concurrency = int(os.environ.get("RB_API_CONCURRENCY", "5"))
    _ask_api_sem = asyncio.Semaphore(ask_api_concurrency)

    if len(module_knowledge) == 1:
        # Single agent.md → one LLM call
        mod_name, knowledge = module_knowledge[0]
        tool_hint = ""
        if answer_tools_wrapped:
            tool_hint = """

You ALSO have tools to inspect the actual source code at answer time:
- search_code(query, file_pattern): grep across the workspace
- read_file(file_path, start_line, end_line): read specific line ranges
- list_directory(path): list files
- read_file_metadata(file_path): file size + line count
- search_by_type(file_type): list files of a type (e.g. "py")

Use them when:
- You need to verify or pin down an exact line number
- The pre-computed knowledge is vague or summarized away
- The question asks for an exhaustive list (audit, find every, compare across modules)
- You're unsure whether a fact is current
Prefer reading the actual code over guessing from the summary."""
        answer_prompt = f"""\
Answer this question using the project context AND module knowledge below.{tool_hint}
Be specific — cite file paths, function names, and line numbers (verify with tools when possible).
If neither the summary nor the source covers the question, say so.

Question: {question}
{project_section}

Module: {mod_name}
Knowledge:
{knowledge[:80_000]}
"""
        answer_agent = Agent(
            name="AnswerAgent",
            instructions="Answer concisely with specific code references. Use the inspection tools to verify line numbers and enumerate items when the question demands it. No preamble.",
            model=model,
            tools=answer_tools_wrapped,
        )
        try:
            # Tool-using agent needs more turns: each tool call consumes one.
            single_max_turns = 30 if answer_tools_wrapped else 1
            answer = await _run_with_optional_stream(
                agent=answer_agent,
                prompt=answer_prompt,
                max_turns=single_max_turns,
                timeout=ask_timeout if ask_timeout > 0 else None,
                stream_enabled=settings.STREAM_ENABLED,
                progress_label="Generating answer from agent.md...",
            )
            print("[4/4] Answer synthesized.", file=sys.stderr)
            return _prepend_degradation_banner(answer, degraded_modules)
        except Exception as exc:
            logger.warning("ask: answer agent failed: %s", exc)
            return None
    else:
        # Multiple agent.md → parallel LLM calls (with concurrency limit) → synthesizer
        async def _answer_from_doc(
            mod_name: str, knowledge: str
        ) -> tuple[str, str | None]:
            """Answer from a single module's knowledge document.

            Note: streaming is disabled for parallel calls to avoid output interleaving.
            """
            reader_tool_hint = ""
            if answer_tools_wrapped:
                reader_tool_hint = """

You ALSO have inspection tools (search_code, read_file, list_directory,
read_file_metadata, search_by_type) bound to this workspace. Use them to:
- Verify line numbers in your answer
- Pull in a few extra lines of code when the summary is vague
- Enumerate matching items across files when the question is an audit
Prefer concrete source over guessing."""
            prompt = f"""\
Answer this question using the project context AND module knowledge below.{reader_tool_hint}
Be specific — cite file paths, function names, line numbers.
If neither source helps for this module, respond with exactly "(not relevant)".

Question: {question}
{project_section}

Module: {mod_name}
Knowledge:
{knowledge[:60_000]}
"""
            agent = Agent(
                name=f"Reader_{mod_name}",
                instructions="Answer concisely with specific code references. Use the inspection tools when the summary is insufficient or you need to verify. Say '(not relevant)' if neither summary nor source helps.",
                model=model,
                tools=answer_tools_wrapped,
            )
            # Per-doc readers also need more turns when tool-using.
            reader_max_turns = 15 if answer_tools_wrapped else 1
            try:
                async with _ask_api_sem:
                    answer = await _run_with_optional_stream(
                        agent=agent,
                        prompt=prompt,
                        max_turns=reader_max_turns,
                        timeout=ask_timeout if ask_timeout > 0 else None,
                        stream_enabled=False,
                        progress_label=None,
                    )
                return mod_name, answer
            except Exception as exc:
                logger.warning("ask: reader for module %s failed: %s", mod_name, exc)
                return mod_name, None

        partial_answers = await asyncio.gather(
            *[_answer_from_doc(name, knowledge) for name, knowledge in module_knowledge]
        )

        # Filter out failures and irrelevant answers (exact-match only — answers
        # that mention "(not relevant)" inside a longer reply should not be
        # dropped).
        valid_answers = [
            (name, ans) for name, ans in partial_answers
            if ans and ans.strip().lower() != "(not relevant)"
        ]

        if not valid_answers:
            logger.warning("ask: no per-module reader produced a usable answer")
            return None

        if len(valid_answers) == 1:
            print("[4/4] Answer synthesized.", file=sys.stderr)
            return _prepend_degradation_banner(valid_answers[0][1], degraded_modules)

        # Synthesize multiple answers
        synth_parts = "\n\n---\n\n".join(
            f"**From {name}:**\n{ans}" for name, ans in valid_answers
        )
        synth_prompt = f"""\
Synthesize these partial answers into one coherent response.
Keep all specific references (file paths, function names, line numbers).
Be concise. If the project context covers the question more directly than
any per-module answer, prefer it.

Question: {question}
{project_section}

Partial answers:
{synth_parts}
"""
        synth_agent = Agent(
            name="Synthesizer",
            instructions="Combine the answers into one coherent response. Keep all specifics.",
            model=model,
        )
        try:
            answer = await _run_with_optional_stream(
                agent=synth_agent,
                prompt=synth_prompt,
                max_turns=1,
                timeout=ask_timeout if ask_timeout > 0 else None,
                stream_enabled=settings.STREAM_ENABLED,
                progress_label="Synthesizing answers from multiple modules...",
            )
            print("[4/4] Answer synthesized from multiple modules.", file=sys.stderr)
            return _prepend_degradation_banner(answer, degraded_modules)
        except Exception as exc:
            logger.warning("ask: multi-module synthesis failed: %s", exc)
            # Return the first valid answer as fallback
            return _prepend_degradation_banner(valid_answers[0][1], degraded_modules)


async def _ask_with_legacy_facts(workspace: Path, question: str) -> str | None:
    """Answer a question from legacy JSON module facts when available.

    This is the original structured facts path preserved for backward
    compatibility with pre-existing ``modules/*.facts.json`` artifacts.

    Args:
        workspace: Project root directory.
        question: Natural language question.

    Returns:
        Structured answer string, or ``None`` to fall back to swarm.
    """
    rb_dir = workspace / ".repobrain"
    modules_dir = rb_dir / "modules"
    if not (
        (rb_dir / "module_registry.json").is_file()
        and (rb_dir / "status.json").is_file()
        and modules_dir.is_dir()
        and any(modules_dir.glob("*.facts.json"))
    ):
        return None

    registry_entries = _load_registry_entries(workspace)
    refresh_status = _load_refresh_status(workspace)
    candidates = _select_candidate_modules(question, registry_entries)
    if not candidates:
        return None

    print(
        f"[2/4] Pre-routing to structured modules: {', '.join(entry.module for entry in candidates)}",
        file=sys.stderr,
    )

    documents: dict[str, ModuleFactsDocument] = {}
    worker_outputs: list[WorkerEvidence] = []
    verification_reports: list[VerificationResult] = []

    for entry in candidates:
        document = _load_module_facts(workspace, entry.module)
        if document is None:
            continue
        worker_output = _build_worker_evidence(question, entry, document, refresh_status)
        if not worker_output.claims_used:
            continue
        verification = _verify_worker_evidence(
            workspace=workspace,
            question=question,
            document=document,
            worker_output=worker_output,
        )
        documents[entry.module] = document
        worker_outputs.append(worker_output)
        verification_reports.append(verification)

    if not verification_reports:
        return None

    print("[3/4] Verifying structured claims...", file=sys.stderr)
    answer = _synthesize_structured_answer(
        question=question,
        entries=candidates,
        documents=documents,
        worker_outputs=worker_outputs,
        verification_reports=verification_reports,
    )
    if answer is None:
        return None

    print("[4/4] Returning evidence-backed structured answer.", file=sys.stderr)
    return answer


def _load_registry_entries(workspace: Path) -> list[ModuleRegistryEntry]:
    """Load machine-readable module registry entries.

    Args:
        workspace: Project root directory.

    Returns:
        Parsed registry entries.
    """
    registry_path = workspace / ".repobrain" / "module_registry.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    return [ModuleRegistryEntry.model_validate(item) for item in payload]


def _load_refresh_status(workspace: Path) -> RefreshStatus:
    """Load refresh health status from ``.repobrain/status.json``.

    Args:
        workspace: Project root directory.

    Returns:
        Parsed refresh status document.
    """
    status_path = workspace / ".repobrain" / "status.json"
    return RefreshStatus.model_validate_json(status_path.read_text(encoding="utf-8"))


def _load_module_facts(
    workspace: Path,
    module: str,
) -> ModuleFactsDocument | None:
    """Load facts for a single module.

    Args:
        workspace: Project root directory.
        module: Module identifier.

    Returns:
        Parsed facts document, or ``None`` when missing or invalid.
    """
    facts_path = workspace / ".repobrain" / "modules" / f"{module}.facts.json"
    if not facts_path.is_file():
        return None
    try:
        return ModuleFactsDocument.model_validate_json(
            facts_path.read_text(encoding="utf-8")
        )
    except Exception:
        return None


def _select_candidate_modules(
    question: str,
    registry_entries: list[ModuleRegistryEntry],
) -> list[ModuleRegistryEntry]:
    """Select the top candidate modules for a question.

    Args:
        question: Natural language question.
        registry_entries: Machine-readable module registry entries.

    Returns:
        Up to three candidate modules ordered by score.
    """
    question_tokens = _question_tokens(question)
    scored: list[tuple[int, ModuleRegistryEntry]] = []
    for entry in registry_entries:
        score = _score_registry_entry(question_tokens, question.lower(), entry)
        if score <= 0:
            continue
        scored.append((score, entry))

    scored.sort(
        key=lambda item: (
            -item[0],
            item[1].status != "success",
            item[1].module,
        )
    )
    return [entry for _, entry in scored[:3]]


def _question_tokens(question: str) -> list[str]:
    """Tokenize a user question for routing and claim matching.

    Args:
        question: Natural language question.

    Returns:
        Lowercase tokens with lightweight normalization.
    """
    tokens = re.findall(r"[a-zA-Z0-9_]{2,}", question.lower())
    return [token for token in tokens if token not in {"the", "and", "for", "how", "what"}]


def _score_registry_entry(
    question_tokens: list[str],
    question_lower: str,
    entry: ModuleRegistryEntry,
) -> int:
    """Score a registry entry against the current question.

    Args:
        question_tokens: Tokenized question terms.
        question_lower: Raw question lowercased.
        entry: Candidate module registry entry.

    Returns:
        Integer match score.
    """
    score = 0
    routing_tokens = set(entry.keywords)
    routing_tokens.update(_question_tokens(entry.summary))
    for path in entry.top_paths:
        routing_tokens.update(_question_tokens(path.replace("/", " ").replace(".", " ")))

    for token in question_tokens:
        if token in routing_tokens:
            score += 3
        if token in entry.module.lower():
            score += 5
        if any(token in path.lower() for path in entry.top_paths):
            score += 4

    if entry.module.lower() in question_lower:
        score += 8
    return score


def _build_worker_evidence(
    question: str,
    entry: ModuleRegistryEntry,
    document: ModuleFactsDocument,
    refresh_status: RefreshStatus,
) -> WorkerEvidence:
    """Select module claims to answer a question.

    Args:
        question: Natural language question.
        entry: Selected module registry entry.
        document: Module facts document.
        refresh_status: Global refresh status.

    Returns:
        Structured worker evidence payload.
    """
    selected_claims = _select_claims_for_question(question, document)
    claim_ids = [claim.claim_id for claim in selected_claims]
    draft_lines = [claim.statement for claim in selected_claims[:3]]
    module_state = refresh_status.modules.get(entry.module, entry.status)
    return WorkerEvidence(
        module=entry.module,
        draft_answer=" ".join(draft_lines),
        claims_used=claim_ids,
        verification_required=module_state != "success",
    )


def _select_claims_for_question(
    question: str,
    document: ModuleFactsDocument,
) -> list[ModuleClaim]:
    """Pick the most relevant claims for a question.

    Args:
        question: Natural language question.
        document: Module facts document.

    Returns:
        Ordered list of relevant claims.
    """
    question_tokens = set(_question_tokens(question))
    scored: list[tuple[int, ModuleClaim]] = []
    for claim in document.claims:
        score = _score_claim(question_tokens, claim)
        if score <= 0:
            continue
        scored.append((score, claim))

    if not scored:
        fallback = sorted(
            document.claims,
            key=lambda claim: (
                {"high": 0, "medium": 1, "low": 2}.get(claim.importance, 3),
                claim.claim_id,
            ),
        )
        return fallback[:3]

    scored.sort(key=lambda item: (-item[0], item[1].claim_id))
    return [claim for _, claim in scored[:5]]


def _score_claim(question_tokens: set[str], claim: ModuleClaim) -> int:
    """Score one claim for relevance to the question.

    Args:
        question_tokens: Tokenized question terms.
        claim: Candidate module claim.

    Returns:
        Integer relevance score.
    """
    claim_tokens = set(_question_tokens(claim.statement))
    claim_tokens.update(_question_tokens(claim.claim_type.replace("_", " ")))
    for rel_path in claim.source_files:
        claim_tokens.update(_question_tokens(rel_path.replace("/", " ").replace(".", " ")))
    overlap = len(question_tokens & claim_tokens)
    score = overlap * 4
    if claim.importance == "high":
        score += 3
    elif claim.importance == "medium":
        score += 2
    else:
        score += 1
    return score


def _verify_worker_evidence(
    workspace: Path,
    question: str,
    document: ModuleFactsDocument,
    worker_output: WorkerEvidence,
) -> VerificationResult:
    """Verify the worker's selected claims against source evidence.

    Args:
        workspace: Project root directory.
        question: Original user question.
        document: Module facts document.
        worker_output: Structured worker evidence payload.

    Returns:
        Verification report for the selected claims.
    """
    claim_lookup = {claim.claim_id: claim for claim in document.claims}
    verifications: list[ClaimVerification] = []

    for claim_id in worker_output.claims_used[:5]:
        claim = claim_lookup.get(claim_id)
        if claim is None:
            verifications.append(
                ClaimVerification(
                    claim_id=claim_id,
                    state="unverified",
                    notes="Claim was referenced by the worker but not found in module facts.",
                )
            )
            continue

        evidence_results: list[str] = []
        inspected_evidence: list = []
        for evidence in claim.evidence[:2]:
            inspected_evidence.append(evidence)
            file_path = workspace / evidence.file
            if not file_path.is_file():
                evidence_results.append("missing")
                continue
            try:
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                evidence_results.append("missing")
                continue

            snippet = "\n".join(
                lines[evidence.start_line - 1 : min(len(lines), evidence.end_line)]
            ).strip()
            if snippet and evidence.excerpt and snippet == evidence.excerpt.strip():
                evidence_results.append("verified")
            elif snippet:
                evidence_results.append("partial")
            else:
                evidence_results.append("missing")

        if "verified" in evidence_results:
            state = "verified"
            notes = "Evidence excerpt still matches the referenced source lines."
        elif "partial" in evidence_results:
            state = "partially_verified"
            notes = "Source lines were found, but the stored excerpt no longer matches exactly."
        else:
            state = "unverified"
            notes = "Referenced evidence could not be confirmed from current source files."

        verifications.append(
            ClaimVerification(
                claim_id=claim.claim_id,
                state=state,
                notes=notes,
                evidence=inspected_evidence,
            )
        )

    return VerificationResult(
        question=question,
        module=worker_output.module,
        claims=verifications,
        verification_required=worker_output.verification_required,
    )


def _synthesize_structured_answer(
    question: str,
    entries: list[ModuleRegistryEntry],
    documents: dict[str, ModuleFactsDocument],
    worker_outputs: list[WorkerEvidence],
    verification_reports: list[VerificationResult],
) -> str | None:
    """Compose a final answer from verified structured facts.

    Args:
        question: Original user question.
        entries: Routed registry entries.
        documents: Loaded module facts documents by module id.
        worker_outputs: Worker claim selections.
        verification_reports: Verification reports for the selections.

    Returns:
        Final answer string, or ``None`` if no supported claims remain.
    """
    entry_lookup = {entry.module: entry for entry in entries}
    doc_lookup = documents
    verification_lookup = {report.module: report for report in verification_reports}
    worker_lookup = {worker.module: worker for worker in worker_outputs}

    lines: list[str] = []
    verified_count = 0
    partial_count = 0

    for module, report in verification_lookup.items():
        document = doc_lookup.get(module)
        if document is None:
            continue
        claim_lookup = {claim.claim_id: claim for claim in document.claims}
        entry = entry_lookup[module]
        worker_output = worker_lookup[module]
        module_lines: list[str] = []

        if entry.status != "success":
            module_lines.append(f"`{module}` module knowledge is incomplete ({entry.status}).")

        for claim_verification in report.claims:
            claim = claim_lookup.get(claim_verification.claim_id)
            if claim is None:
                continue
            citation = _format_claim_citation(claim_verification)
            if claim_verification.state == "verified":
                verified_count += 1
                module_lines.append(f"- {claim.statement}{citation}")
            elif claim_verification.state == "partially_verified":
                partial_count += 1
                module_lines.append(f"- Possibly: {claim.statement}{citation}")

        if not module_lines and worker_output.draft_answer:
            module_lines.append(worker_output.draft_answer)

        if module_lines:
            lines.append(f"Module `{module}`:")
            lines.extend(module_lines)

    if verified_count == 0 and partial_count == 0:
        return None

    summary = [
        f"Question: {question}",
        "",
        *lines,
        "",
        f"Verification summary: {verified_count} verified, {partial_count} partially verified.",
    ]
    return "\n".join(summary).strip()


def _format_claim_citation(claim_verification: ClaimVerification) -> str:
    """Format the first evidence span for inline answer citations.

    Args:
        claim_verification: Verification result for one claim.

    Returns:
        Short citation string, or an empty string when no evidence exists.
    """
    if not claim_verification.evidence:
        return ""
    evidence = claim_verification.evidence[0]
    return f" ({evidence.file}:{evidence.start_line}-{evidence.end_line})"


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

def _read_context_file(path: Path, label: str) -> str | None:
    """Read a context file and wrap it with a label for prompt injection."""
    if not path.exists() or not path.is_file():
        return None

    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not content:
        return None

    return f"--- {label} ---\n{content}"


def _build_ask_context(workspace: Path, question: str = "") -> str:
    """Collect project context for Q&A with structure-first priority.

    The ordering has been adjusted so that the most universally useful
    sources (structure map, conventions, knowledge graph) come first,
    while niche indexes (media, data) are loaded only when budget
    remains.  When a *question* is provided, a lightweight keyword
    filter boosts sources whose labels overlap with the query.

    Args:
        workspace: Project root directory.
        question: Optional user question for relevance filtering.

    Returns:
        Concatenated context string.
    """
    context_parts: list[str] = []
    max_chars = int(os.environ.get("RB_ASK_CONTEXT_MAX_CHARS", "30000"))

    # Sources ordered by general usefulness (structure > conventions > graph > docs > data > media)
    prioritized_sources = [
        (
            workspace / ".repobrain" / "structure.md",
            ".repobrain/structure.md",
        ),
        (
            workspace / ".repobrain" / "conventions.md",
            ".repobrain/conventions.md",
        ),
        (
            workspace / ".repobrain" / "knowledge_graph.md",
            ".repobrain/knowledge_graph.md",
        ),
        (workspace / ".repobrain" / "rules.md", ".repobrain/rules.md"),
        (
            workspace / ".repobrain" / "decisions" / "log.md",
            ".repobrain/decisions/log.md",
        ),
        (workspace / "CONTEXT.md", "CONTEXT.md"),
        (workspace / "AGENTS.md", "AGENTS.md"),
        (
            workspace / ".repobrain" / "document_index.md",
            ".repobrain/document_index.md",
        ),
        (
            workspace / ".repobrain" / "data_overview.md",
            ".repobrain/data_overview.md",
        ),
        (
            workspace / ".repobrain" / "media_manifest.md",
            ".repobrain/media_manifest.md",
        ),
    ]

    # Lightweight keyword relevance: if the question mentions "media", "data",
    # "document", etc., boost matching sources to the front.
    if question:
        q_lower = question.lower()
        boost_keywords = {
            "media": "media_manifest",
            "image": "media_manifest",
            "video": "media_manifest",
            "data": "data_overview",
            "csv": "data_overview",
            "json": "data_overview",
            "document": "document_index",
            "doc": "document_index",
            "readme": "document_index",
        }
        boosted: set[str] = set()
        for kw, label_fragment in boost_keywords.items():
            if kw in q_lower:
                boosted.add(label_fragment)
        if boosted:
            top: list[tuple[Path, str]] = []
            rest: list[tuple[Path, str]] = []
            for entry in prioritized_sources:
                if any(b in entry[1] for b in boosted):
                    top.append(entry)
                else:
                    rest.append(entry)
            prioritized_sources = top + rest

    for path, label in prioritized_sources:
        rendered = _read_context_file(path, label)
        if rendered:
            if sum(len(p) for p in context_parts) + len(rendered) > max_chars:
                break
            context_parts.append(rendered)

    memory_dir = workspace / ".repobrain" / "memory"
    if memory_dir.exists():
        for memory_file in sorted(memory_dir.glob("*.md")):
            rendered = _read_context_file(
                memory_file,
                f".repobrain/memory/{memory_file.name}",
            )
            if rendered:
                if sum(len(p) for p in context_parts) + len(rendered) > max_chars:
                    break
                context_parts.append(rendered)

    return "\n\n".join(context_parts) if context_parts else "(no context available)"


def _is_structure_query(question: str) -> bool:
    """Heuristic for topology/structure/dependency style questions."""
    q = question.lower()
    keywords = {
        "依赖", "关系", "调用", "结构", "拓扑", "子图", "知识图谱", "谁调用", "路径",
        "dependency", "dependencies", "relation", "relations", "calls", "called by",
        "graph", "topology", "structure", "ownership", "impact",
    }
    return any(k in q for k in keywords)


def _build_graph_skill_context(workspace: Path, question: str) -> str | None:
    """Invoke Graph Skill and convert output to prompt-ready context block."""
    from repobrain_engine.skills.loader import load_skills

    tools: dict = {}
    load_skills(tools)
    query_graph = tools.get("query_graph")
    if not callable(query_graph):
        return None

    try:
        result = query_graph(question, max_hops=2, workspace=str(workspace))
    except Exception:  # noqa: BLE001
        return None

    max_chars = int(os.environ.get("RB_GRAPH_CONTEXT_MAX_CHARS", "8000"))
    max_chars = max(1000, max_chars)

    if isinstance(result, dict):
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        if len(payload) > max_chars:
            payload = payload[:max_chars] + "\n... [truncated by RB_GRAPH_CONTEXT_MAX_CHARS]"
        return "--- graph_skill_context ---\n" + payload
    return f"--- graph_skill_context ---\n{result}"


# ---------------------------------------------------------------------------
# Retrieval / code-search helpers
# ---------------------------------------------------------------------------

def _iter_python_files(workspace: Path) -> list[Path]:
    """Collect python files under workspace with lightweight skip rules."""
    skip_dirs = SKIP_DIRS | {"data", "logs"}
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(workspace):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
        for fname in filenames:
            if fname.endswith(".py"):
                files.append(Path(dirpath) / fname)
    return files


def _iter_shell_files(workspace: Path) -> list[Path]:
    """Collect shell script files under workspace with lightweight skip rules."""
    skip_dirs = SKIP_DIRS | {"data", "logs"}
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(workspace):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
        for fname in filenames:
            p = Path(dirpath) / fname
            if fname.endswith(".sh"):
                files.append(p)
                continue
            if fname in {"Dockerfile", "Makefile"}:
                continue
            try:
                if p.is_file() and p.read_text(encoding="utf-8", errors="ignore").startswith("#!/usr/bin/env bash"):
                    files.append(p)
            except Exception:
                continue
    return files


def _extract_identifiers(question: str) -> list[str]:
    """Extract candidate symbol identifiers from user question."""
    ids = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", question)
    seen: set[str] = set()
    out: list[str] = []
    for item in ids:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _find_function_defs(workspace: Path, identifiers: list[str]) -> list[dict[str, object]]:
    """Find function definitions matching identifiers.

    Results are prioritized: matches in files whose stem contains an
    identifier are ranked first (the actual module, not a wrapper).

    .. deprecated::
        Legacy function using AST parsing. The new ask pipeline uses
        LLM-based analysis via ``agents/*.md`` instead.
    """
    import ast as _ast  # lazy import for legacy path

    targets = {x.lower() for x in identifiers}
    matches: list[dict[str, object]] = []
    for fpath in _iter_python_files(workspace):
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
            tree = _ast.parse(source)
            lines = source.splitlines()
        except Exception:
            continue

        rel = str(fpath.relative_to(workspace))
        stem = fpath.stem.lower()
        # Boost: file stem contains one of the target identifiers
        file_match = any(t in stem for t in targets)

        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                name = node.name
                if targets and name.lower() not in targets:
                    continue
                start = int(getattr(node, "lineno", 1))
                end = int(getattr(node, "end_lineno", start))
                snippet = "\n".join(lines[start - 1 : min(end, start + 20)])
                matches.append(
                    {
                        "name": name,
                        "file": rel,
                        "start": start,
                        "end": end,
                        "snippet": snippet,
                        "_file_match": file_match,
                    }
                )

    # Sort: file-name matches first, then by path length (shorter = less nested)
    matches.sort(key=lambda m: (not m.get("_file_match", False), len(str(m.get("file", "")))))
    # Clean internal key before returning
    for m in matches:
        m.pop("_file_match", None)
    return matches[:6]


def _find_call_sites(workspace: Path, func_name: str, limit: int = 12) -> list[str]:
    """Find call sites for a function name."""
    pattern = re.compile(rf"\b{re.escape(func_name)}\s*\(")
    calls: list[str] = []
    for fpath in _iter_python_files(workspace):
        try:
            rel = fpath.relative_to(workspace)
            lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, start=1):
            if pattern.search(line) and not line.lstrip().startswith("def "):
                calls.append(f"{rel}:{i}: {line.strip()}")
                if len(calls) >= limit:
                    return calls
    return calls


def _find_shell_function_defs(workspace: Path, identifiers: list[str]) -> list[dict[str, object]]:
    """Find shell function definitions matching identifiers."""
    targets = {x.lower() for x in identifiers}
    matches: list[dict[str, object]] = []
    def_pattern = re.compile(r"^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{")

    for fpath in _iter_shell_files(workspace):
        try:
            rel = fpath.relative_to(workspace)
            lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue

        i = 0
        while i < len(lines):
            line = lines[i]
            m = def_pattern.match(line)
            if not m:
                i += 1
                continue

            name = m.group(1)
            if targets and name.lower() not in targets:
                i += 1
                continue

            start = i + 1
            brace_balance = line.count("{") - line.count("}")
            j = i + 1
            while j < len(lines) and brace_balance > 0:
                brace_balance += lines[j].count("{") - lines[j].count("}")
                j += 1
            end = j if j > start else start
            snippet = "\n".join(lines[start - 1 : min(end, start + 25)])
            matches.append(
                {
                    "name": name,
                    "file": str(rel),
                    "start": start,
                    "end": end,
                    "snippet": snippet,
                }
            )
            i = j
            if len(matches) >= 6:
                return matches
    return matches


def _find_shell_call_sites(workspace: Path, func_name: str, limit: int = 12) -> list[str]:
    """Find shell call sites for a function name."""
    call_pattern = re.compile(rf"\b{re.escape(func_name)}\b")
    def_pattern = re.compile(r"^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{")
    calls: list[str] = []
    for fpath in _iter_shell_files(workspace):
        try:
            rel = fpath.relative_to(workspace)
            lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, start=1):
            if not call_pattern.search(line):
                continue
            if def_pattern.match(line):
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            calls.append(f"{rel}:{i}: {stripped}")
            if len(calls) >= limit:
                return calls
    return calls


def _extract_blueprints_from_app(workspace: Path) -> list[str]:
    """Extract blueprint modules from backend app factory registration."""
    app_path = workspace / "backend" / "app.py"
    if not app_path.is_file():
        return []
    try:
        text = app_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    mods = re.findall(r'"backend\.blueprints\.([a-zA-Z0-9_]+)"', text)
    return mods


def _build_retrieval_semantic_answer(workspace: Path, question: str) -> str | None:
    """Build a semantic answer from retrieval artifacts and code evidence."""
    q = question.strip()
    if not q:
        return None

    lines: list[str] = []
    scan_report = workspace / ".repobrain" / "scan_report.json"
    if scan_report.is_file():
        try:
            payload = json.loads(scan_report.read_text(encoding="utf-8"))
            lines.append(
                "[retrieval] "
                f"files={payload.get('file_count', 0)}, "
                f"elapsed={payload.get('scan_elapsed_seconds', 0.0)}s"
            )
        except Exception:
            pass

    if ("blueprint" in q.lower()) or ("模块" in q and "注册" in q):
        bps = _extract_blueprints_from_app(workspace)
        if bps:
            lines.append("后端注册的 blueprint 模块:")
            lines.extend([f"- {m}" for m in bps])
            lines.append("证据: backend/app.py")
            return "\n".join(lines)

    identifiers = _extract_identifiers(q)
    if not identifiers and ("函数" not in q and "调用" not in q and "function" not in q.lower()):
        return None

    py_defs = _find_function_defs(workspace, identifiers)
    sh_defs = _find_shell_function_defs(workspace, identifiers)
    if not py_defs and not sh_defs:
        return None

    lines.append("基于检索到的函数实现与调用关系:")
    for item in py_defs[:3]:
        name = str(item["name"])
        file = str(item["file"])
        start = int(item["start"])
        lines.append(f"- 函数 {name} 定义于 {file}:{start}")
        snippet = str(item.get("snippet", "")).strip()
        if snippet:
            lines.append("```python")
            lines.append(snippet)
            lines.append("```")
        calls = _find_call_sites(workspace, name, limit=8)
        if calls:
            lines.append("  相关调用:")
            lines.extend([f"  - {c}" for c in calls])

    for item in sh_defs[:3]:
        name = str(item["name"])
        file = str(item["file"])
        start = int(item["start"])
        lines.append(f"- Shell 函数 {name} 定义于 {file}:{start}")
        snippet = str(item.get("snippet", "")).strip()
        if snippet:
            lines.append("```bash")
            lines.append(snippet)
            lines.append("```")
        calls = _find_shell_call_sites(workspace, name, limit=8)
        if calls:
            lines.append("  相关调用:")
            lines.extend([f"  - {c}" for c in calls])

    return "\n".join(lines)


def _build_timeout_fallback_answer(workspace: Path, question: str) -> str:
    """Return relevant knowledge snippets when ask agent times out."""
    rb_dir = workspace / ".repobrain"
    q_lower = question.lower()
    keywords = [w for w in re.split(r"\W+", q_lower) if len(w) > 2]

    lines: list[str] = [
        "LLM answering timed out. Here are the most relevant knowledge snippets:\n",
        f"**Question:** {question}\n",
    ]

    # -- Extract relevant sections from conventions.md --
    conventions = rb_dir / "conventions.md"
    if conventions.exists():
        try:
            text = conventions.read_text(encoding="utf-8")
            relevant = _extract_relevant_sections(text, keywords, max_chars=6000)
            if relevant:
                lines.append("## Project Conventions (relevant excerpts)\n")
                lines.append(relevant)
                lines.append("")
        except Exception:
            pass

    # -- Extract relevant sections from structure.md --
    structure = rb_dir / "structure.md"
    if structure.exists():
        try:
            text = structure.read_text(encoding="utf-8")
            relevant = _extract_relevant_sections(text, keywords, max_chars=8000)
            if relevant:
                lines.append("## Code Structure (relevant excerpts)\n")
                lines.append(relevant)
                lines.append("")
        except Exception:
            pass

    # -- Extract from knowledge_graph.md --
    kg = rb_dir / "knowledge_graph.md"
    if kg.exists():
        try:
            text = kg.read_text(encoding="utf-8")
            relevant = _extract_relevant_sections(text, keywords, max_chars=3000)
            if relevant:
                lines.append("## Knowledge Graph (relevant excerpts)\n")
                lines.append(relevant)
                lines.append("")
        except Exception:
            pass

    # -- Fallback: scan report summary --
    scan_report = rb_dir / "scan_report.json"
    if scan_report.exists() and len(lines) <= 4:
        try:
            payload = json.loads(scan_report.read_text(encoding="utf-8"))
            file_count = int(payload.get("file_count", 0)) if isinstance(payload, dict) else 0
            lines.append(f"*(Project has {file_count} files. Try rephrasing with a more specific question.)*")
        except Exception:
            pass

    if len(lines) <= 4:
        lines.append("No relevant knowledge found. Try running `rb refresh` to rebuild the knowledge base.")

    return "\n".join(lines)


def _extract_relevant_sections(text: str, keywords: list[str], max_chars: int = 6000) -> str:
    """Extract sections from markdown text that match keywords."""
    if not keywords:
        return text[:max_chars]

    sections = re.split(r"(?=^#{1,3}\s)", text, flags=re.MULTILINE)
    scored: list[tuple[int, str]] = []
    for section in sections:
        section_lower = section.lower()
        score = sum(1 for kw in keywords if kw in section_lower)
        if score > 0:
            scored.append((score, section.strip()))

    scored.sort(key=lambda x: x[0], reverse=True)

    result: list[str] = []
    total = 0
    for _score, section in scored:
        if total + len(section) > max_chars:
            remaining = max_chars - total
            if remaining > 200:
                result.append(section[:remaining] + "\n...")
            break
        result.append(section)
        total += len(section)

    return "\n\n".join(result)
