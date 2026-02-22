---
name: connect-dots
description: "Internal chief-of-staff user-intelligence memory model. Use when the agent should: (1) run a silent nightly sensemaking pass to update an internal model of the user/projects/environment from memory files, (2) surface time-sensitive high-confidence suggestions with strict anti-noise gating, or (3) handle consent controls like 'don’t store this', 'forget <x>', or 'show what you currently assume about me' (bounded, cited snapshot). Designed to integrate with OpenClaw memory_search + local SQLite semantic index; writes only to tmp/connect-dots and (feature-flag) memory/internal/connect-dots; never auto-writes MEMORY.md or memory/GOALS.md (proposal only)."
---

# connect-dots — Trusted Chief-of-Staff Memory Model

Purpose: build a **privacy-respecting, evidence-cited user intelligence model** over time (preferences, objectives, projects, environment) so the assistant becomes more context-aware and socially intelligent.

This skill is **not** a dev-ops autopilot. Repo/project signals are **evidence streams** to infer high-level meaning (goals, blockers, motivations).

## Non-negotiables (hard guards)
- **Single-message policy** when surfacing: one calm, high-signal message (no dumps).
- **Strict caps** per section (never exceed).
- **Evidence contract**: every non-trivial item must include `Source: <path#Lx-Ly> (Nd ago)`.
- **No action from uncertain items** until confirmed.
- **Sensitive domains** are auto-hidden unless explicitly requested.
- **Never auto-write** to `MEMORY.md` or `memory/GOALS.md` (proposal/patch only).

## Scopes (v1)
1) `user-profile/preferences` (built gradually from interactions; facts require explicit confirmation)
2) `openclaw-runtime/ops`
3) `repos`

## Where state lives
- Always allowed (ephemeral): `tmp/connect-dots/`
  - `tmp/connect-dots/state.json` (timestamps, cooldowns)
  - `tmp/connect-dots/proposals/` (patch proposals)
- Feature-flag (default ON; indexed/searchable): `memory/internal/connect-dots/`
  - `memory/internal/connect-dots/<scope>/model.json`
  - optional snapshots: `memory/internal/connect-dots/<scope>/snapshots/YYYY-MM-DD.json`

Feature flag:
- ON by default.
- Disable by creating: `memory/internal/connect-dots/.disabled`

## Deterministic gates (locked)
- Night run gate:
  - `night_run = (idle_hours >= 6)`
- Daytime surfacing gate:
  - `surface = (conf >= 80) && (timeliness || blocker || deadline)`

### Timeliness triggers (v1)
- `openclaw-runtime/ops`: health flips to ISSUES, gateway/port down, memory index/search disabled or unavailable.
- `repos`: CI failing, waiting on review, PR stuck > N days, or JD mentions a near-term release/deadline.

## Model policy (locked)
- Nightly brief generation: **force highest reasoning model** (scheduler/config does this).
- Daytime: force highest reasoning only if gate opens and `(conf >= 85% OR action is high-impact/irreversible)`.
- Otherwise: default model.

## Consent controls (must obey)
Handle these immediately and persistently:
- **“don’t store this”** → add to `do_not_store[]` and avoid saving/resurfacing matching content.
- **“forget <x>”** → retract matching items (mark `status=retracted`) and suppress future resurfacing.
- **“show what you currently assume about me”** → render the bounded snapshot below.

## Deterministic core rule (locked)
- **LLM produces proposals. Scripts mutate state.**
- Fail closed: invalid proposal/schema mismatch/bad citations ⇒ **no write**.

Scripts:
- `scripts/build_model.py` — merge proposals, recompute confidence/expiry, TTL decay → writes `model.json`
- `scripts/consent_mutations.py` — apply consent operations (don’t store / forget / confirm / deny)
- `scripts/model_diff.py` — diff snapshots (for “what changed”)
- `scripts/validate_model.py` — JSON Schema validation

Schemas:
- `references/proposal.schema.json`
- `references/model.schema.json`

## Nightly run workflow (silent)
When invoked by an internal scheduler message (e.g., “connect-dots nightly run”):

1) **Check gates**
   - Compute `idle_hours`.
   - If `idle_hours < 6`, exit silently.

2) **Collect evidence** (per scope)
   - Use `memory_search` to find high-signal recent items.
   - For each candidate, `read` the source file and extract precise quotes + line ranges.

3) **Synthesize proposal (LLM output, no writes yet)**
   - Write `tmp/connect-dots/proposals/<scope>.json` matching `references/proposal.schema.json`.

4) **Bridge (proposal → diff → optional apply)**
   - Use `scripts/nightly_run.py`:
     - Phase 1 (2 nights): proposal validate + diff only (no writes)
     - Phase 2: apply via `build_model.py` if validation passes (fail-closed)
   - Per-run artifacts live under: `tmp/connect-dots/runs/<runId>/...`

5) **No messaging at night**
   - Do not DM/announce. This run is internal state preparation.

## Daytime surfacing workflow (human timing)
Only surface when the gate opens. Then:
- Batch into one message.
- If approval required, ask one crisp question with options.

## “Show assumptions about me” (locked output)
Use `scripts/render_assumptions.py` if available; otherwise follow the exact template.

Hard UX rules: one message; strict caps; every non-trivial item includes citation+recency; every hypothesis includes expiry.

1) **Confirmed facts (max 5)**
- `fact · value · last confirmed · Source: path#Lx-Ly (Nd ago)`

2) **Top hypotheses (max 5)**
- `hypothesis · confidence · why I think this · what would confirm/deny · expires: YYYY-MM-DD · Source: ... (Nd ago)`

3) **Stale assumptions (max 3)**
- `item · why stale · proposed action (refresh/drop) · Source: ... (Nd ago)`

4) **Do-not-store protections (active)**
- `patterns/domains currently blocked`

5) **What changed since last snapshot**
- `+ added ...`
- `~ updated ...`
- `- retracted ...`

6) **Control shortcuts**
- `forget <x> · don’t store <x> · confirm <x> · deny <x>`

### Micro-question templates (one at a time)
- Confirm: “Quick confirm: is this true — <statement>? (yes/no)”
- A/B: “For <topic>, which is closer: A <option> or B <option>?”
- Scope check: “Apply this to all chats or only <scope>?”
- Stale refresh: “I might be outdated on <item>. Still true? (yes/no/update)”
- Consent: “Okay to store this as a preference? (store once / store always / don’t store)”

## References
- See `references/spec.md` for schema details, TTL/expiry rules, and the autonomy matrix.
