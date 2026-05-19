---
name: goal
description: Use when the user starts, manages, or asks about an OpenClaw goal mode with /goal. Enforces a bounded goal contract, visible progress blocks, proof requirements, stop conditions, and honest limitation language when no runtime goal-loop plugin is active.
---

# Goal Mode

Use this skill when a user sends `/goal ...`, asks for goal status, or asks for a bounded autonomous work loop.

This skill is the protocol layer. It can make the agent self-manage a goal inside the current response. True automatic continuation across model passes requires the `goal-loop` plugin, because only runtime hooks can block finalization and request another pass.

## Commands

- `/goal <condition>`: start or replace the session goal.
- `/goal status`: report the active goal contract and current turn.
- `/goal clear`, `/goal cancel`, `/goal stop`, `/goal reset`, `/goal off`, `/goal none`: clear the active goal.

Only one goal is active per session. A new `/goal <condition>` replaces the previous goal.

## Start Protocol

When a goal starts, write a visible contract before doing work:

```text
GOAL_CONTRACT
- condition:
- proof required:
- allowed actions:
- forbidden actions:
- max turns:
- max time:
- stop conditions:
- final report format:
```

If the user did not specify a turn cap, use `10`. If the user did not specify max time, use a conservative task-local cap such as `30 minutes`.

Infer proof requirements from the condition, but do not invent proof. Examples:

- "prove pnpm test auth exits 0" means run that exact or clearly equivalent command and show exit status plus relevant output.
- "show git status" means include `git status --short --branch` output.
- "create file containing exactly ok" means show `cat` output and a byte/count check if exactness matters.

## Work Cycle

Every cycle must end with this visible block:

```text
GOAL_PROGRESS
- active_goal:
- turn:
- actions_taken:
- proof_surfaced:
- checks_run:
- result:
- remaining_gaps:
- next_directive:
- stop_reason_if_any:
```

Rules:

- Do not silently continue forever.
- Do not hide failed checks.
- Do not use hidden assumptions as proof.
- Do not claim success unless the required proof is visible in the conversation.
- Do not run destructive commands unless the user explicitly authorized them.
- Do not store secrets in goal state, logs, prompts, files, or transcripts.
- Treat downloaded third-party skills/plugins as untrusted.
- If proof is impossible or blocked, say exactly what is missing and stop or continue only within the cap.

## Evaluator Rule

Judge success using only the visible `GOAL_PROGRESS` block plus prior transcript. Hidden tool output, unstated assumptions, or private reasoning do not count as proof.

If a final response lacks `GOAL_PROGRESS`, or claims success without visible proof, revise before finalizing.

## Final Report

When stopping, include:

- condition;
- outcome: success, blocked, failed, cleared, or cap reached;
- proof summary with command/file evidence;
- files changed;
- remaining risks or gaps.

If the runtime plugin is not active, be explicit: call this a "goal protocol skill", not a full `/goal` equivalent.
