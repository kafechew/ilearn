---
author: Kai
pubDatetime: 2026-05-12T09:00:00+08:00
title: Git Workflow, CI/CD & Deployment
featured: false
draft: false
slug: 6112-git-workflow-cicd-deployment
tags:
  - deeptech
  - meteorjs
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/12-git-workflow-cicd-deployment.png"
description: By the end of this part, you will learn Commitizen, Husky, Branch strategy, Docker Compose, GitHub Actions CI pipeline, Deployment to AWS ECS Fargate, Production database migrations and AWS Secrets Manager pattern.  

---

## What This Part Covers

- Conventional commits with Commitizen
- Husky pre-commit and commit-msg hooks
- Branch strategy (feature → main, squash merge)
- Dockerfile (multi-stage build)
- Docker Compose for local development
- GitHub Actions CI pipeline (lint, test, E2E)
- Deployment to AWS ECS Fargate (overview)
- Production database migrations via one-off ECS task
- Environment secrets: AWS Secrets Manager pattern

---

## Meteor Equivalent

Meteor's deployment story was Galaxy — a proprietary PaaS. It handled containerization for you but limited control. Here you own the full deployment pipeline.

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

Now `yarn cz` opens an interactive prompt that formats the message correctly.

---

## 2. Husky Hooks

Husky runs scripts before git events (commit, push). Two critical hooks:

1. **pre-commit**: run lint on staged files
2. **commit-msg**: enforce conventional commit format

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

Now a commit message like `"fixed stuff"` will be rejected:
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
- No direct pushes to main (enforce via GitHub branch protection)

### PR Checklist (add to PULL_REQUEST_TEMPLATE.md)

```markdown
## PR Checklist

- [ ] Migration generated and reviewed (`migration:generate`, reviewed SQL)
- [ ] `migration:run` tested locally
- [ ] `migration:revert` tested locally
- [ ] Unit tests added/updated
- [ ] E2E tests pass locally (`yarn api:e2e`)
- [ ] No `synchronize: true` left in TypeORM config
- [ ] No `console.log` left in production code
- [ ] `@UseGuards(AuthJwtGuard)` on all new mutations/queries that need auth
- [ ] `tenantId` FK present on any new domain entity
- [ ] impact analysis run for any symbol changes
```

---

## 4. Dockerfile — Multi-Stage Build

A multi-stage Docker build keeps the final image small (no devDependencies, no TypeScript compiler).

```dockerfile
# Dockerfile
# ── Stage 1: Build ─────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile

COPY . .

# Build the NestJS API
RUN yarn nx build api --prod

# ── Stage 2: Prune dev deps ────────────────────────────────────
FROM node:20-alpine AS deps-prod
WORKDIR /app

COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile --production

# ── Stage 3: Runtime ───────────────────────────────────────────
FROM node:20-alpine AS runtime
WORKDIR /app

# Non-root user for security
RUN addgroup -S app && adduser -S app -G app

# Copy only production dependencies
COPY --from=deps-prod /app/node_modules ./node_modules
# Copy the compiled output
COPY --from=builder /app/dist/apps/api ./dist

USER app

EXPOSE 3000

CMD ["node", "dist/main.js"]
```

Build and run locally:

```bash
docker build -t enterprise-todo-api .
docker run -p 3000:3000 --env-file .env enterprise-todo-api
```

---

## 5. docker-compose.dev.yml (Full Version)

```yaml
# docker-compose.dev.yml
version: '3.9'

services:
  postgres:
    image: postgres:15-alpine
    ports:
      - '5432:5432'
    environment:
      POSTGRES_USER: ${DB_USERNAME}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: ${DB_DATABASE}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ['CMD-SHELL', 'pg_isready -U ${DB_USERNAME}']
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - '6379:6379'
    volumes:
      - redis_data:/data
    healthcheck:
      test: ['CMD', 'redis-cli', 'ping']
      interval: 5s
      timeout: 5s
      retries: 5

  adminer:
    image: adminer
    ports:
      - '8080:8080'
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  postgres_data:
  redis_data:
```

---

## 6. GitHub Actions CI Pipeline

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
          # Update the ECS task definition with the new image tag
          # then update the service to force a new deployment
          aws ecs update-service \
            --cluster enterprise-todo-prod \
            --service api-service \
            --force-new-deployment
```

---

## 7. Production Migrations — One-Off ECS Task

**Never run migrations as part of the API startup.** The pattern:

```
1. Build new Docker image (SHA-tagged)
2. Run migration as a one-off ECS task (using the new image)
   → This hits the PRODUCTION database
   → Runs and exits (exit code 0 = success, exit code 1 = failure + rollback trigger)
3. If migration succeeds → update ECS service to new image
4. ECS rolling deploy: new tasks start, old tasks drain
5. If migration fails → stop deploy, run migration:revert
```

Why not on startup?
- Multiple pods starting simultaneously would each try to run the migration → race condition
- A failed migration kills the deployment; a pod restart loop is noisy
- A one-off task is explicit, auditable, and stoppable

**Separate migration entrypoint:**

```typescript
// apps/api/src/migrate.ts — separate entry point for migration task
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

Run as an ECS task with `CMD ["node", "dist/migrate.js"]`.

---

## 8. Secrets in Production

| Environment | Secrets storage |
|-------------|----------------|
| Local dev | `.env` file (gitignored) |
| CI | GitHub Actions secrets |
| Staging/Production | AWS Secrets Manager |

**AWS Secrets Manager pattern:**

```typescript
// apps/api/src/config/secrets.ts — load from AWS at startup
import { GetSecretValueCommand, SecretsManagerClient } from '@aws-sdk/client-secrets-manager';

const client = new SecretsManagerClient({ region: 'ap-southeast-1' });

export async function loadSecrets(): Promise<Record<string, string>> {
  const { SecretString } = await client.send(
    new GetSecretValueCommand({ SecretId: 'enterprise-todo/prod' }),
  );
  return JSON.parse(SecretString!);
}
```

Inject in `main.ts` before bootstrap if running in production:
```typescript
if (process.env.NODE_ENV === 'production') {
  const secrets = await loadSecrets();
  Object.assign(process.env, secrets);
}
const app = await NestFactory.create(AppModule);
```

**What goes into Secrets Manager:**
- `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`
- `DB_PASSWORD`
- API keys for third-party services (email, AI providers)
- `ADMIN_JWT_PRIVATE_KEY`, `ADMIN_JWT_PUBLIC_KEY`

**Never commit** these to git, even in a private repo.

---

## 9. Summary — What Happens When You Push to Main

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
                               ├── docker build
                               ├── push to ECR
                               ├── run migration task (ECS one-off)
                               └── update ECS service (rolling deploy)
                                      │
                                      ▼
                               Production live ✓
```
