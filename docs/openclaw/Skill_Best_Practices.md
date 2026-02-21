# OpenClaw Skill Best Practices (notes)

Source: https://docs.openclaw.ai/tools/skills (fetched 2026-02-21)

## Skill packaging + precedence
- Skill folder contains `SKILL.md` with YAML frontmatter.
- Load precedence (highest → lowest):
  1) `<workspace>/skills`
  2) `~/.openclaw/skills`
  3) bundled skills
- Conflicting skill names: higher-precedence wins.

## SKILL.md frontmatter constraints
- Must include at least:
  - `name: <skill-name>`
  - `description: <single-line>`
- The embedded parser supports **single-line** frontmatter keys only.
- `metadata` should be a **single-line JSON object**.

## Gating / eligibility (load-time)
Use `metadata.openclaw` to gate skills by environment:
- `os`: only include on specific platforms (`darwin|linux|win32`).
- `requires.bins`: binaries required on PATH.
- `requires.env`: env vars required.
- `requires.config`: config paths that must be truthy.

## Security + trust
- Treat third-party skills as untrusted: read before enabling.
- Prefer least-privilege and sandboxing for risky tool surfaces.
- Keep secrets out of prompts/logs; use `skills.entries.<name>.env` / `apiKey` when needed.

## Operational guidance
- Keep skills deterministic: explicit triggers, clear state files, and reversible steps.
- Make end triggers robust (normalize whitespace/case and handle quoted replies).
- Include a verification checklist (smoke checks) and rollback steps.
