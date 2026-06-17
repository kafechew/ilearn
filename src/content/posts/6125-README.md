---
author: Kai
pubDatetime: 2026-05-25T09:00:00+08:00
title: "The README — Enterprise NestJS Monorepo (enterprise-todo)"
featured: false
draft: false
slug: 6125-README
tags:
  - deeptech
  - nestjs
  - nx
  - typescript
  - graphql
  - postgresql
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/25-README.png"
description: "The production-ready README for the enterprise-todo repository built across all 24 parts of this series. Copy this into your repo's README.md — it covers stack, prerequisites, getting started, every environment variable, every script, the architecture, and all known gotchas."
---

> **This post is the README.** By the end of the 24-part series you have a full enterprise NestJS + Next.js monorepo. Copy the content below directly into `README.md` at the root of your workspace.

---

# enterprise-todo

An enterprise-grade todo application built across a 24-part tutorial series — demonstrating every pattern needed to build a production NestJS + Next.js monorepo from scratch.

**What this is:**
- A working fullstack application (user API + admin portal API + Next.js frontend)
- A production-ready scaffold for enterprise NestJS projects
- A Meteor-to-NestJS migration case study with full code at every step

---

## Tutorial Series

Each part adds one layer of the stack with working code and Meteor migration context.

| Part | Slug | Title | Key concepts |
|------|------|-------|-------------|
| 1 | 6101 | Meteor → NestJS: The Mental Shift | Explicit vs implicit philosophy, monorepo rationale, concept translation |
| 2 | 6102 | Environment Setup & Nx Workspace | nvm, Yarn, Docker Compose, Nx scaffold, first NestJS app |
| 3 | 6103 | TypeScript Decorators, DI & Modules | Decorators, dependency injection, module system, GraphQL vs REST |
| 4 | 6104 | Database: PostgreSQL, TypeORM & Migrations | Entities, AbstractEntity, SnakeNamingStrategy, migration workflow |
| 5 | 6105 | Production Hardening: Config, Logging & Security | Joi validation, typed AppConfig, LoggingInterceptor, Helmet, throttling, AllExceptionsFilter |
| 6 | 6106 | CQRS — The Enterprise Request Pipeline | CommandBus, QueryBus, nestjs-typed-cqrs, 9-step pattern, thin handlers |
| 7 | 6107 | GraphQL API + Next.js Frontend | DTOs, @FilterableField, ConnectionType, cursor pagination, Next.js 16, Apollo Client v4 |
| 8 | 6108 | Authentication: JWT RS256, Guards & Validation | RS256 key pairs, Passport JWT, AuthJwtGuard, @CurrentUser(), ValidationPipe, dual-auth |
| 9 | 6109 | Extended Auth: Email, SecuredTokens & 2FA | Nodemailer + Bull, single-use tokens, password reset, TOTP 2FA with otplib |
| 10 | 6110 | Case Study 1 — Tag Module (9-Step Build) | Full walkthrough of every step with zero skipped |
| 11 | 6111 | Case Study 2 — Todo Module (FK + Auth + DataLoader) | Foreign keys, ownership scoping, N+1 prevention, Scope.REQUEST |
| 12 | 6112 | Testing: Unit + E2E with Real DB | Jest, mock TypeORM correctly, real PostgreSQL in E2E, CI integration |
| 13 | 6113 | Queues & Real-Time: Bull + Redis PubSub | Bull jobs, Redis PubSub vs in-process, GraphQL subscriptions |
| 14 | 6114 | Advanced Data Patterns | LowerCaseTransformer, AuditSubscriber, pessimistic-lock running numbers, libs/core |
| 15 | 6115 | Multi-Tenancy & RBAC | tenantId pattern, TenantGuard, @Authorize, ACPermissionGuard, RBAC |
| 16 | 6116 | Dual-App Portal: Platform Interceptor | apps/portal-api, RequestPlatformInterceptor, platform JWT claim, PortalJwtStrategy |
| 17 | 6117 | Media Library: S3, Presigned URLs & CDN | S3 presigned upload flow, magic-byte validation, sharp thumbnails, CloudFront |
| 18 | 6118 | Affiliate & Referral Tree: Materialized Path | referralCode, materialized path, downline queries, referral stats |
| 19 | 6119 | Git Workflow, Husky & CI/CD | Conventional commits, Commitizen, Husky, branch strategy, GitHub Actions CI |
| 20 | 6120 | Production Deployment: ECS, RDS & ElastiCache | ECS Fargate, RDS Multi-AZ, ElastiCache TLS, ALB, Secrets Manager, OIDC CD |
| 21 | 6121 | Claude Code: AI Development Layer | .claude/ structure, CLAUDE.md, graphify, gitnexus, 6-phase AI workflow |
| 22 | 6122 | MCP: GitHub, ClickUp & Project Management | GitHub MCP, built-in OAuth integrations, prompt library |
| 23 | 6123 | Memory, Knowledge Graphs & Code Intelligence | Persistent memory, graphify codebase graph, gitnexus call graph |
| 24 | 6124 | Tech Lead SDLC & AI-Assisted Daily Workflow | Ticket-to-production case study, sprint ceremonies, ADRs, onboarding |

---

## Stack

| Layer | Technology |
|-------|-----------|
| Monorepo | Nx 22 |
| Backend | NestJS 11, Express 5, Apollo Server v5 (code-first GraphQL), TypeORM 0.3.x, CQRS |
| Frontend | Next.js 16 (App Router), Tailwind CSS v4, Apollo Client v4, Shadcn UI (base-nova) |
| Database | PostgreSQL 15 |
| Cache / Queue | Redis 7 (Alpine) |
| Auth | Passport JWT — RS256 (asymmetric, 4096-bit RSA keys) |
| Runtime | Node 20, Yarn 1.x (Classic) |
| Infrastructure | Docker Compose (local) · ECS Fargate + RDS + ElastiCache (production) |

**Key ecosystem packages:**

| Package | Purpose |
|---------|---------|
| `nestjs-typed-cqrs` | Type-safe `CommandBus` / `QueryBus` — no `any` on bus execute/dispatch |
| `nestjs-dev-utilities` | `AbstractEntity` base class (id, createdAt, updatedAt, deletedAt, soft-delete) |
| `@ptc-org/nestjs-query-core` | `Query<T>` filter/sort/paging types |
| `@ptc-org/nestjs-query-graphql` | `@FilterableField`, `QueryArgsType`, `ConnectionType` (Relay cursor pagination) |
| `@ptc-org/nestjs-query-typeorm` | `TypeOrmQueryService<T>` + `FilterQueryBuilder` |
| `typeorm-naming-strategies` | Automatic snake_case column and table names |
| `@jorgebodega/typeorm-seeding` | Database seeders |
| `@as-integrations/express5` | Apollo Server v5 → Express 5 adapter — **required**, the Express 4 adapter is incompatible |
| `otplib` | RFC 6238 TOTP — 2FA secret generation and token verification |
| `sharp` | Image processing for media thumbnails in the Bull processor |

---

## Project Structure

```
enterprise-todo/
├── apps/
│   ├── api/                           ← NestJS user API  (GraphQL at :3333)
│   │   └── src/
│   │       ├── app/
│   │       │   ├── app.module.ts      ← root module; explicit entities[], CqrsModule.forRoot()
│   │       │   ├── app.resolver.ts    ← health check
│   │       │   └── ormconfig.ts       ← TypeORM DataSource for the CLI (no NestJS DI)
│   │       ├── config/
│   │       │   ├── config.validation.ts   ← Joi schema (all env vars declared here)
│   │       │   └── config.mapper.ts       ← typed AppConfig getter
│   │       ├── filters/
│   │       │   └── all-exceptions.filter.ts   ← global; re-throws for GraphQL, logs 5xx
│   │       ├── interceptors/
│   │       │   └── logging.interceptor.ts     ← request/response timing from nestjs-dev-utilities
│   │       ├── subscribers/
│   │       │   └── audit.subscriber.ts        ← AuditSubscriber (createdBy/updatedBy via CLS)
│   │       ├── helpers/
│   │       │   ├── lower-case.transformer.ts
│   │       │   ├── slug.transformer.ts
│   │       │   └── upper-case.transformer.ts
│   │       ├── modules/
│   │       │   ├── auth/              ← JWT RS256, AuthJwtGuard, @CurrentUser()
│   │       │   │   ├── decorators/    ←   current-user.decorator.ts
│   │       │   │   ├── dto/           ←   AuthTokensDto, SignInInput, RegisterInput
│   │       │   │   ├── guards/        ←   auth-jwt.guard.ts
│   │       │   │   ├── strategies/    ←   jwt.strategy.ts
│   │       │   │   ├── auth.interface.ts   ← JwtPayload (sub, username, platform)
│   │       │   │   ├── auth.module.ts
│   │       │   │   ├── auth.resolver.ts
│   │       │   │   └── auth.service.ts
│   │       │   ├── email/             ← Nodemailer + Bull queue (async delivery)
│   │       │   ├── health/            ← HealthResolver (@SkipThrottle)
│   │       │   ├── media/             ← S3 presigned uploads, magic bytes, CloudFront
│   │       │   │   ├── media.entity.ts
│   │       │   │   ├── media.processor.ts   ← Bull worker: validate → thumbnail → mark ready
│   │       │   │   ├── media.resolver.ts
│   │       │   │   └── s3.service.ts
│   │       │   ├── permission/        ← PermissionEntity (slug-based ACL rows)
│   │       │   ├── referral/          ← materialized path tree, referralCode, downline
│   │       │   ├── role/              ← RoleEntity (ManyToMany → permissions)
│   │       │   ├── running-number/    ← pessimistic-lock sequence service
│   │       │   ├── secured-token/     ← single-use tokens (password reset, email verify)
│   │       │   ├── tag/               ← Tag feature (full 9-step CQRS)
│   │       │   ├── todo/              ← Todo feature (CQRS + DataLoader + ownership)
│   │       │   │   ├── cqrs/          ←   inputs, handlers, index
│   │       │   │   ├── dto/           ←   TodoDto, CreateTodoInput, UpdateTodoInput
│   │       │   │   ├── todo.constant.ts
│   │       │   │   ├── todo.entity.ts
│   │       │   │   ├── todo.loader.ts    ← DataLoader (Scope.REQUEST, N+1 fix)
│   │       │   │   ├── todo.module.ts
│   │       │   │   ├── todo.resolver.ts
│   │       │   │   └── todo.service.ts   ← extends TypeOrmQueryService<TodoEntity>
│   │       │   └── user/
│   │       │       ├── dto/           ←   UserDto (no password field)
│   │       │       ├── user.constant.ts
│   │       │       └── user.entity.ts    ← referralCode, path (materialized), 2FA columns
│   │       ├── shared/
│   │       │   └── guards/
│   │       │       ├── ac-permission.guard.ts     ← ACPermissionGuard
│   │       │       ├── use-ac-guard.decorator.ts  ← @UseACGuard('MODULE', ['slug'])
│   │       │       └── allow-guest.decorator.ts   ← @AllowGuest()
│   │       ├── migrations/            ← TypeORM migration files (explicit, no globs)
│   │       ├── seeders/
│   │       │   ├── 0-reset.seeder.ts
│   │       │   ├── 1-user.seeder.ts
│   │       │   └── 2-todo.seeder.ts
│   │       ├── main.ts                ← bootstrap: helmet, throttle, ValidationPipe, CORS
│   │       └── migration-runner.ts    ← ECS one-off migration task entrypoint
│   │
│   ├── api-e2e/                       ← API end-to-end tests (real PostgreSQL + Redis)
│   │
│   ├── portal-api/                    ← NestJS admin portal API  (GraphQL at :3334)
│   │   └── src/
│   │       ├── app/
│   │       │   └── portal-app.module.ts   ← shares same DB; NO separate migrations
│   │       └── modules/
│   │           ├── portal-auth/           ← PortalJwtStrategy ('portal-jwt'), PortalAuthJwtGuard
│   │           └── portal-health/
│   │
│   └── web/                           ← Next.js 16 frontend  (:3000)
│       └── src/
│           ├── app/
│           │   ├── layout.tsx
│           │   ├── page.tsx
│           │   └── providers.tsx      ← ApolloProvider + authLink
│           ├── components/
│           │   ├── todo-list.tsx
│           │   └── ui/                ← Shadcn UI (Button, Input, Card, Checkbox, Badge)
│           ├── graphql/
│           │   ├── generated.ts       ← codegen output (typed hooks)
│           │   ├── auth.operations.ts
│           │   └── todo.operations.ts
│           ├── hooks/
│           │   └── use-auth.ts
│           └── lib/
│               └── apollo-client.ts   ← ApolloClient, InMemoryCache, authLink
│
├── libs/
│   ├── contracts/                     ← shared TypeScript types (api + portal-api + web)
│   └── core/                          ← Joi schema, AppConfig, queue constants,
│                                         RequestPlatformInterceptor, CoreConfigModule
│
├── infra/
│   └── task-definitions/              ← ECS task definitions (api, portal-api, migrator)
│
├── scripts/
│   └── fix-typeorm-deps.cjs           ← ensures single reflect-metadata instance for TypeORM CLI
│
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                     ← lint + unit test + E2E (Postgres + Redis services)
│   │   └── deploy.yml                 ← OIDC → ECR push → migration task → ECS rolling deploy
│   └── PULL_REQUEST_TEMPLATE.md
│
├── codegen.ts                         ← GraphQL Code Generator config
├── commitlint.config.js
├── docker-compose.dev.yml             ← Postgres :5432 · Redis :6379 · Adminer :8080
├── docker-compose.dev.arm.yml         ← Apple Silicon (linux/arm64 images)
├── nx.json
├── package.json
├── tsconfig.base.json
├── tsconfig.typeorm.json              ← TypeORM CLI path aliases (separate from app tsconfig)
└── .env                               ← local env vars (never commit — in .gitignore)
```

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| nvm | latest | `curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh \| bash` |
| Node.js | 20 LTS | `nvm install 20 && nvm alias default 20` |
| Yarn | 1.22.x (Classic) | `npm install -g yarn` |
| Docker Desktop | 24+ with Compose v2 | [docker.com](https://www.docker.com) — verify `docker compose version` |
| Git | 2.x | `brew install git` (macOS) |

**VS Code extensions** (install all for the full AI-assisted dev experience):

```
nrwl.angular-console          Nx Console (project graph, task runner)
esbenp.prettier-vscode        Prettier formatter
dbaeumer.vscode-eslint        ESLint
eamodio.gitlens               Git history + blame inline
kumar-harsh.graphql-for-vscode GraphQL schema highlighting
firsttris.vscode-jest-runner  Run individual Jest tests from the gutter
mikestead.dotenv              .env syntax highlighting
ms-azuretools.vscode-docker   Docker container management
Gruntfuggly.todo-tree         TODO/FIXME tracking in sidebar
anthropic.claude-code         Claude Code AI assistant (if installed)
```

---

## Getting Started

**1. Install dependencies**

```bash
yarn install
```

**2. Create Docker volumes** (first time only)

```bash
docker volume create db_volume
docker volume create redis_volume
```

**3. Start Docker infrastructure**

```bash
yarn docker:dev        # Intel / Linux
yarn docker:dev:arm    # Apple Silicon M1/M2/M3
# Starts: PostgreSQL :5432 · Redis :6379 · Adminer :8080
```

**4. Create your `.env` file**

```bash
cp .env.example .env   # then fill in the required values
```

See the [Environment Variables](#environment-variables) section below for the full reference.

**5. Generate RSA key pairs** (first time only)

```bash
# User API keys (access + refresh)
openssl genrsa -out jwt_private.pem 4096
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
openssl genrsa -out jwt_refresh_private.pem 4096
openssl rsa -in jwt_refresh_private.pem -pubout -out jwt_refresh_public.pem

# Convert each PEM to a single-line string for .env:
awk 'NF {sub(/\r/, ""); printf "%s\\n",$0;}' jwt_private.pem
# Paste the output as JWT_PRIVATE_KEY= in .env (including -----BEGIN/END PRIVATE KEY-----)
```

Generate a separate pair for `ADMIN_JWT_PRIVATE_KEY` / `ADMIN_JWT_PUBLIC_KEY` (portal-api).

**6. Run database migrations**

```bash
yarn api:migration:run
```

**7. (Optional) Seed with sample data**

```bash
yarn api:seed:run
```

**8. Start dev servers**

```bash
# In separate terminals:
yarn api:dev      # → http://localhost:3333  | GraphQL: http://localhost:3333/graphql
yarn web:dev      # → http://localhost:3000
yarn portal:dev   # → http://localhost:3334  | GraphQL: http://localhost:3334/graphql
```

---

## Environment Variables

Create `.env` in the workspace root. All variables are required unless marked optional.

```bash
# ── App ─────────────────────────────────────────────────────────────────────
NODE_ENV=development
PROJECT_PORT=3333
PROJECT_GRAPHQL_PLAYGROUND=true
PROJECT_GRAPHQL_SUBSCRIPTIONS=false
ALLOWED_ORIGINS=                         # production only: comma-separated allowed origins

# ── Database ─────────────────────────────────────────────────────────────────
PROJECT_DB_CONNECTION=postgres
PROJECT_DB_HOST=localhost
PROJECT_DB_PORT=5432
PROJECT_DB_USERNAME=postgres
PROJECT_DB_PASSWORD=postgres
PROJECT_DB_DATABASE=enterprise_todo
PROJECT_DB_DEBUG=false

# ── Database (Test / E2E) ─────────────────────────────────────────────────
PROJECT_DB_DATABASE_TEST=enterprise_todo_test   # E2E test database (separate from main)

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_BULL_HOST=localhost        # Bull queue broker
REDIS_BULL_PORT=6379
REDIS_PUBSUB_HOST=localhost      # GraphQL subscriptions PubSub
REDIS_PUBSUB_PORT=6379

# ── JWT / Auth (RS256) ───────────────────────────────────────────────────────
# Generate: openssl genrsa 4096 | openssl pkcs8 -topk8 -nocrypt
# Then: awk 'NF {sub(/\r/, ""); printf "%s\\n",$0;}' key.pem
# Keep -----BEGIN PRIVATE KEY----- and -----END PUBLIC KEY----- headers
JWT_PRIVATE_KEY=
JWT_PUBLIC_KEY=
JWT_REFRESH_PRIVATE_KEY=
JWT_REFRESH_PUBLIC_KEY=
JWT_EXPIRATION_TIME=1d
JWT_REFRESH_EXPIRATION_TIME=7d

# ── Email (SMTP) ───────────────────────────────────────────────────────────────
# Local dev: use Mailpit (add to docker-compose: port 1025 / UI :8025)
# Production: use AWS SES (SMTP interface)
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_USER=                       # optional in dev (Mailpit accepts unauthenticated)
SMTP_PASS=                       # optional in dev

WEB_URL=http://localhost:3000    # included in password-reset and verify-email links

# ── Two-Factor Auth ───────────────────────────────────────────────────────────
# Dev/test bypass ONLY — code enforces NODE_ENV !== 'production' guard
# Leave empty in staging and production (or the Joi schema will reject it)
TWOFA_BYPASS_PASSWORD=

# ── Media Library (AWS S3 + CloudFront) ───────────────────────────────────────
# Local dev: point at LocalStack or a real dev bucket with restricted CORS
AWS_REGION=ap-southeast-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
S3_BUCKET=enterprise-todo-media-dev
CDN_BASE_URL=https://d1abc.cloudfront.net   # your CloudFront distribution URL

# ── Admin Portal API ──────────────────────────────────────────────────────────
PROJECT_PORTAL_PORT=3334

# Admin JWT (RS256) — SEPARATE key pair from user API — never share
# PortalJwtStrategy lives only in apps/portal-api, never in apps/api
ADMIN_JWT_PRIVATE_KEY=
ADMIN_JWT_PUBLIC_KEY=
ADMIN_JWT_EXPIRATION_TIME=8h
```

---

## Scripts

| Command | What it does |
|---------|-------------|
| `yarn api:dev` | Start user API in watch mode (:3333) |
| `yarn api:build` | Production build of the user API |
| `yarn api:test` | Unit tests for the user API |
| `yarn api:e2e` | End-to-end tests (spins up real Postgres + Redis) |
| `yarn portal:dev` | Start admin portal API in watch mode (:3334) |
| `yarn portal:build` | Production build of the portal API |
| `yarn portal:test` | Unit tests for the portal API |
| `yarn web:dev` | Start Next.js frontend in watch mode (:3000) |
| `yarn codegen` | Generate typed hooks from GraphQL schema via graphql-codegen |
| `yarn format` | Run Prettier across all files |
| `yarn lint` | Lint all projects |
| `yarn lint:fix` | Lint + auto-fix all projects |
| `yarn docker:dev` | Start Postgres · Redis · Adminer (Intel / Linux) |
| `yarn docker:dev:arm` | Start Postgres · Redis · Adminer (Apple Silicon) |
| `yarn docker:stop` | Stop all Docker containers |
| `yarn api:migration:generate <path>` | Generate migration from entity diff (pass full output path: `apps/api/src/migrations/CreateTagTable`) |
| `yarn api:migration:run` | Apply all pending migrations |
| `yarn api:migration:revert` | Revert the last applied migration |
| `yarn api:seed:run` | Truncate + reseed with sample data |
| `yarn dep` | Open Nx project dependency graph in browser |
| `yarn cz` | Commit using Commitizen (conventional commits — enforced by Husky) |

---

## Database

Adminer (web DB UI) is available at `http://localhost:8080` while Docker is running.

| Field | Value |
|-------|-------|
| System | PostgreSQL |
| Server | `postgres` (Docker internal DNS — NOT `localhost`) |
| Username | `postgres` |
| Password | `postgres` |
| Database | `enterprise_todo` |

**Migration rules:**
- `synchronize` is always `false` in all environments — never enable it
- Every schema change goes through a migration file: `generate → review SQL → run → verify in Adminer`
- Never modify a past migration in production — write a new one
- Migration command takes a positional path argument, not `--name`: `yarn api:migration:generate apps/api/src/migrations/CreateTagTable`

---

## Architecture

### Dual-App Monorepo

```
Internet
   ├─ :3333  apps/api         User-facing API   (AuthJwtStrategy      — user RS256 key pair)
   ├─ :3334  apps/portal-api  Admin portal API  (PortalJwtStrategy    — admin RS256 key pair)
   └─ :3000  apps/web         Next.js frontend

libs/core       → Joi schema, typed AppConfig, queue constants, RequestPlatformInterceptor
libs/contracts  → Shared TypeScript types across all three apps
```

`RequestPlatformInterceptor` enforces that a user JWT (stamped `platform: 'user'`) cannot authenticate against the portal API and vice versa — structural enforcement at the interceptor layer before guard logic runs.

### 9-Step CQRS Module Pattern

Every feature module follows this exact sequence:

```
Step 1  Entity        → extends AbstractEntity, columns, relations, @Index on filtered fields
Step 2  Constants     → enums + registerEnumType() (required for GraphQL schema generation)
Step 3  DTOs          → @ObjectType (output), @InputType (mutation), @ArgsType (list query)
Step 4  CQRS Inputs   → FindOne, FindMany, Count, CreateOne, UpdateOne, DeleteOne classes
Step 5  CQRS Handlers → one line each: return this.service.method(args)
Step 6  CQRS Index    → export handler arrays + re-export input classes
Step 7  Service       → extends TypeOrmQueryService<Entity>, business rules, exceptions
Step 8  Resolver      → @UseGuards, @CurrentUser(), dispatch to CommandBus / QueryBus
Step 9  Module        → TypeOrmModule.forFeature([Entity]) + spread handler arrays
        Register      → add to AppModule.imports[] and AppModule entities[] (explicit — no globs)
        Migrate       → generate → review → run → verify
        Test          → service unit tests + handler unit tests + E2E smoke test
```

### Request Lifecycle (user API)

```
GraphQL Request
     │
     ▼
Helmet / ThrottlerGuard     HTTP security headers; rate limit (global, skip health checks)
     │
     ▼
LoggingInterceptor          log request start + end time
     │
     ▼
AuthJwtGuard                verify RS256 JWT signature; reject expired / invalid
     │
     ▼
RequestPlatformInterceptor  reject portal tokens (platform: 'portal') with 403
     │
     ▼
TenantGuard                 extract tenantId from JWT → TenantContext (Scope.REQUEST)
     │
     ▼
ACPermissionGuard           check user.status === ACTIVE + permission slugs
     │
     ▼
ValidationPipe              class-validator on all inputs (whitelist + forbidNonWhitelisted)
     │
     ▼
Resolver method             @CurrentUser() injects typed user; dispatches one command/query
     │
     ▼
Handler                     always one line — calls one service method, nothing else
     │
     ▼
Service  extends TypeOrmQueryService<Entity>   business logic, ownership checks, exceptions
     │
     ▼
@Authorize decorator        nestjs-query merges WHERE tenant_id = $1 at QueryBuilder level
     │
     ▼
PostgreSQL                  tenant isolation guaranteed at the data layer
```

### Key Architectural Rules

- **Handlers are always one-liners.** All business logic lives in the service. If your handler body is more than one line, you're doing the service's job.
- **`CqrsModule.forRoot()`** is called only once, in `AppModule`. Feature modules never import `CqrsModule` directly.
- **Service methods are entity-qualified** — `findOneTodo`, `countTodo` — to avoid name collisions with `TypeOrmQueryService`'s built-in interface methods.
- **`ACPermissionGuard` + `@UseACGuard('MODULE', ['slug'])`** on all protected resolvers. Permission slugs are seeded into `PermissionEntity` rows. Never use a bare `RolesGuard`.
- **`PortalJwtStrategy`** lives exclusively in `apps/portal-api`. Registering it in `apps/api` defeats platform separation and allows portal tokens to authenticate user endpoints.
- **`platform` claim is required** in every JWT payload — `'user'` for the user API, `'portal'` for the portal API. `RequestPlatformInterceptor` rejects mismatches with 403.
- **Resolver never calls service directly** — always dispatches via `CommandBus.execute()` or `QueryBus.execute()`. This makes every operation auditable and replaceable.

---

## Notable Gotchas

**`reflect-metadata` must be `^0.2.2`**

`typeorm` and `nestjs-dev-utilities` bundle their own `reflect-metadata ^0.2.x`. If your root `package.json` has `^0.1.x`, two separate `WeakMap` instances coexist and NestJS's DI metadata becomes invisible after TypeORM initialises. Symptom: `UnknownDependenciesException: Nest can't resolve dependencies of ConfigService`.

Fix: set `"reflect-metadata": "^0.2.2"` in `package.json` and run `yarn install` to force deduplication.

---

**TypeORM entities must be explicitly listed — no glob patterns**

This project builds with Webpack. At runtime everything compiles into a single `main.js` — there are no separate `.entity.js` files on disk for glob patterns to find. `entities: ['**/*.entity{.ts,.js}']` silently finds nothing.

Every entity must be imported and listed explicitly in `AppModule`'s `entities[]`.

---

**All related entities must be registered, even without a feature module**

`TodoEntity` has `@ManyToOne(() => UserEntity)`. Even if no `UserModule` exists yet, `UserEntity` must appear in `AppModule`'s `entities[]`. Omitting it causes `EntityMetadataNotFoundError` at startup.

---

**`graphql` must be pinned to `@16` on Node 20**

`graphql@17` requires Node 22. Installing without a version pin pulls v17 and breaks the build on Node 20. Always: `yarn add graphql@16`.

Same issue with `@graphql-codegen/cli` — pin to `@5`. Version 6 pulls `listr2@10` which also requires Node 22.

---

**TypeORM CLI `migration:generate` takes a positional path, not `--name`**

The `--name` flag was removed in TypeORM 0.3. The correct form is:

```bash
yarn api:migration:generate apps/api/src/migrations/CreateTagTable
# NOT: yarn api:migration:generate --name=create-tag-table
```

---

**Apollo Sandbox: name mutations that return `Boolean`**

Anonymous mutations returning a scalar (`mutation { deleteTodo(id: 1) }`) trigger a spurious "syntax error: invalid number" in Apollo Studio Sandbox. The API is correct — verify with curl. Fix: name the operation:

```graphql
mutation DeleteTodo { deleteTodo(id: 1) }
```

---

**Apollo Client v4: all React APIs moved to `@apollo/client/react`**

Turbopack resolves `@apollo/client` to its core package, which exports no React APIs. Import React APIs from `@apollo/client/react`:

```typescript
// ✅
import { ApolloProvider, useQuery, useMutation } from '@apollo/client/react';
import { ApolloClient, InMemoryCache, gql } from '@apollo/client';

// ❌ — silent undefined at runtime
import { ApolloProvider, useQuery } from '@apollo/client';
```

---

**Tailwind CSS v4: no `tailwind.config.js`, new PostCSS plugin**

This project uses Tailwind v4 (required by shadcn `base-nova` style). Key differences from v3:

```css
/* ✅ Tailwind v4 */
@import "tailwindcss";

/* ❌ Tailwind v3 — do not use */
@tailwind base;
@tailwind components;
@tailwind utilities;
```

```js
// postcss.config.js
// ✅ v4
module.exports = { plugins: { '@tailwindcss/postcss': {} } };

// ❌ v3
module.exports = { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

No `tailwind.config.js` — v4 auto-detects content files.

---

**`@nx/next` uses `dev` target, not `serve`**

`npx nx serve web` fails — the `@nx/next` plugin registers the dev target as `dev`. Use:

```bash
yarn web:dev      # = nx dev web
```

---

**Helmet blocks Apollo Sandbox in development**

`app.use(helmet())` enforces a strict CSP that blocks Apollo Sandbox's inline scripts. The fix — already in `main.ts`:

```typescript
app.use(helmet({
  contentSecurityPolicy: process.env.NODE_ENV === 'production' ? undefined : false,
}));
```

---

**`@SkipThrottle()` on health and internal resolvers**

`ThrottlerGuard` applied globally will rate-limit load balancer health checks in production, causing the ALB to mark the task as unhealthy. `HealthResolver` (and any internal-only resolver) must have `@SkipThrottle()`.

---

**`TWOFA_BYPASS_PASSWORD` is blocked at the code level in production**

The bypass is gated by `process.env.NODE_ENV !== 'production'` in `verifyTwoFactorLogin`. It has no effect in production regardless of the env var value — but for clarity, leave the variable unset in staging and production `.env` files.

---

**`PortalJwtStrategy` in the wrong app**

`PortalJwtStrategy` (named `'portal-jwt'`) belongs exclusively in `apps/portal-api`. Registering it in `apps/api` means a portal-issued token can authenticate user endpoints — defeating the entire dual-auth architecture.

---

## Production Stack (AWS)

Deployed via GitHub Actions CD with OIDC (no long-lived access keys in CI secrets).

```
Route 53
   └─ ALB  (host-based routing)
        ├─ api.yourdomain.com      → ECS Service: enterprise-todo-api
        └─ portal.yourdomain.com  → ECS Service: enterprise-todo-portal-api

ECS Fargate
   ├─ Task: enterprise-todo-api       (port 3333, nestjs user API)
   ├─ Task: enterprise-todo-portal    (port 3334, nestjs admin portal)
   └─ Task: enterprise-todo-migrator  (one-off task — runs BEFORE rolling deploy)

RDS PostgreSQL 15 Multi-AZ
   └─ db.t4g.medium · gp3 · 7-day backups · deletion protection

ElastiCache Redis 7.x
   └─ cache.t4g.small · TLS in-transit + at-rest

ECR
   ├─ enterprise-todo-api       (lifecycle: keep last 20 images)
   └─ enterprise-todo-portal    (lifecycle: keep last 20 images)

AWS Secrets Manager
   └─ All secrets: RSA key pairs, DB password, SMTP credentials, AWS API keys
      (injected as valueFrom into ECS task definitions — never plaintext env vars)
```

**Deployment flow (zero-downtime):**

```
git push → main
   └─ GitHub Actions: build → push to ECR → run migrator task → ECS rolling deploy
```

The migrator task runs the pending migrations inside the VPC, against the real RDS instance, before any new API pod starts serving traffic. This prevents race conditions where the new code starts before the schema is ready.

---

## AI-Assisted Development

This project ships with a full Claude Code configuration in `.claude/`:

```
.claude/
├── CLAUDE.md           ← project rules (stack, commands, architecture, gotchas)
├── rules/
│   ├── architecture.md ← CQRS, module boundaries, handler one-liner rule
│   ├── security.md     ← platform claim, no PortalJwtStrategy in api, ownership scoping
│   ├── performance.md  ← DataLoader, N+1, @Index on filtered columns
│   └── migrations.md   ← no synchronize, no glob entities, no --name flag
├── agents/
│   ├── backend-specialist.md    ← CQRS modules, services, resolvers
│   ├── migration-specialist.md  ← schema changes, pgvector, tenant ordering
│   ├── test-writer.md           ← unit + E2E tests, mock patterns
│   └── frontend-specialist.md   ← Next.js/Tailwind/Apollo
└── memory/
    └── MEMORY.md        ← personal dev context (gitignored — stays local)
```

**Three-layer knowledge system:**

| Layer | Tool | Purpose |
|-------|------|---------|
| Persistent memory | `~/.claude/projects/…/memory/` | Personal dev context across sessions |
| Codebase graph | `graphify` | Semantic relationships, architecture overview |
| Call graph | `gitnexus` | Symbol-level: callers, callees, blast radius |

See Parts 21–24 of the tutorial series for the full AI-assisted development workflow.

---

## License

MIT
