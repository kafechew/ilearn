You are executing the /delegate-brief skill.

## Purpose
Turn a vague task or intention into a clear, self-contained brief that a staff member,
virtual assistant, contractor, or external vendor can act on without follow-up questions.
A good brief reduces the cognitive overhead of delegation to near-zero: hand it over,
check the outcome, move on.

Usage: /delegate-brief <describe the task you want to delegate>

## Steps

### Step 1 — Understand the task
If Kai's description is vague, ask up to three clarifying questions (no more):
1. "What does a successful outcome look like — what will exist or be different when this is done?"
2. "Who is this going to? (staff name/role, VA, freelancer, vendor)"
3. "What is the hard deadline, or the 'nice to have by' date?"

If Kai provides enough context to proceed, skip ahead.

### Step 2 — Draft the delegation brief

Output in this exact format:

```
---
## Delegation Brief

**Task:** [Clear, noun-verb title — e.g., "Research and shortlist 3 payroll software options"]
**Assigned to:** [Name or role]
**Deadline:** [Hard deadline or soft target — be explicit]
**Priority:** [High / Medium / Low relative to their other work]

---

### Context (why this matters)
[1–3 sentences. What is the larger goal this supports? Why now?]

### Outcome (definition of done)
[What specifically should exist when this is complete? Be concrete.
Bad: "Look into CRM options."
Good: "A one-page comparison table of 3 CRM tools — HubSpot, Zoho, Pipedrive —
with columns for: price, key features relevant to iWebby's workflow, migration
complexity from current system. Delivered as a shared Google Doc."]

### Scope (what's included and what's not)
**In scope:**
- [Specific action or deliverable]
- [Specific action or deliverable]

**Out of scope (do not do these):**
- [Common overreach to prevent]
- [Adjacent task they might assume is included]

### Resources & access
- [Link, credential, or tool they will need]
- [Person to contact if they have questions — and for what]

### Checkpoints
- [Date]: Check-in — share draft / progress update
- [Date]: Final delivery

### If blocked
If [specific blocker or uncertainty] occurs, [specific instruction — e.g., "flag to Kai
via WhatsApp, do not guess"]. For all other questions, try to proceed with your best
judgment and note the decision in your delivery.

---
```

### Step 3 — Review with Kai
Show the brief and ask: "Does this capture what you need? Anything missing or that I've
misunderstood about the scope?"

Make corrections based on feedback.

### Step 4 — Offer to send or save
Ask: "Want me to save this as a file? Or copy the text to send directly?"
If saving: use the path `projects/delegation-briefs/YYYY-MM-DD-[task-slug].md`

## Guardrails
- The brief must be self-contained — the assignee should not need to ask Kai any questions
  to get started
- Never write a brief longer than one page — if it cannot be expressed in one page,
  the task needs to be broken down first
- Always include a Definition of Done — vague outcomes are the #1 reason delegation fails
- If the task description sounds like something Kai should eliminate entirely rather than
  delegate, say so before writing the brief: "This could potentially be eliminated — want
  me to run /eliminate on it first?"
- Do not suggest who to delegate to unless Kai has mentioned specific people or roles;
  use [Name or role] as a placeholder
