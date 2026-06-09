---
name: pr-review
description: Reviews a pull request diff or changed files against Webby engineering standards and outputs a structured, prioritized review.
disable-model-invocation: true
---

# PR Review Workflow

For every PR or diff provided, execute the following review pipeline and output into `projects/[project]/decisions/pr-review-[branch].md`:

## Check 1: Standards Compliance
*   Does the code follow Webby's Core Tech Stack Matrix? Flag any unapproved dependencies.
*   Are all new functions and modules covered by Jest tests? Flag if coverage drops below 80%.
*   Are API contracts versioned and backward-compatible?

## Check 2: Architecture Integrity
*   Does this change introduce a new pattern not covered by an existing ADR? If yes, flag: `[ADR REQUIRED]`.
*   Scan `context_brain/02_concepts/` for applicable patterns. Call out missed opportunities (e.g., missing circuit breaker on an external call).

## Check 3: Risk Surface
*   Flag any unvalidated external inputs, missing error handling on I/O boundaries, or secrets in code.

## Output Format
Produce a structured review with three severity tiers:
- 🔴 **Blocking** — Must fix before merge.
- 🟡 **Suggested** — Strongly recommended; team decision.
- 🟢 **Note** — Non-blocking observation for team awareness.