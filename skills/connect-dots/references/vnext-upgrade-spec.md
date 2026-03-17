# connect-dots — vNext upgrade spec

Purpose: define the next implementation step for `connect-dots` after the deterministic core shipped. This spec upgrades the skill into a better **sensemaking + self-improvement loop** without turning it into an autonomous self-modifier.

## 1) Product stance
`connect-dots` is a **trusted chief-of-staff sensemaking system**.

It should:
- observe recurring signals across memory, runtime, and repo context
- form bounded hypotheses
- package high-signal recommendations
- remember what worked and what failed
- stay privacy-safe, reversible, and auditable

It must **not**:
- self-modify code or prompts autonomously
- phone home to a remote hub
- auto-install, auto-update, or auto-heal dependencies
- perform external-facing actions as part of self-improvement

## 2) Core loop (new)
Upgrade the skill from "build model" to a full:

`signal -> hypothesis -> proposed action -> validation -> outcome -> lesson`

### Meanings
- **signal**: evidence-backed observation (memory drift, repeated friction, stale assumption, operational issue, repo blocker)
- **hypothesis**: what might be true and why it matters now
- **proposed action**: the smallest useful intervention or suggestion
- **validation**: how we determine whether the proposal is grounded and safe
- **outcome**: what happened after the recommendation / proposal
- **lesson**: reusable pattern extracted from the run

## 3) Data model additions
Keep current per-scope `model.json` files. Add three new stores.

### 3.1 Run record
Path:
- `tmp/connect-dots/runs/<runId>/run.json`

Minimum shape:
```json
{
  "run_id": "20260317-120000",
  "scope": "user-profile/preferences",
  "mode": "nightly|daytime|explicit-audit",
  "trigger": "nightly_inactivity_gate",
  "signals": ["stale_assumption", "repeated_preference_signal"],
  "hypothesis": {
    "statement": "JD preference on X is stale and should be refreshed",
    "confidence": 0.82,
    "evidence": []
  },
  "proposed_action": {
    "kind": "refresh-question|proposal|silent-update|surface-brief",
    "summary": "Ask one stale-refresh question next time it matters"
  },
  "lane": "observe-only|suggest-only|safe-local-proposal|approval-required",
  "blast_radius_estimate": {
    "class": "memory-only|docs-only|local-analysis|runtime-checks|service-touching|external-facing",
    "justification": "..."
  },
  "validation": {
    "schema_ok": true,
    "citations_ok": true,
    "policy_ok": true
  },
  "outcome": {
    "status": "pending|accepted|rejected|expired|applied|silent",
    "notes": "..."
  },
  "lesson_ids": [],
  "anti_pattern_ids": []
}
```

### 3.2 Lessons store
Path:
- `memory/internal/connect-dots/insights/lessons.json`

Purpose:
- keep successful reusable patterns that improved timing, inference quality, or usefulness

Minimum shape:
```json
{
  "lessons": [
    {
      "id": "lesson-stale-refresh-before-assumption-dump",
      "scope": ["user-profile/preferences"],
      "pattern": "When an assumption is stale but likely still relevant, ask one refresh question before surfacing a larger summary.",
      "signals": ["stale_assumption"],
      "evidence_strength": 0.82,
      "applies_when": ["confidence_between_0.45_and_0.8"],
      "avoid_when": ["user_requested_direct_summary"],
      "created_at": "...",
      "updated_at": "...",
      "source_runs": ["20260317-120000"]
    }
  ]
}
```

### 3.3 Anti-patterns store
Path:
- `memory/internal/connect-dots/insights/anti-patterns.json`

Purpose:
- remember repeated bad moves or invalid inferences

Examples:
- asking for reconfirmation after the preference was already confirmed
- surfacing low-confidence lifestyle hypotheses
- treating assistant/tool chatter as user activity for idle gating

Minimum shape:
```json
{
  "anti_patterns": [
    {
      "id": "anti-repeat-confirmation-for-known-preference",
      "scope": ["user-profile/preferences"],
      "pattern": "Do not ask JD to reconfirm Morning auto-brief behavior once already confirmed unless conflicting evidence appears.",
      "trigger_signals": ["repeat_confirmation", "known_preference"],
      "severity": "medium",
      "created_at": "...",
      "updated_at": "...",
      "source_runs": ["..."]
    }
  ]
}
```

## 4) Approval lanes
All recommendations and generated actions must be assigned to a lane.

### Lane 0 — observe-only
Allowed:
- update run artifacts only
- log lessons / anti-patterns
- no user-facing output required

### Lane 1 — suggest-only
Allowed:
- surface one concise recommendation or question
- no file writes beyond internal state

### Lane 2 — safe-local-proposal
Allowed:
- create drafts, proposals, patches, or internal briefs
- no external effects
- no curated-memory writes without existing rule path

### Lane 3 — approval-required
Triggered by:
- service/config changes
- external sends
- risky operational actions
- anything irreversible or cost-incurring

## 5) Blast-radius classification
Before surfacing or generating a proposal, assign one class:
- `memory-only`
- `docs-only`
- `local-analysis`
- `runtime-checks`
- `service-touching`
- `external-facing`

Policy:
- first four classes may proceed under lanes 0-2
- last two always map to lane 3

## 6) Recommendation packaging
Every surfaced recommendation should be rendered as a compact package:
- **insight** — what was noticed
- **why now** — what made it timely
- **confidence** — numeric + short reason
- **recommended action** — one thing, no bundle spam
- **risk** — low/medium/high
- **next check** — what would validate usefulness

This keeps daytime surfacing disciplined and auditable.

## 7) Lesson extraction rules
Extract a lesson only when one of these is true:
- the recommendation was explicitly confirmed/useful
- the same pattern succeeded across multiple runs
- a previously failing pattern was corrected and now works

Do **not** promote one-off speculation into a lesson.

## 8) Anti-pattern extraction rules
Record an anti-pattern when one of these happens:
- repeated noisy prompting
- stale or contradicted assumption resurfaced
- wrong gate triggered due to poor evidence handling
- recommendation exceeded its blast radius
- confidence was overstated relative to evidence

## 9) Safety rules (keep and extend)
Keep existing hard guards.

Add these:
- never auto-change core persona/identity files as part of connect-dots improvement
- never write to curated memory from lessons/anti-pattern extraction directly
- never infer sensitive domains unless the user explicitly opens that door
- never treat assistant/tool activity as user intent
- never generate more than one high-value clarification question at a time

## 10) Rollout plan
### Phase A — docs only
- add this spec
- keep runtime behavior unchanged

### Phase B — emit run records
- write `run.json` for nightly/daytime flows
- no lessons extraction yet

### Phase C — lessons + anti-patterns
- add append/update scripts
- keep them internal only

### Phase D — scoring + lanes
- compute lane + blast radius before surfacing
- refuse outputs that violate lane policy

### Phase E — usefulness tuning
- incorporate explicit confirmations/denials and repeated outcomes
- improve ranking of recommendation types

## 11) Minimal implementation checklist
1. Add a `run.schema.json` reference.
2. Add deterministic script(s):
   - `scripts/write_run_record.py`
   - `scripts/update_lessons.py`
   - `scripts/update_anti_patterns.py`
3. Update nightly/daytime flow docs to mention run records.
4. Add tests for:
   - lane classification
   - blast-radius classification
   - lesson promotion
   - anti-pattern recording

## 12) Naming guidance
Do not import Evolver vocabulary like `gene`, `capsule`, `mutation`, or `evolution event`.

Use plain language:
- `run record`
- `lesson`
- `anti-pattern`
- `recommendation`
- `approval lane`
- `blast radius`
