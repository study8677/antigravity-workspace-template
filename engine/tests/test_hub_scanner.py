"""Tests for hub.scanner — pure Python, no LLM needed."""
import subprocess
from pathlib import Path

from repobrain_engine.hub._constants import WORKSPACE_ROOT_MODULE_ID
from repobrain_engine.hub.scanner import (
    ScanReport,
    detect_modules,
    extract_structure,
    full_scan,
    quick_scan,
    resolve_module_path,
)


def test_full_scan_empty_dir(tmp_path: Path) -> None:
    report = full_scan(tmp_path)
    assert isinstance(report, ScanReport)
    assert report.file_count == 0
    assert report.languages == {}
    assert report.frameworks == []


def test_full_scan_detects_languages(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('hi')", encoding="utf-8")
    (tmp_path / "style.css").write_text("body{}", encoding="utf-8")

    report = full_scan(tmp_path)
    assert "Python" in report.languages
    assert "JavaScript" in report.languages
    assert report.file_count >= 3


def test_full_scan_defaults_to_no_file_limit(tmp_path: Path, monkeypatch) -> None:
    """Default scanning should not stop at the legacy 5000-file cap."""
    for index in range(5001):
        (tmp_path / f"file_{index:04d}.py").write_text("x = 1\n", encoding="utf-8")

    monkeypatch.delenv("RB_SCAN_MAX_FILES", raising=False)
    monkeypatch.delenv("RB_SCAN_TIMEOUT_SECONDS", raising=False)

    report = full_scan(tmp_path)

    assert report.file_count == 5001
    assert report.timed_out is False
    assert report.scan_stopped_reason == "completed"


def test_full_scan_file_limit_remains_configurable(tmp_path: Path, monkeypatch) -> None:
    """Operators can still opt into bounded scans when needed."""
    for index in range(5):
        (tmp_path / f"file_{index}.py").write_text("x = 1\n", encoding="utf-8")

    monkeypatch.setenv("RB_SCAN_MAX_FILES", "2")

    report = full_scan(tmp_path)

    assert report.file_count == 2
    assert report.timed_out is True
    assert report.scan_stopped_reason == "max_files_reached"


def test_full_scan_detects_frameworks(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:3.12", encoding="utf-8")

    report = full_scan(tmp_path)
    assert any("pyproject" in fw.lower() for fw in report.frameworks)
    assert report.has_docker


def test_full_scan_detects_tests(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    report = full_scan(tmp_path)
    assert report.has_tests


def test_full_scan_reads_readme(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# My Project\nGreat stuff.", encoding="utf-8")
    report = full_scan(tmp_path)
    assert "My Project" in report.readme_snippet


def test_full_scan_skips_node_modules(tmp_path: Path) -> None:
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("module.exports = {}", encoding="utf-8")
    (tmp_path / "app.js").write_text("hi", encoding="utf-8")

    report = full_scan(tmp_path)
    # node_modules files should not be counted
    assert report.file_count == 1


def test_full_scan_skips_generated_artifacts(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "plan.md").write_text("# generated plan\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")

    report = full_scan(tmp_path)

    assert report.file_count == 1
    assert "artifacts/plan.md" not in report.file_metadata
    assert "app.py" in report.file_metadata


def test_full_scan_top_dirs(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".hidden").mkdir()

    report = full_scan(tmp_path)
    assert "src" in report.top_dirs
    assert "tests" in report.top_dirs
    assert ".hidden" not in report.top_dirs


def test_full_scan_skips_custom_venv(tmp_path: Path) -> None:
    """Custom-named venvs (detected by pyvenv.cfg) are excluded."""
    venv = tmp_path / "my_custom_venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("home = /usr/bin", encoding="utf-8")
    (venv / "lib").mkdir()
    (venv / "lib" / "site.py").write_text("# site", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hi')", encoding="utf-8")

    report = full_scan(tmp_path)
    assert report.file_count == 1  # only app.py
    assert "my_custom_venv" not in report.top_dirs


def test_full_scan_excludes_egg_info_from_top_dirs(tmp_path: Path) -> None:
    """egg-info directories are excluded from top_dirs."""
    (tmp_path / "mypackage.egg-info").mkdir()
    (tmp_path / "src").mkdir()

    report = full_scan(tmp_path)
    assert "src" in report.top_dirs
    assert "mypackage.egg-info" not in report.top_dirs


def test_full_scan_detects_nested_tests(tmp_path: Path) -> None:
    """Tests inside subdirectories (engine/tests/) are detected."""
    engine_tests = tmp_path / "engine" / "tests"
    engine_tests.mkdir(parents=True)
    (engine_tests / "test_foo.py").write_text("def test_foo(): pass", encoding="utf-8")

    report = full_scan(tmp_path)
    assert report.has_tests is True


def test_full_scan_detects_pytest(tmp_path: Path) -> None:
    """has_pytest is set when conftest.py or pytest.ini exists."""
    (tmp_path / "conftest.py").write_text("# conftest", encoding="utf-8")

    report = full_scan(tmp_path)
    assert report.has_pytest is True


def test_quick_scan_falls_back_to_full(tmp_path: Path) -> None:
    """quick_scan falls back to full_scan when git fails."""
    (tmp_path / "main.py").write_text("x = 1", encoding="utf-8")
    report = quick_scan(tmp_path, "nonexistent-sha")
    # Should still produce a valid report via fallback
    assert isinstance(report, ScanReport)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        check=True,
    )


def test_quick_scan_includes_worktree_and_untracked_changes(tmp_path: Path) -> None:
    """Quick scans include changes that have not been committed yet."""
    _init_git_repo(tmp_path)
    tracked = tmp_path / "tracked.py"
    tracked.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()

    tracked.write_text("value = 2\n", encoding="utf-8")
    (tmp_path / "new.py").write_text("created = True\n", encoding="utf-8")

    report = quick_scan(tmp_path, base)

    assert report.changed_files == ["new.py", "tracked.py"]
    assert report.file_count == 2
    assert set(report.file_metadata) == {"tracked.py", "new.py"}


def test_quick_scan_uses_workspace_relative_non_ascii_paths(tmp_path: Path) -> None:
    """Git paths stay relative to a nested workspace and preserve Unicode."""
    _init_git_repo(tmp_path)
    subprocess.run(
        ["git", "config", "core.quotePath", "true"], cwd=tmp_path, check=True
    )
    workspace = tmp_path / "子目录"
    workspace.mkdir()
    source = workspace / "测试.py"
    source.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "子目录/测试.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()

    source.write_text("value = 2\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "change"], cwd=tmp_path, check=True)

    report = quick_scan(workspace, base)

    assert report.changed_files == ["测试.py"]
    assert report.scanned_file_samples == ["测试.py"]
    assert report.file_count == 1
    assert "测试.py" in report.file_metadata


def test_quick_scan_reports_both_sides_of_rename(tmp_path: Path) -> None:
    """Renames invalidate both the old and new paths for incremental refresh."""
    _init_git_repo(tmp_path)
    source = tmp_path / "old.py"
    source.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "old.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()

    source.rename(tmp_path / "new.py")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "rename"], cwd=tmp_path, check=True)

    report = quick_scan(tmp_path, base)

    assert report.changed_files == ["new.py", "old.py"]
    assert report.file_count == 1
    assert set(report.file_metadata) == {"new.py"}


def test_detect_modules_finds_go_directories(tmp_path: Path) -> None:
    """Go source directories should be treated as analyzable modules."""
    cmd_dir = tmp_path / "cmd"
    internal_dir = tmp_path / "internal"
    cmd_dir.mkdir()
    internal_dir.mkdir()
    (cmd_dir / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
    (internal_dir / "service.go").write_text(
        "package internal\nfunc Service() {}\n",
        encoding="utf-8",
    )

    modules = detect_modules(tmp_path)

    assert modules == ["cmd", "internal"]


def test_detect_modules_adds_workspace_root_module_for_root_code(tmp_path: Path) -> None:
    """Root-level source files should become a dedicated root module."""
    (tmp_path / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")

    modules = detect_modules(tmp_path)

    assert modules == [WORKSPACE_ROOT_MODULE_ID]
    assert resolve_module_path(tmp_path, WORKSPACE_ROOT_MODULE_ID) == tmp_path


def test_detect_modules_combines_dirs_and_workspace_root(tmp_path: Path) -> None:
    """Repos can have both top-level modules and root source files."""
    api_dir = tmp_path / "api"
    api_dir.mkdir()
    (api_dir / "handler.go").write_text("package api\nfunc Handle() {}\n", encoding="utf-8")
    (tmp_path / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")

    modules = detect_modules(tmp_path)

    assert modules == ["api", WORKSPACE_ROOT_MODULE_ID]


# ---------------------------------------------------------------------------
# Phase 1: config files, entry points, git history
# ---------------------------------------------------------------------------


def test_full_scan_reads_config_files(tmp_path: Path) -> None:
    """Config files present in the project are read into ScanReport."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n', encoding="utf-8"
    )
    (tmp_path / "package.json").write_text(
        '{"name": "demo", "main": "index.js"}', encoding="utf-8"
    )
    report = full_scan(tmp_path)
    assert "pyproject.toml" in report.config_contents
    assert "demo" in report.config_contents["pyproject.toml"]
    assert "package.json" in report.config_contents


def test_full_scan_config_truncates_long_files(tmp_path: Path) -> None:
    """Config files longer than the line limit are truncated."""
    long_content = "\n".join(f"line-{i}" for i in range(500))
    (tmp_path / "pyproject.toml").write_text(long_content, encoding="utf-8")
    report = full_scan(tmp_path)
    lines = report.config_contents["pyproject.toml"].splitlines()
    assert len(lines) <= 200


def test_full_scan_reads_ci_workflows(tmp_path: Path) -> None:
    """CI workflow YAML files under .github/workflows/ are read."""
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "test.yml").write_text("name: CI\non: push\n", encoding="utf-8")
    report = full_scan(tmp_path)
    assert ".github/workflows/test.yml" in report.config_contents


def test_full_scan_detects_entry_points_from_pyproject(tmp_path: Path) -> None:
    """Entry points are extracted from pyproject.toml [project.scripts]."""
    (tmp_path / "pyproject.toml").write_text(
        '[project.scripts]\nrb = "rb_cli.cli:app"\n', encoding="utf-8"
    )
    cli_dir = tmp_path / "rb_cli"
    cli_dir.mkdir()
    (cli_dir / "cli.py").write_text("app = 'hello'\n", encoding="utf-8")
    report = full_scan(tmp_path)
    assert "rb_cli/cli.py" in report.entry_points


def test_full_scan_detects_src_layout_entry_points_from_pyproject(tmp_path: Path) -> None:
    """Entry points in src-layout Python packages should be detected."""
    (tmp_path / "pyproject.toml").write_text(
        '[project.scripts]\nrb = "rb_cli.cli:app"\n', encoding="utf-8"
    )
    cli_dir = tmp_path / "src" / "rb_cli"
    cli_dir.mkdir(parents=True)
    (cli_dir / "cli.py").write_text("app = 'hello'\n", encoding="utf-8")

    report = full_scan(tmp_path)

    assert "src/rb_cli/cli.py" in report.entry_points


def test_full_scan_detects_common_entry_files(tmp_path: Path) -> None:
    """Common entry-point filenames are detected as fallback."""
    (tmp_path / "main.py").write_text("if __name__ == '__main__': pass\n", encoding="utf-8")
    report = full_scan(tmp_path)
    assert "main.py" in report.entry_points


def test_full_scan_git_summary_no_git(tmp_path: Path) -> None:
    """git_summary is empty when the directory is not a git repo."""
    report = full_scan(tmp_path)
    assert report.git_summary == ""


def test_full_scan_git_summary_with_repo(tmp_path: Path) -> None:
    """git_summary contains commit info when a git repo exists."""
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path), capture_output=True, check=True,
    )
    (tmp_path / "hello.py").write_text("x = 1", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(tmp_path), capture_output=True, check=True,
    )
    report = full_scan(tmp_path)
    assert "init" in report.git_summary


# ---------------------------------------------------------------------------
# extract_structure — code skeleton generation
# ---------------------------------------------------------------------------


def test_extract_structure_empty_dir(tmp_path: Path) -> None:
    result = extract_structure(tmp_path)
    assert "Project Structure Map" in result


def test_extract_structure_python_file(tmp_path: Path) -> None:
    """Python files appear in structure with line count (language-agnostic)."""
    code = '''\
"""Auth module for JWT tokens."""

import jwt
from datetime import datetime


class TokenManager:
    """Manages JWT token lifecycle."""

    def create_token(self, user_id: str) -> str:
        """Create a new JWT token."""
        pass


def login(username: str, password: str) -> bool:
    """Authenticate a user."""
    pass
'''
    (tmp_path / "auth.py").write_text(code, encoding="utf-8")
    result = extract_structure(tmp_path)
    assert "auth.py" in result
    assert "Python" in result
    assert "lines" in result


def test_extract_structure_js_file(tmp_path: Path) -> None:
    """JS files appear in structure with line count (language-agnostic)."""
    code = '''\
import express from "express";

export function handleLogin(req, res) {
    return res.json({ ok: true });
}

export class AuthController {
    constructor() {}
}
'''
    (tmp_path / "app.js").write_text(code, encoding="utf-8")
    result = extract_structure(tmp_path)
    assert "app.js" in result
    assert "JavaScript" in result
    assert "lines" in result


def test_extract_structure_go_file(tmp_path: Path) -> None:
    """Go files appear in structure with line count (language-agnostic)."""
    code = '''\
package auth

func Login(username string, password string) error {
    return nil
}

type UserService struct {
    db *sql.DB
}
'''
    (tmp_path / "auth.go").write_text(code, encoding="utf-8")
    result = extract_structure(tmp_path)
    assert "auth.go" in result
    assert "Go" in result
    assert "lines" in result


def test_extract_structure_nested_dirs(tmp_path: Path) -> None:
    """Files in subdirectories are organized by directory in output."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    (tmp_path / "setup.py").write_text("# setup\n", encoding="utf-8")
    result = extract_structure(tmp_path)
    assert "src/" in result
    assert "main.py" in result


def test_extract_structure_skips_node_modules(tmp_path: Path) -> None:
    """node_modules and other skip dirs are excluded."""
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("export function secret() {}", encoding="utf-8")
    (tmp_path / "app.js").write_text("export function main() {}", encoding="utf-8")
    result = extract_structure(tmp_path)
    assert "node_modules" not in result
    assert "app.js" in result


def test_extract_structure_skips_generated_state_and_artifacts(tmp_path: Path) -> None:
    """Generated RepoBrain state and artifact files should not self-pollute."""
    rb_dir = tmp_path / ".repobrain"
    rb_dir.mkdir()
    (rb_dir / "structure.md").write_text("# previous structure\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "plan.md").write_text("# generated plan\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")

    result = extract_structure(tmp_path)

    assert ".repobrain" not in result
    assert "artifacts" not in result
    assert "src" in result
    assert "app.py" in result
