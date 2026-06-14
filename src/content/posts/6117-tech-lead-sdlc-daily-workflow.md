---
author: Kai
pubDatetime: 2026-05-17T09:00:00+08:00
title: Tech Lead SDLC & Daily Workflow
featured: false
draft: false
slug: 6117-tech-lead-sdlc-daily-workflow
tags:
  - deeptech
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/17-tech-lead-sdlc-daily-workflow.png"
description: By the end of this part, you will learn the trole of tech lead, Software Development Lifecycle (SDLC), daily workflow, Sprint ceremonies, Code review, Architecture Decision Records (ADRs) and Onboarding new developers.

---

## What This Part Covers

- What "tech lead" actually means on an enterprise NestJS team
- The complete Software Development Lifecycle (SDLC) from ticket to production
- The daily workflow: morning → development → review → end of day
- Sprint ceremonies and what the tech lead does in each
- Code review: what to check and how to give useful feedback
- Architecture Decision Records (ADRs)
- Onboarding new developers
- Technical debt management

---

## What "Tech Lead" Means

A tech lead is not just a senior developer who writes more code. The role has three distinct responsibilities:

```
1. Technical decisions      — architecture, patterns, tooling, tradeoffs
2. Team enablement          — unblocking developers, setting standards, reviewing PRs
3. Delivery visibility      — translating technical state to PM/product, surfacing risks early
```

In a Meteor project, these were informal — one person knew everything and nothing was written down. In an enterprise NestJS team, they must be explicit.

---

## 1. The Full SDLC

### Phase 1: Discovery (Before Any Code)

When a new feature arrives as a ticket:

**As a developer:**
```
1. Read the ticket carefully — understand WHAT and WHY, not just WHAT
2. Ask: what DB schema does this require?
3. Ask: what new GraphQL operations does this expose?
4. Ask: which existing modules does this touch?
5. Ask: is there a security concern (new user-facing fields, new permissions)?
```

**As a tech lead:**
```
1. Is this the right abstraction? (E.g., "should tags be a separate entity or just an array of strings?")
2. What's the migration risk?
3. Does this break multi-tenancy or RBAC boundaries?
4. What's the test strategy?
5. Is this one PR or multiple?
```

**Design before coding — the 3-question check:**
```
1. What does the DB table look like? (draw it)
2. What GraphQL operations do we expose? (write them as pseudocode)
3. Which existing module is this most like? (pick the reference)
```

Only when you can answer all three do you write the first file.

### Phase 2: Branch & Build

```bash
# Always from latest main
git checkout main && git pull
git checkout -b feat/ticket-description

# Orient with the graph before building
claude
"Query the graph for the reference module I'll use.
Run impact analysis on any existing symbols I plan to change."
```

Build in the 9-step order (entity → DTOs → CQRS → service → resolver → module → register → migrate). This order matters because:
- The entity defines the schema; everything depends on it
- DTOs depend on the entity
- CQRS inputs depend on DTOs
- The service depends on CQRS inputs
- The resolver depends on all of the above

Building out of order causes circular dependency errors and forces rework.

### Phase 3: Verify Locally

This is not optional. Every point must be green before the PR opens.

```bash
# 1. TypeScript compiles without errors
yarn api:dev
# Watch for red compile errors in the terminal output

# 2. Unit tests pass
yarn api:test

# 3. Migration tested
yarn migration:run
# Open Adminer, verify table/columns exist
yarn migration:revert
# Verify table is gone
yarn migration:run
# Run again to leave it clean

# 4. Smoke test in GraphQL Playground
# Test every new operation — success case AND auth rejection case

# 5. Lint
yarn lint

# 6. Scope verification
"Run detect_changes against main and confirm I only touched <module> files."
```

### Phase 4: Code Review

**The PR author's job:**
```bash
# 1. Stage selectively — never git add .
git add apps/api/src/modules/product/
git add apps/api/src/migrations/*product*
git add apps/api/src/app/app.module.ts

# 2. Verify what's staged
git diff --staged

# 3. /code-review before pushing
claude
/code-review

# 4. Commit with Commitizen
yarn cz

# 5. Push and open PR
git push -u origin feat/product-module
"Open a PR for feat/product-module. Fill the template."
```

**The PR description must include:**
```markdown
## Summary
- What was added/changed (bullet points)
- Why it was needed (link to ticket)

## Migration
- Table added: `product`
- Columns: name, price, status, user_id (FK)
- run + revert both tested locally

## Testing
- Unit: product.service.spec.ts (6 tests), product.cqrs.spec.ts (6 tests)
- E2E: product.e2e-spec.ts (create, list, update, delete, auth rejection)

## Checklist
- [x] Tests pass (yarn api:test)
- [x] Lint passes (yarn lint)
- [x] Migration run + revert tested
- [x] Smoke tested in GraphQL Playground
- [x] No .env secrets committed
```

### Phase 5: Deployment

The migration runs first, then the API deploy. (See Part 12 for the ECS task pattern.)

```
1. CI passes on main ✓
2. Migration one-off ECS task runs against production DB
   - If exit code 0 → proceed
   - If exit code 1 → stop, run revert, investigate
3. ECS rolling deploy (new tasks start, old tasks drain with --stop-timeout=30s)
4. Smoke test production: `curl https://api.prod/graphql -d '{"query":"{ __typename }"}'`
5. Monitor error rate in CloudWatch for 10 minutes
6. If clean → done
7. If errors spike → roll back (update ECS service to previous image)
```

### Phase 6: Post-Deployment

```bash
# Update knowledge graphs after deploy
graphify update .
node .gitnexus/run.cjs analyze

# Close ticket
"Mark CU-1234 as complete in ClickUp."

# Update memory if there were non-obvious decisions
"Remember: Product module uses soft-delete via deletedAt column.
Every FindMany query in ProductService must add { deletedAt: { is: null } } filter."
```

---

## 2. Daily Workflow

### Morning (10 minutes)

```bash
git checkout main && git pull

# Check what's in progress
"Show my ClickUp tasks for today's sprint."

# Start infrastructure if needed
yarn docker:dev

# Orient Claude for the day
claude
"Check the gitnexus index status and tell me if it needs updating."
```

**Pick the most important ticket for the day. One ticket at a time.** Multitasking between two features on two branches produces shallow work on both.

### During Development (the Focus Block)

1. **Orient first:** `graphify query` for the reference pattern
2. **Impact check:** `gitnexus impact` on anything you'll modify
3. **Build in order:** entity → DTOs → CQRS → service → resolver → module
4. **Test as you go:** don't save all testing for the end
5. **Commit small, logical units:** one commit per logical step, not one commit per file

**The 20-minute rule:** if you've been stuck on one problem for 20 minutes, ask Claude.

```
"I'm getting a 'Cannot resolve dependency' error in ProductModule.
The error says NestJS can't inject ProductService. Here's my module file: <paste>"
```

The error tables in Parts 08 and 14 cover the common cases. For novel errors, Claude with the codebase context usually finds the cause in seconds.

### Pre-Commit Checklist (Never Skip)

```
[ ] TypeScript compiles (no red in yarn api:dev output)
[ ] Unit tests pass (yarn api:test)
[ ] Lint clean (yarn lint)
[ ] Migration tested run + revert
[ ] Smoke tested in Playground
[ ] detect_changes confirms scope
[ ] /code-review run and issues fixed
```

If any item fails: fix it before committing. A failing CI pipeline wastes reviewer time and signals carelessness.

### End of Day (5 minutes)

```bash
# If PR is not ready — save progress
git add -p              # selective add of clean work
yarn cz                 # commit what's stable as wip: or feat: partial

# Save context to Claude memory
"Remember: Product module is 60% done — entity, DTOs, CQRS inputs complete.
Still need: service, resolver, module file, migration, tests."

# Mark ClickUp task
"Update CU-1234: in progress, 60% done, remaining: service + resolver + tests."
```

---

## 3. Sprint Ceremonies

### Sprint Planning (tech lead's role)

**Before the meeting:**
```
"Query the graph for all modules that reference UserEntity.
I'm planning to add a userId column to TagEntity this sprint
and need to understand potential impact."
```

**During the meeting:**
- Break large tickets into implementable sub-tasks (one module = one ticket)
- Flag migration-heavy tickets (more risk, needs staging deploy)
- Identify dependency order (you can't build Session before User exists)
- Estimate by complexity, not hours (S/M/L, not 2h/5h/8h)

**Red flags to call out in planning:**
- "Let's just add it to the existing module" — usually means scope creep in the PR
- "We'll figure out the schema during development" — always design the schema first
- "The migration will be quick" — migrations on live data are never quick to be safe

### Sprint Review (tech lead's role)

- Demo what was actually built, not what was planned
- Show the GraphQL Playground output — concrete, not abstract
- Call out any planned items that weren't shipped and explain why (migrations, unexpected complexity)

### Retrospective

Questions worth asking:
- Did any PRs sit in review for more than 2 days? Why?
- Did any migration fail or need rework? What was missed in review?
- Did any tests fail in CI that passed locally? Why?

---

## 4. Code Review Standards

### What to Check in Every PR

**Security (non-negotiable):**
```
[ ] Every new mutation has @UseGuards(AuthJwtGuard)
[ ] No userId, tenantId as @Field() on any input type
[ ] No new secrets in code or .env committed
[ ] Validation decorators on all input fields
```

**Architecture:**
```
[ ] Entity extends AbstractEntity
[ ] Module uses NestjsQueryGraphQLModule.forFeature (not plain TypeOrmModule)
[ ] Handler files contain one-liners — zero logic
[ ] Resolver doesn't import Repository directly
[ ] CqrsModule in module imports
```

**Database:**
```
[ ] @Index() on every FK column
[ ] @Index() on every frequently-queried column
[ ] Migration generated (not synchronize:true)
[ ] Migration run + revert tested
```

**Tests:**
```
[ ] Unit tests cover happy path + error cases
[ ] Handler tests verify delegation pattern
[ ] At least one E2E test exists
```

### How to Write Review Comments

**Bad (no actionable next step):**
```
"This doesn't look right."
"Performance issue here."
```

**Good (specific, with reason and fix):**
```
"Handler has logic (lines 12-15): the slug uniqueness check belongs in the service,
not the handler. Handlers should be: `return this.service.createOne(command.args)`
Move the check to ProductService.createOne()."

"Missing @Index() on userId column (product.entity.ts:24).
Without this index, getTodos queries will do full table scans when tenants have
thousands of products. Add: @Index() above @Column() userId."
```

Good review comments:
1. Quote the exact line(s)
2. Explain WHY it's a problem
3. Suggest the specific fix

### Approval Philosophy

- Approve if: code works correctly, follows the patterns, has tests, passes security check
- Request changes if: any security issue, any missing test, any pattern violation
- Comment without blocking if: style preferences, minor suggestions, "consider this" items

Don't block on personal style when the code follows the project's established patterns. Consistency is more valuable than any one developer's preferences.

---

## 5. Architecture Decision Records (ADRs)

An ADR documents a significant technical decision: what was decided, why, and what alternatives were rejected. They prevent the same debate happening twice.

### When to Write an ADR

- Choosing between two libraries or approaches
- Deciding on a schema design that could go multiple ways
- Introducing a new pattern that others will follow
- Making a tradeoff between consistency and a specific module's needs

### ADR Template

```markdown
# ADR-001: Use Bull Queues for All Async Operations

## Status
Accepted (2026-06-01)

## Context
Some operations (email, AI evaluation, report generation) are too slow to run
inline in a GraphQL mutation. We need a way to defer work.

## Decision
All async operations use Bull queues backed by Redis.
No inline async work in mutation handlers.

## Alternatives Considered
- `setTimeout` / `setImmediate`: lost on process restart, no retry
- Direct async/await in background: no queue, no monitoring, no retry
- AWS SQS: added infrastructure complexity for same result

## Consequences
- Requires Redis in every environment
- Adds bull-board for local debugging
- Jobs survive API restarts
- Automatic retry with exponential backoff
- Dead letter queue for failed jobs
```

Store ADRs in:
```
docs/adr/
├── 001-bull-queues-for-async.md
├── 002-rs256-jwt-dual-keypairs.md
├── 003-shared-table-multitenancy.md
```

Index them in `CLAUDE.md`:
```markdown
## Architecture Decisions
Key decisions are in docs/adr/. Reference before proposing alternatives.
```

---

## 6. Onboarding New Developers

A new developer on an enterprise NestJS team needs 4 things in order:

**Day 0 — Machine Setup:**
- Node 20 via nvm, Yarn 1.x, Docker Desktop, Claude Code
- VS Code + extensions (ESLint, Prettier, GitLens, Jest runner)
- Clone repo, install deps, set up `.env`, start Docker containers

**Day 1 — Run the System:**
- `yarn migration:run` → `yarn api:dev`
- Smoke test in GraphQL Playground (register, signIn, `me` query)
- Browse the codebase via `graphify query "overall architecture"`

**Week 1 — Build the First Module (Tag):**
- Follow the 9-step pattern manually — no agents
- Every step explained in Parts 08, 09
- Opens first PR at end of the week

**Week 2 — Build the Second Module (with FK + ownership):**
- Follow the Bookmark/Todo pattern (Part 09)
- Write their own unit tests and E2E test
- Understand DataLoader and N+1

**After Week 2 — Graduate to agents:**
- Start using `backend-specialist` agent for scaffolding
- Use `test-writer` agent for tests
- Use `/code-review` before every PR

**The Golden Rule for onboarding:**
> New developers must build the first two modules manually before using agents. Agents accelerate; they don't teach. You need the muscle memory first.

---

## 7. Technical Debt Management

Technical debt is not bad code — it's a trade-off between speed and quality, made explicitly or accidentally.

### Classify Debt

| Type | Example | Priority |
|------|---------|----------|
| Security debt | HS256 JWT in a module | Critical — fix now |
| Architecture debt | Logic in a handler | High — fix next sprint |
| Performance debt | Missing @Index() on FK | Medium — fix before scale |
| Test debt | No E2E test for a module | Medium — fix before release |
| Cleanup debt | Unused import | Low — fix opportunistically |

### Managing Debt in Practice

**Track it:** Create ClickUp tickets labeled `chore` for each debt item. Don't fix debt in the same PR as a feature — it muddles the diff.

**Allocate time:** Reserve 20% of sprint capacity for debt reduction (the "chore" tickets).

**The boy scout rule:** "Leave the campground cleaner than you found it." If you're in a file and you see a missing `@Index()` that's quick to add, add it and include it in your PR. Don't create a separate ticket for a 3-line fix.

**Never refactor inside a feature PR:** If you need to refactor a module to add the feature cleanly, do the refactor in a separate PR first, then build the feature. Mixed PRs are impossible to review.

---

## 8. The Senior Developer Mindset

The things that distinguish a senior engineer from a mid-level engineer on this stack:

| Mid-level | Senior |
|-----------|--------|
| Follows the pattern | Knows why the pattern exists |
| Writes code that works | Writes code that's safe to change |
| Asks "how do I do X?" | Asks "should we do X?" |
| Fixes the bug | Finds the category of bug and adds a rule to prevent it |
| Merges the feature | Thinks about what the migration looks like in production |
| Uses agents to generate code | Uses agents as assistants, reviews everything generated |
| Knows the codebase | Maintains the documentation of the codebase |

The last row is the most important for this era of AI-assisted development. **A senior developer in 2026 is not the person who writes the most code — it's the person who maintains the highest quality signal in the knowledge systems so the whole team (human and AI) can move fast safely.**

---

## Complete Series: What You Can Do Now

| Part | Capability |
|------|-----------|
| 01 | Explain the NestJS stack vs Meteor — philosophy, not just syntax |
| 02 | Bootstrap a production-grade Nx monorepo from scratch |
| 03 | Understand NestJS DI, request lifecycle, module system |
| 04 | Model data in TypeORM, run migrations safely |
| 05 | Write typed CQRS — commands, queries, thin handlers |
| 06 | Full GraphQL API + cursor pagination + Next.js frontend |
| 07 | RS256 JWT auth, guards, refresh tokens |
| 08 | Build a complete module (Tag) — all 9 steps |
| 09 | FK relations, DataLoader, ownership enforcement |
| 10 | Unit tests (mock repos) + E2E tests (real DB) |
| 11 | Bull queues for async, Redis PubSub for real-time |
| 12 | CI/CD, Docker, production migration strategy |
| 13 | Multi-tenancy, RBAC, dual-auth portals |
| 14 | Claude Code, agents, graphify, gitnexus — the AI layer |
| 15 | GitHub MCP, ClickUp/Lark — project management integration |
| 16 | Persistent memory, knowledge graphs, code intelligence |
| 17 | Tech lead SDLC, daily workflow, code review, ADRs, onboarding |

You now have everything needed to be a productive senior enterprise NestJS developer — not just someone who follows patterns, but someone who understands them well enough to enforce them, explain them to others, and extend them safely.
