"""Generation-based storage for RepoBrain knowledge artifacts.

The control directory remains ``<workspace>/.repobrain``.  Knowledge artifacts
live in immutable-ish generation directories below it and readers resolve the
active generation through ``current.json``.  A refresh writes a complete
candidate generation first and promotes it with one atomic pointer replace.
"""
from __future__ import annotations

import json
import os
import shutil
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


GENERATION_SCHEMA_VERSION = 1
CURRENT_FILENAME = "current.json"
GENERATIONS_DIRNAME = "generations"
RUNS_DIRNAME = "runs"

_knowledge_root_override: ContextVar[Path | None] = ContextVar(
    "repobrain_knowledge_root_override",
    default=None,
)


def control_root(workspace: Path) -> Path:
    """Return the project-local RepoBrain control directory."""
    return workspace.expanduser().resolve() / ".repobrain"


def read_current_pointer(workspace: Path) -> dict[str, object] | None:
    """Read and validate the active generation pointer."""
    path = control_root(workspace) / CURRENT_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != GENERATION_SCHEMA_VERSION:
        return None
    generation = str(payload.get("generation", "")).strip()
    if not generation or Path(generation).name != generation:
        return None
    generation_root = control_root(workspace) / GENERATIONS_DIRNAME / generation
    if not generation_root.is_dir():
        return None
    return payload


def active_generation_root(workspace: Path) -> Path | None:
    """Return the active generation directory, if a valid pointer exists."""
    pointer = read_current_pointer(workspace)
    if pointer is None:
        return None
    return control_root(workspace) / GENERATIONS_DIRNAME / str(pointer["generation"])


def knowledge_root(workspace: Path) -> Path:
    """Resolve the knowledge directory used by the current operation.

    During refresh this returns the staging generation selected by
    :func:`use_knowledge_root`.  Normal readers use the active generation and
    fall back to the legacy root layout when no generation has been promoted.
    """
    override = _knowledge_root_override.get()
    if override is not None:
        return override
    active = active_generation_root(workspace)
    return active if active is not None else control_root(workspace)


@contextmanager
def use_knowledge_root(path: Path) -> Iterator[Path]:
    """Temporarily route all storage-aware readers/writers to ``path``."""
    resolved = path.expanduser().resolve()
    token = _knowledge_root_override.set(resolved)
    try:
        yield resolved
    finally:
        _knowledge_root_override.reset(token)


def create_generation(
    workspace: Path,
    generation: str,
    *,
    clone_active: bool,
) -> Path:
    """Create a candidate generation, optionally copying the active one."""
    if Path(generation).name != generation:
        raise ValueError(f"Invalid generation id: {generation!r}")
    root = control_root(workspace)
    target = root / GENERATIONS_DIRNAME / generation
    if target.exists():
        raise FileExistsError(f"Generation already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    active = active_generation_root(workspace) if clone_active else None
    if active is not None:
        shutil.copytree(active, target)
    else:
        target.mkdir(parents=True)
    return target


def new_generation_id(head_sha: str | None) -> str:
    """Build a filesystem-safe generation id."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = (head_sha or "no-head")[:12]
    return f"{stamp}-{suffix}"


def promote_generation(
    workspace: Path,
    *,
    generation: str,
    head_sha: str,
    merkle_root: str,
    snapshot_path: str = "snapshot.json",
) -> dict[str, object]:
    """Atomically make a completed generation visible to readers."""
    root = control_root(workspace)
    generation_root = root / GENERATIONS_DIRNAME / generation
    if not generation_root.is_dir():
        raise FileNotFoundError(f"Cannot promote missing generation: {generation_root}")
    payload: dict[str, object] = {
        "schema_version": GENERATION_SCHEMA_VERSION,
        "generation": generation,
        "head_sha": head_sha,
        "merkle_root": merkle_root,
        "snapshot_path": snapshot_path,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
    }
    root.mkdir(parents=True, exist_ok=True)
    pointer = root / CURRENT_FILENAME
    tmp = root / f".{CURRENT_FILENAME}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, pointer)
    # Compatibility/diagnostic marker only.  Incremental truth comes from the
    # active generation pointer and its snapshot.
    (root / ".last_refresh_sha").write_text(head_sha, encoding="utf-8")
    return payload


def write_run_record(workspace: Path, run_id: str, payload: dict[str, object]) -> Path:
    """Persist an auditable incremental-run document."""
    if Path(run_id).name != run_id:
        raise ValueError(f"Invalid run id: {run_id!r}")
    runs_dir = control_root(workspace) / RUNS_DIRNAME
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{run_id}.json"
    tmp = runs_dir / f".{run_id}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


@contextmanager
def refresh_lock(workspace: Path) -> Iterator[Path]:
    """Serialize refresh processes for one workspace.

    The lock is intentionally outside generations so a failed candidate cannot
    make it visible. A dead PID lock is removed once and retried.
    """
    root = control_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "refresh.lock"

    def acquire() -> int:
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)

    try:
        try:
            fd = acquire()
        except FileExistsError:
            try:
                existing_pid = int(path.read_text(encoding="utf-8").strip())
                os.kill(existing_pid, 0)
            except (OSError, ValueError):
                path.unlink(missing_ok=True)
                fd = acquire()
            else:
                raise RuntimeError(
                    f"Another RepoBrain refresh is active for this workspace (pid {existing_pid})."
                ) from None
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        yield path
    finally:
        try:
            if path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                path.unlink(missing_ok=True)
        except OSError:
            pass


def remove_generation(path: Path) -> None:
    """Remove an unpromoted candidate generation."""
    if path.is_dir():
        shutil.rmtree(path)
