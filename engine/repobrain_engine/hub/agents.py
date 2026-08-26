"""OpenAI Agent SDK agents for the Knowledge Hub.

Two multi-agent swarms:

Refresh Swarm (rb refresh) — 3 agents:
    ScanAnalyst → ArchitectureReviewer → ConventionWriter

Ask Swarm (rb ask) — 3 agents:
    ContextCurator → DeepAnalyst → AnswerSynthesizer
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

from repobrain_engine.hub.storage import knowledge_root

if TYPE_CHECKING:
    from repobrain_engine.config import Settings
    from repobrain_engine.hub.host_runner import HostRunnerModel


def create_model(settings: "Settings") -> "Union[str, HostRunnerModel]":
    """Resolve an LLM model for the Agent SDK from settings.

    Priority:
    1. OPENAI_BASE_URL (any key)   → litellm/openai/<model> (custom endpoint)
    2. OPENAI_API_KEY (no base)    → <OPENAI_MODEL> (standard OpenAI)
    3. RB_HOST_RUNNER (no key)     → HostRunnerModel (local CLI, no API key)
    4. None                        → raise ValueError

    When a custom OPENAI_BASE_URL is provided (e.g. NVIDIA, Ollama), the
    model is routed through litellm so that the Agent SDK can reach the
    non-standard endpoint.  Environment variables required by litellm are
    set via ``os.environ[…]`` (overwrite, not setdefault) so that the
    *current* settings always take effect — avoiding first-caller-wins bugs
    in long-lived processes.

    A configured API backend always wins so users who *have* keys keep the
    full-capability refresh (tool-using / handoff swarms). Only when no
    OpenAI backend is present do we fall back to a local host runner, which
    drives the tool-free stages of refresh without an API key.

    Args:
        settings: Application settings.

    Returns:
        A model string suitable for openai-agents[litellm], or a
        :class:`HostRunnerModel` instance backed by a local CLI.

    Raises:
        ValueError: When no LLM backend is configured.
    """
    import os

    # Custom endpoint (NVIDIA, Ollama, etc.) — route through litellm.
    # Use os.environ[…] = … (not setdefault) so settings always win.
    if settings.OPENAI_BASE_URL:
        os.environ["OPENAI_API_BASE"] = settings.OPENAI_BASE_URL
        if settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
        return f"litellm/openai/{settings.OPENAI_MODEL}"

    # Standard OpenAI (no custom base URL)
    if settings.OPENAI_API_KEY:
        return settings.OPENAI_MODEL

    # No API key configured — drive a local headless CLI if requested.
    from repobrain_engine.hub.host_runner import (
        HostRunnerModel,
        is_host_runner_enabled,
    )

    # Use getattr so callers passing a minimal settings stub (older tests,
    # embedders) without the RB_HOST_* fields still get the ValueError path.
    host_runner = getattr(settings, "RB_HOST_RUNNER", "")
    if is_host_runner_enabled(host_runner):
        return HostRunnerModel(
            runner=host_runner,
            workspace=settings.project_root_path,
            model=getattr(settings, "RB_HOST_MODEL", None),
            command=getattr(settings, "RB_HOST_COMMAND", None),
            output_mode=getattr(settings, "RB_HOST_OUTPUT_MODE", None),
            timeout_seconds=getattr(settings, "RB_HOST_TIMEOUT_SECONDS", None),
        )

    raise ValueError(
        "No LLM configured. Run rb-setup or set OPENAI_BASE_URL, "
        "OPENAI_API_KEY, and OPENAI_MODEL in .env — or set RB_HOST_RUNNER "
        "(codex/generic) to drive a local CLI without an API key."
    )


def _import_agent():
    """Import Agent class with a helpful error message."""
    try:
        from agents import Agent
        return Agent
    except ImportError:
        raise ImportError(
            "OpenAI Agent SDK not found. Install: pip install repobrain-engine"
        ) from None


def _get_model_settings_kwargs() -> dict:
    """Build Agent kwargs carrying model_settings from RB_REASONING_EFFORT.

    ``extra_body`` is the SDK escape hatch for request body fields that are
    not first-class ``Agent`` constructor arguments.
    Common values: low, medium, high (for o1/o3 models)
    Returns empty dict if env var is not set (for SDK compatibility).
    """
    import os
    from agents import ModelSettings

    effort = os.environ.get("RB_REASONING_EFFORT", "").strip()
    if effort:
        return {"model_settings": ModelSettings(extra_body={"reasoning_effort": effort})}
    return {}



# ---------------------------------------------------------------------------
# Refresh Swarm — 3 agents: ScanAnalyst → ArchitectureReviewer → ConventionWriter
# ---------------------------------------------------------------------------

_SCAN_ANALYST_INSTRUCTIONS = """\
You are a code analyst specializing in language and framework detection.

Given a project scan report, perform deep analysis of:
- Programming languages and their distribution (primary vs secondary)
- Frameworks and libraries detected (web, data, ML, etc.)
- Code patterns and style observations (naming, structure, idioms)
- Dependency management approach

Produce a structured analysis in bullet points. Be specific — cite file
counts and concrete patterns, not vague observations.

When your analysis is complete, hand off to ArchitectureReviewer for
structural and DevOps analysis.
"""

_ARCHITECTURE_REVIEWER_INSTRUCTIONS = """\
You are a software architecture reviewer.

Building on the previous code analysis, focus on:
- Project directory structure and organization patterns
- Testing approach, framework, and coverage indicators
- CI/CD pipeline setup and automation
- Docker/container configuration
- Build system and packaging approach
- Configuration management patterns

Add your structural findings to the analysis chain. Be specific — name
directories, config files, and tools you observe.

When your review is complete, hand off to ConventionWriter to produce the
final conventions document.
"""

_CONVENTION_WRITER_INSTRUCTIONS = """\
You are a technical writer specializing in developer documentation.

Using ALL analysis from the previous agents (code analysis + architecture
review), produce a concise conventions document in Markdown. The document
must cover:
- Primary language(s) and framework(s)
- Project structure overview
- Code style observations
- Testing approach
- CI/CD setup

Keep it under 300 words. Output ONLY the Markdown content, no preamble,
no commentary. Start directly with a heading.
"""


def build_refresh_swarm(model: str):
    """Build the Refresh Swarm — a 3-agent chain for project analysis.

    Flow: ScanAnalyst → ArchitectureReviewer → ConventionWriter

    Args:
        model: Model identifier string.

    Returns:
        The entry-point Agent (ScanAnalyst). Pass it to Runner.run().
    """
    Agent = _import_agent()

    convention_writer = Agent(
        name="ConventionWriter",
        instructions=_CONVENTION_WRITER_INSTRUCTIONS,
        model=model,
        **_get_model_settings_kwargs(),
    )

    architecture_reviewer = Agent(
        name="ArchitectureReviewer",
        instructions=_ARCHITECTURE_REVIEWER_INSTRUCTIONS,
        model=model,
        handoffs=[convention_writer],
        **_get_model_settings_kwargs(),
    )

    scan_analyst = Agent(
        name="ScanAnalyst",
        instructions=_SCAN_ANALYST_INSTRUCTIONS,
        model=model,
        handoffs=[architecture_reviewer],
        **_get_model_settings_kwargs(),
    )

    return scan_analyst


_SINGLE_TURN_CONVENTION_INSTRUCTIONS = """\
You are a code analyst and technical writer.

Given a project scan report, analyze the codebase and write a concise
conventions document in a **single pass** (no handoffs, no tools). Cover:
- Primary language(s) and framework(s), with concrete evidence
- Project directory structure and organization patterns
- Code style observations (naming, structure, idioms)
- Testing approach, framework, and coverage indicators
- CI/CD setup, build system, and container configuration

Be specific — cite file counts, directory names, and concrete config files
you observe, not vague generalities.

Keep it under 300 words. Output ONLY the Markdown content, no preamble,
no commentary. Start directly with a heading.
"""


def build_single_turn_convention_agent(model):
    """Build a tool-free, single-turn conventions agent (no handoffs).

    This collapses the 3-hop ScanAnalyst → ArchitectureReviewer →
    ConventionWriter handoff chain into one agent so it can be driven by a
    :class:`~repobrain_engine.hub.host_runner.HostRunnerModel`, which only
    supports single-turn, tool-free, handoff-free generation.

    Args:
        model: Model identifier string or a ``Model`` instance.

    Returns:
        A single Agent that emits the conventions Markdown in one turn.
    """
    Agent = _import_agent()
    return Agent(
        name="ConventionWriterSingleTurn",
        instructions=_SINGLE_TURN_CONVENTION_INSTRUCTIONS,
        model=model,
        **_get_model_settings_kwargs(),
    )


# ---------------------------------------------------------------------------
# Ask Swarm — Dynamic Module-based Router-Worker pattern
# ---------------------------------------------------------------------------

_ROUTER_INSTRUCTIONS = """\
You are the Router agent for a software project Q&A system.

You have access to the project's **graph-first context** (knowledge graph,
structure map, document index, data overview, media manifest). Use this to
route requests beyond code, including documentation/data/media questions.

Your job:
1. Read the user's question carefully.
2. Based on the structure map, identify which module(s) are most relevant.
3. Hand off to the appropriate **ModuleAgent**.  Each ModuleAgent has
   deep knowledge of its module and tools to explore code.
4. For documentation/data/media questions, route to the module that owns those
    files; if uncertain, use Module_full_project first.
5. For git-related questions (recent changes, commit history, who changed
   what), hand off to the **GitAgent**.
6. For structure/dependency topology questions, prefer agents/tools that can
    query graph semantics (e.g. query_graph) before deep file reading.
7. For cross-module questions, hand off to one module first, it can
   hand off to other modules as needed.

When agents return findings, synthesize them into a final answer:
- Lead with a direct answer to the question
- **Cite specific file paths, line numbers, and function names**
- Include commit history when it explains "why"
- Be concise — under 200 words unless the question demands more

Output ONLY the final answer.  No preamble.
"""

_MODULE_AGENT_INSTRUCTIONS_TEMPLATE = """\
You are a ModuleAgent responsible for the **{module}** module.

You have deep knowledge of this module (provided below) and tools to
explore its code in real time.

**Your module knowledge:**
{knowledge}

**Your tools:**
1. ``search_code`` — find where a function/class/pattern appears
2. ``read_file`` — read actual source code
3. ``list_directory`` — explore sub-directories
4. ``git_file_history`` — check when/why files were changed
5. ``read_file_metadata`` — inspect file metadata
6. ``search_by_type`` — find docs/data/media/code files
7. ``summarize_directory`` — summarize a folder by extension and size
8. ``read_binary_stub`` — preview binary files safely
9. ``query_graph`` — retrieve query-relevant semantic triples from graph store
{mcp_tools_section}

**Strategy:** Use your pre-loaded knowledge to answer quickly. For dependency,
ownership, and topology questions, call ``query_graph`` first, then verify
with file tools when needed.

If the question involves another module, hand off to that module's agent
or back to the Router.

Return findings with exact source paths. For code, include line numbers and
function/class names. For non-code files, include file path + metadata cues.
Be thorough but concise.
"""

_GIT_AGENT_INSTRUCTIONS = """\
You are the GitAgent, specialized in understanding the project's git
history and development activity.

You have pre-loaded git insights (provided below) and tools for deeper
analysis.

**Your git knowledge:**
{knowledge}

**Your tools:**
1. ``git_log`` — recent commits, optionally filtered by path
2. ``git_diff`` — inspect what changed in a specific commit
3. ``git_blame`` — see who wrote specific lines and when
4. ``git_file_history`` — history of a specific file

Answer questions about:
- Recent changes and development activity
- Who changed what and why
- Module-level change frequency and trends
- Specific commit details

If the question requires understanding code logic (not just history),
hand off to the relevant ModuleAgent or Router.

Be precise — cite commit hashes, dates, authors, and file paths.
"""

_MCP_TOOLS_ADDENDUM = """
**MCP (Model Context Protocol) tools:**
{mcp_tool_list}

Use these for external knowledge-graph queries, database access,
or any capability not covered by the built-in tools above.
"""

# -- Refresh Module Agents --------------------------------------------------

_REFRESH_MODULE_INSTRUCTIONS_TEMPLATE = """\
You are a RefreshModuleAgent responsible for analyzing the **{module}** module.

Your job is to thoroughly read and understand all the code in your module,
then write a comprehensive knowledge document using the ``write_module_doc`` tool.

**Code structure of your module (auto-extracted):**
{structure}

**Steps:**
1. Use ``list_directory`` to explore the module structure
2. Use ``read_file`` to read key source files
3. Use ``search_code`` to find important patterns and relationships
4. Use ``git_file_history`` on key files to understand recent changes
5. Synthesize your understanding into a comprehensive Markdown document
6. Call ``write_module_doc`` with the document

**Your document MUST cover:**
- Module purpose and responsibilities (1-2 sentences)
- Directory structure overview
- Key files and what each one does
- Important classes/functions: name, purpose, parameters, relationships
- Internal data flow: how components call each other
- Dependencies: what external/internal modules this module imports
- Design patterns used
- Public API: what this module exposes to other modules
- Recent changes: what has been modified recently and why

Write the document in Markdown. Be specific — cite file names, function
signatures, and class hierarchies. This document will be used by another
agent to answer questions about this module, so completeness matters.
"""

_REFRESH_GIT_INSTRUCTIONS = """\
You are the RefreshGitAgent responsible for analyzing the project's git history.

Your job is to understand the project's development activity and write
a comprehensive git insights document using the ``write_git_doc`` tool.

**Pre-extracted git data:**
{git_data}

**Steps:**
1. Use ``git_log`` to review recent commits across the project
2. Use ``git_log`` with path filters to see per-module activity
3. Use ``git_diff`` on interesting commits to understand key changes
4. Synthesize everything into a comprehensive Markdown document
5. Call ``write_git_doc`` with the document

**Your document MUST cover:**
- Development activity summary (last 30 commits overview)
- Per-module change frequency and which modules are most active
- Key recent changes: what significant features/fixes were added recently
- Contributors and their areas of focus
- Development velocity: are there patterns in the commit history?
- Notable architectural or breaking changes in recent history

Write in Markdown. Be specific — cite commit hashes, dates, and file paths.
"""


_MAP_AGENT_INSTRUCTIONS = """\
You are a Map Agent that creates a routing index for a codebase knowledge system.

You are given knowledge documents (agent.md files) produced by module analysis
agents. Each document describes one module or one group within a module.

Your job: produce a concise **map.md** that a Router agent can use to decide
which module knowledge to consult when answering a question.

FORMAT — one entry per module/group:

## module_name
**Path:** `path/to/module/`
**Description:** 1-2 sentences describing what this module does.
**Key topics:** comma-separated keywords (5-10 tags)

Rules:
- Start with `# Module Map`
- Cover EVERY module/group you are given — do not skip any
- Descriptions must be concrete — mention specific technologies, protocols, patterns
- Key topics should be what a user might ask about
- Keep each entry SHORT — the Router reads the ENTIRE map
- Output ONLY Markdown. No commentary, no preamble.
"""


def build_map_agent(model: str):
    """Build the Map Agent that generates map.md from agent.md files.

    Args:
        model: Model identifier string.

    Returns:
        The Map Agent. Pass it to Runner.run() with agent.md contents as input.
    """
    Agent = _import_agent()
    return Agent(
        name="MapAgent",
        instructions=_MAP_AGENT_INSTRUCTIONS,
        model=model,
        **_get_model_settings_kwargs(),
    )


def _wrap_tools(tool_dict: dict) -> list:
    """Wrap plain functions with the Agent SDK ``function_tool`` decorator.

    Args:
        tool_dict: Mapping of tool name to callable (from create_ask_tools).

    Returns:
        List of decorated tool functions.
    """
    try:
        from agents import function_tool
    except ImportError:
        return []

    wrapped: list = []
    for fn in tool_dict.values():
        wrapped.append(function_tool(fn))
    return wrapped


def _detect_areas(workspace: Path) -> list[str]:
    """Detect code areas in a project (with two-level resolution).

    Args:
        workspace: Project root directory.

    Returns:
        List of module identifiers (e.g. ``["engine_hub", "engine_tools", "cli"]``).
    """
    from repobrain_engine.hub.scanner import detect_modules
    return detect_modules(workspace)


def _resolve_module_path(workspace: Path, module_id: str) -> Path:
    """Resolve a module identifier to its filesystem directory.

    Args:
        workspace: Project root directory.
        module_id: Module identifier from :func:`_detect_areas`.

    Returns:
        Absolute path to the module directory.
    """
    from repobrain_engine.hub.scanner import resolve_module_path
    return resolve_module_path(workspace, module_id)


def _read_module_knowledge(workspace: Path, module_name: str) -> str:
    """Read pre-generated module knowledge document(s).

    Checks the new ``agents/`` directory first (single file or
    multi-group directory), then falls back to legacy ``modules/``.

    Args:
        workspace: Project root directory.
        module_name: Module name (matches filename without .md).

    Returns:
        Content of the module document(s), or a fallback message.
    """
    rb_dir = knowledge_root(workspace)

    # New format: agents/{module}.md (single group)
    agent_md = rb_dir / "agents" / f"{module_name}.md"
    if agent_md.is_file():
        try:
            return agent_md.read_text(encoding="utf-8")
        except OSError:
            pass

    # New format: agents/{module}/ (multi-group directory)
    agent_dir = rb_dir / "agents" / module_name
    if agent_dir.is_dir():
        parts: list[str] = []
        for md_file in sorted(agent_dir.glob("*.md")):
            try:
                parts.append(md_file.read_text(encoding="utf-8"))
            except OSError:
                continue
        if parts:
            return "\n\n---\n\n".join(parts)

    # Legacy format: modules/{module}.md
    legacy_path = rb_dir / "modules" / f"{module_name}.md"
    if legacy_path.is_file():
        try:
            return legacy_path.read_text(encoding="utf-8")
        except OSError:
            pass

    return "(No pre-generated knowledge available. Use your tools to explore.)"


def _read_git_knowledge(workspace: Path) -> str:
    """Read the pre-generated git insights document.

    Args:
        workspace: Project root directory.

    Returns:
        Content of the git insights document, or a fallback message.
    """
    doc_path = knowledge_root(workspace) / "modules" / "_git_insights.md"
    if doc_path.is_file():
        try:
            return doc_path.read_text(encoding="utf-8")
        except OSError:
            pass
    return "(No pre-generated git insights available. Use your tools to explore.)"


def _read_structure_map(workspace: Path) -> str:
    """Read the project structure map for the Router.

    Args:
        workspace: Project root directory.

    Returns:
        Content of structure.md, or a fallback message.
    """
    doc_path = knowledge_root(workspace) / "structure.md"
    if doc_path.is_file():
        try:
            return doc_path.read_text(encoding="utf-8")
        except OSError:
            pass
    return "(No structure map available. Run `rb-refresh --workspace /path/to/project` first.)"


def _read_map_md(workspace: Path) -> str | None:
    """Read the map.md routing index (generated during refresh step 8).

    Args:
        workspace: Project root directory.

    Returns:
        Content of map.md, or None if not available.
    """
    doc_path = knowledge_root(workspace) / "map.md"
    if doc_path.is_file():
        try:
            return doc_path.read_text(encoding="utf-8")
        except OSError:
            pass
    return None


def _read_module_registry(workspace: Path) -> str | None:
    """Read the module registry (generated during refresh step 8).

    Args:
        workspace: Project root directory.

    Returns:
        Content of module_registry.md, or None if not available.
    """
    doc_path = knowledge_root(workspace) / "module_registry.md"
    if doc_path.is_file():
        try:
            return doc_path.read_text(encoding="utf-8")
        except OSError:
            pass
    return None


# ---------------------------------------------------------------------------
# Build Refresh Module Swarm
# ---------------------------------------------------------------------------


def build_refresh_module_swarm(
    model: str,
    workspace: Path,
) -> list:
    """Build RefreshModuleAgents that self-learn their code areas.

    Each agent is given its module's code structure, exploration tools,
    and a write tool to persist its knowledge document.

    Args:
        model: Model identifier string.
        workspace: Project root directory.

    Returns:
        List of (module_name, Agent) tuples. Run each agent with
        Runner.run() to trigger self-learning.
    """
    Agent = _import_agent()

    from repobrain_engine.hub.scanner import detect_modules, generate_module_context, resolve_module_path
    from repobrain_engine.hub.ask_tools import (
        create_ask_tools,
        create_write_tools,
    )

    modules = detect_modules(workspace)
    agents_list: list = []

    for mod in modules:
        mod_path = resolve_module_path(workspace, mod)
        # Get code structure for this module
        structure = generate_module_context(workspace, mod_path.name)

        # Create tools: code exploration (scoped to module) + write doc
        explore_tools = create_ask_tools(mod_path)
        write_tools = create_write_tools(workspace, mod)
        all_tools = {**explore_tools, **write_tools}

        instructions = _REFRESH_MODULE_INSTRUCTIONS_TEMPLATE.format(
            module=mod,
            structure=structure,
        )

        agent = Agent(
            name=f"RefreshModule_{mod}",
            instructions=instructions,
            model=model,
            tools=_wrap_tools(all_tools),
            **_get_model_settings_kwargs(),
        )
        agents_list.append((mod, agent))

    return agents_list


_REFRESH_PRELOADED_INSTRUCTIONS_TEMPLATE = """\
You are a RefreshModuleAgent analyzing the **{module}** module, group **{group_name}**.

All source files in your group are pre-loaded below. Read them carefully
and produce a comprehensive Markdown knowledge document.

Your document MUST cover (for every file in the group):
- **What each file does** — purpose, responsibilities (1-2 sentences per file)
- **Key classes/functions** — name, purpose, parameters, return types
- **Data flow** — how components call each other, what data passes between them
- **Dependencies** — what external/internal modules each file imports and why
- **Design patterns** — any notable patterns (factory, observer, protocol, etc.)
- **Public API** — what this code exposes to other modules
- **Configuration** — environment variables, settings, constants

Rules:
- Output ONLY Markdown. No JSON, no code fences around the whole output.
- Be specific — cite file paths, function names, class names, line numbers.
- Cover ALL pre-loaded files, not just the important ones.
- Be thorough but concise — this document will be read by other agents.
- Use headers (##, ###) to organize by file or topic.
- Start with a brief overview paragraph of the group's overall purpose.

**Pre-loaded source files ({file_count} files, ~{token_count} tokens):**

{file_context}
"""


def build_refresh_module_swarm_v2(
    model: str,
    workspace: Path,
    modules_filter: list[str] | None = None,
) -> list:
    """Build RefreshModuleAgents using smart functional grouping.

    Uses knowledge-graph import relationships to group files into
    functional units. Pre-loads file contents into agent context
    instead of using tool calls.

    Each sub-agent needs only 1 LLM turn (read context → produce analysis).
    If a module has multiple groups, a merge agent combines the outputs.

    Args:
        model: Model identifier string.
        workspace: Project root directory.
        modules_filter: Optional list of module names to process.
            When provided, only these modules are included.

    Returns:
        List of ``(module_name, group_entries)`` tuples where each
        ``group_entries`` item is ``(group_name, FileGroup, Agent)``.
    """
    Agent = _import_agent()

    from repobrain_engine.hub.scanner import detect_modules, resolve_module_path
    from repobrain_engine.hub.module_grouping import (
        load_module_files,
        group_files,
        format_group_context,
    )

    modules = detect_modules(workspace)
    if modules_filter is not None:
        modules = [m for m in modules if m in modules_filter]
    result: list = []

    for mod in modules:
        mod_path = resolve_module_path(workspace, mod)
        files = load_module_files(mod_path, workspace)

        if not files:
            continue

        groups = group_files(files, workspace)

        if not groups:
            continue

        group_entries: list[tuple[str, object, object]] = []
        for i, group in enumerate(groups):
            context = format_group_context(group)
            instructions = _REFRESH_PRELOADED_INSTRUCTIONS_TEMPLATE.format(
                module=mod,
                group_name=group.name,
                file_count=len(group.files),
                token_count=group.total_tokens,
                file_context=context,
            )
            agent = Agent(
                name=f"RefreshModule_{mod}_sub{i}_{group.name}",
                instructions=instructions,
                model=model,
                **_get_model_settings_kwargs(),
            )
            group_entries.append((group.name, group, agent))

        result.append((mod, group_entries))

    return result


def build_refresh_git_agent(model: str, workspace: Path):
    """Build the RefreshGitAgent that analyzes git history.

    Args:
        model: Model identifier string.
        workspace: Project root directory.

    Returns:
        The GitAgent. Run with Runner.run() to trigger self-learning.
    """
    Agent = _import_agent()

    from repobrain_engine.hub.scanner import extract_git_insights
    from repobrain_engine.hub.ask_tools import (
        create_git_tools,
        create_git_write_tools,
    )

    git_data = extract_git_insights(workspace)
    git_tools = create_git_tools(workspace)
    write_tools = create_git_write_tools(workspace)
    all_tools = {**git_tools, **write_tools}

    instructions = _REFRESH_GIT_INSTRUCTIONS.format(git_data=git_data)

    return Agent(
        name="RefreshGitAgent",
        instructions=instructions,
        model=model,
        tools=_wrap_tools(all_tools),
        **_get_model_settings_kwargs(),
    )


# ---------------------------------------------------------------------------
# Build Ask Swarm — dynamic module-based
# ---------------------------------------------------------------------------


def build_ask_swarm(
    model: str,
    workspace: Optional[Path] = None,
    mcp_tools: Optional[dict] = None,
):
    """Build the Ask Swarm using a dynamic module-based Router-Worker pattern.

    Each detected module gets a ModuleAgent pre-loaded with its knowledge
    document (generated during refresh). A GitAgent handles git-related
    questions. All agents can handoff to each other for cross-module
    communication.

    Args:
        model: Model identifier string.
        workspace: Project root directory.  When ``None`` the swarm
            falls back to a single agent without tools.
        mcp_tools: Optional dict of MCP tool callables that should be
            injected into every worker agent.

    Returns:
        The entry-point Agent (Router). Pass it to Runner.run().
    """
    Agent = _import_agent()

    if workspace is None:
        return Agent(
            name="AskAgent",
            instructions=(
                "Answer the user's question about the project based on "
                "the provided context.  Be concise and cite file paths."
            ),
            model=model,
            **_get_model_settings_kwargs(),
        )

    from repobrain_engine.hub.ask_tools import (
        create_ask_tools,
        create_git_tools,
    )
    from repobrain_engine.skills.loader import load_skills

    skill_docs: str = ""
    shared_skill_tools: dict = {}
    skill_docs = load_skills(shared_skill_tools) or skill_docs
    wrapped_mcp: list = []
    mcp_tools_section = ""
    mcp_capability_note = ""
    if mcp_tools:
        wrapped_mcp = _wrap_tools(mcp_tools)
        tool_names = list(mcp_tools.keys())
        mcp_tool_list = "\n".join(f"- ``{name}``" for name in tool_names)
        mcp_tools_section = _MCP_TOOLS_ADDENDUM.format(
            mcp_tool_list=mcp_tool_list,
        )
        mcp_capability_note = (
            f"\n\n**MCP tools available** (all agents): {', '.join(tool_names)}"
        )

    # Detect modules and build ModuleAgents
    areas = _detect_areas(workspace)
    workers: list = []

    for mod in areas:
        knowledge = _read_module_knowledge(workspace, mod)
        mod_path = _resolve_module_path(workspace, mod)
        mod_tools = create_ask_tools(mod_path)
        # Reuse globally loaded skill tools to avoid repeated scanning overhead.
        mod_tools.update(shared_skill_tools)
        wrapped = _wrap_tools(mod_tools)

        agent = Agent(
            name=f"Module_{mod}",
            instructions=_MODULE_AGENT_INSTRUCTIONS_TEMPLATE.format(
                module=mod,
                knowledge=knowledge,
                mcp_tools_section=mcp_tools_section,
            ),
            model=model,
            tools=wrapped + wrapped_mcp,
            **_get_model_settings_kwargs(),
        )
        workers.append(agent)

    # Build GitAgent
    git_knowledge = _read_git_knowledge(workspace)
    git_tools = create_git_tools(workspace)
    ask_tools = create_ask_tools(workspace)
    ask_tools.update(shared_skill_tools)
    git_all_tools = {**git_tools}
    # Add git_file_history from ask_tools if available
    if "git_file_history" in ask_tools:
        git_all_tools["git_file_history"] = ask_tools["git_file_history"]

    git_agent = Agent(
        name="GitAgent",
        instructions=_GIT_AGENT_INSTRUCTIONS.format(knowledge=git_knowledge),
        model=model,
        tools=_wrap_tools(git_all_tools) + wrapped_mcp,
        **_get_model_settings_kwargs(),
    )
    workers.append(git_agent)

    # Build full-project fallback worker
    full_tools = create_ask_tools(workspace)
    full_tools.update(shared_skill_tools)
    full_worker = Agent(
        name="Module_full_project",
        instructions=_MODULE_AGENT_INSTRUCTIONS_TEMPLATE.format(
            module="entire project",
            knowledge=_read_structure_map(workspace),
            mcp_tools_section=mcp_tools_section,
        ),
        model=model,
        tools=_wrap_tools(full_tools) + wrapped_mcp,
        **_get_model_settings_kwargs(),
    )
    workers.append(full_worker)

    # Build Router — prefers map.md over module_registry.md over structure.md
    module_list = ", ".join(f"Module_{m}" for m in areas)
    map_content = _read_map_md(workspace)
    if map_content:
        router_context = (
            f"\n\n**Available agents:** {module_list}, GitAgent, Module_full_project\n\n"
            f"**Module Map — what each agent knows:**\n{map_content}"
        )
    else:
        registry = _read_module_registry(workspace)
        if registry:
            router_context = (
                f"\n\n**Available agents:** {module_list}, GitAgent, Module_full_project\n\n"
                f"**Module Registry — what each agent knows:**\n{registry}"
            )
        else:
            structure_map = _read_structure_map(workspace)
            router_context = (
                f"\n\n**Available agents:** {module_list}, GitAgent, Module_full_project\n\n"
                f"**Project Structure Map:**\n{structure_map}"
            )
    router_instructions = _ROUTER_INSTRUCTIONS + router_context
    router_instructions += mcp_capability_note
    if skill_docs.strip():
        router_instructions += f"\n\n**Loaded Skills:**\n{skill_docs}"

    router = Agent(
        name="Router",
        instructions=router_instructions,
        model=model,
        handoffs=workers,
        **_get_model_settings_kwargs(),
    )

    # Star topology: workers hand off back to Router only.
    # This avoids O(N²) handoff references and keeps the Router as
    # the single routing authority for cross-module questions.
    for worker in workers:
        worker.handoffs = [router]

    return router


# ---------------------------------------------------------------------------
# Backward-compatible aliases (used by existing tests)
# ---------------------------------------------------------------------------

def build_refresh_agent(model: str):
    """Build the refresh swarm entry-point agent.

    Args:
        model: Model identifier string.

    Returns:
        The entry-point Agent for the Refresh Swarm.
    """
    return build_refresh_swarm(model)


def build_reviewer_agent(
    model: str,
    workspace: Optional[Path] = None,
    mcp_tools: Optional[dict] = None,
):
    """Build the ask swarm entry-point agent.

    Args:
        model: Model identifier string.
        workspace: Project root directory (passed to build_ask_swarm).
        mcp_tools: Optional dict of MCP tool callables.

    Returns:
        The entry-point Agent for the Ask Swarm.
    """
    return build_ask_swarm(model, workspace=workspace, mcp_tools=mcp_tools)
