---
description: First-time setup. Configure the LLM API key, or a no-API-key local host runner (Codex / Trae / Claude / any headless CLI) that RepoBrain uses for codebase Q&A and refresh. / 首次 setup，配置 RepoBrain 代码问答与 refresh 所需的 LLM API key，或无需 API key 的本地 host runner（Codex / Trae / Claude / 任意无头 CLI）。
---

You are running first-time setup for the RepoBrain plugin. The user just installed the plugin and needs an LLM backend configured before the ask/refresh commands will work (`/repobrain:rb-ask` in Claude Code; `/rb-ask` in Codex CLI). There are two families of backends:

1. **API-key providers** (OpenAI-compatible) — write `OPENAI_*` keys.
2. **Local host runners (no API key)** — drive a headless CLI the user already has logged in (Codex, Trae, Claude, or any command that answers a prompt on stdin). This covers both `rb-ask` **and** `rb-refresh`: refresh runs its tool-free stages (module docs, map) through the host runner and automatically falls back to deterministic output for tool/handoff stages (conventions, git insights).

Goal: write a `.env` file at the current workspace root.

你正在执行 RepoBrain 插件的首次 setup。用户刚安装插件，需要先配置一个 LLM 后端，ask/refresh 命令才能正常工作（Claude Code 内为 `/repobrain:rb-ask`；Codex CLI 内为 `/rb-ask`）。后端分两类：

1. **API-key 提供商**（OpenAI 兼容）—— 写入 `OPENAI_*` 配置。
2. **本地 host runner（无需 API key）**—— 驱动用户本机已登录的无头 CLI（Codex、Trae、Claude，或任意能在命令行吃 prompt、吐文本的命令）。这条路同时支持 `rb-ask` **和** `rb-refresh`：refresh 的无工具阶段（module 文档、map）走 host runner，工具/handoff 阶段（conventions、git insights）会自动降级为确定性产物。

目标是在当前工作区根目录写入 `.env` 文件。

## Step 1 — Detect existing config / 步骤 1 —— 检测已有配置

Read `.env` at the workspace root if it exists. If `OPENAI_API_KEY` or `RB_HOST_RUNNER` is already set, ask the user whether to overwrite the RepoBrain LLM/host-runner keys. If they say no, confirm "already configured" and stop.

如果工作区根目录已有 `.env`，先读取它。如果已经设置了 `OPENAI_API_KEY` 或 `RB_HOST_RUNNER`，询问用户是否覆盖 RepoBrain 的 LLM/host-runner 配置。若用户选择不覆盖，确认“already configured / 已配置”并停止。

## Step 2 — Ask which backend (use AskUserQuestion) / 步骤 2 —— 询问后端（使用 AskUserQuestion）

First, detect which local headless CLIs are available so you only offer runners that can actually work. Run these checks (ignore ones that error):

先探测本机可用的无头 CLI，只向用户提供真正能用的 runner。运行以下检查（报错的忽略即可）：

- `command -v codex` and, if present, `codex login status`
- `command -v trae-cli` and, if present, `trae-cli login status`
- `command -v claude` (Claude Code; logged-in state is implicit)
- `command -v gemini`, `command -v ollama`

Present these options. **List the detected local CLIs first** (they need no API key), then the API-key providers:

向用户展示以下选项。**优先列出探测到的本地 CLI**（无需 API key），再列 API-key 提供商：

- **本地 CLI（无 API key）** — pick this if `codex` / `trae-cli` / `claude` / `gemini` was detected. Drives your already-logged-in CLI for both `rb-ask` and `rb-refresh`.
- **OpenAI** — gpt-4o-mini / gpt-4o
- **DeepSeek** — cheap, strong on code
- **Groq** — fast, free tier
- **阿里灵积 (DashScope)** — qwen 系列
- **NVIDIA NIM** — generous free tier
- **Ollama 本地** — no key needed, runs a local model server
- **其他 OpenAI 兼容端点** — custom URL

If the user picks **本地 CLI（无 API key）**, ask a follow-up with the concrete detected runners (e.g. Codex / Trae / Claude) so they choose exactly one.

如果用户选择 **本地 CLI（无 API key）**，再追问一次，列出具体探测到的 runner（如 Codex / Trae / Claude），让用户选定其中一个。

## Step 3 — Collect URL / key / model / 步骤 3 —— 收集 URL / key / model

### 3a — API-key providers / API-key 提供商

Use this table to set the URL and suggest a model based on the provider:

根据用户选择的提供商，使用下表设置 URL 并建议模型：

| Provider / 提供商 | `OPENAI_BASE_URL` | Suggested `OPENAI_MODEL` / 建议模型 |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| 阿里灵积 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-max` |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | `meta/llama-3.3-70b-instruct` |
| Ollama 本地 | `http://localhost:11434/v1` | `llama3.2` (key can be `ollama`) |
| 其他 | ask the user | ask the user |

For non-Ollama providers ask the user to paste their key. For Ollama use `OPENAI_API_KEY=ollama` (the engine requires the field to be non-empty).

非 Ollama 提供商需要让用户粘贴 API key。Ollama 使用 `OPENAI_API_KEY=ollama`（engine 要求该字段非空）。

### 3b — Local host runners (no API key) / 本地 host runner（无 API key）

For a local runner, first **verify the CLI is logged in** — do NOT ask for an API key and do NOT write a fake `OPENAI_API_KEY`. If the login check fails, tell the user to log in first and stop:

选了本地 runner 时，先**确认该 CLI 已登录**——不要询问 API key，也不要写假的 `OPENAI_API_KEY`。若登录检查失败，提示用户先登录并停止：

| Runner | Login check / 登录检查 | `RB_HOST_RUNNER` | Notes / 说明 |
|---|---|---|---|
| Codex | `codex login status` must report a ChatGPT login | `codex` | Built-in preset; model via `RB_HOST_MODEL` |
| Trae | `trae-cli login status` must report logged in | `generic` | Set `RB_HOST_COMMAND` (below) |
| Claude | `claude` present (login is implicit) | `generic` | Set `RB_HOST_COMMAND` (below) |
| 其他 CLI | ask the user how to run it headlessly | `generic` | Set `RB_HOST_COMMAND` (below) |

For **Codex**, no command template is needed — it is a built-in preset. For every **generic** runner, write an `RB_HOST_COMMAND` template. Use these verified templates (all deliver the prompt on **stdin** and read the answer from `{output_file}`, so `RB_HOST_OUTPUT_MODE=file`):

**Codex** 无需命令模板（内置预设）。所有 **generic** runner 都需要写 `RB_HOST_COMMAND` 模板。使用下列已验证的模板（都通过 **stdin** 传入 prompt，从 `{output_file}` 读回答案，因此 `RB_HOST_OUTPUT_MODE=file`）：

| Runner | `RB_HOST_COMMAND` |
|---|---|
| Trae | `trae-cli exec --cd {workspace} --sandbox read-only --skip-git-repo-check --ephemeral -o {output_file}` |
| Claude | `claude -p --add-dir {workspace}` (uses `RB_HOST_OUTPUT_MODE=stdout`) |
| 其他 | Ask the user for a command that reads a prompt on stdin and prints the answer. Add `-o {output_file}` if the CLI supports writing its final message to a file; otherwise use stdout mode. |

Do NOT put `{prompt_file}` in the template — omitting it makes RepoBrain feed the prompt on stdin, which is the most portable path. Only add `{prompt_file}` if a CLI cannot read stdin.

模板里**不要**写 `{prompt_file}`——省略它 RepoBrain 会自动把 prompt 喂给 stdin，这是最通用的方式。只有当某个 CLI 无法读 stdin 时，才加 `{prompt_file}`。

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

For the **Codex** local runner (built-in preset, no command template):

**Codex** 本地 runner（内置预设，无需命令模板）写入：

```
RB_HOST_RUNNER=codex
RB_HOST_MODEL=gpt-5.3-codex-spark
RB_HOST_TIMEOUT_SECONDS=240
RB_HOST_MAX_CONTEXT_CHARS=60000
RB_ASK_TIMEOUT_SECONDS=120
```

For a **generic** local runner (Trae / Claude / other) — substitute the `RB_HOST_COMMAND` and `RB_HOST_OUTPUT_MODE` chosen in Step 3b:

**generic** 本地 runner（Trae / Claude / 其他）写入 —— 代入步骤 3b 选定的 `RB_HOST_COMMAND` 与 `RB_HOST_OUTPUT_MODE`：

```
RB_HOST_RUNNER=generic
RB_HOST_COMMAND=<the chosen command template>
RB_HOST_OUTPUT_MODE=<file or stdout>
RB_HOST_TIMEOUT_SECONDS=240
RB_HOST_MAX_CONTEXT_CHARS=60000
RB_ASK_TIMEOUT_SECONDS=120
```

Do **not** write `RB_REFRESH_SCAN_ONLY=1` by default: host-runner refresh now runs the module/map LLM stages and gracefully degrades the tool/handoff stages. Only add `RB_REFRESH_SCAN_ONLY=1` if the user explicitly wants a fast structure-only index with no LLM narration. Do not write any `OPENAI_*` keys for a local runner.

默认**不要**写 `RB_REFRESH_SCAN_ONLY=1`：host-runner 的 refresh 现在会跑 module/map 的 LLM 阶段，并对工具/handoff 阶段自动降级。只有当用户明确想要"仅结构索引、无 LLM 叙述"的快速模式时，才加 `RB_REFRESH_SCAN_ONLY=1`。本地 runner 不要写任何 `OPENAI_*` 配置。

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

If configured for a local host runner (Codex / Trae / Claude / other), print this instead — fill in the runner name:

如果配置的是本地 host runner（Codex / Trae / Claude / 其他），改为输出（填入 runner 名称）：

```
✅ RepoBrain is configured for local host-runner mode (<runner>).
✅ RepoBrain 已配置为本地 host-runner 模式（<runner>）。

Next / 下一步:
  1. /rb-refresh
     通过本机 <runner> 构建知识库；module 文档与 map 由 <runner> 生成，
     conventions 与 git insights 自动降级为确定性产物。
  2. /rb-ask <question>
     通过本机 <runner> 询问当前代码库（零 API key）。
```

Do NOT call MCP tools from this command. The refresh and ask slash commands use the CLI (`rb-refresh` / `rb-ask`) directly and will read the `.env` file on each run.

不要在本命令中调用 MCP 工具。refresh 和 ask 斜杠命令会直接使用 CLI（`rb-refresh` / `rb-ask`），每次运行都会读取 `.env` 文件。
