import os
from pathlib import Path
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPServerConfig(BaseSettings):
    """Configuration for a single MCP server."""

    name: str = Field(description="Unique name for the MCP server")
    transport: str = Field(
        default="stdio", description="Transport type: stdio, http, sse"
    )
    command: Optional[str] = Field(
        default=None, description="Command to run for stdio transport"
    )
    args: List[str] = Field(
        default_factory=list, description="Arguments for the command"
    )
    url: Optional[str] = Field(default=None, description="URL for http/sse transport")
    env: dict = Field(
        default_factory=dict, description="Environment variables for the server"
    )
    enabled: bool = Field(default=True, description="Whether this server is enabled")

    model_config = SettingsConfigDict(extra="ignore")


class Settings(BaseSettings):
    """Application settings managed by Pydantic."""

    # Agent Configuration
    AGENT_NAME: str = "RepoBrainAgent"
    # Stream Configuration
    STREAM_ENABLED: bool = Field(
        default=False,
        description="Enable streaming for LLM responses via litellm. "
        "Set to true for real-time token streaming.",
    )
    DEBUG_MODE: bool = False
    PROJECT_ROOT: str = Field(
        default_factory=lambda: os.environ.get(
            "WORKSPACE_PATH", str(Path.cwd())
        ),
        description="Absolute path to the user workspace. "
        "Set via --workspace CLI arg or WORKSPACE_PATH env var. "
        "Defaults to current working directory.",
    )

    # External LLM (OpenAI-compatible) Configuration
    OPENAI_BASE_URL: str = Field(
        default="",
        description="Base URL for OpenAI-compatible API (e.g., https://api.openai.com/v1 or http://localhost:11434/v1)",
    )
    OPENAI_API_KEY: str = Field(
        default="",
        description="API key for OpenAI-compatible endpoint. Leave blank if not required.",
    )
    OPENAI_MODEL: str = Field(
        default="gpt-4o-mini",
        description="Default model name for OpenAI-compatible chat completions.",
    )

    # Local host runner (experimental, no API key) Configuration
    RB_HOST_RUNNER: str = Field(
        default="",
        description="Experimental local host runner for rb-ask, e.g. 'codex' or 'generic'.",
    )
    RB_HOST_MODEL: str = Field(
        default="",
        description="Optional model for the 'codex' host runner's --model flag. "
        "Leave empty to let the CLI use its own default model. Ignored by the "
        "'generic' runner (put any model flag directly in RB_HOST_COMMAND).",
    )
    RB_HOST_COMMAND: str = Field(
        default="",
        description="Command template for RB_HOST_RUNNER=generic. Supports placeholders "
        "{prompt_file}, {schema_file}, {output_file}, {workspace}. Example: "
        "'trae exec --prompt {prompt_file}'. When {prompt_file} is omitted, the prompt "
        "is sent on stdin.",
    )
    RB_HOST_OUTPUT_MODE: str = Field(
        default="file",
        description="Where the generic host runner reads its JSON answer from: "
        "'file' (the {output_file}) or 'stdout'.",
    )
    RB_HOST_TIMEOUT_SECONDS: float = Field(
        default=600.0,
        description="Timeout in seconds for local host runner calls.",
    )
    RB_HOST_MAX_CONTEXT_CHARS: int = Field(
        default=60000,
        description="Maximum prompt size passed to the local host runner.",
    )
    RB_REFRESH_SCAN_ONLY: bool = Field(
        default=False,
        description="Run refresh without LLM analysis and write scan artifacts only.",
    )

    # Auto-refresh gate for rb-ask (let the CLI refresh itself instead of
    # relying on an agent to notice and run rb-refresh manually).
    RB_ASK_AUTO_REFRESH: str = Field(
        default="stale",
        description="When rb-ask should build/rebuild the knowledge base on its "
        "own: 'off' (never), 'first-only' (only when .repobrain is missing), or "
        "'stale' (missing OR more than RB_ASK_AUTO_REFRESH_LAG commits behind "
        "HEAD). Default 'stale' covers both first run and drift.",
    )
    RB_ASK_AUTO_REFRESH_LAG: int = Field(
        default=20,
        description="Commit lag past which 'stale' mode triggers an auto-refresh "
        "before answering. Ignored when RB_ASK_AUTO_REFRESH is 'off'/'first-only'.",
    )

    # Memory Configuration
    MEMORY_FILE: str = "memory/agent_memory.md"
    MEMORY_SUMMARY_FILE: str = "memory/agent_summary.md"
    ARTIFACTS_DIR: str = Field(
        default="artifacts",
        description="Directory for artifacts and logs. Relative paths are resolved from PROJECT_ROOT.",
    )

    # RepoBrain Context Directory
    REPOBRAIN_DIR: str = Field(
        default=".repobrain",
        description="Directory for project context files. Relative to PROJECT_ROOT.",
    )

    # MCP Configuration
    MCP_ENABLED: bool = Field(default=False, description="Enable MCP integration")
    MCP_SERVERS_CONFIG: str = Field(
        default="mcp_servers.json", description="Path to MCP servers configuration file"
    )
    MCP_CONNECTION_TIMEOUT: int = Field(
        default=30, description="Timeout in seconds for MCP server connections"
    )
    MCP_TOOL_PREFIX: str = Field(
        default="mcp_", description="Prefix for MCP tool names to avoid conflicts"
    )

    model_config = SettingsConfigDict(
        env_file=str(
            Path(
                os.environ.get("WORKSPACE_PATH", str(Path.cwd()))
            ) / ".env"
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def project_root_path(self) -> Path:
        """Return project root as an absolute path."""
        return Path(self.PROJECT_ROOT).expanduser().resolve()

    def resolve_path(self, path_value: str) -> Path:
        """
        Resolve a path value against project root when it is not absolute.

        Args:
            path_value: Relative or absolute file system path.

        Returns:
            Absolute resolved path.
        """
        path = Path(path_value).expanduser()
        if path.is_absolute():
            return path
        return self.project_root_path / path

    @property
    def memory_file_path(self) -> Path:
        """Return the resolved memory file path."""
        return self.resolve_path(self.MEMORY_FILE)

    @property
    def memory_summary_file_path(self) -> Path:
        """Return the resolved memory summary file path."""
        return self.resolve_path(self.MEMORY_SUMMARY_FILE)

    @property
    def repobrain_dir_path(self) -> Path:
        """Return the resolved repobrain context directory path."""
        return self.resolve_path(self.REPOBRAIN_DIR)

    @property
    def artifacts_path(self) -> Path:
        """Return the resolved artifacts directory path."""
        return self.resolve_path(self.ARTIFACTS_DIR)


# Lazy global settings — instantiated on first access so that env-var
# overrides in tests take effect.
_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the global Settings instance, creating it on first call.

    Resolves the .env path from the *current* value of WORKSPACE_PATH
    rather than the value frozen at class-definition time. This lets
    runtime workspace upgrades (e.g. via MCP roots protocol) take effect
    after `reset_settings()`.
    """
    global _settings
    if _settings is None:
        env_path = Path(os.environ.get("WORKSPACE_PATH", str(Path.cwd()))) / ".env"
        _settings = Settings(_env_file=str(env_path))
    return _settings


def reset_settings() -> None:
    """Reset the cached settings (useful in tests after changing env vars)."""
    global _settings
    _settings = None


class _SettingsProxy:
    """Transparent proxy so ``from config import settings`` keeps working."""

    def __getattr__(self, name: str):
        return getattr(get_settings(), name)

    def __setattr__(self, name: str, value):
        setattr(get_settings(), name, value)

    def __repr__(self) -> str:
        return repr(get_settings())


settings = _SettingsProxy()
