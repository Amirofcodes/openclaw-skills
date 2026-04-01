# connect-dots — Pending decisions integration (simple version)

Purpose: let `connect-dots` become aware of the workspace pending-decisions canon without turning it into an autonomy loophole.

Source file:
- `docs/assistant/PENDING_DECISIONS.md`

## Why this matters
A deferred decision is a useful signal about:
- what JD intentionally parked
- what must be revisited when a trigger is hit
- which decision classes still require JD involvement
- which low-risk decision classes might later become safe to handle autonomously

This helps `connect-dots` become a better chief-of-staff assistant by learning decision patterns, not by silently taking extra authority.

## Minimal scope
Phase 1 should stay simple.

`connect-dots` should be able to:
1. read the active pending-decisions canon
2. detect when a revisit trigger has likely become relevant
3. notice obvious missing deferred decisions from explicit language like:
   - "we'll decide later"
   - "not now"
   - "after X"
   - "defer this"
4. generate a structured candidate/proposal for a new PD entry

Current deterministic helper path:
- `scripts/pending_decisions.py parse` — parse active/resolved PD entries
- `scripts/pending_decisions.py prepare-proposal` — validate a structured candidate, dedupe it against canon, and render a reviewable row + markdown block
- `references/pending-decision.schema.json` — proposal-mode candidate schema

It should **not** yet:
- silently rewrite the canon from vague inference
- promote a one-off approval into broad autonomy
- infer that unresolved strategy questions are now safe to decide alone

## Write policy
Start in **proposal mode**.

Meaning:
- LLM may propose a pending-decision candidate
- deterministic script validates shape, dedupe, and trigger presence
- output is a local proposal or patch
- no auto-append to canon until the path is proven reliable

Later, auto-append can be allowed only for:
- explicit defer language
- clear trigger
- `docs-only` blast radius
- no duplicate / collision

## What to learn over time
Use accepted/rejected/edited pending decisions to learn:
- which decision classes JD consistently defers
- which decision classes JD wants revisited with a trigger
- which low-risk classes JD is happy for the assistant to handle autonomously
- which classes remain approval-first (external, strategic, risky, irreversible, secrets)

This is a **decision-policy learning loop**, not permission creep.

## Recommended first implementation
Keep it minimal:
1. parse `docs/assistant/PENDING_DECISIONS.md`
2. expose active items to nightly/daytime reasoning
3. emit `pending_decision_candidates.json` from explicit defer signals
4. optionally render a markdown patch for review

## Safety line
Target outcome:
- fewer unnecessary questions for JD over time
- better timing on resurfacing real decisions
- more autonomy for low-risk internal work
- no silent expansion into higher-risk decisions
