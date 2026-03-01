---
name: brainstorm
description: "Use this skill for a live brainstorming meeting: take structured notes while the user thinks out loud, extract claims to fact-check, and produce a final report only when the user ends the session with the exact phrase `brainstorming done` (case-insensitive, normalized)."
---

# brainstorm — Live Session Notes + Fact-checking → Final Report

## Canonical commands (verbatim)
- Start: `/brainstorm start <title>`
- Finish + produce report (allowed natural language): `brainstorming done`

If `<title>` is omitted, ask **one** question: “What’s the topic/title?”

## Source of truth
- Active pointer (canonical): `tmp/brainstorm-active.json`
- Fallback (only if pointer missing): newest `tmp/brainstorm-*/` directory

## End-trigger normalization (FIXED)
Goal: recognize the end trigger reliably across whitespace/case/quotes.

End triggers (case-insensitive):
- `brainstorming done`

### Normalization algorithm
Given the raw user message text:
1) Keep `raw` as-is for logging.
2) Build `candidates`:
   - the full message as one string
   - each individual line (split on `\n`)
3) For each candidate line:
   - trim leading/trailing whitespace
   - strip common quote/reply prefixes **once** (if present): `>`, `|`, `"`, `“`, `”`
   - trim again
4) Match (case-insensitive):
   - `^brainstorming\s+done\s*$`
5) If **any** candidate matches → treat as end trigger.

This accepts standalone, reply, and quoted contexts.

## Reject diagnostics (FIXED)
If the message appears to be an attempted end trigger but does not match:
- Condition: candidate contains `brainstorm` and `done` (any case) but fails the end-trigger regex.
- Append one line to: `tmp/brainstorm-rejects.log`
  - timestamp
  - raw input
  - normalized candidate(s)
  - reject reason (e.g., “extra text after done”)
- Reply with the exact allowed trigger:
  - `brainstorming done`

## Preflight (env / permissions / deps)
- Ensure workspace dirs exist: `tmp/`, `reports/`
- No sub-agents unless the user explicitly asks.
- Fact-check (optional) uses `web_search` + `web_fetch`.

## State files
`tmp/brainstorm-active.json` (recommended schema)
```json
{
  "id": "<timestamp>-<slug>",
  "slug": "<slug>",
  "title": "<Title>",
  "startedAt": "<ISO timestamp>",
  "notesPath": "tmp/brainstorm-<slug>/notes.md",
  "claimsPath": "tmp/brainstorm-<slug>/claims.md"
}
```

Working dir:
- `tmp/brainstorm-<slug>/notes.md` (append-only)
- `tmp/brainstorm-<slug>/claims.md` (append-only)

Slug rules: lowercase, spaces→`-`, strip non `[a-z0-9-]`.

## Runbook (deterministic)

### 1) Start / initialize
Trigger:
- explicit: `/brainstorm start <title>`
- implicit: “let’s brainstorm” / “use this session as a brainstorming meeting”

Steps:
1. Get title (if missing, ask one question).
2. Compute slug.
3. Create `tmp/brainstorm-<slug>/`.
4. Create/append `notes.md`, `claims.md`.
5. Write/overwrite `tmp/brainstorm-active.json`.
6. Confirm in chat where notes are saved + reminder to end with `brainstorming done` to generate the report.

### 2) During the brainstorm (each user message)
- Append message to `notes.md` (timestamp best-effort).
- Extract factual claims → append to `claims.md` as `C-001 UNVERIFIED: ...`.
- Do **not** validate ideas as “true/false” in-chat unless you have actually checked.
- If the user writes just `done`, ask one clarification question: “Do you mean **brainstorming done** (end + generate report)?” (Do not generate until confirmed.)
- Only mark verified/contradicted if you actually checked sources.

### 3) On end trigger → generate report
When an end trigger is detected:
1. Load `tmp/brainstorm-active.json`.
2. Fact-check pass (timebox):
   - Prioritize the top 5–15 highest-impact claims from `claims.md`.
   - Use `web_fetch` / `openclaw docs` (and `web_search` only if configured).
   - Record sources as URLs (and short quotes/snippets when useful).
   - Classify each claim: Verified / Contradicted / Plausible-but-unverified / Unknown.
3. Generate final report in chat.
4. Write `reports/brainstorm-<slug>/report.md`.
5. Clear active state: delete `tmp/brainstorm-active.json` or overwrite with `{}`.

Report format:
- Title + date
- Executive summary (5–10 bullets)
- Session notes (grouped, but don’t drop important details)
- Ideas / options (pros/cons + assumptions)
- Fact-check results:
  - Verified (with sources)
  - Contradicted (with sources)
  - Plausible but unverified
  - Unknown / needs follow-up
- Decisions / next steps

## Verification (smoke checks)
After end:
- `reports/brainstorm-<slug>/report.md` exists and is non-empty
- `tmp/brainstorm-active.json` cleared
- notes/claims files exist

## Rollback
If you need to undo:
- delete `tmp/brainstorm-active.json`
- delete `tmp/brainstorm-<slug>/` and `reports/brainstorm-<slug>/`
