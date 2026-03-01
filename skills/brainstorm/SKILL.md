---
name: brainstorm
description: "Use this skill for a live brainstorming meeting: take structured notes while the user thinks out loud, extract claims to fact-check, and produce a final report only when the user ends the session with the exact phrase `brainstorming done` (case-insensitive, normalized)."
---

# brainstorm — Live Session Notes + Fact-checking → Final Report

## Canonical commands (verbatim)
- Start: `/brainstorm start <title>`
- Finish + produce report (allowed natural language): `brainstorming done`

If `<title>` is omitted, ask **one** question: “What’s the topic/title?”

### Title conventions (mode)
Default mode is **general**.

To run a brainstorm as part of the **coding workflow** (generate execution artifacts), encode the mode into the title:
- Coding workflow:
  - `/brainstorm start [coding] <title>`
  - `/brainstorm start coding: <title>`
- General (optional explicit tag):
  - `/brainstorm start [general] <title>`

Mode detection rule (deterministic):
- If title contains `[coding]` or starts with `coding:` → `mode=coding-workflow`
- Else → `mode=general`

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

## Mode behavior

### Mode: general
- Produces the standard brainstorm report.

### Mode: coding-workflow
In addition to the standard report, produces the minimum execution artifacts:
- `BRIEF.md`
- `TECH_NOTES.md`
- `OPEN_QUESTIONS.md`

These are written to:
- `reports/brainstorm-<slug>/artifacts/`

Note: We intentionally keep this minimal to avoid overplanning. These artifacts + the brainstorm report should be sufficient to generate `ROADMAP.md` and `TODO.md` in the next phase.

## State files
`tmp/brainstorm-active.json` (recommended schema)
```json
{
  "id": "<timestamp>-<slug>",
  "slug": "<slug>",
  "title": "<Title>",
  "mode": "general | coding-workflow",
  "startedAt": "<ISO timestamp>",
  "notesPath": "tmp/brainstorm-<slug>/notes.md",
  "claimsPath": "tmp/brainstorm-<slug>/claims.md",
  "reportDir": "reports/brainstorm-<slug>/",
  "artifactsDir": "reports/brainstorm-<slug>/artifacts/"
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
2. Determine mode from title (see "Title conventions").
3. Normalize title:
   - strip `[coding]` / `[general]` tags if present
   - strip leading `coding:` if present
   - trim whitespace
4. Compute slug from the normalized title.
5. Create `tmp/brainstorm-<slug>/`.
6. Create/append `notes.md`, `claims.md`.
7. Write/overwrite `tmp/brainstorm-active.json` (include `mode`, `reportDir`, `artifactsDir`).
8. Confirm in chat:
   - where notes are saved
   - which mode is active
   - reminder to end with `brainstorming done` to generate the report (and artifacts if coding-workflow).

### 2) During the brainstorm (each user message)
- Append message to `notes.md` (timestamp best-effort).
- Extract factual claims → append to `claims.md` as `C-001 UNVERIFIED: ...`.
- Do **not** validate ideas as “true/false” in-chat unless you have actually checked.
- If the user writes just `done`, ask one clarification question: “Do you mean **brainstorming done** (end + generate report)?” (Do not generate until confirmed.)
- Only mark verified/contradicted if you actually checked sources.

### 3) On end trigger → generate report (+ artifacts in coding mode)
When an end trigger is detected:
1. Load `tmp/brainstorm-active.json`.
2. Fact-check pass (timebox):
   - Prioritize the top 5–15 highest-impact claims from `claims.md`.
   - Use `web_fetch` / `openclaw docs` (and `web_search` only if configured).
   - Record sources as URLs (and short quotes/snippets when useful).
   - Classify each claim: Verified / Contradicted / Plausible-but-unverified / Unknown.
3. Generate final report in chat.
4. Write `reports/brainstorm-<slug>/report.md`.
5. If `mode=coding-workflow`, also write artifacts:
   - `reports/brainstorm-<slug>/artifacts/BRIEF.md`
   - `reports/brainstorm-<slug>/artifacts/TECH_NOTES.md`
   - `reports/brainstorm-<slug>/artifacts/OPEN_QUESTIONS.md`
6. Clear active state: delete `tmp/brainstorm-active.json` or overwrite with `{}`.

Report format:
- Title + date
- Mode (general | coding-workflow)
- Executive summary (5–10 bullets)
- Session notes (grouped, but don’t drop important details)
- Ideas / options (pros/cons + assumptions)
- Fact-check results:
  - Verified (with sources)
  - Contradicted (with sources)
  - Plausible but unverified
  - Unknown / needs follow-up
- Decisions / next steps
- (If coding-workflow) Artifacts:
  - paths to BRIEF/TECH_NOTES/OPEN_QUESTIONS

Artifact guidelines (coding-workflow)
- BRIEF.md
  - goal
  - non-goals
  - constraints
  - success criteria
- TECH_NOTES.md
  - chosen stack + reasons
  - tradeoffs
  - risks
  - key implementation notes
- OPEN_QUESTIONS.md
  - must-answer before sprint-001
  - optional nice-to-answer later

## Verification (smoke checks)
After end:
- `reports/brainstorm-<slug>/report.md` exists and is non-empty
- `tmp/brainstorm-active.json` cleared
- notes/claims files exist
- If `mode=coding-workflow`:
  - `reports/brainstorm-<slug>/artifacts/BRIEF.md` exists and is non-empty
  - `reports/brainstorm-<slug>/artifacts/TECH_NOTES.md` exists and is non-empty
  - `reports/brainstorm-<slug>/artifacts/OPEN_QUESTIONS.md` exists and is non-empty

## Rollback
If you need to undo:
- delete `tmp/brainstorm-active.json`
- delete `tmp/brainstorm-<slug>/` and `reports/brainstorm-<slug>/`
