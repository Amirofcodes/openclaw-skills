---
name: media-intake
description: "Use when the user sends screenshots, photos, documents, or other media and expects grounded interpretation first. Follow this for screenshot triage, image understanding, evidence extraction, relation-to-context checks, and deciding whether to store, ignore, or ask one clarification question."
---

# media-intake — Grounded screenshot/media interpretation

Purpose: stop context-driven hallucination when JD sends media. Treat every screenshot/photo/document as evidence first, not as illustration for the current thread.

## Non-negotiables
- Do **not** infer screenshot meaning from nearby chat context alone.
- First describe what is actually visible.
- Then ask: why might JD have sent this?
- Only after that connect it to current context or memory.
- If key visual content is unreadable or uncertain, say so explicitly.
- If the media could matter in more than one way, present the top 2 interpretations and recommend the most likely one.
- Do not ignore screenshots. Every screenshot must be actively interpreted.

## Intake workflow

### 1) Identify the artifact
Classify the media before making claims:
- screenshot of app/site/UI
- screenshot of email/message/document
- photo of physical object/place/paper
- receipt / invoice / ticket / booking
- chart / graph / dashboard
- mixed / unclear

### 2) Extract visible facts only
List the grounded observations that are actually visible:
- app/site/service name if visible
- page/screen type
- key labels/buttons/headings
- visible prices, dates, names, locations, warnings, statuses
- whether the screenshot appears complete or cropped

Rule: if a fact is not visible, do not state it as visible.

### 3) Ask the meaning questions internally
After extracting the visible facts, reason through these questions in order:
1. Is this directly related to the current thread?
2. If not, does it connect to something durable in memory/profile?
3. Is JD likely signaling:
   - a decision
   - a blocker
   - a correction
   - evidence for canon/profile
   - a request for explanation/comparison
4. What would break if I interpret this wrongly?

### 4) Choose response mode
Use one mode only.

#### Mode A — direct interpretation
Use when the screenshot is clear and relevance is strong.
Reply with:
- what it is
- why it likely matters here
- the actionable takeaway

#### Mode B — careful ambiguity
Use when the screenshot is readable but meaning is ambiguous.
Reply with:
- what is clearly visible
- the 1–2 most likely interpretations
- one concise clarification question only if needed

#### Mode C — unreadable/insufficient
Use when the screenshot cannot be reliably read.
Reply with:
- what can be identified safely
- what cannot be read
- what higher-confidence input would help

## Memory/canon rule
If the screenshot establishes a durable fact, store only the durable fact, not a transcript dump.
Examples of durable items:
- booking window chosen
- payment constraint discovered
- travel preference confirmed
- employer/mission dates
- account/system status that affects future planning

Do not store:
- redundant visual clutter
- raw secrets
- full payment details
- speculative interpretations

## Response shape
Default compact shape:
1. `What it is:`
2. `Why JD probably sent it:`
3. `What matters:`
4. `Question:` only if ambiguity remains materially important

## Anti-patterns
Never do these:
- “This confirms X” when X is not visible in the media
- treating a screenshot as proof of the surrounding thread topic without checking
- ignoring a screenshot and responding only to the text thread
- asking JD to explain the screenshot before attempting interpretation
- over-reading cropped or blurry content

## Escalation rule
If repeated media misunderstandings happen, update durable canon/behavior docs the same day with the specific corrected guardrail.
