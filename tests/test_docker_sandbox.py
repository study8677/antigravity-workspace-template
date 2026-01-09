import pytest

from src.sandbox.factory import get_sandbox
from src.sandbox.docker_exec import DockerSandbox


def _docker_env_available() -> bool:
    try:
        import docker  # type: ignore

        try:
            client = docker.from_env()
            client.ping()
            return True
        except Exception:
            return False
    except Exception:
        return False


@pytest.mark.skipif(_docker_env_available(), reason="Docker daemon available; this test checks the missing-daemon path")
def test_missing_docker_daemon(monkeypatch):
    monkeypatch.setenv("SANDBOX_TYPE", "docker")
    s = get_sandbox()
    assert isinstance(s, DockerSandbox)
    r = s.execute("print('hi')", timeout=2)
    assert r.exit_code != 0
    assert "docker" in (r.stderr or "").lower()
    assert any(term in (r.stderr or "").lower() for term in ["not available", "not installed", "error"])


@pytest.mark.skipif(not _docker_env_available(), reason="Docker daemon required for this test")
def test_docker_timeout_enforcement(monkeypatch):
    monkeypatch.setenv("SANDBOX_TYPE", "docker")
    s = get_sandbox()
    assert isinstance(s, DockerSandbox)
    r = s.execute("import time; time.sleep(10)", timeout=2)
    assert r.exit_code == -1
    assert r.meta.get("timed_out") is True
    assert "timed out" in r.stderr.lower()


@pytest.mark.skipif(not _docker_env_available(), reason="Docker daemon required for this test")
def test_docker_success_execution(monkeypatch):
    monkeypatch.setenv("SANDBOX_TYPE", "docker")
    s = get_sandbox()
    assert isinstance(s, DockerSandbox)
    r = s.execute("print('Hello from Docker')", timeout=10)
    assert r.exit_code == 0
    assert "Hello from Docker" in r.stdout
