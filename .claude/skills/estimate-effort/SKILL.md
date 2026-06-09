---
name: estimate-effort
description: Evaluates a user story or epic, matches it against the team complexity matrix, and outputs a structured effort estimate in story points and dev-days.
disable-model-invocation: true
---

# Effort Estimation Procedure

1. **Parse Scope:** Read the user story or epic requirements provided.
2. **Access Ground Truth:** Read `context_brain/04_effort_matrices/team-velocity.md` to load current team capacity and story-point-to-day conversion rates.
3. **Classify Complexity:** Match the feature against the complexity tiers in the matrix (XS / S / M / L / XL).
4. **Identify Risk Multipliers:** Flag unknowns that inflate estimates (new external API, unfamiliar domain, missing requirements). Apply documented risk buffers.
5. **Output Generation:** Write a structured estimate table named `effort-estimate-[feature].md` inside `projects/[project]/decisions/`.