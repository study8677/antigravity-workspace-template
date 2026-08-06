---
description: First-time setup. Configure the LLM API key or local Codex host runner RepoBrain uses for codebase Q&A. / 首次 setup，配置 RepoBrain 代码问答所需的 LLM API key 或本地 Codex host runner。
---

You are running first-time setup for the RepoBrain plugin. The user just installed the plugin and needs either an LLM API key or the explicit local Codex host-runner mode configured before the ask commands will work (`/repobrain:rb-ask` in Claude Code; `/rb-ask` in Codex CLI). Full LLM refresh still requires an API key; no-key users can run scan-only refresh. Goal: write a `.env` file at the current workspace root.

你正在执行 RepoBrain 插件的首次 setup。用户刚安装插件，需要先配置 LLM API key，或显式启用本地 Codex host-runner 模式，ask 命令才能正常工作（Claude Code 内为 `/repobrain:rb-ask`；Codex CLI 内为 `/rb-ask`）。完整 LLM refresh 仍需要 API key；无 key 用户可以运行 scan-only refresh。目标是在当前工作区根目录写入 `.env` 文件。

## Step 1 — Detect existing config / 步骤 1 —— 检测已有配置

Read `.env` at the workspace root if it exists. If `OPENAI_API_KEY` or `RB_HOST_RUNNER` is already set, ask the user whether to overwrite the RepoBrain LLM/host-runner keys. If they say no, confirm "already configured" and stop.

如果工作区根目录已有 `.env`，先读取它。如果已经设置了 `OPENAI_API_KEY` 或 `RB_HOST_RUNNER`，询问用户是否覆盖 RepoBrain 的 LLM/host-runner 配置。若用户选择不覆盖，确认“already configured / 已配置”并停止。

## Step 2 — Ask which LLM provider (use AskUserQuestion) / 步骤 2 —— 询问 LLM 提供商（使用 AskUserQuestion）

Present these options:

向用户展示以下选项：

- **OpenAI** — gpt-4o-mini / gpt-4o
- **DeepSeek** — cheap, strong on code
- **Groq** — fast, free tier
- **阿里灵积 (DashScope)** — qwen 系列
- **NVIDIA NIM** — generous free tier
- **[OrcaRouter](https://www.orcarouter.ai)** — one key for 150+ models; gateway-level, zero-trust AI-agent security on the same endpoint
- **Ollama 本地** — no key needed, runs locally
- **Codex CLI 本地实验模式** — no API key, uses the user's local `codex login`; supports `rb-ask` only
- **其他 OpenAI 兼容端点** — custom URL

## Step 3 — Collect URL / key / model / 步骤 3 —— 收集 URL / key / model

Use this table to set the URL and suggest a model based on the provider:

根据用户选择的提供商，使用下表设置 URL 并建议模型：

| Provider / 提供商 | `OPENAI_BASE_URL` | Suggested `OPENAI_MODEL` / 建议模型 |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| 阿里灵积 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-max` |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | `meta/llama-3.3-70b-instruct` |
| OrcaRouter | `https://api.orcarouter.ai/v1` | `orcarouter/auto` |
| Ollama 本地 | `http://localhost:11434/v1` | `llama3.2` (key can be `ollama`) |
| Codex CLI 本地实验模式 | not used | `gpt-5.3-codex-spark` via `RB_HOST_MODEL` |
| 其他 | ask the user | ask the user |

For non-Ollama providers ask the user to paste their key. For Ollama use `OPENAI_API_KEY=ollama` (the engine requires the field to be non-empty).

非 Ollama 提供商需要让用户粘贴 API key。Ollama 使用 `OPENAI_API_KEY=ollama`（engine 要求该字段非空）。

For Codex CLI local experimental mode, first check that `codex login status` reports a ChatGPT login. Do not ask for an API key and do not write a fake `OPENAI_API_KEY`.

Codex CLI 本地实验模式需要先确认 `codex login status` 显示已用 ChatGPT 登录。不要询问 API key，也不要写假的 `OPENAI_API_KEY`。

## Step 4 — Write `.env` / 步骤 4 —— 写入 `.env`

Write to `<workspace>/.env`:

写入 `<workspace>/.env`：

For OpenAI-compatible providers:

OpenAI-compatible provider 写入：

```
OPENAI_BASE_URL=<chosen URL>
OPENAI_API_KEY=<the key, or "ollama">
OPENAI_MODEL=<chosen model>
RB_ASK_TIMEOUT_SECONDS=120
```

For Codex CLI local experimental mode:

Codex CLI 本地实验模式写入：

```
RB_HOST_RUNNER=codex
RB_HOST_MODEL=gpt-5.3-codex-spark
RB_HOST_TIMEOUT_SECONDS=240
RB_HOST_MAX_CONTEXT_CHARS=60000
RB_REFRESH_SCAN_ONLY=1
RB_ASK_TIMEOUT_SECONDS=120
```

If `.env` already existed and the user opted to overwrite, replace only the relevant keys above; preserve any other lines.

如果 `.env` 已存在且用户选择覆盖，只替换上面相关 key；保留其他行。

## Step 5 — Ensure `.env` is git-ignored / 步骤 5 —— 确保 `.env` 已加入 git ignore

Check `<workspace>/.gitignore`. If `.env` is not listed (and there is no globbing rule that already covers it), append `.env` on a new line. If `.gitignore` doesn't exist, create one with `.env`.

检查 `<workspace>/.gitignore`。如果 `.env` 未列出，且没有其他 glob 规则覆盖它，就追加一行 `.env`。如果 `.gitignore` 不存在，创建一个只包含 `.env` 的文件。

## Step 6 — Tell the user next steps / 步骤 6 —— 告诉用户下一步

Print exactly (use the Claude form `/repobrain:rb-*` if running in Claude Code; use the bare form `/rb-*` if running in Codex CLI):

严格输出（在 Claude Code 内使用 `/repobrain:rb-*` 形式；在 Codex CLI 内使用裸 `/rb-*` 形式）：

```
✅ RepoBrain is configured for this project.
✅ RepoBrain 已为当前项目配置完成。

Next / 下一步:
  1. /rb-refresh        — build the knowledge base (API-key mode)
     构建知识库（一次性操作；小仓库通常需要几分钟）。
  2. /rb-ask <question> — ask anything about the codebase
     询问任何关于代码库的问题。
```

If configured for Codex CLI local experimental mode, print this instead:

如果配置的是 Codex CLI 本地实验模式，改为输出：

```
✅ RepoBrain is configured for local Codex host-runner mode.
✅ RepoBrain 已配置为本地 Codex host-runner 模式。

Next / 下一步:
  1. /rb-refresh
     无 API key 时生成本地扫描知识产物。
  2. /rb-ask <question>
     通过本机 Codex 登录询问当前代码库。
```

Do NOT call MCP tools from this command. The refresh and ask slash commands use the CLI (`rb-refresh` / `rb-ask`) directly and will read the `.env` file on each run.

不要在本命令中调用 MCP 工具。refresh 和 ask 斜杠命令会直接使用 CLI（`rb-refresh` / `rb-ask`），每次运行都会读取 `.env` 文件。
