---
author: Kai
pubDatetime: 2026-05-24T09:00:00+08:00
title: "Tech Lead SDLC & Daily Workflow: Ticket to Production"
featured: false
draft: false
slug: 6124-tech-lead-sdlc-daily-workflow
tags:
  - deeptech
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/24-tech-lead-sdlc-daily-workflow.png"
description: The complete SDLC from ticket to production — SDLC phases, daily workflow, a real end-to-end case study building the Product module, sprint ceremonies, code review standards, ADRs, and onboarding new developers.

---

## What This Part Covers

- What "tech lead" actually means on an enterprise NestJS team
- The complete SDLC: six phases from ticket to production
- The daily workflow: morning → development → pre-commit → end of day
- **Real-world case study**: building the Product module, start to finish
- Sprint ceremonies and the tech lead's role in each
- Code review: what to check and how to give useful feedback
- Architecture Decision Records (ADRs)
- Onboarding new developers
- Technical debt management

**Prerequisites:** Part 19 covers Commitizen, Husky, branch strategy, GitHub branch protection, and CI/CD setup. Part 22 covers MCP tool setup (GitHub, ClickUp, Lark). This part assumes both are in place and shows how they work together in practice.

---

## What "Tech Lead" Means

A tech lead is not a senior developer who writes more code. The role has three distinct responsibilities:

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
1. Read the ticket — understand WHAT and WHY, not just WHAT
2. What DB schema does this require?
3. What new GraphQL operations does this expose?
4. Which existing modules does this touch?
5. Is there a security concern (new user-facing fields, new permissions)?
```

**As a tech lead:**
```
1. Is this the right abstraction? (e.g. should tags be a separate entity or an array?)
2. What is the migration risk?
3. Does this break multi-tenancy or RBAC boundaries?
4. What is the test strategy?
5. Is this one PR or multiple?
```

**The 3-question design check — answer all three before writing the first file:**
```
1. What does the DB table look like? (draw it)
2. What GraphQL operations do we expose? (write as pseudocode)
3. Which existing module is this most like? (pick the reference)
```

### Phase 2: Branch & Build

```bash
# Always branch from latest main
git checkout main && git pull
git checkout -b feat/product-module

# Orient with the graph before building
claude
"Query the graph for the reference module closest to what I'm building.
Run impact analysis on any existing symbols I plan to change."
```

Build in the 9-step order: entity → DTOs → CQRS inputs → CQRS handlers → CQRS index → service → resolver → module → register → migrate.

This order matters. The entity defines the schema. DTOs depend on the entity. CQRS inputs depend on DTOs. The service depends on CQRS inputs. The resolver depends on everything above. Building out of order causes circular dependency errors and forces rework.

### Phase 3: Verify Locally

Every point must be green before the PR opens.

```bash
# 1. TypeScript compiles
yarn api:dev
# Watch for red compile errors in the output

# 2. Unit tests pass
yarn api:test

# 3. Migration round-trip
yarn migration:run
# Open Adminer, verify table and columns exist
yarn migration:revert
# Verify table is gone / columns removed
yarn migration:run
# Run again — leave it clean for E2E

# 4. Smoke test in GraphQL Playground
# Test each new operation: success case AND auth rejection case

# 5. Lint
yarn lint

# 6. Scope verification
"Run detect_changes against main and confirm I only touched product module files."
```

### Phase 4: Commit and Open PR

```bash
# Stage selectively — never git add .
git add apps/api/src/modules/product/
git add apps/api/src/migrations/*product*
git add apps/api/src/app/app.module.ts

# Verify what's staged
git diff --staged

# Self-review before pushing
claude
/code-review

# Fix anything flagged, then commit
yarn cz
# feat(product): add product CRUD module with CQRS pattern

# Push and open PR via GitHub MCP
git push -u origin feat/product-module
"Open a PR for feat/product-module.
Title: feat(product): add product CRUD module
Fill the PR template from .github/PULL_REQUEST_TEMPLATE.md.
Link to ticket CU-1234."
```

### Phase 5: Deployment

```
1. CI passes on main ✓
2. Migration one-off ECS task runs against production DB
   - Exit code 0 → proceed to rolling deploy
   - Exit code 1 → stop, run revert, investigate before retrying
3. ECS rolling deploy: new tasks start, old tasks drain (--stop-timeout=30s)
4. Production smoke test:
   curl https://api.prod/graphql -d '{"query":"{ __typename }"}'
5. Monitor CloudWatch error rate for 10 minutes
6. Clean → done | Errors spike → roll back to previous image
```

> **See Part 20** for the complete production deployment setup: ECS Fargate task definition, RDS Multi-AZ, ElastiCache with TLS, GitHub Actions OIDC CD pipeline, and the one-off migration task pattern.

See Part 19 for the full ECS migration task pattern and GitHub Actions CI/CD pipeline.

### Phase 6: Post-Deployment

```bash
# Update knowledge graphs
graphify update .
node .gitnexus/run.cjs analyze

# Close the ticket
"Mark CU-1234 as complete in ClickUp."

# Save non-obvious decisions to Claude memory
"Remember: Product module uses soft-delete via deletedAt.
Every FindMany in ProductService must include { deletedAt: { is: null } } filter."
```

---

## 2. Daily Workflow

### Morning (10 minutes)

```bash
git checkout main && git pull

yarn docker:dev

claude
"Show my ClickUp tasks for today's sprint."
"Check the gitnexus index status — does it need updating?"
```

**Pick the most important ticket. One ticket at a time.** Multitasking between two features on two branches produces shallow work on both. The ticket you don't finish today is a context-switch cost tomorrow.

### During Development (the Focus Block)

1. **Orient first:** `graphify query` for the reference pattern closest to your feature
2. **Impact check:** `gitnexus impact` on anything you plan to modify
3. **Build in order:** entity → DTOs → CQRS → service → resolver → module
4. **Test as you go:** don't save all testing for the end
5. **Commit in logical units:** one commit per meaningful step, not one commit per file

**The 20-minute rule:** if you've been stuck on one problem for 20 minutes, ask Claude.

```
"I'm getting 'Cannot resolve dependency' in ProductModule.
NestJS can't inject ProductService. Here's my module file: <paste>"
```

### Pre-Commit Checklist (Non-Negotiable)

```
[ ] TypeScript compiles (no red in yarn api:dev)
[ ] Unit tests pass (yarn api:test)
[ ] Lint clean (yarn lint)
[ ] Migration: run + revert + run again
[ ] Smoke tested in GraphQL Playground
[ ] detect_changes confirms you only touched the expected module
[ ] /code-review run and findings resolved
```

If any item fails: fix it before committing. A failing CI pipeline wastes reviewer time and signals carelessness.

### End of Day (5 minutes)

```bash
# Save stable progress — even if the feature isn't done
git add apps/api/src/modules/product/product.entity.ts
git add apps/api/src/modules/product/dto/
yarn cz
# chore(product): wip entity and DTOs — service and resolver pending

# Save context so tomorrow starts fast
"Remember: Product module is 50% done.
Entity, DTOs, CQRS inputs complete.
Still need: service, resolver, module file, migration, tests."

# Update ClickUp
"Update CU-1234: in progress. Entity + DTOs done. Service and resolver next."
```

---

## 3. Real-World Case Study: Building the Product Module

This is a complete walkthrough of a single feature — from Monday morning standup to the PR merged and ticket closed — using the full toolchain: Commitizen, GitHub MCP, ClickUp, gitnexus, and Claude agents.

The feature: **CU-1234 — Add Product module** (name, price, status, userId FK).

---

### 8:30am — Morning Standup

```bash
git checkout main && git pull
yarn docker:dev
claude
```

```
"Show my ClickUp tasks for today's sprint that aren't started."
```

Claude returns:
```
CU-1234: Add Product module (unstarted, estimated 3h)
CU-1240: Fix N+1 on TagResolver (unstarted, estimated 1h)
```

CU-1234 is the more impactful ticket. Pick it.

```
"Mark CU-1234 as in progress."
```

```bash
git checkout -b feat/product-module
```

---

### 9:00am — Discovery

Before writing a single file, answer the 3-question design check.

**Q1: What does the table look like?**
```
product
  id          uuid PK
  name        varchar(255)
  price       decimal(10,2)
  status      enum: active | inactive | archived
  user_id     uuid FK → user
  tenant_id   uuid FK → tenant
  created_at  timestamp
  updated_at  timestamp
  deleted_at  timestamp (soft-delete)
```

**Q2: What GraphQL operations do we expose?**
```
Query:   products(filter, paging, sorting): ProductConnection
Query:   product(id: ID!): ProductDto
Mutation: createProduct(input: CreateProductInput!): ProductDto
Mutation: updateProduct(input: UpdateProductInput!): ProductDto
Mutation: deleteProduct(id: ID!): ProductDto
```

**Q3: Which existing module is the closest reference?**

```
"Query the graph for the module that most closely matches
a module with user ownership, soft-delete, and standard CRUD."
```

gitnexus returns: `TodoModule` — has userId FK, soft-delete, full CQRS pattern. Use it as the reference.

**Impact check before touching anything shared:**

```
"Run impact analysis on FilterQueryBuilder."
```

Result: Medium risk. 3 services depend on it. Confirm the Product service will extend it the same way as Todo — no changes needed to FilterQueryBuilder itself. Proceed.

---

### 9:30am — Build (9-Step Order)

**Step 1 — Entity**

Following `TodoEntity` as the template:

```typescript
// apps/api/src/modules/product/product.entity.ts
@Entity('product')
export class ProductEntity extends AbstractEntity {
  @Column({ length: 255 })
  name: string;

  @Column({ type: 'decimal', precision: 10, scale: 2 })
  price: number;

  @Column({ type: 'enum', enum: ProductStatus, default: ProductStatus.ACTIVE })
  status: ProductStatus;

  @Index()
  @Column({ type: 'uuid' })
  userId: string;

  @Index()
  @Column({ type: 'uuid' })
  tenantId: string;

  @Column({ type: 'timestamp', nullable: true })
  deletedAt: Date | null;

  @ManyToOne(() => UserEntity)
  @JoinColumn({ name: 'user_id' })
  user: UserEntity;
}
```

Register it in `AppModule` immediately — TypeORM won't load it otherwise.

**Step 2 — Constants**

```typescript
// apps/api/src/modules/product/product.constants.ts
export enum ProductStatus {
  ACTIVE = 'active',
  INACTIVE = 'inactive',
  ARCHIVED = 'archived',
}
```

**Steps 3–7** — DTOs, CQRS inputs, handlers, service, resolver. Follow the same 9-step pattern from Part 08. At each step:

```
"Use the backend-specialist agent to scaffold <step> for Product,
following the TodoModule pattern exactly."
```

Review every file the agent generates before moving to the next step. Agents scaffold correctly about 90% of the time; the remaining 10% are subtle mismatches (wrong import path, missing decorator, incorrect generic type). Reading the output is not optional.

**After the service is done — smoke test in GraphQL Playground:**
```graphql
mutation {
  createProduct(input: { name: "Test", price: 9.99, status: ACTIVE }) {
    id
    name
    price
    status
  }
}
```

If this returns data, the entity, module registration, resolver, and service are all wired correctly. If it throws, the error tells you exactly which layer is broken.

---

### 11:30am — Migration

```bash
yarn api:migration:generate apps/api/src/migrations/AddProductModule
```

Read the generated SQL before running it:

```sql
CREATE TABLE "product" (
  "id" uuid NOT NULL DEFAULT uuid_generate_v4(),
  "name" character varying(255) NOT NULL,
  "price" numeric(10,2) NOT NULL,
  "status" "product_status_enum" NOT NULL DEFAULT 'active',
  "user_id" uuid NOT NULL,
  "tenant_id" uuid NOT NULL,
  "deleted_at" TIMESTAMP,
  "created_at" TIMESTAMP NOT NULL DEFAULT now(),
  "updated_at" TIMESTAMP NOT NULL DEFAULT now(),
  CONSTRAINT "PK_product" PRIMARY KEY ("id")
);
CREATE INDEX "IDX_product_user_id" ON "product" ("user_id");
CREATE INDEX "IDX_product_tenant_id" ON "product" ("tenant_id");
```

Looks correct. Run the round-trip:

```bash
yarn api:migration:run
# Verify in Adminer: localhost:8080 → product table exists with correct columns

yarn api:migration:revert
# Verify in Adminer: product table is gone

yarn api:migration:run
# Leave it clean for tests
```

---

### 12:00pm — Tests

```
"Use the test-writer agent to write unit tests for ProductService,
following the pattern in apps/api/src/modules/todo/test/todo.service.spec.ts."
```

```
"Write an E2E test for the product module covering:
createProduct, products query, updateProduct, deleteProduct, and an
unauthenticated rejection case. Follow the pattern in apps/api/e2e/todo.e2e-spec.ts."
```

Run them:

```bash
yarn api:test
# All tests: ✓

yarn api:e2e
# product.e2e-spec.ts: 5 passed ✓
```

---

### 2:00pm — Pre-Commit Verification

```bash
# Full checklist
yarn lint          # ✓
yarn api:test      # ✓
yarn api:e2e       # ✓
```

```
"Run detect_changes against main. Confirm I only touched product module files,
the product migration, and app.module.ts."
```

Result confirms scope. No unexpected changes.

```
/code-review
```

Claude flags two things:
1. `ProductResolver.deleteProduct` is missing `@UseGuards(AuthJwtGuard)` — add it
2. `ProductService.findManyProducts` is missing the `deletedAt: { is: null }` filter — add it

Fix both. Re-run tests to confirm nothing broke.

---

### 2:30pm — Commit

```bash
# Stage selectively
git add apps/api/src/modules/product/
git add apps/api/src/migrations/1748000000000-AddProductModule.ts
git add apps/api/src/app/app.module.ts

# Verify
git diff --staged
# Confirms: only product module files, one migration, app module registration

yarn cz
```

Commitizen prompt:
```
? Select the type of change: feat
? What is the scope: product
? Short description: add product CRUD module with soft-delete and ownership
? Longer description: (press enter to skip)
? Breaking changes: No
? Issues closed: CU-1234
```

Commit message:
```
feat(product): add product CRUD module with soft-delete and ownership

Closes CU-1234
```

---

### 2:45pm — Open PR

```bash
git push -u origin feat/product-module
```

```
"Open a PR for feat/product-module.
Title: feat(product): add product CRUD module
Fill the PR template from .github/PULL_REQUEST_TEMPLATE.md.
The migration adds a product table — run and revert both tested.
Unit tests: 6. E2E tests: 5.
Link to ticket CU-1234."
```

Claude creates the PR and returns: `https://github.com/org/enterprise-todo/pull/45`

```
"Post a message to #backend-team in Lark:
'Product module PR ready for review: https://github.com/org/enterprise-todo/pull/45
Adds full CRUD with soft-delete, ownership, and migration. Needs 1 approval.'"
```

Update ClickUp:
```
"Add a comment to CU-1234: 'PR #45 open for review. Migration tested locally.'"
```

---

### Next Morning — CI Passes, PR Merged

```
"Check the CI status on PR #45."
```

```
lint: ✓  unit-test: ✓  e2e-test: ✓
```

Alex approved. Squash merge.

```
"PR #45 is approved with all checks green. Squash merge and delete the branch."
```

GitHub Actions CD runs: builds image → migration ECS task (exits 0) → rolling deploy.

```bash
git checkout main && git pull

# Update knowledge graphs
graphify update .
node .gitnexus/run.cjs analyze
```

```
"Mark CU-1234 as complete in ClickUp."
```

Done. CU-1234 moved from "In Progress" to "Complete." The Product module is in production. Total time: one focused day.

---

## 4. Sprint Ceremonies

### Sprint Planning (tech lead's role)

**Before the meeting:**
```
"Query the graph for all modules that reference UserEntity.
I'm planning to add a userId FK to TagEntity this sprint —
I need to understand the full impact."
```

**During the meeting:**
- Break large tickets into implementable sub-tasks (one module = one ticket)
- Flag migration-heavy tickets — they carry more risk and need a staging deploy step
- Identify dependency order: Session module can't be built before User exists
- Estimate by complexity (S/M/L), not hours

**Red flags to surface in planning:**
- "Let's just add it to the existing module" — scope creep in the PR
- "We'll figure out the schema during development" — always design schema first
- "The migration will be quick" — migrations on live data are never trivially quick

### Sprint Review

- Demo what was actually built, not what was planned
- Show GraphQL Playground output — concrete, not abstract
- Name any planned items that didn't ship and explain why (unexpected migration complexity, unblocked dependency)

### Retrospective

Questions worth asking every sprint:
- Did any PRs sit in review for more than 2 days? Why?
- Did any migration fail or need rework in staging? What was missed in review?
- Did any test pass locally but fail in CI? Why?

---

## 5. Code Review Standards

### What to Check in Every PR

**Security (non-negotiable):**
```
[ ] Every new mutation has @UseGuards(AuthJwtGuard)
[ ] No userId or tenantId exposed as @Field() on any input type
[ ] No secrets in code or .env committed
[ ] Validation decorators on all input fields
```

**Architecture:**
```
[ ] Entity extends AbstractEntity
[ ] Module uses NestjsQueryGraphQLModule.forFeature (not plain TypeOrmModule)
[ ] Handlers are one-liners — zero business logic
[ ] Resolver does not import Repository directly
```

**Database:**
```
[ ] @Index() on every FK column
[ ] @Index() on every frequently-queried column
[ ] Migration generated (not synchronize: true)
[ ] Migration run + revert tested locally
```

**Tests:**
```
[ ] Unit tests cover happy path + error cases
[ ] Handler tests verify the delegation pattern
[ ] At least one E2E test exists
```

### How to Write Review Comments

**Unhelpful:**
```
"This doesn't look right."
"Performance issue here."
```

**Useful — specific, with reason and fix:**
```
"Handler has business logic (lines 12–15): the slug uniqueness check belongs in
ProductService, not the handler. Move it there.
Handlers should be one line: `return this.service.createOne(command.args)`"

"Missing @Index() on userId (product.entity.ts:24).
Without this index, getTodos does a full table scan when tenants have
thousands of products. Add: @Index() on the line above @Column() userId."
```

Good review comments:
1. Quote the exact line(s)
2. Explain WHY it's a problem
3. State the specific fix

### Approval Philosophy

- **Approve** if: code is correct, follows patterns, has tests, passes security check
- **Request changes** if: any security issue, missing test, pattern violation
- **Comment without blocking** if: style preference, non-breaking suggestion, "consider this"

Don't block on personal style when the code follows the project's established patterns. Consistency is more valuable than any individual's preferences.

---

## 6. Architecture Decision Records (ADRs)

An ADR documents a significant technical decision: what was decided, why, and what alternatives were rejected. They prevent the same debate from happening twice.

### When to Write an ADR

- Choosing between two libraries or approaches
- Deciding on a schema design that could go multiple ways
- Introducing a new pattern that others will follow
- Making a tradeoff between consistency and one module's specific needs

### ADR Template

```markdown
# ADR-001: Use Bull Queues for All Async Operations

## Status
Accepted (2026-06-01)

## Context
Some operations (email, AI evaluation, report generation) are too slow
to run inline in a GraphQL mutation.

## Decision
All async operations use Bull queues backed by Redis.
No inline async work in mutation handlers.

## Alternatives Considered
- `setTimeout` / `setImmediate`: lost on process restart, no retry
- Direct async/await in background: no queue, no monitoring, no retry
- AWS SQS: added infrastructure complexity for equivalent result

## Consequences
- Requires Redis in every environment
- Adds bull-board for local debugging
- Jobs survive API restarts
- Automatic retry with exponential backoff
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

## 7. Onboarding New Developers

A new developer needs four things in order:

**Day 0 — Machine Setup:**
- Node 20 via nvm, Yarn 1.x, Docker Desktop, Claude Code
- VS Code + extensions: ESLint, Prettier, GitLens, Jest Runner
- Clone repo, install deps, set up `.env`, start Docker containers

**Day 1 — Run the System:**
- `yarn migration:run` → `yarn api:dev`
- Smoke test in GraphQL Playground: register → signIn → `me` query
- Browse the codebase: `graphify query "overall architecture"`

**Week 1 — Build the First Module (Tag) Manually:**
- Follow the 9-step pattern without agents
- Every step is covered in Parts 08 and 09
- Opens their first PR at the end of the week

**Week 2 — Build the Second Module (with FK + ownership):**
- Follow the Bookmark/Todo pattern (Part 09)
- Write their own unit and E2E tests
- Understand DataLoader and N+1

**After Week 2 — Graduate to Agents:**
- Start using `backend-specialist` for scaffolding
- Use `test-writer` for tests
- Use `/code-review` before every PR

**The Golden Rule for onboarding:**
> New developers must build the first two modules manually before using agents. Agents accelerate; they don't teach. The muscle memory has to come first.

---

## 8. Technical Debt Management

Technical debt is not bad code — it's a tradeoff between speed and quality, made explicitly or accidentally.

### Classify Debt

| Type | Example | Priority |
|------|---------|----------|
| Security debt | HS256 JWT in a module | Critical — fix now |
| Architecture debt | Business logic in a handler | High — fix next sprint |
| Performance debt | Missing @Index() on FK | Medium — fix before scale |
| Test debt | No E2E test for a module | Medium — fix before release |
| Cleanup debt | Unused import | Low — fix opportunistically |

### Managing Debt in Practice

**Track it in ClickUp:** Create tickets labeled `chore` for each item. Don't fix debt inside a feature PR — it muddies the diff and makes both changes harder to review or revert.

**Allocate time:** Reserve 20% of sprint capacity for `chore` tickets.

**The boy scout rule:** If you're in a file and see a missing `@Index()` that's a 2-line fix, add it and include it in the PR. Don't create a separate ticket for a 2-line fix.

**Never refactor inside a feature PR.** If the feature requires refactoring an existing module first, do the refactor in a separate PR, merge it, then build the feature. Mixed PRs are impossible to review.

---

## 9. The Senior Developer Mindset

| Mid-level | Senior |
|-----------|--------|
| Follows the pattern | Knows why the pattern exists |
| Writes code that works | Writes code that's safe to change |
| Asks "how do I do X?" | Asks "should we do X?" |
| Fixes the bug | Finds the category of bug, adds a rule to prevent it |
| Merges the feature | Thinks about what the migration looks like in production |
| Uses agents to generate code | Uses agents as assistants, reviews everything generated |
| Knows the codebase | Maintains the knowledge systems so the whole team moves fast safely |

The last row is the most important for AI-assisted development. **A senior developer in 2026 is not the person who writes the most code — it's the person who maintains the highest quality signal in the knowledge systems so both human and AI can move fast without breaking things.**

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
| 12 | Email, 2FA, API keys, audit logging |
| 13 | Two-factor authentication deep dive |
| 14 | API key management |
| 15 | Multi-tenancy, RBAC, dual-auth portals |
| 16 | Dual-app monorepo — portal API & platform interceptor |
| 17 | Media library — S3 presigned uploads, CDN |
| 18 | Affiliate referral tree — materialized path |
| 19 | Git workflow & CI/CD pipeline |
| 20 | Production deployment — ECS Fargate, RDS, ElastiCache |
| 21 | Claude Code & the AI development layer |
| 22 | MCP integrations — GitHub, ClickUp, Lark |
| 23 | Memory, knowledge graphs & code intelligence |
| 24 | Tech lead SDLC, daily workflow, case study, code review, ADRs, onboarding |

You now have everything needed to be a productive senior enterprise NestJS developer — not just someone who follows patterns, but someone who understands them well enough to enforce them, explain them to others, and extend them safely.

This is Part 24 — the final part of the 24-part Meteor to NestJS migration series. The series is complete.
