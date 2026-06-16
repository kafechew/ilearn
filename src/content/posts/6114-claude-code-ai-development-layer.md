---
author: Kai
pubDatetime: 2026-05-14T09:00:00+08:00
title: Claude Code & the AI Development Layer
featured: false
draft: false
slug: 6114-claude-code-ai-development-layer
tags:
  - deeptech
  - ai
  - agentic
  - claude code
  - meteorjs
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/14-claude-code-ai-development-layer.png"
description: By the end of this part, you will learn Claude Code configuration, MCP servers, graphify, gitnexus, and the 6-phase AI-accelerated module workflow.  

---

## What This Part Covers

- What Claude Code is and why it changes how enterprise development works
- Installing and configuring Claude Code for a NestJS project
- The `.claude/` directory — every file explained
- MCP servers: what they are and which ones matter
- `graphify` — introduced here; full deep-dive in Part 6116
- `gitnexus` — introduced here; full deep-dive in Part 6116
- The 6-phase AI-accelerated module workflow
- The prompt library: copy-paste starters for every phase
- What agents cannot do — keeping judgment with the human

---

## Meteor Equivalent

Meteor developers had no equivalent. You Googled, read StackOverflow, pasted code from the docs. In 2026, that workflow is the slow path.

| Old workflow | AI-accelerated workflow |
|-------------|------------------------|
| Read docs, grep files, understand the pattern | `graphify query "how does auth work"` → answer in 5 seconds |
| Manually check "what calls this function?" | `gitnexus impact({ target: "signIn" })` → blast radius in seconds |
| Write boilerplate from scratch | `backend-specialist` agent generates 12 files, you review |
| Forget a `@UseGuards` on a mutation | `/code-review` catches it before the PR |
| Lose context across sessions | Persistent memory recalls your last decision |

The shift is not "AI writes your code." It is **AI handles the mechanical + structural work; you handle the business logic and judgment**.

---

## 1. Install Claude Code

```bash
npm install -g @anthropic-ai/claude-code
claude --version
# claude 1.x.x
```

Start a session from your project root:
```bash
cd /path/to/enterprise-todo
claude
```

Claude Code reads the `.claude/` directory in your project and the global `~/.claude/` automatically on startup.

---

## 2. The `.claude/` Directory

Every enterprise project should have this structure:

```
.claude/
├── CLAUDE.md               ← instructions loaded on every Claude session
├── agents/                 ← sub-agent persona definitions
│   ├── backend-specialist.md
│   ├── migration-specialist.md
│   └── test-writer.md
├── rules/                  ← standing rules (injected as system context)
│   ├── architecture.md
│   ├── security.md
│   ├── performance.md
│   └── migrations.md
├── skills/                 ← slash command workflows
│   └── graphify/
│       └── SKILL.md
├── mcp.json                ← MCP server connections
├── settings.json           ← hooks (auto-run on tool calls)
└── settings.local.json     ← personal permission allowlist (gitignored)
```

### 2.1 CLAUDE.md — The Project Briefing

This file is loaded automatically at the start of every Claude session. It tells Claude:
- What the project is and what stack it uses
- What commands to run
- Which rule files to load
- What code intelligence tools are available

```markdown
# enterprise-todo CLAUDE.md

## Caveman Mode
Terse, imperative. No pleasantries.

## Rule Files
@.claude/rules/architecture.md
@.claude/rules/security.md
@.claude/rules/performance.md
@.claude/rules/migrations.md

## Project Overview
**What it is:** Enterprise NestJS GraphQL API for a todo app
**Stack:** NestJS 11, GraphQL/Apollo, TypeORM/PostgreSQL, Redis/Bull, Passport JWT RS256
**Modules:** Auth, User, Tag, Todo

## Commands
# Start:  yarn api:dev
# Test:   yarn api:test
# Build:  yarn api:build
# Lint:   yarn lint

## Architecture
Nx monorepo. apps/api is the main NestJS GraphQL API. libs/contracts has shared types.
All modules follow CQRS: Resolver → Bus → Handler → Service → Repository.
Feature branches → squash merge to main. Conventional commits via yarn cz.
```

The `@.claude/rules/architecture.md` syntax tells Claude to load the content of that file inline. You maintain rules in separate files instead of one giant CLAUDE.md.

### 2.2 rules/ — Standing Constraints

Claude loads these automatically because CLAUDE.md references them. They encode the non-negotiables:

```markdown
# .claude/rules/architecture.md
- Every module MUST follow the 9-step pattern: Entity → DTO → CQRS Input → Handler → Service → Resolver → Module → Register → Migrate.
- Handlers are thin. No business logic in handlers — it belongs in services.
- Resolvers do not touch repositories directly. Always go through CQRS bus.
- Use AbstractEntity and AbstractDto as base classes.
- All paginated lists use Relay cursor pagination (Connection types) — never raw arrays.
- Use @IsUndefined() (not @IsOptional()) for partial update input fields.
```

```markdown
# .claude/rules/security.md
- Every mutation and sensitive query MUST have @UseGuards(AuthJwtGuard).
- Never store secrets in code. Use .env locally, AWS Secrets Manager in production.
- All JWT uses RS256. Never use HS256.
- ValidationPipe with forbidNonWhitelisted: true is global — never disable it.
- userId is NEVER a @Field() on any input type — always injected from JWT.
```

When you type "create a Product module", Claude reads these rules first and generates code that complies with them — without you repeating "don't forget guards" every time.

### 2.3 agents/ — Sub-Agent Personas

Agents are specialized sub-instances of Claude with a focused system prompt. You invoke them for parallelisable or deep specialized work.

```markdown
---
# .claude/agents/backend-specialist.md
name: backend-specialist
description: Expert in this project's NestJS/CQRS/TypeORM/GraphQL backend patterns.
Use for: adding modules, reviewing handlers, writing service logic, debugging queries.
---

You are a backend specialist for the enterprise-todo project.

Stack: NestJS 11, TypeScript 5, GraphQL (Apollo + nestjs-query), TypeORM 0.3, PostgreSQL,
Redis/Bull, Passport JWT RS256, CQRS via @nestjs/cqrs + nestjs-typed-cqrs.

You know the 9-step module pattern and apply it precisely. When asked to scaffold a module,
produce all 9 files in the correct pattern without asking for clarification on structure.

Rules you always follow:
- Run impact analysis before touching any existing symbol
- Handlers are always one-liners: service.method(message.args)
- Every domain entity carries tenantId FK for multi-tenancy
- userId is never a @Field() on inputs — always injected from JWT
- DataLoaders are Scope.REQUEST — never singleton
```

```markdown
---
# .claude/agents/migration-specialist.md
name: migration-specialist
description: Safe DB migration generation and review.
---

You are a database migration specialist.

ORM: TypeORM 0.3 + PostgreSQL 15. SnakeNamingStrategy active.
AbstractEntity provides id (SERIAL PK), created_at, updated_at.

Before generating any migration:
1. Read the entity file
2. Check existing migrations for current DB state
3. Generate, then READ the SQL — verify it matches intent
4. Check for: DROP COLUMN (data loss), ALTER TYPE (lock), NOT NULL without default

Always provide a rollback plan. For destructive changes, recommend multi-step migration.
```

```markdown
---
# .claude/agents/test-writer.md
name: test-writer
description: Writes unit and E2E tests following the project's test patterns.
---

You write unit and E2E tests for the enterprise-todo project.

Unit tests:
- Mock repositories with jest.fn() + getRepositoryToken(Entity)
- Test service methods independently
- Test handler execute() = delegates to service with message.args

E2E tests:
- Use supertest against the real NestJS app
- Real PostgreSQL test database — never mock the DB
- Test: happy path, auth rejection, business rule violations

Always run yarn api:test after writing unit tests. Verify no regressions.
```

**How to invoke agents:**
```
# In Claude session:
"Use the backend-specialist agent to scaffold a Product module with..."
"Use the test-writer agent to write unit tests for ProductService..."
"Use the migration-specialist to review this migration file: <paste content>"
```

### 2.4 mcp.json — Tool Connections

MCP (Model Context Protocol) servers give Claude specialized tool access beyond its built-in capabilities.

```json
// .claude/mcp.json
{
  "mcpServers": {
    "gitnexus": {
      "command": "node",
      "args": [".gitnexus/run.cjs", "mcp"]
    },
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
      }
    }
  }
}
```

| Server | What it enables |
|--------|----------------|
| `gitnexus` | Call graph, impact analysis, blast radius, safe renames |
| `sequential-thinking` | Structured multi-step reasoning for complex problems |
| `github` | Read/create issues and PRs without leaving the terminal |

Verify connected:
```bash
claude
/mcp
# → gitnexus: connected
# → sequential-thinking: connected
# → github: connected
```

### 2.5 settings.json — Auto Hooks

Hooks run automatically before or after specific tool calls. They nudge Claude toward better habits without you typing reminders.

```json
// .claude/settings.json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{
          "type": "command",
          "command": "echo 'Reminder: for codebase questions, prefer graphify query over grep'"
        }]
      }
    ]
  }
}
```

Practical effect: when Claude reaches for `grep` to understand the codebase, the hook reminds it to use the knowledge graph instead — saving tokens and returning more accurate results.

### 2.6 settings.local.json — Your Permission Allowlist

This file is gitignored (yours alone). Pre-approve common commands so Claude doesn't ask for permission every run.

```json
// .claude/settings.local.json
{
  "permissions": {
    "allow": [
      "Bash(git status)",
      "Bash(git log *)",
      "Bash(git diff *)",
      "Bash(yarn api:test*)",
      "Bash(yarn lint*)",
      "Bash(graphify *)",
      "Bash(nx show project *)"
    ]
  }
}
```

---

## 3. graphify — Semantic Codebase Search

`graphify` builds a knowledge graph from your source code's AST (abstract syntax tree). It extracts symbols, relationships, and concepts — then lets you query in natural language. Use it to understand how the codebase is structured without opening individual files.

```bash
# Initial build (runs once, or after major refactors)
graphify export .

# Fast update after edits (AST-only, no API cost)
graphify update .
```

Example queries:

```bash
graphify query "how does auth guard work"
graphify path "TodoResolver" "TodoService"
graphify explain "FilterQueryBuilder"
```

**When to use:** understanding unfamiliar code. For modifying or debugging specific files, Read directly.

> Graphify is covered in full — what it stores, how to maintain it, team practices — in Part 6116: Memory, Knowledge Graphs & Code Intelligence.

---

## 4. gitnexus — Call Graph & Impact Analysis

`gitnexus` indexes the actual call relationships between functions, classes, and modules. It answers: "if I change X, what breaks?" Use it before touching any existing symbol.

**The most important rule in this stack:**

> **MUST run impact analysis before editing any symbol.**

```
# In Claude session, before touching any function:
"I want to modify signIn in AuthService. Run impact analysis first."
```

Claude runs:
```
impact({ target: "signIn", direction: "upstream" })
```

Returns:
```
Symbol: signIn (AuthService)
Direct callers: signInCommandHandler.execute
Affected processes: Authentication Flow (3 steps)
Risk level: LOW

Upstream chain:
AuthResolver.signIn → CommandBus → SignInCommandHandler.execute → AuthService.signIn
```

LOW risk → safe to proceed. If it returns HIGH or CRITICAL, Claude explains why and what else would break.

> gitnexus tools — `context`, `detect_changes`, `rename` — are covered in full in Part 6116: Memory, Knowledge Graphs & Code Intelligence.

---

## 5. The 6-Phase AI-Accelerated Workflow

This is the complete workflow for adding a new module using AI tools at each phase. Everything here is optional — all of it can be done without agents. The agents save time on repetitive structure; they don't replace judgment.

> **Read this only after building at least two modules manually.** You need the muscle memory to catch mistakes in what agents generate.

### Phase 1 — Orient (Before Creating Any File)

```bash
claude
```

**Understand the territory:**
```
"Query the graph for how the Tag module is structured.
I'm about to build a similar module called Product."
```
Claude runs `graphify query "tag module structure"` → returns the relevant nodes.

**Find the closest reference:**
```
"Which existing module is most similar to what I'm building?
I need: one entity, FK to user, ownership-scoped reads, no nested relations."
```

**Check blast radius on anything you plan to touch:**
```
"I need to extend AbstractEntity to add a soft-delete column.
Run impact analysis first."
```

### Phase 2 — Scaffold with backend-specialist

```
"Use the backend-specialist agent to scaffold a Product module.

Entity: Product
Columns: name (string, required), price (decimal, required), status (ProductStatus enum: ACTIVE/ARCHIVED), userId (FK to user, required, server-injected)
GraphQL: createProduct (auth), updateProduct (auth, ownership), deleteProduct (auth, ownership), getMyProducts (auth, paginated, userId filter), product (public, by id)
Ownership: userId injected from JWT in resolver, never from @Args()
Pattern reference: follow the Tag module exactly for structure, Bookmark module for ownership"
```

**Your job after scaffold returns:**

```bash
# 1. Review every generated file — do not skip
# Check: AbstractEntity base class on entity
# Check: @UseGuards(AuthJwtGuard) on all mutations
# Check: userId has NO @Field() on any input — only declared as TypeScript property
# Check: NestjsQueryGraphQLModule.forFeature in module (not plain TypeOrmModule)
# Check: handlers are one-liners
# Check: module imported in AppModule

# 2. TypeScript compile check
yarn api:dev
# Fix compile errors before continuing

# 3. Ask Claude to review the output
"Review the generated Product module files.
Check: AbstractEntity, guard usage, userId security, module wiring, thin handlers.
List any violations."
```

### Phase 3 — Migration Review with migration-specialist

```bash
yarn migration:generate --name=create-product-table
```

Then:
```
"Use the migration-specialist to review this migration.
Flag: data loss risk, missing constraints, NOT NULL without default, unexpected table changes.
<paste the full migration TypeScript file>"
```

Common issues the specialist catches:
- Missing `@Index()` on the `userId` FK column (you'll add it to the entity)
- `NOT NULL` on a new column that will fail if the table has existing rows
- Extra tables appearing in the diff (you touched something you didn't mean to)

### Phase 4 — Test Generation with test-writer

```
"Use the test-writer agent to write unit tests for ProductService.
Cover: createOne happy path, createOne DB error throws BadRequestException,
updateOne not-found throws, deleteOne happy path.
Follow the TagService test pattern exactly.
Write to: apps/api/src/modules/product/test/product.service.spec.ts"
```

```
"Use the test-writer to write CQRS handler tests for the Product module.
Each handler: one test, verifies delegation to service method with message.args.
Write to: apps/api/src/modules/product/test/product.cqrs.spec.ts"
```

```
"Use the test-writer to write E2E tests for Product.
Cover: createProduct (auth), createProduct (no auth → 401), getMyProducts (only own records),
updateProduct, deleteProduct.
Write to: apps/api-e2e/src/api/product.e2e-spec.ts"
```

Then verify:
```bash
yarn api:test        # unit tests must pass
yarn api:e2e         # E2E must pass (Docker running)
```

### Phase 5 — Pre-PR Code Review

```bash
# In Claude session with feature branch checked out:
/code-review
```

This reviews the current `git diff` against main. Claude checks for:
- Missing guards on mutations
- `userId` exposed as `@Field()` on any input
- Logic inside CQRS handlers
- Wrong base class
- Missing `CqrsModule` import
- Unindexed FK columns

For focused review:
```
"Review only the resolver and entity for the Product module.
Check: (1) all mutations have @UseGuards, (2) userId is never a @Field(),
(3) @Index() on the userId column in the entity,
(4) no direct repository access in the resolver."
```

### Phase 6 — Update Knowledge Graphs After Merge

```bash
# After PR is merged, pull main and update both graphs:
git checkout main && git pull

# Update codebase knowledge graph (fast, no API cost)
graphify update .

# Re-index call graph with new symbols
node .gitnexus/run.cjs analyze
```

If your module introduced a non-obvious pattern (custom soft-delete, unusual query scope):
```
"Document the Product module's soft-delete pattern as a concept note.
The soft-delete uses a deletedAt column filtered in every FindMany query
via a custom scope — different from the standard deleteOne() pattern used in Tag."
```

---

## 6. Prompt Library

Copy-paste these into any Claude session. Substitute `<Module>` with your module name.

**Orient before building:**
```
"Query the graph for modules that have: FK to user, ownership-scoped queries.
I'm designing <Module> and need the right reference module."
```

**Scaffold a module:**
```
"Use the backend-specialist agent to scaffold a <Module> module.
Entity columns: <list>
GraphQL operations: <list>
Ownership: userId injected from JWT, not from client
FK dependencies: <list any FKs>
Reference pattern: <Tag | Bookmark | Todo>"
```

**Check impact before editing existing code:**
```
"I need to change <FunctionName> in <file>.
Run impact analysis and report the blast radius before I proceed."
```

**Review a migration:**
```
"Review this migration for safety. Flag DROP statements, missing constraints,
NOT NULL without defaults, and verify down() is reversible:
<paste migration content>"
```

**Generate tests for a finished module:**
```
"Write unit tests for <Module>Service: happy path, not-found error, silence mode.
Write E2E tests: authenticated create, auth rejection, list shows only own records.
Follow the patterns in tag.service.spec.ts and tag.e2e-spec.ts exactly."
```

**Pre-PR review:**
```
"Review my current git diff for: missing guards, userId as @Field(),
logic in CQRS handlers, wrong base class, missing CqrsModule.
List violations only — no praise."
```

**Detect unintended changes:**
```
"Run detect_changes against main and tell me which symbols I changed
outside of <Module>. If any exist, explain why."
```

---

## 7. What Agents Cannot Do

These limits are non-negotiable. Know them before relying on agents.

- **Agents don't know your domain.** They know the NestJS pattern. Business rules — what the module *should* do, what's valid, what's not — are yours to specify precisely in the prompt.

- **Agents can misread existing modules.** Always tell them which module to reference. "Follow the Bookmark pattern" is better than "follow existing patterns."

- **Agents generate optimistically.** They won't say "this FK to TenantEntity doesn't exist yet." They'll write the import and leave you a compile error. Read every generated file.

- **`/code-review` sees diff, not runtime.** It catches structural and security issues visible in static code. It won't catch wrong business logic.

- **`graphify update` is AST-only.** New architectural decisions, ADRs, or domain context need manual documentation to appear in the knowledge graph.

- **Agents can't make judgment calls.** "Should this be a queue job or a subscription?" — that's yours. The agent will implement whatever you decide.

The right mental model: **you are the architect, the agents are skilled contractors**. A contractor builds what you specify precisely; they don't redesign the building.

---

## Summary

| Tool | When to use | What it does | See |
|------|-------------|--------------|-----|
| `CLAUDE.md` + rules | Always | Loads project context and constraints automatically | — |
| `agents/` | Phase 2, 3, 4 | Scaffolds modules, reviews migrations, writes tests | — |
| `graphify query` | Phase 1, anytime | Semantic search over codebase without reading files | Part 6116 |
| `gitnexus impact` | Before any edit to existing code | Blast radius, risk level | Part 6116 |
| `gitnexus detect_changes` | Before every commit | Verify you only changed what you meant to | Part 6116 |
| `/code-review` | Phase 5, before every PR | Security + pattern violations in the diff | — |
| `settings.local.json` | Once, personal setup | Pre-approve common commands to reduce prompts | — |
