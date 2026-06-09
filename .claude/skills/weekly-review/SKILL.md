You are executing the /weekly-review skill.

## Purpose
A structured weekly review that captures the past week, clears mental RAM, and sets
the minimum essential agenda for the next 7 days. Applies the Essentialism filter at
every stage — the goal is not a longer to-do list, it is a shorter, better one.

Run this every Friday afternoon or Sunday evening. Takes 20–30 minutes.

## Steps

### Step 1 — Capture & Brain-Dump (5 min)
Ask Kai: "What's on your mind right now? Dump everything — work, personal, pending,
half-finished, worrying, exciting. Don't filter. One item per line."

Wait for the full dump. Acknowledge it and move to Step 2.

### Step 2 — Categorise
Sort the dump into five buckets:
- **Done** — completed this week (acknowledge, then let go)
- **Carry forward** — not done, still essential
- **Delegate** — needs to happen, but not by Kai personally
- **Eliminate** — should not exist on any list (challenge each item — "what happens if we never do this?")
- **Someday/Maybe** — not now, but don't want to lose it

Show the sorted list. Ask Kai to confirm or adjust the categorisation.

### Step 3 — Essentialism Filter on Carry-Forward
For every item in the Carry Forward bucket, apply the three-question filter:
1. Is this essential — would its absence make a meaningful difference?
2. Can it be automated or delegated instead?
3. What is the minimum effective dose?

Flag items that fail Question 1 as candidates for elimination.
Flag items that pass Question 2 as candidates for a delegation brief.

### Step 4 — Next Week's Vital Few
From what remains after filtering, identify:
- **The one non-negotiable outcome for the week** (if nothing else gets done, this must)
- **Up to 3 additional high-value outcomes**
- **No more than 5 specific tasks** (if the list is longer, eliminate or defer more)

Output format:
```
## Week of [date]

### The One Thing
[Single most important outcome]

### High-Value Outcomes
1. [Outcome]
2. [Outcome]
3. [Outcome]

### Tasks (≤5)
- [ ] [Task]
- [ ] [Task]
- [ ] [Task]

### Delegating This Week
- [Task] → [Person/VA] by [date]

### Eliminated
- [Item] (reason: [why it doesn't matter])

### Someday/Maybe Parking
- [Item]
```

### Step 5 — Check: Work / Life Balance Signal
Ask one question: "On a scale of 1–10, how sustainable does next week feel?"
If below 7, ask: "What would make it a 7?" Apply the Essentialism filter to the answer.

### Step 6 — Save the output
If Kai confirms the plan, offer to save it as a dated note:
`memory/weekly-reviews/YYYY-MM-DD.md`

## Guardrails
- Never add items to Kai's list — only help process and reduce what Kai provides
- Never suggest doing more; always suggest doing less and better
- If the Carry Forward list has more than 10 items, challenge it before moving on
- The output plan must always have fewer items than the input dump
