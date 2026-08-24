"""Local host-backed runners for experimental no-API-key workflows.

Two runners are supported for ``rb-ask``:

* ``codex`` — drive the user's local ``codex exec`` login (built-in preset).
* ``generic`` — drive *any* headless agent CLI (Trae, Gemini CLI, Claude Code,
  or any command that answers a prompt on the command line) via the
  ``RB_HOST_COMMAND`` template. This makes the host-runner mechanism portable
  across hosts instead of being hard-wired to Codex.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_HOST_TIMEOUT_SECONDS = 600.0
DEFAULT_HOST_MAX_CONTEXT_CHARS = 60000

#: Host runners recognized by ``rb-ask``. ``codex`` is a built-in preset;
#: ``generic`` is configured through ``RB_HOST_COMMAND``.
SUPPORTED_HOST_RUNNERS = frozenset({"codex", "generic"})

#: Placeholders substituted into ``RB_HOST_COMMAND`` for the generic runner.
GENERIC_PROMPT_FILE_PLACEHOLDER = "{prompt_file}"
GENERIC_SCHEMA_FILE_PLACEHOLDER = "{schema_file}"
GENERIC_OUTPUT_FILE_PLACEHOLDER = "{output_file}"
GENERIC_WORKSPACE_PLACEHOLDER = "{workspace}"

#: How the generic runner recovers its answer: from ``{output_file}`` or stdout.
GENERIC_OUTPUT_MODES = frozenset({"file", "stdout"})
DEFAULT_GENERIC_OUTPUT_MODE = "file"


class HostRunnerError(ValueError):
    """Raised when a local host runner cannot produce an answer."""


@dataclass(frozen=True)
class HostRunnerAnswer:
    """Structured answer returned by a local host runner."""

    answer: str
    sources: list[str]
    limitations: list[str]

    def to_markdown(self) -> str:
        """Render the structured payload as user-facing Markdown."""
        parts = [self.answer.strip()]
        if self.sources:
            parts.append(
                "Sources:\n" + "\n".join(f"- {source}" for source in self.sources)
            )
        if self.limitations:
            parts.append(
                "Limitations:\n"
                + "\n".join(f"- {limitation}" for limitation in self.limitations)
            )
        return "\n\n".join(part for part in parts if part.strip())


def normalize_host_runner_name(value: str | None) -> str:
    """Normalize a host runner name from env/settings."""
    return (value or "").strip().lower()


def is_host_runner_enabled(value: str | None) -> bool:
    """Return whether a supported local host runner was requested."""
    return normalize_host_runner_name(value) in SUPPORTED_HOST_RUNNERS


def is_host_runner_model(model: object) -> bool:
    """Return whether ``model`` is a :class:`HostRunnerModel` instance.

    Used by ``rb-refresh`` to detect the no-API-key path and pre-emptively
    route tool-using / handoff stages to deterministic fallbacks instead of
    letting them fail at ``get_response``.
    """
    return isinstance(model, HostRunnerModel)


async def run_host_runner(
    *,
    runner: str,
    workspace: Path,
    question: str,
    context: str,
    retrieval_evidence: str | None = None,
    graph_context: str | None = None,
    model: str | None = None,
    command: str | None = None,
    output_mode: str | None = None,
    timeout_seconds: float | None = None,
    max_context_chars: int | None = None,
) -> str:
    """Run the configured local host runner and return Markdown output."""
    runner_name = normalize_host_runner_name(runner)
    if runner_name not in SUPPORTED_HOST_RUNNERS:
        supported = ", ".join(sorted(SUPPORTED_HOST_RUNNERS))
        raise HostRunnerError(
            f"Unsupported host runner: {runner or '<empty>'}. "
            f"Supported values: {supported}."
        )

    if runner_name == "codex":
        answer = await run_codex_host_runner(
            workspace=workspace,
            question=question,
            context=context,
            retrieval_evidence=retrieval_evidence,
            graph_context=graph_context,
            model=model,
            timeout_seconds=timeout_seconds,
            max_context_chars=max_context_chars,
        )
    else:  # runner_name == "generic"
        answer = await run_generic_host_runner(
            workspace=workspace,
            question=question,
            context=context,
            retrieval_evidence=retrieval_evidence,
            graph_context=graph_context,
            command=command,
            output_mode=output_mode,
            timeout_seconds=timeout_seconds,
            max_context_chars=max_context_chars,
        )
    return answer.to_markdown()


async def run_codex_host_runner(
    *,
    workspace: Path,
    question: str,
    context: str,
    retrieval_evidence: str | None = None,
    graph_context: str | None = None,
    model: str | None = None,
    timeout_seconds: float | None = None,
    max_context_chars: int | None = None,
) -> HostRunnerAnswer:
    """Answer with ``codex exec`` using the user's local Codex login."""
    import asyncio

    return await asyncio.to_thread(
        _run_codex_host_runner_sync,
        workspace=workspace,
        question=question,
        context=context,
        retrieval_evidence=retrieval_evidence,
        graph_context=graph_context,
        model=model,
        timeout_seconds=timeout_seconds,
        max_context_chars=max_context_chars,
    )


def build_codex_command(
    *,
    workspace: Path,
    model: str | None,
    schema_path: Path,
    output_path: Path,
    prompt: str,
) -> list[str]:
    """Build the ``codex exec`` command for a read-only host-runner ask."""
    cmd = [
        "codex",
        "exec",
        "--cd",
        str(workspace),
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
    ]
    if model:
        cmd += ["--model", model]
    cmd += [
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
        prompt,
    ]
    return cmd


def _run_codex_host_runner_sync(
    *,
    workspace: Path,
    question: str,
    context: str,
    retrieval_evidence: str | None,
    graph_context: str | None,
    model: str | None,
    timeout_seconds: float | None,
    max_context_chars: int | None,
) -> HostRunnerAnswer:
    if shutil.which("codex") is None:
        raise HostRunnerError(
            "Codex CLI is not installed or not on PATH. Install Codex CLI and run "
            "`codex login` before using RB_HOST_RUNNER=codex."
        )

    model_name = _resolve_host_model(model)
    timeout = _resolve_timeout(timeout_seconds)
    max_chars = _resolve_max_context_chars(max_context_chars)

    prompt = _build_host_prompt(
        workspace=workspace,
        question=question,
        context=context,
        retrieval_evidence=retrieval_evidence,
        graph_context=graph_context,
        max_context_chars=max_chars,
    )

    with tempfile.TemporaryDirectory(prefix="rb-host-runner-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        schema_path = tmp_path / "codex_host_answer.schema.json"
        output_path = tmp_path / "codex_host_answer.json"
        schema_path.write_text(
            json.dumps(_host_answer_schema(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        cmd = build_codex_command(
            workspace=workspace,
            model=model_name,
            schema_path=schema_path,
            output_path=output_path,
            prompt=prompt,
        )

        completed = _run_host_subprocess(
            cmd,
            workspace=workspace,
            timeout=timeout,
            label="Codex host runner",
        )
        return _read_host_answer(
            completed,
            output_path=output_path,
            label="Codex host runner",
        )


async def run_generic_host_runner(
    *,
    workspace: Path,
    question: str,
    context: str,
    retrieval_evidence: str | None = None,
    graph_context: str | None = None,
    command: str | None = None,
    output_mode: str | None = None,
    timeout_seconds: float | None = None,
    max_context_chars: int | None = None,
) -> HostRunnerAnswer:
    """Answer via an arbitrary headless agent CLI configured by ``RB_HOST_COMMAND``."""
    import asyncio

    return await asyncio.to_thread(
        _run_generic_host_runner_sync,
        workspace=workspace,
        question=question,
        context=context,
        retrieval_evidence=retrieval_evidence,
        graph_context=graph_context,
        command=command,
        output_mode=output_mode,
        timeout_seconds=timeout_seconds,
        max_context_chars=max_context_chars,
    )


def normalize_generic_output_mode(value: str | None) -> str:
    """Normalize ``RB_HOST_OUTPUT_MODE`` to a supported value."""
    mode = (value or "").strip().lower()
    if not mode:
        return DEFAULT_GENERIC_OUTPUT_MODE
    if mode not in GENERIC_OUTPUT_MODES:
        supported = ", ".join(sorted(GENERIC_OUTPUT_MODES))
        raise HostRunnerError(
            f"Unsupported RB_HOST_OUTPUT_MODE={value!r}. Supported values: {supported}."
        )
    return mode


def build_generic_command(
    *,
    template: str,
    workspace: Path,
    schema_path: Path,
    output_path: Path,
    prompt_path: Path,
) -> tuple[list[str], bool]:
    """Render ``RB_HOST_COMMAND`` into an argv list.

    Returns the argv and whether the template referenced ``{prompt_file}``. When
    it did not, the prompt must be delivered on stdin by the caller.

    Placeholders: ``{prompt_file}``, ``{schema_file}``, ``{output_file}``,
    ``{workspace}``.
    """
    template = (template or "").strip()
    if not template:
        raise HostRunnerError(
            "RB_HOST_RUNNER=generic requires RB_HOST_COMMAND to be set, e.g. "
            "RB_HOST_COMMAND='mycli exec --prompt {prompt_file}'."
        )

    uses_prompt_file = GENERIC_PROMPT_FILE_PLACEHOLDER in template
    substitutions = {
        GENERIC_PROMPT_FILE_PLACEHOLDER: str(prompt_path),
        GENERIC_SCHEMA_FILE_PLACEHOLDER: str(schema_path),
        GENERIC_OUTPUT_FILE_PLACEHOLDER: str(output_path),
        GENERIC_WORKSPACE_PLACEHOLDER: str(workspace),
    }

    try:
        tokens = shlex.split(template)
    except ValueError as exc:
        raise HostRunnerError(
            f"Invalid RB_HOST_COMMAND (could not parse): {exc}"
        ) from exc
    if not tokens:
        raise HostRunnerError("RB_HOST_COMMAND parsed to an empty command.")

    argv = [_apply_placeholders(token, substitutions) for token in tokens]
    return argv, uses_prompt_file


def _apply_placeholders(token: str, substitutions: dict[str, str]) -> str:
    for placeholder, value in substitutions.items():
        token = token.replace(placeholder, value)
    return token


def _run_generic_host_runner_sync(
    *,
    workspace: Path,
    question: str,
    context: str,
    retrieval_evidence: str | None,
    graph_context: str | None,
    command: str | None,
    output_mode: str | None,
    timeout_seconds: float | None,
    max_context_chars: int | None,
) -> HostRunnerAnswer:
    template = command if command is not None else os.environ.get("RB_HOST_COMMAND")
    mode = normalize_generic_output_mode(
        output_mode if output_mode is not None else os.environ.get("RB_HOST_OUTPUT_MODE")
    )
    timeout = _resolve_timeout(timeout_seconds)
    max_chars = _resolve_max_context_chars(max_context_chars)

    prompt = _build_host_prompt(
        workspace=workspace,
        question=question,
        context=context,
        retrieval_evidence=retrieval_evidence,
        graph_context=graph_context,
        max_context_chars=max_chars,
    )

    with tempfile.TemporaryDirectory(prefix="rb-host-runner-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        schema_path = tmp_path / "generic_host_answer.schema.json"
        output_path = tmp_path / "generic_host_answer.json"
        prompt_path = tmp_path / "generic_host_prompt.txt"
        schema_path.write_text(
            json.dumps(_host_answer_schema(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        prompt_path.write_text(prompt, encoding="utf-8")

        argv, uses_prompt_file = build_generic_command(
            template=template,
            workspace=workspace,
            schema_path=schema_path,
            output_path=output_path,
            prompt_path=prompt_path,
        )

        # Verify the host executable resolves before launching, for a clear error.
        executable = argv[0]
        if shutil.which(executable) is None and not Path(executable).exists():
            raise HostRunnerError(
                f"Generic host runner command not found on PATH: {executable!r}. "
                "Check RB_HOST_COMMAND points at an installed CLI."
            )

        # When the template does not reference {prompt_file}, feed prompt on stdin.
        stdin_text = None if uses_prompt_file else prompt
        completed = _run_host_subprocess(
            argv,
            workspace=workspace,
            timeout=timeout,
            label="Generic host runner",
            stdin_text=stdin_text,
        )

        expected_output = output_path if mode == "file" else None
        return _read_host_answer(
            completed,
            output_path=expected_output,
            label="Generic host runner",
        )


def _run_host_subprocess(
    cmd: list[str],
    *,
    workspace: Path,
    timeout: float,
    label: str,
    stdin_text: str | None = None,
) -> subprocess.CompletedProcess:
    """Run a host-runner subprocess with shared timeout/error handling."""
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(workspace),
            text=True,
            input=stdin_text,
            capture_output=True,
            timeout=timeout if timeout > 0 else None,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HostRunnerError(f"{label} timed out after {timeout:g}s.") from exc
    except OSError as exc:
        raise HostRunnerError(
            f"Failed to run {label}: {_redact_secrets(str(exc))}"
        ) from exc

    if completed.returncode != 0:
        stderr = _redact_secrets((completed.stderr or completed.stdout or "").strip())
        raise HostRunnerError(
            f"{label} failed" + (f": {stderr[:1200]}" if stderr else ".")
        )
    return completed


def _read_host_answer(
    completed: subprocess.CompletedProcess,
    *,
    output_path: Path | None,
    label: str,
) -> HostRunnerAnswer:
    """Recover the JSON answer from an output file (if any) then stdout."""
    raw_output = ""
    if output_path is not None and output_path.is_file():
        raw_output = output_path.read_text(encoding="utf-8").strip()
    if not raw_output:
        raw_output = (completed.stdout or "").strip()
    if not raw_output:
        raise HostRunnerError(f"{label} returned no output.")
    return parse_host_runner_answer(raw_output)


def parse_host_runner_answer(raw_output: str) -> HostRunnerAnswer:
    """Parse a host runner JSON answer payload."""
    payload = _parse_json_object(raw_output)
    answer = str(payload.get("answer") or "").strip()
    if not answer:
        raise HostRunnerError("Host runner returned JSON without a non-empty answer.")
    return HostRunnerAnswer(
        answer=answer,
        sources=_coerce_string_list(payload.get("sources")),
        limitations=_coerce_string_list(payload.get("limitations")),
    )


def _parse_json_object(raw_output: str) -> dict[str, Any]:
    text = (raw_output or "").strip()
    if not text:
        raise HostRunnerError("Host runner returned no output.")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
        if fenced:
            try:
                payload = json.loads(fenced.group(1))
            except json.JSONDecodeError as exc:
                raise HostRunnerError(
                    "Host runner returned invalid JSON in a fenced block."
                ) from exc
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end < start:
                raise HostRunnerError(
                    "Host runner returned non-JSON output. "
                    f"Preview: {_redact_secrets(text[:400])}"
                )
            try:
                payload = json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise HostRunnerError(
                    "Host runner returned malformed JSON. "
                    f"Preview: {_redact_secrets(text[:400])}"
                ) from exc

    if not isinstance(payload, dict):
        raise HostRunnerError("Host runner JSON output must be an object.")
    return payload


def _build_host_prompt(
    *,
    workspace: Path,
    question: str,
    context: str,
    retrieval_evidence: str | None,
    graph_context: str | None,
    max_context_chars: int,
) -> str:
    sections = [
        (
            "You are RepoBrain's local host runner for read-only codebase Q&A.\n"
            "You may inspect files in the workspace, but you must not modify files, run "
            "formatters, create commits, or perform network or write-side effects.\n"
            "Use the supplied RepoBrain context first, then verify with source files "
            "when needed. Cite concrete file paths and line numbers when possible.\n"
            "Return only JSON matching the provided output schema with keys: "
            "answer, sources, limitations."
        ),
        f"Workspace: {workspace}",
        f"Question:\n{question.strip()}",
    ]
    if context.strip():
        sections.append("RepoBrain context:\n" + context.strip())
    if retrieval_evidence and retrieval_evidence.strip():
        sections.append("Retrieval evidence:\n" + retrieval_evidence.strip())
    if graph_context and graph_context.strip():
        sections.append("Graph context:\n" + graph_context.strip())

    prompt = "\n\n".join(sections)
    if max_context_chars > 0 and len(prompt) > max_context_chars:
        overflow_note = (
            "\n\n[RepoBrain note: context was truncated to fit "
            f"RB_HOST_MAX_CONTEXT_CHARS={max_context_chars}.]"
        )
        prompt = prompt[: max(0, max_context_chars - len(overflow_note))] + overflow_note
    return prompt


# Backwards-compatible alias — some callers/tests may import the codex name.
_build_codex_prompt = _build_host_prompt


def _host_answer_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "answer": {"type": "string"},
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
            "limitations": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
        },
        "required": ["answer", "sources", "limitations"],
    }


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return [str(value)]
    return [str(item).strip() for item in value if str(item).strip()]


def _coerce_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_timeout(timeout_seconds: float | None) -> float:
    """Resolve the host-runner timeout from an explicit arg or env fallback."""
    return _coerce_float(
        timeout_seconds
        if timeout_seconds is not None
        else os.environ.get("RB_HOST_TIMEOUT_SECONDS"),
        DEFAULT_HOST_TIMEOUT_SECONDS,
    )


def _resolve_host_model(model: str | None) -> str | None:
    """Resolve the codex model from an explicit arg or env; None = let the CLI decide."""
    resolved = model if model is not None else os.environ.get("RB_HOST_MODEL")
    resolved = (resolved or "").strip()
    return resolved or None


def _resolve_max_context_chars(max_context_chars: int | None) -> int:
    """Resolve the max prompt size from an explicit arg or env fallback."""
    return _coerce_int(
        max_context_chars
        if max_context_chars is not None
        else os.environ.get("RB_HOST_MAX_CONTEXT_CHARS"),
        DEFAULT_HOST_MAX_CONTEXT_CHARS,
    )


def _redact_secrets(text: str) -> str:
    redacted = text
    for key, value in os.environ.items():
        key_upper = key.upper()
        if not value or len(value) < 4:
            continue
        if any(marker in key_upper for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
            redacted = redacted.replace(value, "<redacted>")
    redacted = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "sk-<redacted>", redacted)
    return redacted


# ---------------------------------------------------------------------------
# Free-form text generation (used by rb-refresh via HostRunnerModel)
#
# Unlike rb-ask, the refresh module swarm expects raw Markdown, not the
# answer/sources/limitations JSON envelope. These helpers run the same host CLI
# but return the model's text output verbatim.
# ---------------------------------------------------------------------------


def build_codex_text_command(
    *,
    workspace: Path,
    model: str | None,
    output_path: Path,
    prompt: str,
) -> list[str]:
    """Build ``codex exec`` for a read-only free-form text generation."""
    cmd = [
        "codex",
        "exec",
        "--cd",
        str(workspace),
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
    ]
    if model:
        cmd += ["--model", model]
    cmd += [
        "--output-last-message",
        str(output_path),
        prompt,
    ]
    return cmd


def run_host_text_generation(
    *,
    runner: str,
    prompt: str,
    workspace: Path,
    model: str | None = None,
    command: str | None = None,
    output_mode: str | None = None,
    timeout_seconds: float | None = None,
) -> str:
    """Run a host CLI for a single free-form text completion and return its text.

    This is the synchronous core shared by both the ``codex`` and ``generic``
    runners when driving ``rb-refresh`` through :class:`HostRunnerModel`.
    """
    runner_name = normalize_host_runner_name(runner)
    if runner_name not in SUPPORTED_HOST_RUNNERS:
        supported = ", ".join(sorted(SUPPORTED_HOST_RUNNERS))
        raise HostRunnerError(
            f"Unsupported host runner: {runner or '<empty>'}. "
            f"Supported values: {supported}."
        )

    timeout = _resolve_timeout(timeout_seconds)

    if runner_name == "codex":
        if shutil.which("codex") is None:
            raise HostRunnerError(
                "Codex CLI is not installed or not on PATH. Install Codex CLI and run "
                "`codex login` before using RB_HOST_RUNNER=codex."
            )
        model_name = _resolve_host_model(model)
        with tempfile.TemporaryDirectory(prefix="rb-host-runner-") as tmp_dir:
            output_path = Path(tmp_dir) / "codex_host_text.txt"
            cmd = build_codex_text_command(
                workspace=workspace,
                model=model_name,
                output_path=output_path,
                prompt=prompt,
            )
            completed = _run_host_subprocess(
                cmd, workspace=workspace, timeout=timeout, label="Codex host runner"
            )
            return _read_host_text(completed, output_path=output_path, label="Codex host runner")

    # generic
    template = command if command is not None else os.environ.get("RB_HOST_COMMAND")
    mode = normalize_generic_output_mode(
        output_mode if output_mode is not None else os.environ.get("RB_HOST_OUTPUT_MODE")
    )
    with tempfile.TemporaryDirectory(prefix="rb-host-runner-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        schema_path = tmp_path / "generic_host_answer.schema.json"
        output_path = tmp_path / "generic_host_text.txt"
        prompt_path = tmp_path / "generic_host_prompt.txt"
        # Schema is unused for text mode but kept so the same template works for
        # both ask (JSON) and refresh (text); the CLI may ignore {schema_file}.
        schema_path.write_text(
            json.dumps(_host_answer_schema(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        prompt_path.write_text(prompt, encoding="utf-8")

        argv, uses_prompt_file = build_generic_command(
            template=template,
            workspace=workspace,
            schema_path=schema_path,
            output_path=output_path,
            prompt_path=prompt_path,
        )
        executable = argv[0]
        if shutil.which(executable) is None and not Path(executable).exists():
            raise HostRunnerError(
                f"Generic host runner command not found on PATH: {executable!r}. "
                "Check RB_HOST_COMMAND points at an installed CLI."
            )
        stdin_text = None if uses_prompt_file else prompt
        completed = _run_host_subprocess(
            argv,
            workspace=workspace,
            timeout=timeout,
            label="Generic host runner",
            stdin_text=stdin_text,
        )
        expected_output = output_path if mode == "file" else None
        return _read_host_text(
            completed, output_path=expected_output, label="Generic host runner"
        )


def _read_host_text(
    completed: subprocess.CompletedProcess,
    *,
    output_path: Path | None,
    label: str,
) -> str:
    """Recover free-form text from an output file (if any) then stdout."""
    raw_output = ""
    if output_path is not None and output_path.is_file():
        raw_output = output_path.read_text(encoding="utf-8").strip()
    if not raw_output:
        raw_output = (completed.stdout or "").strip()
    if not raw_output:
        raise HostRunnerError(f"{label} returned no output.")
    return raw_output


class HostRunnerModel:
    """An Agents-SDK ``Model`` backed by a local headless CLI (no API key).

    This lets ``rb-refresh`` drive the preloaded module swarm through the user's
    local Codex login or any generic CLI. It only supports **single-turn,
    text-only** generation: agents that require function/tool calling or
    handoffs cannot be represented faithfully by a text-only CLI and raise a
    clear error so the caller can fall back.

    The SDK's runner resolves ``agent.model`` with ``isinstance(model, Model)``
    where ``Model`` is an ABC. We register this class as a *virtual* subclass
    lazily (see :func:`_register_as_agents_model`) so the ask-only host-runner
    path never has to import ``agents`` while refresh can still hand a
    ``HostRunnerModel`` straight to ``Runner.run``.
    """

    def __init__(
        self,
        *,
        runner: str,
        workspace: Path,
        model: str | None = None,
        command: str | None = None,
        output_mode: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        _register_as_agents_model()
        self._runner = normalize_host_runner_name(runner)
        self._workspace = workspace
        self._model = model
        self._command = command
        self._output_mode = output_mode
        self._timeout_seconds = timeout_seconds

    async def get_response(
        self,
        system_instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        *,
        previous_response_id=None,
        conversation_id=None,
        prompt=None,
        **kwargs,
    ):
        import asyncio

        from agents.items import ModelResponse
        from agents.usage import Usage

        if tools:
            raise HostRunnerError(
                "HostRunnerModel does not support tool calls. The "
                f"'{self._runner}' host runner can only drive tool-free, "
                "single-turn agents (e.g. the preloaded refresh module swarm)."
            )
        if handoffs:
            raise HostRunnerError(
                "HostRunnerModel does not support handoffs. The "
                f"'{self._runner}' host runner can only drive single-agent, "
                "single-turn generation."
            )

        composed = _compose_model_prompt(system_instructions, input)
        text = await asyncio.to_thread(
            run_host_text_generation,
            runner=self._runner,
            prompt=composed,
            workspace=self._workspace,
            model=self._model,
            command=self._command,
            output_mode=self._output_mode,
            timeout_seconds=self._timeout_seconds,
        )

        output_item = _build_text_output_item(text)
        return ModelResponse(output=[output_item], usage=Usage(), response_id=None)

    def stream_response(self, *args, **kwargs):
        raise HostRunnerError(
            "HostRunnerModel does not support streaming responses. "
            "Run refresh without STREAM_ENABLED when using a host runner."
        )

    # -- SDK Model helpers ---------------------------------------------------
    # The runner calls these non-abstract ``Model`` helpers directly. Because
    # HostRunnerModel is registered as a *virtual* subclass (not inherited) it
    # does not pick up their defaults, so we mirror the SDK's no-op behavior.

    def get_retry_advice(self, request):
        """No provider-specific retry guidance for a local CLI."""
        return None

    async def _cleanup_on_run_end(self, owner) -> None:
        """No run-scoped resources to release for a subprocess-backed model."""
        return None


def _compose_model_prompt(system_instructions, input) -> str:
    """Flatten SDK system instructions + input items into a single prompt."""
    parts: list[str] = []
    if system_instructions:
        parts.append(str(system_instructions).strip())

    if isinstance(input, str):
        parts.append(input.strip())
    elif isinstance(input, list):
        for item in input:
            parts.append(_stringify_input_item(item))
    elif input is not None:
        parts.append(str(input))

    return "\n\n".join(part for part in parts if part and part.strip())


def _stringify_input_item(item: Any) -> str:
    """Best-effort extraction of text from an SDK input item."""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        content = item.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text") or block.get("content")
                    if isinstance(text, str):
                        texts.append(text)
                elif isinstance(block, str):
                    texts.append(block)
            if texts:
                return "\n".join(texts).strip()
        # Fall back to a stable string form for unknown dict shapes.
        return json.dumps(item, ensure_ascii=False, sort_keys=True)
    return str(item)


def _build_text_output_item(text: str):
    """Wrap free-form text in a ResponseOutputMessage the SDK understands."""
    from openai.types.responses import ResponseOutputMessage, ResponseOutputText

    return ResponseOutputMessage(
        id="rb-host-runner",
        content=[ResponseOutputText(text=text, type="output_text", annotations=[])],
        role="assistant",
        status="completed",
        type="message",
    )


_registered_as_agents_model = False


def _register_as_agents_model() -> None:
    """Register :class:`HostRunnerModel` as a virtual subclass of ``agents.Model``.

    The SDK runner resolves an agent's model with ``isinstance(model, Model)``.
    Registering here (only when the SDK is importable) makes a
    ``HostRunnerModel`` satisfy that check without ``HostRunnerModel`` having to
    inherit from ``Model`` at import time — keeping the ask-only host-runner
    path independent of the ``agents`` package. Best-effort: if the SDK is not
    installed, refresh will surface a clear ImportError elsewhere.
    """
    global _registered_as_agents_model
    if _registered_as_agents_model:
        return
    try:
        from agents.models.interface import Model
    except ImportError:
        return
    Model.register(HostRunnerModel)
    _registered_as_agents_model = True
