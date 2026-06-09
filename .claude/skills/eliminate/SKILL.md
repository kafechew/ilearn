You are executing the /eliminate skill.

## Purpose
Apply the Essentialism filter to any list — tasks, projects, meetings, tools, subscriptions,
team responsibilities, features, or anything that is consuming time or attention. The goal
is to surface what can be safely cut, deferred, or handed off without meaningful loss.

Usage: /eliminate <list of items, or paste the list after the command>

## Steps

### Step 1 — Ingest the list
If Kai has not provided a list, ask: "What are you trying to evaluate? Paste the list
(tasks, projects, tools, meetings — any format is fine)."

Accept the list as-is and proceed to Step 2.

### Step 2 — Classify each item
For every item on the list, apply three questions and assign a classification:

**Question A — Is it essential?**
"If this did not exist, or was never done, would it make a meaningful negative difference
to what Kai actually cares about?" If the honest answer is no → Eliminate candidate.

**Question B — Is it Kai's unique contribution?**
"Does this require Kai's specific relationships, expertise, or creativity? Or could
someone else — a staff member, VA, or system — handle this?" If someone else can → Delegate candidate.

**Question C — Can it be automated?**
"Is this recurring, rule-based, or process-driven enough that a system could do it?"
If yes → Automate candidate.

**Classifications:**
- **Keep** — essential, requires Kai personally, cannot be automated
- **Eliminate** — fails Question A (not essential)
- **Delegate** — passes A, fails B (Kai not required)
- **Automate** — passes A, fails C (system can handle it)
- **Defer** — essential but not time-sensitive (move to Someday/Maybe)

### Step 3 — Output the classified list

```
## Elimination Analysis

### Keep (Kai's irreplaceable contribution)
- [Item] — [one-line reason it's essential and personal]

### Eliminate (safe to cut)
- [Item] — [one-line consequence of cutting: "negligible / duplicated by X / no longer relevant"]

### Delegate (essential, but not Kai's job)
- [Item] → suggested delegate: [role/person type] | use /delegate-brief to write the handoff

### Automate (essential, but should be a system)
- [Item] → suggested automation: [tool/approach — cron, skill, MCP, Zapier, etc.]

### Defer (important, not urgent)
- [Item] → revisit: [suggested timeframe or trigger condition]

---
## Summary
- Total items reviewed: N
- Eliminated: N
- Delegated: N
- Automated: N
- Deferred: N
- **Net reduction in Kai's personal load: N items (XX%)**
```

### Step 4 — Confirm eliminations
For every item in the Eliminate bucket, ask once: "Anything on the eliminate list you
want to challenge or keep?" Let Kai override freely — this is advisory, not prescriptive.

### Step 5 — Offer next steps
- For Delegate items: "Want me to run /delegate-brief for any of these?"
- For Automate items: "Want me to design an automation for any of these?"
- For Eliminate items: "Do you want to document why these were cut (useful for saying no to future similar requests)?"

## Guardrails
- Never challenge Kai's decision to keep something — only surface the option to cut
- Never suggest new items or additional work — this skill only reduces, never adds
- If the list has fewer than 3 items, still apply the filter — even a small list can have waste
- If everything on the list is genuinely essential, say so directly rather than forcing cuts
