"""Pytest configuration helpers.

This conftest ensures the engine root is on `sys.path` so tests can import
the `repobrain_engine` package regardless of how pytest is invoked.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def commit_workspace():
    """Return a helper that initializes and commits a clean fixture repo."""

    def _commit(path: Path) -> str:
        subprocess.run(["git", "init", "-q"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
        subprocess.run(["git", "add", "-f", "."], cwd=path, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture baseline"], cwd=path, check=True)
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, text=True).strip()

    return _commit
