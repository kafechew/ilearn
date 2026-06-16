---
author: Kai
pubDatetime: 2026-05-02T09:00:00+08:00
title: Environment Setup & Nx Workspace
featured: false
draft: false
slug: 6102-env-setup-nx-workspace
tags:
  - deeptech
  - meteorjs
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/02-environment-setup-nx-workspace.png"
description: By the end of this part, you will have a running (empty) enterprise-todo backend accessible at localhost.
---

## What This Part Covers

- Installing every system dependency (Node, Yarn, Docker, VS Code)
- Creating the Nx monorepo workspace from scratch
- Adding NestJS backend + Next.js frontend + shared library
- Spinning up PostgreSQL, Redis, and Adminer via Docker
- Writing the environment file
- Booting the server and verifying it works

By the end of this part, you will have a running (empty) enterprise-todo backend accessible at `http://localhost:3333/graphql`.

---

## Meteor Equivalent

In Meteor you ran one command:

```bash
meteor create --blaze my-todo-app
cd my-todo-app
meteor
# → App running at http://localhost:3000
```

The framework created the directory structure, started MongoDB, and served both client and server in one process.

In the enterprise world, you build this infrastructure yourself — explicitly. It takes longer the first time. After that, every project starts the same way and every team member knows exactly what is running and why.

---

## 1. Machine Prerequisites

### 1.1 Node.js via nvm

Never install Node directly. Use `nvm` (Node Version Manager) — it lets you switch Node versions per project without conflicts.

```bash
# Install nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash

# Reload your shell (or open a new terminal)
source ~/.zshrc   # or ~/.bashrc on Linux

# Install and use Node 20 (the project's LTS version)
nvm install 20
nvm use 20
nvm alias default 20

# Verify
node -v   # v20.x.x
npm -v    # 10.x.x
```

> **Why Node 20 specifically?** NestJS 11 requires Node 18+. Node 22 is the latest but has occasional compatibility issues with some packages. Node 20 is the LTS version — stable, widely tested, and officially supported by NestJS.

### 1.2 Yarn 1.x

This project uses Yarn Classic (v1), not Yarn 2/3/4. Do not upgrade.

```bash
npm install -g yarn
yarn -v   # 1.22.x
```

> **Why Yarn over npm?** Yarn 1 has a deterministic lockfile (`yarn.lock`) and faster installs via cache. Nx also has first-class Yarn support for workspace management. The "classic" version is deliberately chosen for stability — Yarn 2+ changed the resolution model significantly.

### 1.3 Docker Desktop

Download from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/).

After installation:

```bash
docker -v               # Docker version 24+
docker compose version  # Docker Compose v2.x
```

> **What Docker gives you:** Instead of installing PostgreSQL and Redis directly on your machine (which conflicts between projects), Docker runs each service in an isolated container. You can start, stop, and delete them without touching your OS. Every team member runs identical infrastructure.

### 1.4 Git

macOS ships with an old Git. Upgrade:

```bash
brew install git
git -v   # git version 2.x
```

---

## 2. VS Code Setup

### 2.1 Install VS Code

Download from [code.visualstudio.com](https://code.visualstudio.com/).

### 2.2 Install Extensions

> **`zsh: command not found: code`?** The `code` command isn't in your PATH yet. Install it from VS Code:
>
> 1. Open VS Code
> 2. Press **Cmd+Shift+P** and run: `Shell Command: Install 'code' command in PATH`
> 3. Restart your terminal
>
> Then retry:
>
> `code --install-extension nrwl.angular-console`
>
> Alternatively, install the extension directly in VS Code via **Extensions** (Cmd+Shift+X) → search "Angular Console" → Install.

Run these commands one by one (or paste all at once):

```bash
code --install-extension nrwl.angular-console        # Nx Console — visual project graph + task runner
code --install-extension esbenp.prettier-vscode       # Auto-format on save
code --install-extension dbaeumer.vscode-eslint       # Inline lint errors
code --install-extension eamodio.gitlens              # Git blame, history, CodeLens
code --install-extension kumar-harsh.graphql-for-vscode  # GraphQL schema syntax + autocomplete
code --install-extension firsttris.vscode-jest-runner # Run single Jest test from editor
code --install-extension mikestead.dotenv             # .env syntax highlighting
code --install-extension ms-azuretools.vscode-docker  # Container management UI
code --install-extension Gruntfuggly.todo-tree        # Shows TODO/FIXME in sidebar
```

### 2.3 VS Code User Settings

Open `Cmd+Shift+P` → "Open User Settings (JSON)" and add:

```json
{
  "editor.formatOnSave": true,
  "editor.defaultFormatter": "esbenp.prettier-vscode",
  "editor.codeActionsOnSave": {
    "source.fixAll.eslint": "explicit"
  },
  "eslint.validate": ["javascript", "typescript"],
  "typescript.tsdk": "node_modules/typescript/lib"
}
```

**What each setting does:**

- `formatOnSave` — runs Prettier every time you save. Eliminates all whitespace/format debates.
- `defaultFormatter` — ensures VS Code uses Prettier, not its own formatter.
- `source.fixAll.eslint` — auto-fixes ESLint errors on save (unused imports, sorting).
- `typescript.tsdk` — uses the project's TypeScript version, not VS Code's bundled one.

---

## 3. Create the Nx Workspace

This is the enterprise equivalent of `meteor create`. One command creates the monorepo scaffold:

```bash
cd dev # any folder you prefer to host your app
npx create-nx-workspace@latest enterprise-todo --preset=apps
```

When prompted:

- **CI/CD pipeline?** → Skip (we configure this in Part 12)
- **Enable Nx Cloud?** → No (free tier but not needed for learning)

```bash
cd enterprise-todo
```

Your directory now looks like:

```
enterprise-todo/
├── apps/          ← your applications live here
├── libs/          ← shared libraries live here
├── nx.json        ← Nx configuration
├── package.json   ← root package.json (all deps managed here)
└── tsconfig.base.json ← shared TypeScript config
```

> **Meteor analogy:** Meteor has one directory for everything. Nx separates apps (`apps/`) from shared code (`libs/`). The `apps/` directory is where `apps/api` (your NestJS server) and `apps/web` (your Next.js frontend) will live.

### 3.1 Add Framework Plugins

Install the Nx plugins for NestJS, Next.js, and plain JS libraries:

```bash
yarn add --dev @nx/nest @nx/next @nx/js
```

These plugins give you generators (code scaffolding commands) that know how to create NestJS apps, Next.js apps, and shared libraries inside your monorepo.

### 3.2 Generate the NestJS Backend

```bash
npx nx g @nx/nest:app apps/api
```

When prompted (need to arrow up, not default):

- **linter?** → `eslint`
- **Port?** → `3333`
- **E2E test runner?** → `jest`

This creates `apps/api/` with a minimal NestJS app. Check what was created:

```
apps/api/
├── src/
│   ├── app/
│   │   ├── app.module.ts      ← root NestJS module
│   │   └── app.controller.ts  ← default HTTP controller (we'll replace this)
│   └── main.ts                ← entry point, bootstraps the app
├── project.json               ← Nx target definitions (build, serve, test, lint)
└── tsconfig.app.json          ← TypeScript config for this app
```

> **Meteor analogy:** `apps/api/src/main.ts` is your `server/main.js`. `app.module.ts` is the root of everything the server knows about — equivalent to all your `server/` imports combined.

### 3.3 Generate the Next.js Frontend

```bash
npx nx g @nx/next:app apps/web --src=true --appDir=true --style=tailwind
```

When prompted:

- **linter?** → `eslint`
- **unit test runner?** → `jest` (we use Jest for unit tests)
- **E2E test runner?** → `playwright` or `none`

This creates `apps/web/` with a Next.js 16 App Router app pre-configured with Tailwind CSS.

> **Meteor analogy:** `apps/web/` is your `client/` directory. But now it is a completely separate application — it communicates with `apps/api` only through HTTP, not through shared memory.

### 3.4 Generate the Shared Contracts Library

```bash
npx nx g @nx/js:lib libs/contracts --bundler=tsc
```

- **linter?** → `eslint`
- **unit test runner?** → `jest`

This creates a shared TypeScript library. Both `apps/api` and `apps/web` can import from it.

```
libs/contracts/
└── src/
    ├── index.ts         ← exports everything
    └── lib/
        └── contracts.ts ← your shared types
```

> **Meteor analogy:** In Meteor you put isomorphic code in `imports/` and both client and server could import it. In the enterprise monorepo, `libs/contracts` is that shared space — but it exports _only what you explicitly export_, and only TypeScript types (no server code on the client, no client code on the server).

---

## 4. Install Backend Dependencies

From the workspace root:

```bash
yarn add @nestjs/graphql @nestjs/apollo graphql@16 @apollo/server @as-integrations/express5 express
yarn add @nestjs/typeorm typeorm pg
yarn add @nestjs/cqrs nestjs-typed-cqrs nestjs-dev-utilities
yarn add @ptc-org/nestjs-query-graphql @ptc-org/nestjs-query-typeorm @ptc-org/nestjs-query-core
yarn add @nestjs/config
yarn add @nestjs/passport passport passport-jwt
yarn add @nestjs/jwt
yarn add class-validator class-transformer
yarn add bcrypt
yarn add --dev @types/pg @types/passport-jwt @types/bcrypt
```

> **`reflect-metadata` gotcha:** After installing, check that `reflect-metadata` is `^0.2.2` in your root `package.json`. `typeorm` and `nestjs-dev-utilities` both bundle `^0.2.x` — if the root dep is `^0.1.x` (the Nx default), two separate `WeakMap` instances coexist and NestJS DI metadata breaks at runtime with `UnknownDependenciesException: Nest can't resolve dependencies of ConfigService`. Fix: set `"reflect-metadata": "^0.2.2"` in `package.json` and re-run `yarn install`.

**What each package does:**

| Package                              | Purpose                                               | Meteor equivalent                             |
| ------------------------------------ | ----------------------------------------------------- | --------------------------------------------- |
| `@nestjs/graphql` + `@nestjs/apollo` | GraphQL schema + Apollo server integration            | DDP transport layer                           |
| `graphql`                            | Core GraphQL library                                  | (no equivalent — Meteor used DDP not GraphQL) |
| `@nestjs/typeorm` + `typeorm`        | ORM for database operations                           | `mongo` driver integration                    |
| `pg`                                 | PostgreSQL driver                                     | (no equivalent — Meteor used MongoDB)         |
| `@nestjs/cqrs`                       | Command/Query bus infrastructure                      | Meteor Methods mechanism                      |
| `nestjs-typed-cqrs`                  | Type-safe return types on CQRS bus                    | (no equivalent — Meteor was untyped)          |
| `nestjs-dev-utilities`               | `AbstractEntity`, `AbstractDto` base classes          | (convention enforcer)                         |
| `@ptc-org/nestjs-query-*`            | Auto-generated GraphQL filtering, sorting, pagination | Minimongo's query capabilities                |
| `@nestjs/config`                     | Environment variable management                       | `Meteor.settings`                             |
| `@nestjs/passport` + `passport-jwt`  | JWT authentication strategy                           | `accounts-base`                               |
| `@nestjs/jwt`                        | JWT sign/verify                                       | (handled by accounts package in Meteor)       |
| `class-validator`                    | Decorator-based validation                            | `check()` from `meteor/check`                 |
| `class-transformer`                  | Transform plain objects to class instances            | (no direct equivalent)                        |
| `bcrypt`                             | Password hashing                                      | `accounts-password`'s internal hashing        |

---

## 5. Docker Infrastructure

Instead of Meteor's embedded MongoDB, you run your own services in Docker containers.

### 5.1 Create Docker Volumes (once only)

Open Docker Desktop.

```bash
docker volume create db_volume
docker volume create redis_volume
```

Volumes are persistent storage on your machine. Without them, restarting a container wipes all data.

### 5.2 Create the Docker Compose File

Create `docker-compose.dev.yml` in the workspace root:

```yaml
version: "3.8"

services:
  postgres:
    image: postgres:15-alpine
    container_name: enterprise_todo_postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: enterprise_todo
    ports:
      - "5432:5432"
    volumes:
      - db_volume:/var/lib/postgresql/data
    networks:
      - app-network

  redis:
    image: redis:alpine
    container_name: enterprise_todo_redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis_volume:/data
    networks:
      - app-network

  adminer:
    image: adminer
    container_name: enterprise_todo_adminer
    restart: unless-stopped
    ports:
      - "8080:8080"
    networks:
      - app-network

volumes:
  db_volume:
    external: true
  redis_volume:
    external: true

networks:
  app-network:
    driver: bridge
```

**What each container does:**

| Container  | What it runs                   | Port | Meteor equivalent               |
| ---------- | ------------------------------ | ---- | ------------------------------- |
| `postgres` | PostgreSQL database            | 5432 | Meteor's embedded MongoDB       |
| `redis`    | Redis cache + queue broker     | 6379 | (no equivalent in basic Meteor) |
| `adminer`  | Web UI to inspect the database | 8080 | Mongo Compass equivalent        |

### 5.3 Add a Convenience Script

In `package.json` at the workspace root, add:

```json
{
  "scripts": {
    "docker:dev": "docker compose -f docker-compose.dev.yml up -d",
    "docker:stop": "docker compose -f docker-compose.dev.yml down"
  }
}
```

Start the containers:

```bash
yarn docker:dev        # Intel Mac / Linux
yarn docker:dev:arm    # Apple Silicon (M1/M2/M3)
```

> **Apple Silicon:** The standard `postgres:15-alpine` image runs via Rosetta 2 emulation on M-series Macs. Create a separate `docker-compose.dev.arm.yml` using `--platform linux/arm64` images if you experience slowness or crashes.

Wait ~10 seconds, then verify all three are running:

```bash
docker ps
# Should show: enterprise_todo_postgres, enterprise_todo_redis, enterprise_todo_adminer
```

### 5.4 Verify Adminer

Open `http://localhost:8080` in your browser and log in:

| Field    | Value                                                   |
| -------- | ------------------------------------------------------- |
| System   | PostgreSQL                                              |
| Server   | `postgres` (the container name — Docker's internal DNS) |
| Username | `postgres`                                              |
| Password | `postgres`                                              |
| Database | `enterprise_todo`                                       |

You should see an empty database. This is where your tables will appear after running migrations (Part 04).

> **Adminer is your Mongo Compass.** Every table, row, and relationship in your PostgreSQL database is visible here. You will use it constantly during development to verify that migrations ran correctly and data was saved as expected.

---

## 6. Environment Variables

Create `.env` at the workspace root:

```bash
# ── App ─────────────────────────────────────────────────────
NODE_ENV=development
PROJECT_PORT=3333
PROJECT_GRAPHQL_PLAYGROUND=true
PROJECT_GRAPHQL_SUBSCRIPTIONS=false

# ── Database ─────────────────────────────────────────────────
PROJECT_DB_CONNECTION=postgres
PROJECT_DB_HOST=localhost
PROJECT_DB_PORT=5432
PROJECT_DB_USERNAME=postgres
PROJECT_DB_PASSWORD=postgres
PROJECT_DB_DATABASE=enterprise_todo
PROJECT_DB_DEBUG=false

# ── Database (Test) ───────────────────────────────────────────
PROJECT_DB_DATABASE_TEST=enterprise_todo_test

# ── Redis ─────────────────────────────────────────────────────
REDIS_BULL_HOST=localhost
REDIS_BULL_PORT=6379

# ── JWT (RS256 — sample keys for development only) ────────────
# In production: generate real keys and store in AWS Secrets Manager
JWT_EXPIRATION_TIME=1d
JWT_REFRESH_EXPIRATION_TIME=7d

# Paste your RSA keys here — see Part 07 for key generation
JWT_PRIVATE_KEY=
JWT_PUBLIC_KEY=
JWT_REFRESH_PRIVATE_KEY=
JWT_REFRESH_PUBLIC_KEY=
```

Add `.env` to your `.gitignore` (it should already be there from Nx):

```bash
echo ".env" >> .gitignore
echo ".env.local" >> .gitignore
```

> **Meteor analogy:** In Meteor you used `Meteor.settings` (loaded from `settings.json`) for server config. In the enterprise stack, environment variables are the standard — they work across Docker, ECS, Kubernetes, and local development without code changes.

> **Security rule:** Never commit `.env` to Git. Production values (especially JWT private keys and DB passwords) must go into AWS Secrets Manager or Tencent SSM — never in `.env` files that get deployed.

---

## 7. Configure the NestJS App Module

Replace the default `apps/api/src/app/app.module.ts`:

```typescript
import { Module } from "@nestjs/common";
import { ConfigModule, ConfigService } from "@nestjs/config";
import { TypeOrmModule } from "@nestjs/typeorm";
import { GraphQLModule } from "@nestjs/graphql";
import { ApolloDriver, ApolloDriverConfig } from "@nestjs/apollo";
import { CqrsModule } from "@nestjs/cqrs";
import { AppResolver } from "./app.resolver";

@Module({
  imports: [
    // Load .env into process.env — available everywhere via ConfigService
    ConfigModule.forRoot({
      isGlobal: true, // no need to import ConfigModule in every feature module
      envFilePath: ".env",
    }),

    // TypeORM: connect to PostgreSQL
    TypeOrmModule.forRootAsync({
      inject: [ConfigService],
      useFactory: (config: ConfigService) => ({
        type: "postgres",
        host: config.get("PROJECT_DB_HOST"),
        port: config.get<number>("PROJECT_DB_PORT"),
        username: config.get("PROJECT_DB_USERNAME"),
        password: config.get("PROJECT_DB_PASSWORD"),
        database: config.get("PROJECT_DB_DATABASE"),
        entities: [],
        // ⚠️ Never use a glob pattern here (e.g. "**/*.entity{.ts,.js}").
        // This project builds with Webpack — at runtime everything is bundled into
        // main.js, so glob discovery finds nothing. Every entity must be explicitly
        // imported and listed here. See Part 04 when you add the first entity.
        synchronize: false, // NEVER true in production — use migrations
        logging: config.get("PROJECT_DB_DEBUG") === "true",
      }),
    }),

    // GraphQL: code-first schema generation via Apollo
    GraphQLModule.forRootAsync<ApolloDriverConfig>({
      driver: ApolloDriver,
      inject: [ConfigService],
      useFactory: (config: ConfigService) => ({
        autoSchemaFile: true, // generate schema.gql automatically from decorators
        playground: config.get("PROJECT_GRAPHQL_PLAYGROUND") === "true",
        context: ({ req }) => ({ req }), // pass request context (needed for guards)
      }),
    }),

    // CQRS: registers CommandBus, QueryBus, EventBus globally
    CqrsModule.forRoot(),
  ],
  providers: [AppResolver],
})
export class AppModule {}
```

Add the `apps/api/src/app/app.resolver.ts`:

```typescript
import { Query, Resolver } from "@nestjs/graphql";

@Resolver()
export class AppResolver {
  @Query(() => String)
  health(): string {
    return "ok";
  }
}
```

**What each module does:**

| Module                       | Purpose                                                                           |
| ---------------------------- | --------------------------------------------------------------------------------- |
| `ConfigModule`               | Reads `.env` into `process.env`, provides `ConfigService` for typed access        |
| `TypeOrmModule.forRootAsync` | Connects to PostgreSQL, registers all entities, manages connection pool           |
| `GraphQLModule`              | Starts Apollo Server, auto-generates GraphQL schema from your decorators          |
| `CqrsModule.forRoot()`       | Makes `CommandBus`, `QueryBus`, and `EventBus` available for injection everywhere |

### 7.1 Update main.ts

Replace `apps/api/src/main.ts`:

```typescript
import { NestFactory } from "@nestjs/core";
import { ValidationPipe } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { AppModule } from "./app/app.module";

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  const config = app.get(ConfigService);

  // Global validation pipe — runs class-validator on every input automatically
  // forbidNonWhitelisted: reject unknown fields (prevents mass-assignment attacks)
  // whitelist: strip unknown fields before they reach handlers
  // transform: convert plain JSON objects to typed DTO class instances
  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      forbidNonWhitelisted: true,
      transform: true,
    })
  );

  // CORS — allow all origins in dev, restrict in production
  app.enableCors({
    origin:
      config.get("NODE_ENV") === "development"
        ? "*"
        : process.env.ALLOWED_ORIGINS,
  });

  const port = config.get<number>("PROJECT_PORT") ?? 3333;
  await app.listen(port);

  console.log(`🚀 API running at http://localhost:${port}`);
  console.log(`📊 GraphQL Playground: http://localhost:${port}/graphql`);
}

bootstrap();
```

> **Meteor analogy:** In Meteor there was no explicit bootstrap — the framework handled startup. `main.ts` is where you explicitly configure every global behaviour of your server before it starts accepting requests.

---

## 8. Add Nx Scripts

In `package.json` at the workspace root:

```json
{
  "scripts": {
    "api:dev": "nx serve api",
    "api:build": "nx build api",
    "api:test": "nx test api",
    "api:e2e": "nx e2e api-e2e",
    "web:dev": "nx dev web",
    "format": "prettier --write \"**/*.{ts,tsx,js,jsx,json,md}\"",
    "docker:dev": "docker compose -f docker-compose.dev.yml up -d",
    "docker:dev:arm": "docker compose -f docker-compose.dev.arm.yml up -d",
    "docker:stop": "docker compose -f docker-compose.dev.yml down",
    "lint": "nx run-many --target=lint --all",
    "lint:fix": "nx run-many --target=lint --all --fix",
    "dep": "nx graph"
  }
}
```

> **`@nx/next` uses `dev`, not `serve`:** The Next.js Nx plugin registers `devTargetName: "dev"` (not `serve`). Running `nx serve web` fails. Always use `yarn web:dev` or `nx dev web` for the frontend.

---

## 9. Boot and Verify

Make sure Docker containers are running:

```bash
yarn docker:dev
docker ps  # should show postgres, redis, adminer
```

Start the NestJS dev server:

```bash
yarn api:dev
```

You should see:

```
🚀 API running at http://localhost:3333
📊 GraphQL Playground: http://localhost:3333/graphql
```

Open `http://localhost:3333/graphql`. You will see the GraphQL Playground — an interactive query editor. It exposes a single `health` query from `AppResolver` (a placeholder so the schema is valid). Real queries and mutations will be added in later parts.

> **Meteor analogy:** This is your `meteor` command equivalent — but now you know exactly what is running and why. PostgreSQL is handling data. Redis is ready for queues. The NestJS app is serving GraphQL. The Next.js frontend will be added in Part 06.

---

## 10. Nx Workspace Commands Reference

```bash
# View the project dependency graph in browser
yarn dep
# or: npx nx graph

# Run the API dev server
yarn api:dev

# Run tests for API
yarn api:test

# Run lint on all projects
yarn lint

# See all available targets for the API app
npx nx show project api

# Check what projects are affected by uncommitted changes
npx nx affected:graph

# Clear Nx cache (if builds behave strangely)
npx nx reset
```

---

## Summary

You have set up:

- Node 20 (via nvm), Yarn 1.x, Docker Desktop, VS Code with all extensions
- An Nx monorepo with `apps/api` (NestJS), `apps/web` (Next.js), and `libs/contracts` (shared types)
- PostgreSQL + Redis + Adminer running in Docker
- `.env` with all required variables
- `AppModule` with ConfigModule, TypeORM, GraphQL, and CqrsModule wired up
- `main.ts` with global `ValidationPipe` configured
- The API running at `http://localhost:3333/graphql`

| Meteor                    | What you just built                         |
| ------------------------- | ------------------------------------------- |
| `meteor create`           | Nx workspace with three separate projects   |
| Embedded MongoDB          | PostgreSQL in Docker                        |
| `meteor` (single process) | NestJS at :3333 (will add Next.js at :4200) |
| No configuration          | `.env` + `ConfigModule` + `ValidationPipe`  |
