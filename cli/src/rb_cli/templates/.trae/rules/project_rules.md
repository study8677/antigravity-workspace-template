# Trae bootstrap rules

Authoritative behavior rules live in `AGENTS.md` at the project root. Read it
first, then load dynamic context from `.repobrain/` (`conventions.md`,
`structure.md`, `decisions/log.md`, `memory/`).

## Use the RepoBrain knowledge hub

**MANDATORY.** For any *broad* codebase question — "where is X implemented",
"how does X work", "what calls X", architecture, dependency/impact analysis,
data flow, onboarding — you MUST run `rb-ask` first:

```bash
rb-ask "<question>" --workspace .
```

**Hard rule: do NOT manually `grep`, `rg`, `find`, or fan out file reads to
answer a broad question before you have run `rb-ask` for it.** It returns an
answer grounded in real source with file paths and line numbers; start there,
then open only the specific files it points you to.

You do **not** need to run `rb-refresh` by hand: `rb-ask` builds the knowledge
base itself on first use and rebuilds it when it drifts too far behind HEAD
(controlled by `RB_ASK_AUTO_REFRESH` in `.env`). Run `rb-refresh --workspace .`
explicitly only when you want to force a full rebuild.

This works with an API key **or**, with no API key, a local host runner
(`RB_HOST_RUNNER` in `.env`) — including Trae itself — so you can query
RepoBrain without any key changing hands.

Direct file reads or `rg` are allowed **only** to verify exact lines after
`rb-ask` points at a file, for narrow single-symbol lookups (not broad
exploration), or when `rb-ask` is genuinely unavailable.
