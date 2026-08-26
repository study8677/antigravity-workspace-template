"""
RepoBrain CLI – rb init <target_dir>

Copies portable RepoBrain context files into any project directory so AI IDEs
can share the same repository knowledge entrypoints.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from importlib import resources as importlib_resources
from importlib.util import find_spec
from pathlib import Path
from typing import Final

import typer
from rich.console import Console

from rb_cli.reader import append_to_memory, append_decision
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree

# Use a group (rich_markup_mode) so subcommands like `rb init` are not
# flattened into the root command by Typer's single-command optimisation.
app = typer.Typer(
    name="rb",
    help="RepoBrain – inject portable AI repository context into any project.",
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()


# ── Helpers ─────────────────────────────────────────────────────────


def _get_templates_dir() -> Path:
    """Return the absolute path to the bundled templates/ directory.

    Works both in editable installs and built wheels because hatch
    force-includes the directory into the package.
    """
    pkg_root = importlib_resources.files("rb_cli")
    templates = pkg_root / "templates"
    # importlib.resources may return a Traversable; resolve to a real Path.
    return Path(str(templates))


def _copy_tree(src: Path, dst: Path, force: bool = False) -> list[str]:
    """Recursively copy *src* into *dst*, preserving dotfiles.

    Args:
        src: Source directory to copy from.
        dst: Destination directory to copy into.
        force: If True, overwrite existing files.

    Returns a list of relative paths that were created.
    """
    created: list[str] = []
    for item in sorted(src.rglob("*")):
        if item.name == "__pycache__":
            continue
        relative = item.relative_to(src)
        target = dst / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if force or not target.exists():
                shutil.copy2(item, target)
            created.append(str(relative))
    return created


_REPO_ROOT = Path(__file__).resolve().parents[3]  # cli/src/rb_cli/cli.py → repo root
_ENGINE_SCRIPTS: Final[dict[str, str]] = {
    "ask": "rb-ask",
    "refresh": "rb-refresh",
    "mcp": "rb-mcp",
}
_INSTALL_ENGINE_HINT: Final[str] = (
    "pip install ./engine or pip install "
    "\"git+https://github.com/study8677/repobrain.git#subdirectory=engine\""
)


def _run_hub(workspace: Path, *args: str) -> int:
    """Run a supported engine-backed command.

    Args:
        workspace: Target project root.
        *args: Command name followed by command-specific arguments.

    Returns:
        Exit code from the delegated engine process.
    """
    import subprocess

    if not args:
        console.print("[red]No engine command provided.[/red]")
        return 1

    command = args[0]
    script_name = _ENGINE_SCRIPTS.get(command)
    if script_name is None:
        console.print(f"[red]Unsupported engine command: {command}[/red]")
        return 1

    script_path = shutil.which(script_name)
    if script_path:
        cmd = [script_path] + list(args[1:]) + ["--workspace", str(workspace)]
        return subprocess.run(cmd, check=False).returncode

    engine_dir = _REPO_ROOT / "engine"
    if (engine_dir / "repobrain_engine" / "__main__.py").exists():
        cmd = [
            sys.executable,
            "-m",
            "repobrain_engine",
            command,
            *args[1:],
            "--workspace",
            str(workspace),
        ]
        return subprocess.run(cmd, cwd=str(engine_dir), check=False).returncode

    console.print(f"[red]Engine not installed. Install: {_INSTALL_ENGINE_HINT}[/red]")
    return 1


def _load_workspace_env(workspace: Path) -> tuple[bool, dict[str, str]]:
    """Load simple KEY=VALUE entries from the workspace .env plus process env."""
    env_path = workspace / ".env"
    values: dict[str, str] = {}
    if env_path.is_file():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key:
                values[key] = value
    for key in (
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "RB_HOST_RUNNER",
    ):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return env_path.is_file(), values


def _mask_secret(value: str) -> str:
    """Mask an API key, preserving only the first and last four characters."""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _one_line_error(exc: BaseException) -> str:
    """Return an exception message safe for one-line CLI output."""
    message = str(exc).replace("\n", " ").replace("\r", " ").strip()
    return message or exc.__class__.__name__


def _mcp_log_path() -> Path:
    """Return the rb-mcp diagnostic log path without importing the engine."""
    data_dir = os.environ.get("CLAUDE_PLUGIN_DATA_DIR", "").strip()
    if data_dir:
        base = Path(data_dir).expanduser()
    else:
        base = Path.home() / ".claude" / "plugins" / "data" / "repobrain-repobrain"
    return base / "rb-mcp.log"


def _engine_is_available() -> tuple[bool, str]:
    """Return whether the engine can be invoked and the human-readable source."""
    script = shutil.which("rb-ask")
    if script:
        return True, f"rb-ask at {script}"
    if find_spec("repobrain_engine") is not None:
        return True, "repobrain_engine importable"
    return False, f"not found; install: {_INSTALL_ENGINE_HINT}"


def _check_provider(env_values: dict[str, str]) -> tuple[str, str]:
    """Check configured provider reachability."""
    host_runner = env_values.get("RB_HOST_RUNNER", "").strip().lower()
    if host_runner == "codex":
        codex = shutil.which("codex")
        if not codex:
            return "⚠", "codex CLI not found on PATH"
        try:
            result = subprocess.run(
                [codex, "login", "status"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "⚠", _one_line_error(exc)
        if result.returncode != 0:
            error = (
                result.stderr
                or result.stdout
                or f"exit {result.returncode}"
            ).strip()
            return "⚠", _one_line_error(RuntimeError(error))
        return "✓", "codex host runner login status ok"

    base_url = env_values.get("OPENAI_BASE_URL", "").rstrip("/")
    api_key = env_values.get("OPENAI_API_KEY", "")
    if not base_url or not api_key:
        return "⚠", "provider not checked because OpenAI-compatible config is incomplete"
    models_url = f"{base_url}/models"
    try:
        import requests
    except ImportError:
        request = urllib.request.Request(
            models_url,
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=5):
                pass
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            return "⚠", _one_line_error(exc)
    else:
        try:
            response = requests.get(
                models_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=5,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - doctor should report raw provider errors
            return "⚠", _one_line_error(exc)
    return "✓", f"GET {models_url} ok"


def _git_commit_lag(workspace: Path) -> str:
    """Return a human-readable freshness summary against git HEAD."""
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"git skipped ({_one_line_error(exc)})"
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return "git freshness skipped (not a git repository)"

    sha_path = workspace / ".repobrain" / ".last_refresh_sha"
    try:
        last_sha = sha_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ".last_refresh_sha missing"
    if not last_sha:
        return ".last_refresh_sha empty"

    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"{last_sha}..HEAD"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"git freshness skipped ({_one_line_error(exc)})"
    if result.returncode != 0:
        error = _one_line_error(RuntimeError(result.stderr or result.stdout))
        return f"git freshness skipped ({error})"
    return f"{int(result.stdout.strip() or '0')} commit(s) behind HEAD"


def _active_knowledge_root(workspace: Path) -> Path:
    """Resolve a generation pointer without importing the optional engine."""
    control = workspace / ".repobrain"
    pointer_path = control / "current.json"
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return control
    if not isinstance(pointer, dict):
        return control
    generation = str(pointer.get("generation", "")).strip()
    if not generation or Path(generation).name != generation:
        return control
    candidate = control / "generations" / generation
    return candidate if candidate.is_dir() else control


def _status_health(workspace: Path) -> str:
    """Return partial/failed module and group counts from status.json."""
    status_path = _active_knowledge_root(workspace) / "status.json"
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "status.json missing"
    except (json.JSONDecodeError, OSError, TypeError) as exc:
        return f"status.json unreadable ({_one_line_error(exc)})"
    if not isinstance(payload, dict):
        return "status.json unreadable (not an object)"

    def _count_degraded(name: str) -> int:
        values = payload.get(name, {})
        if not isinstance(values, dict):
            return 0
        return sum(1 for state in values.values() if state in {"partial", "failed", "unresolved"})

    return (
        f"{_count_degraded('modules')} partial/failed module(s), "
        f"{_count_degraded('groups')} partial/failed group(s)"
    )


def _knowledge_health(workspace: Path) -> tuple[str, str]:
    """Check .repobrain artifact existence and health summaries."""
    control_dir = workspace / ".repobrain"
    rb_dir = _active_knowledge_root(workspace)
    map_path = rb_dir / "map.md"
    agents_dir = rb_dir / "agents"
    missing = [
        label
        for label, exists in (
            (".repobrain/", control_dir.is_dir()),
            ("map.md", map_path.is_file()),
            ("agents/", agents_dir.is_dir()),
        )
        if not exists
    ]
    existence = "artifacts present" if not missing else f"missing {', '.join(missing)}"
    lag = _git_commit_lag(workspace)
    status = _status_health(workspace)
    degraded = not lag.startswith("0 commit(s)") and not lag.startswith(
        "git freshness skipped"
    )
    degraded = degraded or not status.startswith(
        "0 partial/failed module(s), 0 partial/failed group(s)"
    )
    prefix = "⚠" if missing or degraded else "✓"
    return prefix, f"{existence}; {lag}; {status}"


def _doctor_print(message: str) -> None:
    """Print doctor output literally, without Rich markup or link wrapping."""
    console.print(Text(message), soft_wrap=True)

# ── Commands ────────────────────────────────────────────────────────


@app.command("init")
def init_cmd(
    target_dir: str = typer.Argument(
        ...,
        help="Directory to inject RepoBrain context into.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing files instead of skipping them.",
    ),
) -> None:
    """Inject RepoBrain context files into TARGET_DIR."""

    target = Path(target_dir).resolve()

    # ── Pre-flight checks ───────────────────────────────────────────
    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)
        console.print(f"[dim]Created directory [bold]{target}[/bold][/dim]")

    templates = _get_templates_dir()
    if not templates.exists():
        console.print(
            "[bold red]✗[/bold red] Templates directory not found. "
            "Is the package installed correctly?",
        )
        raise typer.Exit(code=1)

    # ── Copy templates with spinner ─────────────────────────────────
    with console.status(
        "[cyan]⚛  Injecting RepoBrain context files…[/cyan]",
        spinner="dots",
    ):
        created = _copy_tree(templates, target, force=force)
        # let the user enjoy the spinner for a beat
        time.sleep(0.6)

    # ── Create artifacts scaffold ───────────────────────────────────
    with console.status(
        "[magenta]📂  Scaffolding artifacts directory…[/magenta]",
        spinner="dots",
    ):
        (target / "artifacts" / "logs").mkdir(parents=True, exist_ok=True)
        (target / "artifacts" / ".gitkeep").touch()
        (target / "artifacts" / "logs" / ".gitkeep").touch()
        time.sleep(0.3)

    # ── Success panel ───────────────────────────────────────────────
    tree = Tree(f"[bold green]{target.name}/[/bold green]")
    for path_str in created:
        tree.add(f"[dim]{path_str}[/dim]")
    artifacts_node = tree.add("[bold green]artifacts/[/bold green]")
    artifacts_node.add("[dim]logs/[/dim]")

    console.print()
    console.print(tree)
    console.print()

    next_steps = Text.assemble(
        ("Next steps:\n\n", "bold"),
        ("  1. ", "bold cyan"),
        ("cd ", ""),
        (str(target), "bold"),
        ("\n", ""),
        ("  2. ", "bold cyan"),
        ("Open the directory in your AI IDE (Cursor, VS Code, Windsurf…)\n", ""),
        ("  3. ", "bold cyan"),
        ("Start prompting — RepoBrain context is already loaded.\n", ""),
    )

    console.print(
        Panel(
            next_steps,
            title="[bold green]✔ RepoBrain initialized[/bold green]",
            border_style="green",
            padding=(1, 2),
        ),
    )


# ── Version ──────────────────────────────────────────────────────────


@app.command("version")
def version_cmd() -> None:
    """Print the CLI version."""
    from rb_cli import __version__

    console.print(f"[bold cyan]rb[/bold cyan] v{__version__}")


# ── Hub Commands ─────────────────────────────────────────────────────


@app.command("ask")
def ask_cmd(
    question: str = typer.Argument(..., help="Question about the project."),
    workspace: str = typer.Option(".", "--workspace", "-w", help="Project directory."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit a machine-readable JSON envelope for programmatic callers.",
    ),
) -> None:
    """Ask a question about the project (requires LLM)."""
    workspace_path = Path(workspace).resolve()
    args = ["ask", question]
    if json_output:
        args.append("--json")
    code = _run_hub(workspace_path, *args)
    raise typer.Exit(code=code)


@app.command("refresh")
def refresh_cmd(
    workspace: str = typer.Option(".", "--workspace", "-w", help="Project directory."),
    quick: bool = typer.Option(
        False,
        "--quick",
        help="Judge committed diff impact and update only affected Agent groups.",
    ),
    failed_only: bool = typer.Option(
        False,
        "--failed-only",
        help="Resume failed/pending groups for the current target commit.",
    ),
) -> None:
    """Refresh project context in .repobrain/ (requires LLM)."""
    workspace_path = Path(workspace).resolve()
    args: list[str] = ["refresh"]
    if quick:
        args.append("--quick")
    if failed_only:
        args.append("--failed-only")
    code = _run_hub(workspace_path, *args)
    raise typer.Exit(code=code)


@app.command("doctor")
def doctor_cmd(
    workspace: str = typer.Option(".", "--workspace", "-w", help="Project directory."),
) -> None:
    """Diagnose RepoBrain first-run and provider configuration."""
    workspace_path = Path(workspace).resolve()
    blocking = False

    engine_ok, engine_detail = _engine_is_available()
    if engine_ok:
        _doctor_print(f"✓ Engine install: {engine_detail}")
    else:
        _doctor_print(f"✗ Engine install: {engine_detail}")
        blocking = True

    env_exists, env_values = _load_workspace_env(workspace_path)
    openai_keys = ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")
    missing = [key for key in openai_keys if not env_values.get(key)]
    host_runner = env_values.get("RB_HOST_RUNNER", "").strip().lower()
    openai_ready = not missing
    codex_ready = host_runner == "codex"
    config_source = ".env" if env_exists else "process env"
    if openai_ready:
        key = _mask_secret(env_values.get("OPENAI_API_KEY", ""))
        _doctor_print(
            f"✓ {config_source} config: "
            f"OPENAI_BASE_URL={env_values['OPENAI_BASE_URL']}; "
            f"OPENAI_API_KEY={key}; "
            f"OPENAI_MODEL={env_values['OPENAI_MODEL']}"
        )
    elif codex_ready:
        _doctor_print(f"✓ {config_source} config: RB_HOST_RUNNER=codex")
    else:
        reason = ".env missing" if not env_exists else f"missing {', '.join(missing)}"
        _doctor_print(f"✗ .env config: {reason}; run rb-setup")
        blocking = True

    provider_prefix, provider_detail = _check_provider(env_values)
    _doctor_print(f"{provider_prefix} Provider reachability: {provider_detail}")

    knowledge_prefix, knowledge_detail = _knowledge_health(workspace_path)
    _doctor_print(f"{knowledge_prefix} Knowledge base health: {knowledge_detail}")

    _doctor_print(f"✓ Log location: rb-mcp diagnostic log: {_mcp_log_path()}")

    raise typer.Exit(code=1 if blocking else 0)


@app.command("report")
def report_cmd(
    message: str = typer.Argument(..., help="Report message to log."),
    workspace: str = typer.Option(".", "--workspace", "-w", help="Project directory."),
) -> None:
    """Log a report to .repobrain/memory/reports.md (no LLM needed)."""
    workspace_path = Path(workspace).resolve()
    target = append_to_memory(workspace_path, "reports.md", message)
    console.print(f"[green]Logged report to {target.relative_to(workspace_path)}[/green]")


@app.command("log-decision")
def log_decision_cmd(
    decision: str = typer.Argument(..., help="The decision made."),
    rationale: str = typer.Argument(..., help="Why this decision was made."),
    workspace: str = typer.Option(".", "--workspace", "-w", help="Project directory."),
) -> None:
    """Log an architectural decision to .repobrain/decisions/log.md (no LLM needed)."""
    workspace_path = Path(workspace).resolve()
    target = append_decision(workspace_path, decision, rationale)
    console.print(f"[green]Logged decision to {target.relative_to(workspace_path)}[/green]")


@app.command("clean")
def clean_cmd(
    workspace: str = typer.Option(".", "--workspace", "-w", help="Project directory."),
    force: bool = typer.Option(False, "--force", "-f", help="Force clean without prompting."),
) -> None:
    """Clean agent memory and logs to restore a pristine environment."""
    workspace_path = Path(workspace).resolve()

    if not force:
        if not typer.confirm(f"Are you sure you want to clean logs and memory in {workspace_path}?"):
            console.print("[dim]Aborted clean.[/dim]")
            raise typer.Exit()

    cleaned_count = 0

    # Directories to clean
    dirs_to_clean = [
        workspace_path / "artifacts" / "logs",
        workspace_path / ".repobrain" / "memory",
        workspace_path / "memory", # legacy
    ]

    for d in dirs_to_clean:
        if d.exists() and d.is_dir():
            for item in d.iterdir():
                if item.name == ".gitkeep":
                    continue
                try:
                    if item.is_file():
                        item.unlink(missing_ok=True)
                        cleaned_count += 1
                    elif item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                        cleaned_count += 1
                except Exception:
                    pass

    console.print(f"[green]✔ Cleaned {cleaned_count} temporary files/directories.[/green]")


if __name__ == "__main__":
    app()
