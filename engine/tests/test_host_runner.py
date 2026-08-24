"""Tests for local host runner integration."""
from __future__ import annotations

import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from repobrain_engine.hub.host_runner import (
    SUPPORTED_HOST_RUNNERS,
    HostRunnerError,
    HostRunnerModel,
    build_codex_command,
    build_generic_command,
    is_host_runner_enabled,
    is_host_runner_model,
    normalize_generic_output_mode,
    parse_host_runner_answer,
    run_codex_host_runner,
    run_generic_host_runner,
    run_host_runner,
    run_host_text_generation,
)


def test_codex_command_constructs_read_only_exec(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.json"
    output_path = tmp_path / "answer.json"

    cmd = build_codex_command(
        workspace=tmp_path,
        model="gpt-5.3-codex-spark",
        schema_path=schema_path,
        output_path=output_path,
        prompt="answer this",
    )

    assert cmd[:2] == ["codex", "exec"]
    assert cmd[cmd.index("--cd") + 1] == str(tmp_path)
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in cmd
    assert "--skip-git-repo-check" in cmd
    assert cmd[cmd.index("--model") + 1] == "gpt-5.3-codex-spark"
    assert cmd[cmd.index("--output-schema") + 1] == str(schema_path)
    assert cmd[cmd.index("--output-last-message") + 1] == str(output_path)
    assert cmd[-1] == "answer this"


@pytest.mark.asyncio
async def test_missing_codex_cli_has_clear_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: None)

    with pytest.raises(HostRunnerError, match="Codex CLI is not installed"):
        await run_codex_host_runner(
            workspace=tmp_path,
            question="What is this?",
            context="context",
        )


@pytest.mark.asyncio
async def test_codex_timeout_reports_deadline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/codex")

    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr("subprocess.run", _timeout)

    with pytest.raises(HostRunnerError, match="timed out after 1s"):
        await run_codex_host_runner(
            workspace=tmp_path,
            question="What is this?",
            context="context",
            timeout_seconds=1,
        )


@pytest.mark.asyncio
async def test_codex_output_last_message_json_is_parsed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/codex")
    seen: dict[str, list[str]] = {}

    def _run(cmd, **kwargs):
        seen["cmd"] = cmd
        output_path = Path(cmd[cmd.index("--output-last-message") + 1])
        output_path.write_text(
            '{"answer": "It uses host mode.", "sources": ["a.py:1"], "limitations": []}',
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", _run)

    answer = await run_codex_host_runner(
        workspace=tmp_path,
        question="What is this?",
        context="context",
        retrieval_evidence="evidence",
        model="gpt-5.3-codex-spark",
    )

    assert answer.answer == "It uses host mode."
    assert answer.sources == ["a.py:1"]
    assert seen["cmd"][0:2] == ["codex", "exec"]


def test_non_json_output_is_diagnostic() -> None:
    with pytest.raises(HostRunnerError, match="non-JSON output"):
        parse_host_runner_answer("plain text answer")


@pytest.mark.asyncio
async def test_codex_failure_redacts_env_secrets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/codex")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-value")

    def _run(*args, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="provider rejected sk-super-secret-value",
        )

    monkeypatch.setattr("subprocess.run", _run)

    with pytest.raises(HostRunnerError) as excinfo:
        await run_codex_host_runner(
            workspace=tmp_path,
            question="What is this?",
            context="context",
        )

    message = str(excinfo.value)
    assert "sk-super-secret-value" not in message
    assert "<redacted>" in message


# ---------------------------------------------------------------------------
# Generic host runner (portable to any headless agent CLI)
# ---------------------------------------------------------------------------


def _write_fake_cli(tmp_path: Path, name: str, body: str) -> Path:
    """Write an executable POSIX shell script acting as a fake host CLI."""
    script = tmp_path / name
    script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


def test_registry_includes_codex_and_generic() -> None:
    assert {"codex", "generic"} <= set(SUPPORTED_HOST_RUNNERS)
    assert is_host_runner_enabled("codex")
    assert is_host_runner_enabled("generic")
    assert is_host_runner_enabled("GENERIC ")
    assert not is_host_runner_enabled("trae")
    assert not is_host_runner_enabled("")


def test_generic_command_substitutes_placeholders(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.json"
    output_path = tmp_path / "out.json"
    prompt_path = tmp_path / "prompt.txt"

    argv, uses_prompt_file = build_generic_command(
        template="mycli exec --prompt {prompt_file} --schema {schema_file} "
        "--out {output_file} --cwd {workspace}",
        workspace=tmp_path,
        schema_path=schema_path,
        output_path=output_path,
        prompt_path=prompt_path,
    )

    assert uses_prompt_file is True
    assert argv[0:2] == ["mycli", "exec"]
    assert argv[argv.index("--prompt") + 1] == str(prompt_path)
    assert argv[argv.index("--schema") + 1] == str(schema_path)
    assert argv[argv.index("--out") + 1] == str(output_path)
    assert argv[argv.index("--cwd") + 1] == str(tmp_path)


def test_generic_command_without_prompt_placeholder_signals_stdin(tmp_path: Path) -> None:
    argv, uses_prompt_file = build_generic_command(
        template="mycli exec",
        workspace=tmp_path,
        schema_path=tmp_path / "s.json",
        output_path=tmp_path / "o.json",
        prompt_path=tmp_path / "p.txt",
    )
    assert argv == ["mycli", "exec"]
    assert uses_prompt_file is False


def test_generic_command_empty_template_is_diagnostic(tmp_path: Path) -> None:
    with pytest.raises(HostRunnerError, match="RB_HOST_COMMAND"):
        build_generic_command(
            template="   ",
            workspace=tmp_path,
            schema_path=tmp_path / "s.json",
            output_path=tmp_path / "o.json",
            prompt_path=tmp_path / "p.txt",
        )


def test_normalize_generic_output_mode() -> None:
    assert normalize_generic_output_mode(None) == "file"
    assert normalize_generic_output_mode("") == "file"
    assert normalize_generic_output_mode("STDOUT") == "stdout"
    with pytest.raises(HostRunnerError, match="RB_HOST_OUTPUT_MODE"):
        normalize_generic_output_mode("pipe")


@pytest.mark.asyncio
async def test_generic_runner_file_mode_reads_output_file(tmp_path: Path) -> None:
    cli = _write_fake_cli(
        tmp_path,
        "fakehost",
        # Writes JSON to the file passed after --out.
        'while [ "$1" != "--out" ]; do shift; done\n'
        'shift\n'
        'printf \'{"answer":"from file","sources":["x.py:1"],"limitations":[]}\' > "$1"\n',
    )

    answer = await run_generic_host_runner(
        workspace=tmp_path,
        question="What?",
        context="ctx",
        command=f"{cli} --out {{output_file}} --prompt {{prompt_file}}",
        output_mode="file",
        timeout_seconds=30,
    )

    assert answer.answer == "from file"
    assert answer.sources == ["x.py:1"]


@pytest.mark.asyncio
async def test_generic_runner_stdout_mode_reads_stdout(tmp_path: Path) -> None:
    cli = _write_fake_cli(
        tmp_path,
        "fakehost_stdout",
        'printf \'{"answer":"from stdout","sources":[],"limitations":["partial"]}\'\n',
    )

    answer = await run_generic_host_runner(
        workspace=tmp_path,
        question="What?",
        context="ctx",
        command=f"{cli} --prompt {{prompt_file}}",
        output_mode="stdout",
        timeout_seconds=30,
    )

    assert answer.answer == "from stdout"
    assert answer.limitations == ["partial"]


@pytest.mark.asyncio
async def test_generic_runner_feeds_prompt_on_stdin_without_placeholder(tmp_path: Path) -> None:
    # No {prompt_file} in the template -> prompt should arrive on stdin.
    # The fake CLI echoes back a JSON answer embedding the stdin length so we can
    # assert the prompt was actually piped in.
    cli = _write_fake_cli(
        tmp_path,
        "fakehost_stdin",
        'input=$(cat)\n'
        'case "$input" in\n'
        '  *"unique-question-marker"*)\n'
        '    printf \'{"answer":"got stdin","sources":[],"limitations":[]}\' ;;\n'
        '  *)\n'
        '    printf \'{"answer":"no stdin","sources":[],"limitations":[]}\' ;;\n'
        'esac\n',
    )

    answer = await run_generic_host_runner(
        workspace=tmp_path,
        question="unique-question-marker",
        context="ctx",
        command=f"{cli}",
        output_mode="stdout",
        timeout_seconds=30,
    )

    assert answer.answer == "got stdin"


@pytest.mark.asyncio
async def test_generic_runner_missing_command_is_diagnostic(tmp_path: Path) -> None:
    with pytest.raises(HostRunnerError, match="RB_HOST_COMMAND"):
        await run_generic_host_runner(
            workspace=tmp_path,
            question="What?",
            context="ctx",
            command="",
            timeout_seconds=30,
        )


@pytest.mark.asyncio
async def test_generic_runner_missing_executable_is_diagnostic(tmp_path: Path) -> None:
    with pytest.raises(HostRunnerError, match="not found on PATH"):
        await run_generic_host_runner(
            workspace=tmp_path,
            question="What?",
            context="ctx",
            command="rb-nonexistent-cli-xyz --prompt {prompt_file}",
            timeout_seconds=30,
        )


@pytest.mark.asyncio
async def test_generic_runner_failure_redacts_env_secrets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MY_API_KEY", "sk-super-secret-value")
    cli = _write_fake_cli(
        tmp_path,
        "fakehost_fail",
        'echo "provider rejected sk-super-secret-value" 1>&2\n'
        'exit 3\n',
    )

    with pytest.raises(HostRunnerError) as excinfo:
        await run_generic_host_runner(
            workspace=tmp_path,
            question="What?",
            context="ctx",
            command=f"{cli}",
            output_mode="stdout",
            timeout_seconds=30,
        )

    message = str(excinfo.value)
    assert "sk-super-secret-value" not in message
    assert "<redacted>" in message


@pytest.mark.asyncio
async def test_generic_runner_timeout_reports_deadline(tmp_path: Path) -> None:
    cli = _write_fake_cli(tmp_path, "fakehost_slow", "sleep 5\n")

    with pytest.raises(HostRunnerError, match="timed out after"):
        await run_generic_host_runner(
            workspace=tmp_path,
            question="What?",
            context="ctx",
            command=f"{cli}",
            output_mode="stdout",
            timeout_seconds=1,
        )


@pytest.mark.asyncio
async def test_run_host_runner_dispatches_generic(tmp_path: Path) -> None:
    cli = _write_fake_cli(
        tmp_path,
        "fakehost_dispatch",
        'printf \'{"answer":"dispatched","sources":[],"limitations":[]}\'\n',
    )

    markdown = await run_host_runner(
        runner="generic",
        workspace=tmp_path,
        question="What?",
        context="ctx",
        command=f"{cli}",
        output_mode="stdout",
        timeout_seconds=30,
    )

    assert "dispatched" in markdown


@pytest.mark.asyncio
async def test_run_host_runner_rejects_unknown_runner(tmp_path: Path) -> None:
    with pytest.raises(HostRunnerError, match="Supported values"):
        await run_host_runner(
            runner="trae",
            workspace=tmp_path,
            question="What?",
            context="ctx",
        )


# ---------------------------------------------------------------------------
# HostRunnerModel — Agents-SDK Model adapter for rb-refresh (no API key)
# ---------------------------------------------------------------------------


def _settings(**overrides) -> SimpleNamespace:
    """Build a minimal Settings-like object for create_model()."""
    base = dict(
        OPENAI_BASE_URL="",
        OPENAI_API_KEY="",
        OPENAI_MODEL="gpt-4o-mini",
        RB_HOST_RUNNER="",
        RB_HOST_MODEL="gpt-5.3-codex-spark",
        RB_HOST_COMMAND="",
        RB_HOST_OUTPUT_MODE="file",
        RB_HOST_TIMEOUT_SECONDS=240.0,
        project_root_path=Path("."),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_create_model_prefers_api_key_over_host_runner() -> None:
    from repobrain_engine.hub.agents import create_model

    # Even with a host runner configured, a real API backend wins.
    model = create_model(
        _settings(OPENAI_API_KEY="sk-x", RB_HOST_RUNNER="generic", RB_HOST_COMMAND="cli")
    )
    assert model == "gpt-4o-mini"
    assert not is_host_runner_model(model)


def test_create_model_prefers_base_url_over_host_runner(monkeypatch) -> None:
    from repobrain_engine.hub.agents import create_model

    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    model = create_model(
        _settings(OPENAI_BASE_URL="http://localhost:11434/v1", RB_HOST_RUNNER="codex")
    )
    assert model == "litellm/openai/gpt-4o-mini"
    assert not is_host_runner_model(model)


def test_create_model_falls_back_to_host_runner_without_api_key() -> None:
    from repobrain_engine.hub.agents import create_model

    model = create_model(
        _settings(RB_HOST_RUNNER="generic", RB_HOST_COMMAND="cli {prompt_file}")
    )
    assert isinstance(model, HostRunnerModel)
    assert is_host_runner_model(model)


def test_create_model_without_any_backend_raises() -> None:
    from repobrain_engine.hub.agents import create_model

    with pytest.raises(ValueError, match="No LLM configured"):
        create_model(_settings())


def test_host_runner_model_is_virtual_agents_model() -> None:
    from agents.models.interface import Model

    model = HostRunnerModel(
        runner="generic", workspace=Path("."), command="cli {prompt_file}"
    )
    # The SDK runner resolves agent.model with isinstance(model, Model).
    assert isinstance(model, Model)


def test_is_host_runner_model_rejects_plain_strings() -> None:
    assert is_host_runner_model("gpt-4o") is False
    assert is_host_runner_model(None) is False


@pytest.mark.asyncio
async def test_host_runner_model_text_generation_via_generic_cli(tmp_path: Path) -> None:
    from agents.model_settings import ModelSettings
    from agents.models.interface import ModelTracing

    cli = _write_fake_cli(
        tmp_path,
        "faketext",
        # Consume stdin, emit raw Markdown (no JSON envelope) on stdout.
        'cat > /dev/null\n'
        'printf \'# Module\\n\\nDoes things.\'\n',
    )
    model = HostRunnerModel(
        runner="generic",
        workspace=tmp_path,
        command=f"{cli}",
        output_mode="stdout",
        timeout_seconds=30,
    )

    response = await model.get_response(
        "You are a refresh module agent.",
        "Analyze the preloaded source.",
        ModelSettings(),
        [],  # no tools
        None,
        [],  # no handoffs
        ModelTracing.DISABLED,
        previous_response_id=None,
        conversation_id=None,
        prompt=None,
    )

    text = response.output[0].content[0].text
    assert text == "# Module\n\nDoes things."


@pytest.mark.asyncio
async def test_host_runner_model_rejects_tools(tmp_path: Path) -> None:
    from agents.model_settings import ModelSettings
    from agents.models.interface import ModelTracing

    model = HostRunnerModel(runner="codex", workspace=tmp_path)
    with pytest.raises(HostRunnerError, match="does not support tool calls"):
        await model.get_response(
            "sys",
            "q",
            ModelSettings(),
            [object()],  # non-empty tools
            None,
            [],
            ModelTracing.DISABLED,
            previous_response_id=None,
            conversation_id=None,
            prompt=None,
        )


@pytest.mark.asyncio
async def test_host_runner_model_rejects_handoffs(tmp_path: Path) -> None:
    from agents.model_settings import ModelSettings
    from agents.models.interface import ModelTracing

    model = HostRunnerModel(runner="codex", workspace=tmp_path)
    with pytest.raises(HostRunnerError, match="does not support handoffs"):
        await model.get_response(
            "sys",
            "q",
            ModelSettings(),
            [],
            None,
            [object()],  # non-empty handoffs
            ModelTracing.DISABLED,
            previous_response_id=None,
            conversation_id=None,
            prompt=None,
        )


def test_host_runner_model_rejects_streaming(tmp_path: Path) -> None:
    model = HostRunnerModel(runner="codex", workspace=tmp_path)
    with pytest.raises(HostRunnerError, match="does not support streaming"):
        model.stream_response()


@pytest.mark.asyncio
async def test_host_runner_model_drives_single_turn_agent_end_to_end(tmp_path: Path) -> None:
    """A real Runner.run over a tool-free agent works through HostRunnerModel."""
    from agents import Agent, Runner, set_tracing_disabled

    set_tracing_disabled(True)
    cli = _write_fake_cli(
        tmp_path,
        "faketext_e2e",
        'cat > /dev/null\n'
        'printf \'# Conventions\\n\\nPython project.\'\n',
    )
    model = HostRunnerModel(
        runner="generic",
        workspace=tmp_path,
        command=f"{cli}",
        output_mode="stdout",
        timeout_seconds=30,
    )
    agent = Agent(name="ConvSingle", instructions="Write conventions.", model=model)

    result = await Runner.run(agent, "Analyze the scan report and write conventions.")

    assert result.final_output == "# Conventions\n\nPython project."


def test_run_host_text_generation_rejects_unknown_runner(tmp_path: Path) -> None:
    with pytest.raises(HostRunnerError, match="Supported values"):
        run_host_text_generation(
            runner="trae",
            prompt="hi",
            workspace=tmp_path,
        )


def test_run_host_text_generation_generic_stdout(tmp_path: Path) -> None:
    cli = _write_fake_cli(
        tmp_path,
        "faketext_stdout",
        'cat > /dev/null\n'
        'printf \'plain markdown, not json\'\n',
    )
    text = run_host_text_generation(
        runner="generic",
        prompt="Summarize.",
        workspace=tmp_path,
        command=f"{cli}",
        output_mode="stdout",
        timeout_seconds=30,
    )
    assert text == "plain markdown, not json"
