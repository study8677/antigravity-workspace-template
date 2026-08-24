Beautiful is better than ugly.
Explicit is better than implicit.
Simple is better than complex.
Complex is better than complicated.
Flat is better than nested.
Sparse is better than dense.
Readability counts.
Special cases aren't special enough to break the rules.
Although practicality beats purity.
Errors should never pass silently.
Unless explicitly silenced.
In the face of ambiguity, refuse the temptation to guess.
There should be one-- and preferably only one --obvious way to do it.
Although that way may not be obvious at first unless you're Dutch.
Now is better than never.
Although never is often better than *right* now.
If the implementation is hard to explain, it's a bad idea.
If the implementation is easy to explain, it may be a good idea.
Namespaces are one honking great idea -- let's do more of those!

## RepoBrain Knowledge Hub

For broad codebase questions, architecture questions, "where is X implemented",
"how does X work", dependency or impact analysis, or onboarding questions, prefer:

```bash
rb-ask "<question>" --workspace .
```

Use this before broad grep, rg, or file search when `.repobrain/` exists.

If you are an LLM or script calling RepoBrain programmatically (not a human
reading the terminal), add `--json` to get a stable, parseable envelope instead
of formatted prose — no need to scrape the text:

```bash
rb-ask "<question>" --workspace . --json
# → {"answer": "...", "sources": [...], "limitations": [...],
#    "workspace": "...", "question": "..."}
```

On failure with `--json`, stdout stays empty and a `{"error": "..."}` object is
written to stderr with a non-zero exit code, so callers can branch on it cleanly.

This CLI is the lightweight way to let any agent that can run shell commands
query RepoBrain — no long-running MCP server required. (An MCP server, `rb-mcp`,
also exists for MCP-only clients, but the CLI is preferred when you can shell
out.) Both paths run the same engine, so they work with an API-key provider or,
with no API key, a local host runner (`RB_HOST_RUNNER` in `.env`) that drives a
CLI you are already logged into (Codex / Trae / Claude / …).

You normally do **not** need to run `rb-refresh` yourself: `rb-ask` keeps its
own knowledge base current. It builds the base automatically on first use (when
`.repobrain/` is missing) and rebuilds it when it drifts too far behind HEAD.
This is governed by `RB_ASK_AUTO_REFRESH` in `.env` (`stale` = first-run +
drift, the default; `first-only`; or `off`).

Run this explicitly only to force a full rebuild:

```bash
rb-refresh --workspace .
```

Use direct file reads or rg only for:

- verifying exact lines after `rb-ask` gives candidate files
- narrow symbol or string searches
- editing or debugging specific files
- cases where `rb-ask` is unavailable or fails
