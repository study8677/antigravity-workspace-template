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

**MANDATORY.** When `.repobrain/` exists, any *broad* codebase question MUST go
through `rb-ask` first. Broad questions include: architecture, "where is X
implemented", "how does X work", "what calls X", dependency or impact analysis,
data flow, and onboarding.

```bash
rb-ask "<question>" --workspace .
```

**Hard rule — do NOT manually `grep`, `rg`, `find`, or fan out file reads to
answer a broad question before you have run `rb-ask` for it.** Doing so is
wasteful and skips the grounded, cross-referenced answer the hub already has.
`rb-ask` returns an answer backed by real source with file paths and line
numbers; start there, then open only the specific files it points you to.

This CLI is the lightweight way to let any agent that can run shell commands
query RepoBrain — no long-running MCP server required. (An MCP server, `rb-mcp`,
also exists for MCP-only clients, but the CLI is preferred when you can shell
out.) Both paths run the same engine, so they work with an API-key provider or,
with no API key, a local host runner (`RB_HOST_RUNNER` in `.env`) that drives a
CLI you are already logged into (Codex / Trae / Claude / …).

`rb-ask` is read-only. It warns when committed code is newer than the active
knowledge generation but never refreshes automatically. Build the first
generation explicitly with:

```bash
rb-refresh --workspace .
```

After later commits, run the committed-diff impact loop manually. It requires a
clean worktree and updates only Agent groups that RepoBrain's planner and
verifier prove are affected:

```bash
rb-refresh --workspace . --quick
```

Direct file reads, `grep`, or `rg` are allowed **only** for:

- verifying exact lines after `rb-ask` gives candidate files
- narrow symbol or single-string lookups (not broad exploration)
- editing or debugging specific files you already located
- cases where `rb-ask` is genuinely unavailable or fails (state which)
