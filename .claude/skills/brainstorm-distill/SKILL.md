You are executing the /brainstorm-distill skill.

## Purpose
A two-phase thinking tool: first expand (generate many ideas without judgment), then
ruthlessly compress (extract only what is essential and actionable). The output should
always be smaller than the input — that is how you know the distillation worked.

Usage: /brainstorm-distill <topic or question>

## Steps

### Phase 1 — Diverge (Brainstorm)
Generate ideas broadly on the topic. No judgment, no filtering. Use one of these modes
depending on the topic type:

**For a decision:** List all the options you can think of, including unconventional ones.
**For a problem:** List all possible causes and all possible solutions.
**For a creative brief:** List all the angles, formats, audiences, or framings.
**For a plan:** List all the things that could be done, regardless of priority.

Output 8–15 items. Aim for breadth over depth at this stage.

Pause and show the full list. Ask: "Anything missing you want to add before we distill?"

### Phase 2 — Distill (Compress)
Apply the Essentialism filter to the brainstorm output:

1. **Eliminate duplicates and variations** — merge similar items into one
2. **Apply the vital-few filter** — which 20% of these ideas would produce 80% of the value?
3. **Apply the minimum-dose filter** — which is the smallest version of this that still matters?
4. **Apply the now/later/never filter:**
   - **Now:** Essential and time-sensitive
   - **Later:** Important but not urgent
   - **Never:** Eliminate — sounds good but not essential

Output the distilled result:
```
## Brainstorm: [Topic]

### Distilled Essentials (the vital few)
1. [Idea/action — why it made the cut]
2. [Idea/action — why it made the cut]
3. [Idea/action — why it made the cut]

### Later (important, not urgent)
- [Item]

### Eliminated (and why)
- [Item] — [one-line reason: not essential / not differentiated / better covered by X]

### Recommended Next Action
[Single most important next step from the distilled list]
```

### Step 3 — Decision (if applicable)
If the brainstorm was toward a decision, end with:
```
## Recommendation
[Direct recommendation — one sentence]

## Key trade-off accepted
[What you give up by choosing this]
```

## Guardrails
- The distilled output must always have fewer items than the brainstorm input
- Never present all brainstorm items as equally valid — the point is to discriminate
- If the recommended next action is unclear, ask one clarifying question before guessing
- Never output a brainstorm without a distillation — the two phases are always paired
