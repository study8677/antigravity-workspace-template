# Trae bootstrap rules

Authoritative behavior rules live in `AGENTS.md` at the project root. Read it
first, then load dynamic context from `.repobrain/` (`conventions.md`,
`structure.md`, `decisions/log.md`, `memory/`).

## Use the RepoBrain knowledge hub

For broad codebase questions — "where is X implemented", "how does X work",
architecture, dependency/impact analysis, onboarding — prefer running:

```bash
rb-ask "<question>" --workspace . --json
```

over grep / rg / manual file reading. It returns an answer grounded in real
source with file paths and line numbers. The `--json` form gives you a stable
`{answer, sources, limitations, workspace, question}` object; on failure stdout
stays empty and a `{"error": "..."}` object is written to stderr with a
non-zero exit code, so you can branch on it cleanly.

You do **not** need to run `rb-refresh` by hand: `rb-ask` builds the knowledge
base itself on first use and rebuilds it when it drifts too far behind HEAD
(controlled by `RB_ASK_AUTO_REFRESH` in `.env`). Run `rb-refresh --workspace .`
explicitly only when you want to force a full rebuild.

This works with an API key **or**, with no API key, a local host runner
(`RB_HOST_RUNNER` in `.env`) — including Trae itself — so you can query
RepoBrain without any key changing hands.

Use direct file reads or rg only to verify exact lines after `rb-ask` points at
a file, for narrow symbol searches, or when `rb-ask` is unavailable.
