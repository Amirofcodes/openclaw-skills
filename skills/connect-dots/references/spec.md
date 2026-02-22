# connect-dots — Spec (locked)

This is the implementation contract for the internal "trusted chief-of-staff" user-intelligence skill.

## 1) Goals
- Extract **meaning** from user actions/requests across sessions to improve assistant responses and proactivity.
- Treat projects/repos as **evidence streams**, not the objective.

## 2) Scopes (v1)
- `user-profile/preferences`
- `openclaw-runtime/ops`
- `repos`

## 3) Storage + write policy
Allowed:
- `tmp/connect-dots/...` (always)
- `memory/internal/connect-dots/...` (feature flag, default ON)

Never auto-write:
- `MEMORY.md`
- `memory/GOALS.md`

Curated-memory updates are proposal/patch only.

Feature flag:
- disable indexing writes by creating: `memory/internal/connect-dots/.disabled`

## 4) Gates (deterministic)
Night run:
- `night_run = (idle_hours >= 6)`

Daytime surfacing:
- `surface = (conf >= 80) && (timeliness || blocker || deadline)`

## 5) Timeliness triggers (v1)
- `openclaw-runtime/ops`:
  - health flips to ISSUES
  - gateway/port down
  - memory index/search disabled or unavailable
- `repos`:
  - CI failing
  - waiting on review
  - PR stuck > N days
  - near-term release/deadline mentioned by user

## 6) Autonomy matrix (no gray zone)
Allow (auto-run; then inform JD):
- local non-destructive scripts
- read-only checks (status/logs/health)
- proposal file generation, drafts, plans
- branch-safe analysis

Deny by default (approval-first):
- external sends
- git push/merge
- config/service changes
- deletes
- cost-incurring actions

Doubt path: ask JD (one crisp question with options).

## 7) Confidence + staleness
Confidence is explicit and auditable:
- `conf = f(source_count, recency, cross_source_agreement, user_confirmed_signals) - conflicts`

Staleness:
- Apply TTL decay.
- **Expiry is required** on every hypothesis (`expires_at`).
- When expired: move to `stale_items` (or mark stale and cap confidence) until refreshed.

## 8) Privacy + consent contract
- Location storage: default timezone-only; country only with explicit reason/consent; city opt-in only.
- Consent controls:
  - “don’t store this”
  - “forget <x>”
  - “show what you currently assume about me”
- Sensitive domains are auto-hidden unless explicitly requested.

## 9) Model schema (recommended)
Directory:
- `memory/internal/connect-dots/<scope>/model.json`
- `memory/internal/connect-dots/<scope>/snapshots/YYYY-MM-DD.json`

Top-level (suggested):
```json
{
  "scope": "user-profile/preferences",
  "updatedAt": "2026-02-22T00:00:00+01:00",
  "confirmed_facts": [],
  "hypotheses": [],
  "stale_items": [],
  "open_loops": [],
  "candidate_moves": [],
  "do_not_store": []
}
```

Item shape (suggested):
```json
{
  "id": "pref-tone-direct",
  "statement": "JD prefers concise, unsugarcoated communication.",
  "confidence": 0.86,
  "first_seen": "...",
  "last_seen": "...",
  "expires_at": "...",
  "status": "active",
  "evidence": [
    {
      "path": "memory/2026-02-21.md",
      "lines": "L10-L18",
      "quote": "...",
      "ts": "..."
    }
  ]
}
```

## 10) Deterministic core (locked)
Best compromise (trust + auditability):
- LLM does synthesis/proposals.
- Scripts do all state mutation.
- Fail closed: invalid proposal/schema mismatch/bad citations => no write.

Artifacts:
- Proposal schema: `references/proposal.schema.json`
- Model schema: `references/model.schema.json`
- Builder: `scripts/build_model.py`
- Consent mutations: `scripts/consent_mutations.py`
- Diff: `scripts/model_diff.py`
- Validator: `scripts/validate_model.py`

## 11) "Show assumptions about me" (locked)
Sections + strict caps:
1) Confirmed facts (max 5)
2) Top hypotheses (max 5)
3) Stale assumptions (max 3)
4) Do-not-store protections (active)
5) What changed since last snapshot (diff)
6) Control shortcuts

Micro-question templates (one at a time):
- Confirm yes/no
- A/B preference
- Scope check
- Stale refresh
- Consent check (store once / always / don’t store)
