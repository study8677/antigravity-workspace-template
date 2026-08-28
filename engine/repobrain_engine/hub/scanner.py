"""Project scanner — pure Python, no LLM dependency.

Scans a project directory and produces a :class:`ScanReport` with
language, framework, and structural metadata.

Knowledge-graph construction has been moved to
:mod:`repobrain_engine.hub.knowledge_graph` and code-structure
extraction to :mod:`repobrain_engine.hub.structure`.  Both are
re-exported here for backward compatibility.
"""
from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from repobrain_engine.hub._constants import (
    DATA_EXTS,
    DOCUMENTATION_EXTS,
    FRAMEWORK_MARKERS,
    LANG_MAP,
    MEDIA_EXTS,
    SKIP_DIRS,
    SOURCE_CODE_EXTS,
    WORKSPACE_ROOT_MODULE_ID,
)
from repobrain_engine.hub._utils import env_float, env_int

# ---------------------------------------------------------------------------
# Re-exports for backward compatibility
# ---------------------------------------------------------------------------
from repobrain_engine.hub.knowledge_graph import (  # noqa: F401
    build_knowledge_graph,
    render_knowledge_graph_markdown,
    render_knowledge_graph_mermaid,
)
from repobrain_engine.hub.structure import (  # noqa: F401
    extract_structure,
    generate_module_context,
)

# ---------------------------------------------------------------------------
# Internal aliases (kept as private names so old code referencing
# scanner._SKIP_DIRS etc. still works within this module)
# ---------------------------------------------------------------------------
_SKIP_DIRS = SKIP_DIRS
_LANG_MAP = LANG_MAP
_DOCUMENTATION_EXTS = DOCUMENTATION_EXTS
_DATA_EXTS = DATA_EXTS
_MEDIA_EXTS = MEDIA_EXTS
_FRAMEWORK_MARKERS = FRAMEWORK_MARKERS
_TEXT_EXTS = set(LANG_MAP) | DOCUMENTATION_EXTS | DATA_EXTS | {".env", ".log"}

# Scanner-specific constants
_CONFIG_LINE_LIMIT = 200
_CONFIG_TOTAL_LIMIT = 30_000
_ENTRY_POINT_LINE_LIMIT = 50
_DEFAULT_SCAN_TIMEOUT_SECONDS = 0.0
_DEFAULT_SCAN_MAX_FILES: int | None = None
_DEFAULT_SCAN_SAMPLE_FILES = 50


@dataclass
class ScanReport:
    """Result of scanning a project directory."""

    root: Path
    languages: dict[str, int] = field(default_factory=dict)
    frameworks: list[str] = field(default_factory=list)
    top_dirs: list[str] = field(default_factory=list)
    file_count: int = 0
    has_tests: bool = False
    has_ci: bool = False
    has_docker: bool = False
    has_pytest: bool = False
    readme_snippet: str = ""
    config_contents: dict[str, str] = field(default_factory=dict)
    entry_points: dict[str, str] = field(default_factory=dict)
    git_summary: str = ""
    walked_file_count: int = 0
    type_distribution: dict[str, int] = field(default_factory=dict)
    scan_elapsed_seconds: float = 0.0
    timed_out: bool = False
    scan_stopped_reason: str = ""
    scanned_file_samples: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    unreadable_files: int = 0
    oversized_files: int = 0
    binary_files: int = 0
    file_metadata: dict[str, dict[str, object]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_venv_dir(path: Path) -> bool:
    """Detect virtual environments by the presence of ``pyvenv.cfg``.

    Args:
        path: Directory to check.

    Returns:
        True if the directory looks like a Python virtual environment.
    """
    return (path / "pyvenv.cfg").is_file()


def _env_optional_positive_int(name: str, default: int | None) -> int | None:
    """Read a positive integer limit; unset, zero, or negative means unlimited."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value <= 0:
        return None
    return value


def _find_venv_dirs(root: Path) -> set[str]:
    """Discover virtualenv directory names under *root* (up to two levels deep).

    Args:
        root: Project root directory.

    Returns:
        Set of directory names that are virtual environments.
    """
    venv_names: set[str] = set()
    try:
        entries = list(root.iterdir())
    except OSError:
        return venv_names
    for d in entries:
        if d.is_dir():
            if _is_venv_dir(d):
                venv_names.add(d.name)
            # Also check one level deep (e.g. engine/venv)
            if not d.name.startswith(".") and d.name not in SKIP_DIRS:
                try:
                    for sub in d.iterdir():
                        if sub.is_dir() and _is_venv_dir(sub):
                            venv_names.add(sub.name)
                except OSError:
                    pass
    return venv_names


def _should_skip(path: Path, extra_skip: set[str] | None = None) -> bool:
    """Check if a relative path should be skipped during scanning.

    Args:
        path: Relative path (from root) to evaluate.
        extra_skip: Additional directory names to skip (e.g. detected venvs).

    Returns:
        True if the path falls inside a skippable directory.
    """
    skip = SKIP_DIRS | extra_skip if extra_skip else SKIP_DIRS
    for part in path.parts:
        if part in skip or part.endswith(".egg-info"):
            return True
    return False


def _classify_file(path: Path) -> tuple[str, str, bool]:
    """Classify a file into a high-level type with mime and binary flag."""
    ext = path.suffix.lower()
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    if ext in LANG_MAP:
        return "code", mime, False
    if ext in DOCUMENTATION_EXTS:
        return "documentation", mime, ext == ".pdf"
    if ext in DATA_EXTS:
        return "data", mime, ext in {".db", ".sqlite", ".parquet"}
    if ext in MEDIA_EXTS:
        return "media", mime, True

    try:
        sample = path.read_bytes()[:2048]
    except OSError:
        return "other", mime, False

    is_binary = b"\x00" in sample
    if is_binary:
        return "binary", mime, True
    return "other", mime, False


def _update_scan_stats(
    report: ScanReport,
    rel: Path,
    item: Path,
    sample_limit: int,
) -> None:
    """Update file-level counters and metadata for a scanned file."""
    rel_str = rel.as_posix()
    report.walked_file_count += 1
    report.file_count += 1

    ext = item.suffix.lower()
    if ext in LANG_MAP:
        lang = LANG_MAP[ext]
        report.languages[lang] = report.languages.get(lang, 0) + 1

    try:
        size = item.stat().st_size
    except OSError:
        report.unreadable_files += 1
        return

    file_type, mime, is_binary = _classify_file(item)
    report.type_distribution[file_type] = report.type_distribution.get(file_type, 0) + 1
    if is_binary:
        report.binary_files += 1
    if size > 1_000_000:
        report.oversized_files += 1

    report.file_metadata[rel_str] = {
        "type": file_type,
        "size": size,
        "mime": mime,
        "is_binary": is_binary,
    }

    if len(report.scanned_file_samples) < sample_limit:
        report.scanned_file_samples.append(rel_str)


def _finalize_scan_report(report: ScanReport, root: Path, venv_dirs: set[str]) -> None:
    """Fill derived report fields after the file scan loop.

    ``has_tests`` and ``has_pytest`` are now detected during the main
    ``os.walk`` pass in :func:`full_scan`, so this function no longer
    needs to do additional ``rglob`` traversals.
    """
    report.languages = dict(
        sorted(report.languages.items(), key=lambda item: item[1], reverse=True)
    )

    skip_dirs = SKIP_DIRS | venv_dirs
    report.top_dirs = sorted(
        d.name
        for d in root.iterdir()
        if d.is_dir()
        and not d.name.startswith(".")
        and d.name not in skip_dirs
        and not d.name.endswith(".egg-info")
    )

    # has_tests / has_pytest are set by the main scan loop — only apply
    # lightweight root-level fallback checks here for quick_scan paths
    # that may not walk deeply enough.
    if not report.has_pytest:
        report.has_pytest = any(
            (root / f).exists() for f in ("pytest.ini", "conftest.py")
        )
    report.has_ci = (root / ".github" / "workflows").exists() or (root / ".gitlab-ci.yml").exists()
    report.has_docker = (root / "Dockerfile").exists() or (root / "docker-compose.yml").exists()

    for name in ("README.md", "readme.md", "README.rst", "README"):
        readme = root / name
        if readme.exists():
            try:
                lines = readme.read_text(encoding="utf-8").splitlines()[:10]
                report.readme_snippet = "\n".join(lines)
            except OSError:
                pass
            break

    report.config_contents = _read_config_files(root)
    report.entry_points = _read_entry_points(root, report.config_contents)
    report.git_summary = _extract_git_summary(root)


# ---------------------------------------------------------------------------
# Config / entry-point / git helpers
# ---------------------------------------------------------------------------

_CONFIG_FILES: list[str] = [
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
    "tsconfig.json",
    ".env.example",
    ".gitlab-ci.yml",
    "Makefile",
]

_COMMON_ENTRY_FILES: list[str] = [
    "main.py",
    "app.py",
    "manage.py",
    "index.ts",
    "index.js",
    "src/index.ts",
    "src/index.js",
    "src/main.ts",
    "src/main.py",
    "main.go",
    "cmd/main.go",
    "src/main.rs",
    "src/lib.rs",
]


def _read_file_head(path: Path, max_lines: int) -> str | None:
    """Read the first *max_lines* of a text file.

    Args:
        path: File to read.
        max_lines: Maximum number of lines to return.

    Returns:
        The truncated content, or None if the file cannot be read.
    """
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:max_lines]
        return "\n".join(lines)
    except OSError:
        return None


def _read_config_files(root: Path) -> dict[str, str]:
    """Read well-known config files from the project root.

    Args:
        root: Project root directory.

    Returns:
        Mapping of relative file path to its (possibly truncated) content.
    """
    contents: dict[str, str] = {}
    total_bytes = 0

    for name in _CONFIG_FILES:
        path = root / name
        if not path.is_file():
            continue
        text = _read_file_head(path, _CONFIG_LINE_LIMIT)
        if text is None:
            continue
        if total_bytes + len(text) > _CONFIG_TOTAL_LIMIT:
            break
        contents[name] = text
        total_bytes += len(text)

    workflows_dir = root / ".github" / "workflows"
    if workflows_dir.is_dir():
        try:
            for wf in sorted(workflows_dir.glob("*.yml")):
                rel = f".github/workflows/{wf.name}"
                text = _read_file_head(wf, _CONFIG_LINE_LIMIT)
                if text is None:
                    continue
                if total_bytes + len(text) > _CONFIG_TOTAL_LIMIT:
                    break
                contents[rel] = text
                total_bytes += len(text)
        except OSError:
            pass

    return contents


def _read_entry_points(root: Path, config_contents: dict[str, str]) -> dict[str, str]:
    """Detect and read project entry-point files.

    Args:
        root: Project root directory.
        config_contents: Already-read config file contents.

    Returns:
        Mapping of relative file path to its first N lines.
    """
    candidates: list[str] = []

    pyproject_text = config_contents.get("pyproject.toml", "")
    if pyproject_text:
        try:
            import tomllib  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            try:
                import tomli as tomllib  # type: ignore[import-not-found, no-redef]
            except ModuleNotFoundError:
                tomllib = None  # type: ignore[assignment]
        if tomllib is not None:
            try:
                data = tomllib.loads(pyproject_text)
                scripts = data.get("project", {}).get("scripts", {})
                for _cmd, ref in scripts.items():
                    mod = ref.split(":")[0].replace(".", "/") + ".py"
                    candidates.append(mod)
                    candidates.append(f"src/{mod}")
            except Exception:
                pass

    pkg_text = config_contents.get("package.json", "")
    if pkg_text:
        try:
            data = json.loads(pkg_text)
            main = data.get("main")
            if main:
                candidates.append(main)
        except Exception:
            pass

    candidates.extend(_COMMON_ENTRY_FILES)

    entry_points: dict[str, str] = {}
    for rel in candidates:
        path = root / rel
        if not path.is_file():
            continue
        if rel in entry_points:
            continue
        text = _read_file_head(path, _ENTRY_POINT_LINE_LIMIT)
        if text is not None:
            entry_points[rel] = text
        if len(entry_points) >= 5:
            break

    return entry_points


def _extract_git_summary(root: Path) -> str:
    """Extract recent git history as a plain-text summary.

    Args:
        root: Project root directory.

    Returns:
        Multi-line string with recent commits and contributor activity,
        or an empty string if git is unavailable.
    """
    parts: list[str] = []

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-20"],
            capture_output=True,
            text=True,
            cwd=str(root),
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts.append("Recent commits:\n" + result.stdout.strip())
    except FileNotFoundError:
        return ""

    try:
        result = subprocess.run(
            ["git", "shortlog", "-sn", "--since=3 months ago"],
            capture_output=True,
            text=True,
            cwd=str(root),
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts.append("Contributors (last 3 months):\n" + result.stdout.strip())
    except FileNotFoundError:
        pass

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Public scan functions
# ---------------------------------------------------------------------------

def full_scan(root: Path) -> ScanReport:
    """Perform a full project scan.

    Uses a single ``os.walk`` pass with directory pruning instead of
    multiple ``Path.rglob("*")`` calls, avoiding redundant traversals
    of skipped directories (venvs, node_modules, etc.).

    Args:
        root: Project root directory.

    Returns:
        ScanReport with project analysis.
    """
    report = ScanReport(root=root)
    venv_dirs = _find_venv_dirs(root)

    for marker, name in FRAMEWORK_MARKERS.items():
        if (root / marker).exists():
            report.frameworks.append(name)

    scan_timeout = env_float(
        "RB_SCAN_TIMEOUT_SECONDS",
        _DEFAULT_SCAN_TIMEOUT_SECONDS,
        minimum=0.0,
    )
    max_files = _env_optional_positive_int(
        "RB_SCAN_MAX_FILES",
        _DEFAULT_SCAN_MAX_FILES,
    )
    sample_limit = env_int(
        "RB_SCAN_SAMPLE_FILES",
        _DEFAULT_SCAN_SAMPLE_FILES,
        minimum=1,
    )
    started = time.monotonic()

    skip_names = SKIP_DIRS | venv_dirs
    test_dir_names = {"tests", "test", "spec", "specs", "__tests__"}
    pytest_file_names = {"conftest.py", "pytest.ini"}
    hit_limit = False

    for dirpath_str, dirnames, filenames in os.walk(root):
        # Prune skipped directories in-place so os.walk never descends
        dirnames[:] = [
            d for d in dirnames
            if d not in skip_names
            and not d.startswith(".")
            and not d.endswith(".egg-info")
        ]

        dirpath = Path(dirpath_str)

        # Detect test directories and pytest markers during the walk
        dir_name = dirpath.name
        if dir_name in test_dir_names:
            report.has_tests = True
        for fname in filenames:
            if fname in pytest_file_names:
                report.has_pytest = True
                break

        for fname in filenames:
            item = dirpath / fname
            try:
                rel = item.relative_to(root)
            except ValueError:
                continue

            if max_files is not None and report.walked_file_count >= max_files:
                report.timed_out = True
                report.scan_stopped_reason = "max_files_reached"
                hit_limit = True
                break
            if scan_timeout > 0 and (time.monotonic() - started) >= scan_timeout:
                report.timed_out = True
                report.scan_stopped_reason = "timeout"
                hit_limit = True
                break

            _update_scan_stats(report, rel, item, sample_limit)

        if hit_limit:
            break

    report.scan_elapsed_seconds = time.monotonic() - started
    if not report.scan_stopped_reason:
        report.scan_stopped_reason = "completed"

    _finalize_scan_report(report, root, venv_dirs)
    return report


_MODULE_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".tox",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
    ".next", ".nuxt", "target", "vendor", ".repobrain", ".context",
    "artifacts", ".github", ".agent", ".agents",
})

# Extensions that count as real source code (not just .md/.json/.yml)
_CODE_EXTS: frozenset[str] = SOURCE_CODE_EXTS


def list_root_module_files(root: Path) -> list[Path]:
    """Return analyzable source files that live directly under *root*.

    Args:
        root: Project root directory.

    Returns:
        Sorted list of direct child files that count as source code.
    """
    files: list[Path] = []
    try:
        for item in sorted(root.iterdir()):
            if not item.is_file():
                continue
            if item.name.startswith("."):
                continue
            if item.suffix.lower() in SOURCE_CODE_EXTS:
                files.append(item)
    except OSError:
        return []
    return files


def _dir_has_code(directory: Path, venv_dirs: set[str]) -> bool:
    """Check whether *directory* contains at least one source-code file."""
    skip = _MODULE_SKIP_DIRS | venv_dirs
    for dirpath_str, dirnames, filenames in os.walk(directory):
        dirnames[:] = [
            d for d in dirnames
            if d not in skip and not d.startswith(".") and not d.endswith(".egg-info")
        ]
        for fname in filenames:
            if Path(fname).suffix.lower() in _CODE_EXTS:
                return True
    return False


def detect_modules(root: Path) -> list[str]:
    """Detect code modules using pure directory structure (language-agnostic).

    Top-level directories are scanned first.  When a top-level directory
    has many code-bearing sub-directories (≥ ``_AUTO_SPLIT_THRESHOLD``),
    it is automatically split into sub-modules.

    **Two-level resolution:** When a top-level directory contains exactly
    one code-bearing child directory (e.g. ``engine/repobrain_engine/``),
    the detection descends one level and checks for auto-split there.
    This is fully language-agnostic — no ``__init__.py`` or any other
    language-specific marker is required.

    Only directories that contain actual source code (not just docs or
    data) are treated as modules.

    Args:
        root: Project root directory.

    Returns:
        List of module identifiers.  Two-level modules use underscore
        separators (e.g. ``"engine_hub"``) so they remain safe for
        agent names and filesystem paths. A workspace-root source module
        is represented by ``WORKSPACE_ROOT_MODULE_ID``.
    """
    skip = _MODULE_SKIP_DIRS.copy()
    venv_dirs = _find_venv_dirs(root)
    skip = skip | venv_dirs

    modules: list[str] = []
    try:
        for item in sorted(root.iterdir()):
            if not item.is_dir():
                continue
            if item.name.startswith(".") or item.name in skip:
                continue
            if item.name.endswith(".egg-info"):
                continue
            if not _dir_has_code(item, venv_dirs):
                continue

            # Try auto-split at top level first
            child_subs = _detect_sub_modules_any_lang(item, item.name, venv_dirs, skip)
            if len(child_subs) >= _AUTO_SPLIT_THRESHOLD:
                modules.extend(child_subs)
                continue

            # Two-level: if top dir has exactly one code-bearing child,
            # descend one level and try auto-split there.
            inner = _find_single_code_child(item, venv_dirs, skip)
            if inner is not None:
                deep_subs = _detect_sub_modules_any_lang(inner, item.name, venv_dirs, skip)
                if len(deep_subs) >= 3:
                    modules.extend(deep_subs)
                    continue

            # Fallback: treat entire top-level dir as one module
            modules.append(item.name)
    except OSError:
        pass

    if list_root_module_files(root):
        modules.append(WORKSPACE_ROOT_MODULE_ID)

    return modules


#: When a top-level directory has this many or more code-bearing
#: sub-directories, auto-split into sub-modules (language-agnostic).
_AUTO_SPLIT_THRESHOLD = int(os.environ.get("RB_AUTO_SPLIT_THRESHOLD", "6"))


_NON_MODULE_DIR_NAMES: frozenset[str] = frozenset({
    "tests", "test", "spec", "specs", "__tests__",
    "docs", "doc", "examples", "example", "samples",
    "scripts", "tools", "fixtures", "testdata",
})
"""Directory names that are not considered primary code modules when
resolving two-level module structure (e.g. ``engine/tests/`` is not
the main code package of ``engine/``)."""


def _find_single_code_child(
    top_dir: Path,
    venv_dirs: set[str],
    skip: set[str],
) -> Path | None:
    """Find the single primary code-bearing child directory inside *top_dir*.

    Language-agnostic: checks for any directory containing source code,
    not for any language-specific marker.  Directories whose names match
    common non-module patterns (tests, docs, examples, etc.) are excluded
    from candidate consideration.

    Returns ``None`` if there are zero or multiple primary candidates.

    Args:
        top_dir: Parent directory to inspect.
        venv_dirs: Virtual-environment directory names to skip.
        skip: Additional directory names to skip.

    Returns:
        The single primary code-bearing child, or None.
    """
    candidates: list[Path] = []
    try:
        for child in top_dir.iterdir():
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name in skip:
                continue
            if child.name.lower() in _NON_MODULE_DIR_NAMES:
                continue
            if _dir_has_code(child, venv_dirs):
                candidates.append(child)
    except OSError:
        return None
    return candidates[0] if len(candidates) == 1 else None


def _detect_sub_modules_any_lang(
    parent_dir: Path,
    parent_name: str,
    venv_dirs: set[str],
    skip: set[str],
) -> list[str]:
    """Detect sub-modules by scanning direct child directories for code.

    Unlike :func:`_detect_sub_modules`, this is language-agnostic — it does
    not require ``__init__.py`` or any inner package structure.  Used for
    auto-splitting large directories (e.g. TypeScript ``extensions/``).

    Returns module ids as ``"{parent}_{child}"`` (slash-free).
    """
    sub_modules: list[str] = []
    try:
        for child in sorted(parent_dir.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name.startswith("_"):
                continue
            if child.name in skip:
                continue
            if _dir_has_code(child, venv_dirs):
                sub_modules.append(f"{parent_name}_{child.name}")
    except OSError:
        pass
    return sub_modules


def resolve_module_path(root: Path, module_id: str) -> Path:
    """Resolve a module identifier to its filesystem directory.

    For simple modules the path is ``root / module_id``.  For two-level
    modules (``"parent_child"``) the path is resolved by scanning for
    the single code-bearing inner directory (language-agnostic).

    Args:
        root: Project root directory.
        module_id: Module identifier returned by :func:`detect_modules`.

    Returns:
        Absolute path to the module directory, or the workspace root for
        ``WORKSPACE_ROOT_MODULE_ID``.
    """
    if module_id == WORKSPACE_ROOT_MODULE_ID:
        return root

    # Simple case: top-level directory exists directly
    direct = root / module_id
    if direct.is_dir():
        return direct

    # Two-level case: "parent_child" → root/parent/<inner>/child
    # OR direct auto-split: "parent_child" → root/parent/child.
    # Parent directory names can themselves contain underscores
    # (e.g. ``docs_src_additional_responses`` → ``docs_src/additional_responses``),
    # so try the longest existing parent prefix first instead of splitting once.
    if "_" in module_id:
        parts = module_id.split("_")
        venv_dirs = _find_venv_dirs(root)
        skip = _MODULE_SKIP_DIRS | venv_dirs
        for split_at in range(len(parts) - 1, 0, -1):
            parent_name = "_".join(parts[:split_at])
            child_name = "_".join(parts[split_at:])
            parent_dir = root / parent_name
            if not parent_dir.is_dir():
                continue
            # First try: single code-bearing inner dir
            inner = _find_single_code_child(parent_dir, venv_dirs, skip)
            if inner is not None:
                child_dir = inner / child_name
                if child_dir.is_dir():
                    return child_dir
            # Second try: direct child (extensions_slack → extensions/slack)
            child_dir = parent_dir / child_name
            if child_dir.is_dir():
                return child_dir

    # Fallback
    return direct


def extract_git_insights(root: Path) -> str:
    """Extract comprehensive git insights for the project.

    Args:
        root: Project root directory.

    Returns:
        Markdown string with git analysis, or empty string if git
        is unavailable.
    """
    parts: list[str] = ["# Git Insights\n"]

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-30", "--format=%h %ai %s"],
            capture_output=True, text=True, cwd=str(root), check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts.append("## Recent Commits\n```\n" + result.stdout.strip() + "\n```")
    except FileNotFoundError:
        return ""

    modules = detect_modules(root)
    if modules:
        freq_lines: list[str] = []
        for mod in modules:
            try:
                result = subprocess.run(
                    ["git", "log", "--oneline", "--since=3 months ago", "--", f"{mod}/"],
                    capture_output=True, text=True, cwd=str(root), check=False,
                )
                if result.returncode == 0:
                    count = len(result.stdout.strip().splitlines()) if result.stdout.strip() else 0
                    freq_lines.append(f"- **{mod}**: {count} commits")
            except FileNotFoundError:
                break
        if freq_lines:
            parts.append("## Module Change Frequency (3 months)\n" + "\n".join(freq_lines))

    try:
        result = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:", "-20"],
            capture_output=True, text=True, cwd=str(root), check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            files = list(dict.fromkeys(
                f.strip() for f in result.stdout.splitlines() if f.strip()
            ))[:20]
            parts.append("## Recently Modified Files\n" + "\n".join(f"- {f}" for f in files))
    except FileNotFoundError:
        pass

    try:
        result = subprocess.run(
            ["git", "shortlog", "-sn", "--since=3 months ago"],
            capture_output=True, text=True, cwd=str(root), check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts.append("## Contributors (3 months)\n```\n" + result.stdout.strip() + "\n```")
    except FileNotFoundError:
        pass

    return "\n\n".join(parts)


def quick_scan(root: Path, since_sha: str) -> ScanReport:
    """Perform a quick scan of files changed since a git commit.

    Args:
        root: Project root directory.
        since_sha: Git commit SHA to diff against.

    Returns:
        ScanReport with analysis of changed files only.
    """
    report = ScanReport(root=root)

    try:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                "-z",
                "--no-renames",
                "--relative",
                since_sha,
                "--",
                ".",
            ],
            capture_output=True,
            cwd=str(root),
            check=False,
        )
        if result.returncode != 0:
            return full_scan(root)

        untracked_result = subprocess.run(
            [
                "git",
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                ".",
            ],
            capture_output=True,
            cwd=str(root),
            check=False,
        )
        if untracked_result.returncode != 0:
            return full_scan(root)

        raw_paths = (
            result.stdout.split(b"\0")
            + untracked_result.stdout.split(b"\0")
        )
        changed_files = sorted(
            {os.fsdecode(raw_path) for raw_path in raw_paths if raw_path}
        )
        report.changed_files = changed_files
    except FileNotFoundError:
        return full_scan(root)

    venv_dirs = _find_venv_dirs(root)
    for marker, name in FRAMEWORK_MARKERS.items():
        if (root / marker).exists():
            report.frameworks.append(name)

    sample_limit = env_int(
        "RB_SCAN_SAMPLE_FILES",
        _DEFAULT_SCAN_SAMPLE_FILES,
        minimum=1,
    )
    started = time.monotonic()
    for file_str in changed_files:
        filepath = root / file_str
        if not filepath.exists() or not filepath.is_file():
            continue
        rel = Path(file_str)
        if _should_skip(rel, venv_dirs):
            continue
        _update_scan_stats(report, rel, filepath, sample_limit)

    report.scan_elapsed_seconds = time.monotonic() - started
    report.scan_stopped_reason = "completed"
    _finalize_scan_report(report, root, venv_dirs)
    return report
