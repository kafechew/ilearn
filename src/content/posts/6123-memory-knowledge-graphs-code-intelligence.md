---
author: Kai
pubDatetime: 2026-05-23T09:00:00+08:00
title: Memory, Knowledge Graphs & Code Intelligence
featured: false
draft: false
slug: 6123-memory-knowledge-graphs-code-intelligence
tags:
  - deeptech
  - ai
  - agentic
  - memory
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/23-memory-knowledge-graphs-code-intelligence.png"
description: The authoritative reference for Claude's three-layer knowledge system - persistent memory, graphify codebase graph, and gitnexus call graph — what each stores, how to maintain them, and how they compose.
---

## What This Part Covers

- Claude's persistent memory system — what it is, how to use it
- The three types of persistent knowledge: memory, graphify, gitnexus
- What each one stores, when to use each, and how they compose
- Practical prompts for reading, writing, and maintaining each
- Why knowledge management is a senior developer skill
- This part is the deep-dive reference for graphify and gitnexus, introduced in Part 21.

---

> If you haven't set up Claude Code or the `.claude/` directory yet, start with Part 21. This part assumes the tools are installed and your project is configured.

## The Problem: Context Doesn't Survive Sessions

Every time you start a new Claude session, Claude starts fresh. It has no memory of:

- The architectural decision you made last Tuesday
- The pattern violation you told it to never repeat
- The business rule that isn't in the code but in your head
- The "why" behind any existing code

In Meteor development, this was fine because the codebase was small and you kept everything in your head. At enterprise scale with a team of 5+, that doesn't work. Knowledge needs to be persistent, searchable, and shared.

Three tools solve this in three different ways:

| Tool          | What it stores                             | Survives sessions? | Searchable by Claude?   |
| ------------- | ------------------------------------------ | ------------------ | ----------------------- |
| Claude Memory | Human context, preferences, decisions      | ✅                 | ✅ Always loaded        |
| graphify      | Codebase structure, symbols, relationships | ✅                 | ✅ Via `graphify query` |
| gitnexus      | Call graph, blast radius, execution flows  | ✅                 | ✅ Via MCP tools        |

---

## 1. Claude's Persistent Memory System

### 1.1 Where It Lives

```
~/.claude/projects/-Users-<you>-dev-enterprise-todo/memory/
├── MEMORY.md          ← index (loaded in every session)
├── user_profile.md    ← who you are
├── feedback_*.md      ← guidance Claude should always follow
├── project_*.md       ← ongoing project state and decisions
└── reference_*.md     ← pointers to external resources
```

> **Path encoding:** Claude Code encodes the project path by replacing `/` with `-`. On macOS with a project at `/Users/kai/dev/myapp`, the memory directory is `~/.claude/projects/-Users-kai-dev-myapp/memory/`. On Linux, a project at `/home/kai/dev/myapp` would be `~/.claude/projects/-home-kai-dev-myapp/memory/`. Windows paths encode differently. The simplest way to find the correct path: run `ls ~/.claude/projects/` and look for the directory that matches your project name.

`MEMORY.md` is always loaded. It's an index file — each line points to a memory file with a one-sentence description. Claude reads the index and loads specific files when relevant.

### 1.2 The Four Memory Types

**User memories** — who you are, your expertise, your preferences:

```
# user_role.md
---
name: user-role
type: user
---
Senior NestJS developer. Strong TypeScript background.
Deep expertise in PostgreSQL and TypeORM. Prefers terse, code-first explanations.
Frame new concepts in terms of TypeORM/SQL analogies where possible.
```

**Feedback memories** — guidance Claude should always follow:

```
# feedback_no_summary.md
---
name: feedback-no-trailing-summaries
type: feedback
---
Do NOT add trailing summary sections to responses ("In summary...", "To recap...").
The user can read the response. Summaries add tokens without value.

Why: explicit correction in session on 2026-06-10
How to apply: end responses directly after the last piece of content
```

```
# feedback_test_pattern.md
---
name: feedback-real-db-in-e2e
type: feedback
---
E2E tests MUST use a real PostgreSQL database — never mock the DB.

Why: prior incident where mocked E2E tests passed but the production migration had
a FK constraint that only appeared with real data. The mock missed it entirely.
How to apply: for E2E tests, always set up the real TestingModule with real DB connection.
```

**Project memories** — ongoing state and decisions:

```
# project_auth_decision.md
---
name: project-dual-auth-decision
type: project
---
We use two separate RS256 key pairs: one for users, one for admin portal.

Why: legal requirement — admin operations must be auditable and cannot be performed
with a user JWT even if the user has admin role flag.
How to apply: admin operations use PortalAuthJwtGuard, not AuthJwtGuard.
The key pairs must never be the same even in development.
```

**Reference memories** — pointers to external systems:

```
# reference_tickets.md
---
name: reference-clickup-project
type: reference
---
Backend development tasks are tracked in ClickUp project "ENTERPRISE-TODO".
Sprint board: https://app.clickup.com/...
Bug label: "bug", feature label: "feat", tech debt label: "chore"
```

### 1.3 How to Save Memories

**Tell Claude to remember something:**

```
"Remember: we always soft-delete permission records — never hard-delete.
This is a compliance requirement, not just a pattern preference."
```

Claude creates:

- A new memory file at `~/.claude/projects/.../memory/feedback_soft_delete.md`
- Adds an entry to `MEMORY.md`

**Remember a decision:**

```
"Remember: we decided to use shared-table multi-tenancy (tenantId FK on every domain entity)
instead of separate schemas. Reason: simpler deployment, acceptable for our tenant count (<1000),
easier to backfill historical data. Revisit if we exceed 500 tenants."
```

**Remember your preferences:**

```
"Remember: I prefer service methods as arrow function properties (CqrsQueryFunc/CqrsCommandFunc pattern),
not class methods. Don't suggest converting them to regular methods."
```

### 1.4 How to Read Memories

```
"What do you remember about our auth architecture decisions?"
"Check your memory for any notes on the migration strategy."
"Recall any feedback you have about how I want code structured."
```

### 1.5 What NOT to Save in Memory

- File paths or function names (these go stale as code changes)
- Current sprint tasks (use ClickUp for that)
- Anything already in `CLAUDE.md` or the docs
- Debugging steps or one-off fixes (the fix is in the commit)

```
# BAD — stale in a week:
"Remember: the auth service is in apps/api/src/modules/auth/auth.service.ts"

# GOOD — durable:
"Remember: auth business logic lives in the service layer, not the resolver.
Resolvers are thin — they only dispatch to the command bus."
```

### 1.6 The Memory Lifecycle

```
Write → Claude saves to file in memory/
Read  → Claude loads relevant files based on the conversation
Update → "Update your memory about X — the decision changed because..."
Delete → "Forget your note about X — it's no longer accurate."
```

Memory files are plain markdown — you can read and edit them directly.

---

## 2. graphify — The Codebase Knowledge Graph

Part 21 introduced graphify briefly. This section is the full treatment.

### 2.1 What It Stores

`graphify` extracts your codebase's AST and builds a graph of:

- **Symbols** — classes, functions, interfaces, decorators
- **Relationships** — imports, extends, implements, calls
- **Concepts** — patterns it infers from structure (e.g., "this is a CQRS handler")
- **Clusters** — related symbols grouped by functional area

Unlike Claude memory (which stores human-curated facts), graphify is **automatically extracted from the source code**. It reflects what's actually in the code, not what someone thought was in the code.

### 2.2 Building and Maintaining the Graph

```bash
# Initial build (runs AST extraction + semantic enrichment)
graphify export .

# Fast update after code changes (AST-only, milliseconds, no API cost)
graphify update .

# After merging a PR that adds a major new module:
graphify update .
```

The `graphify-out/` directory contains:

```
graphify-out/
├── graph.json         ← full symbol graph (don't read this directly)
├── GRAPH_REPORT.md    ← architecture summary (read for broad overview)
└── wiki/
    └── index.md       ← navigable codebase overview
```

### 2.3 Query Patterns

```bash
# Concept search — best for "how does X work"
graphify query "JWT authentication flow"
graphify query "how DataLoader prevents N+1"
graphify query "CQRS handler thin delegation"

# Relationship path — best for "how are A and B connected"
graphify path "TodoResolver" "PostgreSQL"
graphify path "AuthService" "JwtStrategy"

# Deep explanation — best for understanding a specific node
graphify explain "FilterQueryBuilder"
graphify explain "AbstractCqrsCommandInput"
```

**In Claude sessions:**

```
"Query the graph: which modules currently use @Authorize decorator?"
"Explain how FilterQueryBuilder.select() works in this codebase."
"Find all symbols that depend on TenantContext."
```

### 2.4 When to Use graphify vs Read

| Question                                   | Tool                    |
| ------------------------------------------ | ----------------------- |
| "How does X work?"                         | `graphify query "X"`    |
| "Which files use X?"                       | `graphify query "X"`    |
| "What's the relationship between A and B?" | `graphify path "A" "B"` |
| "I need to edit file X.ts"                 | Read the file directly  |
| "I need to debug a specific function"      | Read the specific file  |

Rule: use graphify for **understanding**, Read/Edit for **modifying**.

### 2.5 Practical Use Cases

**New developer onboarding:**

```
"I just joined this project. Query the graph for the overall architecture.
What are the main modules, how do they relate, and what's the request lifecycle?"
```

**Before adding a module:**

```
"Query the graph for the closest existing module to what I'm building:
an entity with a userId FK, ownership-scoped reads, no complex relations."
```

**Finding where a concept is implemented:**

```
"Which file implements the cursor pagination logic? Query the graph."
```

**Understanding a bug:**

```
"The getTodos query is returning todos from other users. Query the graph
to trace how the userId filter flows from the resolver to the SQL query."
```

---

## 3. gitnexus — The Call Graph

Part 21 introduced gitnexus briefly. This section is the full treatment.

### 3.1 What It Stores

Where graphify understands structure and concepts, gitnexus understands **runtime call relationships**:

- Which functions call which other functions
- Which commands/queries flow through the CQRS bus
- Which execution flows exist (e.g., "Authentication Flow", "Create Todo Flow")
- The blast radius of changing any symbol

```bash
# Build/update the gitnexus index
node .gitnexus/run.cjs analyze

# Check index freshness
# In Claude: "Check the gitnexus index status"
```

### 3.2 The Three Essential gitnexus Operations

**Impact analysis — before every edit to existing code:**

```
"I need to change signIn in AuthService.
Run impact analysis on it before I touch anything."
```

Claude runs:

```
impact({ target: "signIn", direction: "upstream" })
```

Returns:

```
Symbol: AuthService.signIn
Direct callers: SignInCommandHandler
Affected execution flows: Authentication Flow
Risk: LOW

Upstream chain:
AuthResolver → CommandBus → SignInCommandHandler → AuthService.signIn
```

LOW → safe. HIGH or CRITICAL → stop, understand the blast radius first.

**Context — full picture of a symbol:**

```
"Give me full context on TodoService.createOne:
who calls it, what it calls, which execution flows it's in."
```

Claude runs:

```
context({ name: "TodoService.createOne" })
```

Returns: callers, callees, execution flows, related symbols.

**Detect changes — verify scope before commit:**

```
"Run detect_changes against main. Tell me every symbol I changed or added.
Flag anything outside the TodoModule."
```

Claude runs:

```
detect_changes({ scope: "compare", base_ref: "main" })
```

This is critical before opening a PR. You might have accidentally modified a shared utility, or the agent's scaffold might have touched an existing file it shouldn't have.

### 3.3 Safe Rename

```
"Rename createOneTodoCommandHandler to createTodoCommandHandler
everywhere it's referenced in the codebase."
```

Claude runs:

```
rename({ from: "createOneTodoCommandHandler", to: "createTodoCommandHandler" })
```

gitnexus uses the call graph to find all actual symbol references (not string matches). A regular find-and-replace would also rename comments, logs, and string literals that happen to contain the name. gitnexus renames only the actual symbol and its references.

---

## 4. How All Three Compose

The three systems answer different questions:

```
"How does the auth module work?"
→ graphify query "auth module"
  Returns: structure, file locations, conceptual relationships

"What calls signIn?"
→ gitnexus context({ name: "signIn" })
  Returns: call chain, execution flows, callers

"We decided to use RS256 always — never HS256."
→ Claude memory (feedback_rs256.md)
  Returns: this rule in every future session automatically
```

They compose in a session:

```
"I want to add a refresh token rotation feature to AuthService.
1. Query the graph for how auth is currently structured.
2. Run impact analysis on generateTokens.
3. Check your memory for any auth-related decisions I've made.
Then give me a plan."
```

Claude:

1. Runs `graphify query "auth module token generation"`
2. Runs `gitnexus impact({ target: "generateTokens", direction: "upstream" })`
3. Reads auth-related memory files
4. Synthesizes a plan using all three sources

---

## 5. Building a Knowledge Culture on the Team

For a team of 5+ developers, knowledge management is a shared practice, not a personal one.

### 5.1 What to Document When

After any significant architectural decision:

```
"Document this decision: we chose to use Bull queues over direct async processing
for all email operations. Reason: email delivery has ~5% failure rate,
queues give us retry + dead letter. Apply to: any new notification or alert feature."
```

After a production incident that revealed a pattern to avoid:

```
"Remember: never use Scope.DEFAULT for DataLoaders.
Incident: user A's todo data appeared in user B's request because the singleton
loader cached across requests. Always use Scope.REQUEST."
```

After a non-obvious business rule is discovered:

```
"Remember: a Todo can only be deleted by its owner or a tenant admin.
Service-level deletion (e.g., cascade from workspace deletion) bypasses this check.
Both paths must explicitly verify ownership or admin role."
```

### 5.2 Team Shared Memory

For decisions that apply to all team members, write them into `CLAUDE.md` (committed) or the `rules/` files rather than personal memory:

```markdown
# .claude/rules/architecture.md (add after a decision)

- Never use Scope.DEFAULT for DataLoaders — always Scope.REQUEST.
  [Incident 2026-05-14: data leakage between requests]
```

This way the rule applies in everyone's Claude sessions, not just yours.

> **Team memory sync:** Memory files live in `~/.claude/` on each developer's local machine — they are NOT in the git repo. Team knowledge that should be shared belongs in `.claude/rules/` (checked into git) or in CLAUDE.md. Use personal memory for individual context (your current focus, your coding preferences) and shared rules for team conventions and architecture decisions.

### 5.3 Keeping Knowledge Fresh

Knowledge goes stale. A monthly maintenance habit:

```
"Review my memory files for this project.
Flag anything that references file paths, function names, or states
that may no longer be accurate given the current codebase."
```

```bash
# After major refactors, rebuild graphs:
graphify update .
node .gitnexus/run.cjs analyze
```

---

## Summary

| System        | What to store                                            | When to update                       | How Claude accesses it                 |
| ------------- | -------------------------------------------------------- | ------------------------------------ | -------------------------------------- |
| Claude Memory | Human context, decisions, preferences, patterns-to-avoid | When you learn something non-obvious | Always loaded (MEMORY.md index)        |
| graphify      | Codebase structure, symbols, concepts                    | After every PR merge                 | `graphify query/path/explain`          |
| gitnexus      | Call graph, execution flows, blast radius                | After every PR merge                 | `impact/context/detect_changes/rename` |

The senior developer practice: **leave the codebase better documented than you found it.** This means running `graphify update` after every merge, saving important decisions to memory, and adding rules to `.claude/rules/` when patterns are established.
