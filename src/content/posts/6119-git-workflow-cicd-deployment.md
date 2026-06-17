---
author: Kai
pubDatetime: 2026-05-19T09:00:00+08:00
title: Git Commit Standards & CI/CD Pipeline
featured: false
draft: false
slug: 6119-git-workflow-cicd-deployment
tags:
  - deeptech
  - meteorjs
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/19-git-workflow-cicd-deployment.png"
description: Set up Commitizen with correct selective staging, Husky pre-commit hooks, branch strategy, GitHub branch protection rules, Docker multi-stage build, GitHub Actions CI/CD, and production migration patterns on AWS ECS Fargate.

---

## What This Part Covers

With all features built (Parts 1–18), Part 19 covers the professional development workflow that keeps the codebase maintainable at team scale. These practices apply from your very first commit, but they matter most when you have a full-featured backend and a team shipping to production.

- Conventional commits with Commitizen — and the staging mistake that bites everyone
- Husky pre-commit and commit-msg hooks
- Branch strategy (feature → main, squash merge)
- GitHub branch protection rules
- Dockerfile (multi-stage build)
- Docker Compose for local development
- GitHub Actions CI pipeline (lint, test, E2E)
- Deployment to AWS ECS Fargate
- Production database migrations via one-off ECS task
- Environment secrets: AWS Secrets Manager pattern

---

## Meteor Equivalent

Meteor's deployment story was Galaxy — a proprietary PaaS. It handled containerization but limited control. Here you own the full pipeline.

| Concern | Meteor/Galaxy | Enterprise NestJS |
|---------|--------------|-------------------|
| Commit message format | Ad hoc | Conventional commits (auto-changelog) |
| Build | `meteor deploy` | Docker multi-stage build |
| Hosting | Galaxy | AWS ECS Fargate / Tencent TKE |
| Migrations | `aldeed:migrations` runs on startup | One-off ECS task BEFORE rolling deploy |
| Secrets | Meteor settings / env vars | AWS Secrets Manager (never in code) |
| CI | Often manual | GitHub Actions on every push |

---

## 1. Conventional Commits + Commitizen

> **Part 02** covers workspace creation, initial Commitizen setup, and the VS Code Source Control workflow. This section assumes that setup is complete and goes deeper on automation (Husky hooks), branch protection, and CI/CD. ← [Environment Setup & Nx Workspace](/posts/6102-env-setup-nx-workspace)

### Why Conventional Commits

A consistent commit message format enables:
- `CHANGELOG.md` auto-generation
- Automatic semantic versioning
- Filtered `git log` for releases

Format:
```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `ci`

Examples:
```
feat(todo): add priority field to Todo entity
fix(auth): prevent timing attack on signIn
test(tag): add E2E tests for create and delete
chore(deps): upgrade @nestjs/graphql to 13.1.0
```

### Install Commitizen

```bash
yarn add -D commitizen cz-conventional-changelog
```

```json
// package.json
{
  "scripts": {
    "cz": "cz"
  },
  "config": {
    "commitizen": {
      "path": "./node_modules/cz-conventional-changelog"
    }
  }
}
```

### The Correct Commit Workflow: Stage → Verify → cz

`yarn cz` formats the commit message. It does not decide what to stage. Staging is your responsibility — and it's where the most common mistakes happen.

**Never do this:**
```bash
git add .     # stages everything: .env, debug logs, half-finished files, unrelated changes
yarn cz
```

**Do this instead:**
```bash
# Stage by module — name exactly what you changed
git add apps/api/src/modules/product/
git add apps/api/src/migrations/*product*
git add apps/api/src/app/app.module.ts

# Verify what will actually be in the commit
git diff --staged

# Only then open the commit prompt
yarn cz
```

Why this matters:
- `git add .` will stage `.env` if you ever forget to `.gitignore` it — once pushed, a secret is compromised
- Unrelated changes in the same commit make PRs harder to review, revert, and bisect
- The commit message should accurately describe the staged diff — if you staged 6 modules, no single message does that

Internalize: **stage → verify → cz**. The `git add .` shortcut is fine for personal scripts and throwaway projects. Not here.

### VS Code Source Control: The Right Visual Tool

`yarn cz` runs in the terminal. It asks the core Git engine whether the staging index has any files. Standalone GUIs (like GitHub Desktop) hold their checkmarks in internal memory and only run `git add` a millisecond before their own commit button — so the terminal always sees an empty index.

VS Code's built-in Source Control writes to the real index on every click. Use it instead:

| Action | Mac | Windows/Linux |
|---|---|---|
| Open Source Control tab | `Cmd+Shift+G` | `Ctrl+Shift+G` |
| Toggle integrated terminal | `Cmd+\`` | `Ctrl+\`` |
| Stage specific lines only | Highlight in diff → right-click → **Stage Selected Ranges** | same |

**Stage Selected Ranges** is the practical superpower here. If a file has both the bug fix you want to commit and a debug log you don't, highlight only the fix lines in the diff editor and stage exactly those. Cleaner commits, no `git stash` gymnastics.

---

## 2. Husky Hooks

Husky runs scripts before git events. Two hooks catch problems before they reach the remote:

1. **pre-commit**: lint staged files (runs first)
2. **commit-msg**: enforce conventional commit format (runs after pre-commit passes)

If lint fails, the commit-msg check never runs. Fix lint errors before worrying about the message format.

```bash
yarn add -D husky lint-staged @commitlint/cli @commitlint/config-conventional
npx husky init
```

### pre-commit hook

```bash
# .husky/pre-commit
#!/usr/bin/env sh
. "$(dirname -- "$0")/_/husky.sh"

npx lint-staged
```

```json
// package.json
{
  "lint-staged": {
    "apps/**/*.ts": ["eslint --fix", "git add"],
    "libs/**/*.ts": ["eslint --fix", "git add"]
  }
}
```

### commit-msg hook

```bash
# .husky/commit-msg
#!/usr/bin/env sh
. "$(dirname -- "$0")/_/husky.sh"

npx --no -- commitlint --edit "$1"
```

```javascript
// commitlint.config.js
module.exports = { extends: ['@commitlint/config-conventional'] };
```

A message like `"fixed stuff"` is rejected at the commit-msg stage:
```
✖ subject may not be empty [subject-empty]
✖ type may not be empty [type-empty]
✖ found 1 problems, 0 warnings
```

---

## 3. Branch Strategy

```
main             ──────────────●──────────────●──────────────→
                               ↑ squash       ↑ squash
feature/add-tag  ──●──●──●────╯              |
                                             |
feature/auth-2fa          ──●──●──●──●──────╯
```

Rules:
- `main` is always deployable
- Feature branches: `feature/<ticket-or-description>`
- Bugfix branches: `fix/<description>`
- PRs squash-merged to main — one commit per feature in history
- No direct pushes to main (enforced via branch protection — see §4)

### PR Template (add to `.github/PULL_REQUEST_TEMPLATE.md`)

```markdown
## Summary
- What was added/changed
- Why (link to ticket)

## Migration
- Tables added/changed:
- Run + revert both tested locally: yes / no

## Testing
- Unit: (test file names + count)
- E2E: (test file + operations covered)

## Checklist
- [ ] Migration generated and reviewed (SQL reviewed, not just generated)
- [ ] `migration:run` tested locally
- [ ] `migration:revert` tested locally
- [ ] Unit tests added/updated
- [ ] E2E tests pass locally (`yarn api:e2e`)
- [ ] No `synchronize: true` left in TypeORM config
- [ ] No `console.log` left in production code
- [ ] `@UseGuards(AuthJwtGuard)` on all new mutations/queries that need auth
- [ ] `tenantId` FK present on any new domain entity
- [ ] impact analysis run for any symbol changes (`gitnexus impact`)
```

---

## 4. GitHub Branch Protection Rules

Set these up once per repository. They enforce the branch strategy at the platform level — no individual can bypass them, including admins, unless the rules are explicitly disabled.

```
GitHub repo → Settings → Branches → Add branch ruleset

Branch name pattern: main
```

```
[✅] Require a pull request before merging
  [✅] Require approvals: 1
  [✅] Dismiss stale pull request approvals when new commits are pushed

[✅] Require status checks to pass before merging
  [✅] Require branches to be up to date before merging
  Status checks: lint, unit-test, e2e-test

[✅] Require conversation resolution before merging
[✅] Delete head branches automatically
[✅] Do not allow bypassing the above settings
```

The last rule is the important one. Without it, the repo owner can force-push over everything. If you ever need to hotfix directly on main, temporarily disable it, apply the fix, then re-enable it immediately. Treating that process as the rare exception keeps the protection meaningful.

---

## 5. Dockerfile — Multi-Stage Build

A multi-stage build keeps the final image small — no devDependencies, no TypeScript compiler.

```dockerfile
# Dockerfile
# ── Stage 1: Build ─────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile

COPY . .
RUN yarn nx build api --prod

# ── Stage 2: Production deps only ─────────────────────────────
FROM node:20-alpine AS deps-prod
WORKDIR /app

COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile --production

# ── Stage 3: Runtime ───────────────────────────────────────────
FROM node:20-alpine AS runtime
WORKDIR /app

RUN addgroup -S app && adduser -S app -G app

COPY --from=deps-prod /app/node_modules ./node_modules
COPY --from=builder /app/dist/apps/api ./dist

USER app

EXPOSE 3000
CMD ["node", "dist/main.js"]
```

Build and test locally:

```bash
docker build -t enterprise-todo-api .
docker run -p 3000:3000 --env-file .env enterprise-todo-api
```

---

## 6. Local Docker Infrastructure

> **`docker-compose.dev.yml` is defined in Part 02 §5.** That file covers PostgreSQL, Redis, and Adminer with named volumes and convenience scripts (`yarn docker:dev`). ← [Environment Setup & Nx Workspace](/posts/6102-env-setup-nx-workspace)

For CI, the services are declared inline in the GitHub Actions workflow (see §7 below) — no compose file is used in CI runners.

---

## 7. GitHub Actions CI Pipeline

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

env:
  NODE_VERSION: '20'

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: 'yarn'
      - run: yarn install --frozen-lockfile
      - run: yarn lint

  unit-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: 'yarn'
      - run: yarn install --frozen-lockfile
      - run: yarn api:test --coverage
      - uses: actions/upload-artifact@v4
        with:
          name: coverage-report
          path: coverage/

  e2e-test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: enterprise_todo_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 5s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 5

    env:
      NODE_ENV: test
      DB_HOST: localhost
      DB_PORT: 5432
      DB_USERNAME: test
      DB_PASSWORD: test
      DB_DATABASE: enterprise_todo_test
      REDIS_HOST: localhost
      REDIS_PORT: 6379
      JWT_PRIVATE_KEY: ${{ secrets.JWT_PRIVATE_KEY_TEST }}
      JWT_PUBLIC_KEY: ${{ secrets.JWT_PUBLIC_KEY_TEST }}

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: 'yarn'
      - run: yarn install --frozen-lockfile
      - name: Run migrations
        run: yarn migration:run
      - run: yarn api:e2e

  build:
    runs-on: ubuntu-latest
    needs: [lint, unit-test, e2e-test]
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ap-southeast-1
      - name: Login to ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2
      - name: Build and push Docker image
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build -t $ECR_REGISTRY/enterprise-todo-api:$IMAGE_TAG .
          docker push $ECR_REGISTRY/enterprise-todo-api:$IMAGE_TAG
      - name: Deploy to ECS
        run: |
          aws ecs update-service \
            --cluster enterprise-todo-prod \
            --service api-service \
            --force-new-deployment
```

---

## 8. Production Migrations — One-Off ECS Task

**Never run migrations inside the API startup.** The pattern:

```
1. Build new Docker image (SHA-tagged)
2. Run migration as a one-off ECS task (using the new image)
   → Hits the PRODUCTION database
   → Exits: code 0 = success | code 1 = failure + rollback trigger
3. If success → update ECS service to new image
4. ECS rolling deploy: new tasks start, old tasks drain
5. If failure → stop deploy, run migration:revert, investigate
```

Why not on startup:
- Multiple pods starting simultaneously each attempt the migration → race condition
- A failed migration kills every pod in a restart loop — noisy and hard to abort cleanly
- A one-off task is explicit, observable, and stoppable before touching the service

> **The migration is the renovation crew, not the building manager.** You wouldn't ask your building manager to renovate the lobby every morning when opening the building — especially with tenants already inside. You schedule the renovation crew for a specific time slot, with no tenants present, and let the manager open up only after the crew has signed off. The ECS one-off migration task is the renovation crew: it runs once, explicitly, before any new API pod starts serving traffic.

```typescript
// apps/api/src/migrate.ts — separate entry point for migration ECS task
import { DataSource } from 'typeorm';
import { dataSourceOptions } from './ormconfig';

async function runMigrations() {
  const dataSource = new DataSource(dataSourceOptions);
  await dataSource.initialize();
  await dataSource.runMigrations();
  await dataSource.destroy();
  process.exit(0);
}

runMigrations().catch((error) => {
  console.error('Migration failed:', error);
  process.exit(1);
});
```

ECS task definition uses `CMD ["node", "dist/migrate.js"]` — a separate task definition from the API service.

---

## 9. Secrets in Production

| Environment | Storage |
|-------------|---------|
| Local dev | `.env` (gitignored) |
| CI | GitHub Actions secrets |
| Staging/Production | AWS Secrets Manager |

```typescript
// apps/api/src/config/secrets.ts
import { GetSecretValueCommand, SecretsManagerClient } from '@aws-sdk/client-secrets-manager';

const client = new SecretsManagerClient({ region: 'ap-southeast-1' });

export async function loadSecrets(): Promise<Record<string, string>> {
  const { SecretString } = await client.send(
    new GetSecretValueCommand({ SecretId: 'enterprise-todo/prod' }),
  );
  return JSON.parse(SecretString!);
}
```

```typescript
// apps/api/src/main.ts
if (process.env.NODE_ENV === 'production') {
  const secrets = await loadSecrets();
  Object.assign(process.env, secrets);
}
const app = await NestFactory.create(AppModule);
```

**What goes in Secrets Manager:**
- `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`
- `DB_PASSWORD`
- Third-party API keys (email provider, AI, SMS)
- `ADMIN_JWT_PRIVATE_KEY`, `ADMIN_JWT_PUBLIC_KEY`

Never commit these to git — even in a private repo. A repo that becomes public, a leaked deploy key, or a compromised team member account all become incidents if secrets are in the codebase.

---

## 10. What Happens When You Push to Main

```
git push origin feature/add-tag ──→ open PR
                                      │
                                      ▼
                               GitHub Actions CI
                               ├── lint ✓
                               ├── unit tests ✓
                               └── E2E tests ✓
                                      │
                          PR approved + squash merge to main
                                      │
                                      ▼
                               GitHub Actions CD
                               ├── docker build (SHA-tagged)
                               ├── push to ECR
                               ├── run migration task (ECS one-off)
                               └── update ECS service (rolling deploy)
                                      │
                                      ▼
                               Production live ✓
```

Part 20 — Production Deployment covers deploying both NestJS apps to AWS ECS Fargate with RDS, ElastiCache, and a zero-downtime migration strategy using the one-off ECS task pattern introduced here.
