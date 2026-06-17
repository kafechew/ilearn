---
author: Kai
pubDatetime: 2026-05-20T09:00:00+08:00
title: Production Deployment — ECS Fargate, RDS, ElastiCache & Zero-Downtime Releases
featured: false
draft: false
slug: 6120-production-deployment-ecs-rds-elasticache
tags:
  - deeptech
  - nestjs
  - aws
  - ecs
  - rds
  - elasticache
  - devops
  - typescript
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/20-production-deployment-ecs-rds-elasticache.png"
description: Deploy both NestJS apps (api + portal-api) and the Next.js frontend to AWS ECS Fargate with RDS PostgreSQL, ElastiCache Redis, Secrets Manager for environment variables, a GitHub Actions CD pipeline, and a zero-downtime migration strategy using one-off ECS tasks
---

## What This Part Covers

- AWS infrastructure overview: ECR, ECS Fargate, RDS, ElastiCache, ALB, Secrets Manager, CloudWatch
- Why environment-specific RSA key pairs are mandatory — and how to generate and store them
- Building and pushing Docker images to ECR from GitHub Actions
- RDS PostgreSQL 15 setup with Multi-AZ for production
- ElastiCache Redis with TLS in-transit and in-rest encryption
- ECS task definitions for `api` and `portal-api` — secrets, health checks, log config
- Application Load Balancer routing: `api.yourdomain.com` → api service, `portal.yourdomain.com` → portal-api service
- Zero-downtime migrations as one-off ECS tasks — run before traffic is routed to new containers
- Complete GitHub Actions CD pipeline extending the CI pipeline from Part 19
- CloudWatch log groups, metric filters, and alarms wired to structured logs from `LoggingInterceptor`
- Go-live checklist and full series completion summary

---

## Meteor Equivalents

| Meteor deployment                         | NestJS enterprise deployment                                         |
| ----------------------------------------- | -------------------------------------------------------------------- |
| `meteor deploy` to Galaxy                 | ECS Fargate (containerised, auto-scaling)                            |
| MongoDB Atlas                             | RDS PostgreSQL 15 (Multi-AZ)                                         |
| Environment variables in Galaxy dashboard | AWS Secrets Manager                                                  |
| Galaxy automatic restarts                 | ECS health checks + rolling deployment                               |
| Single app server                         | Separate `api` + `portal-api` services                               |
| Meteor's built-in DDP pub/sub             | Not applicable — replaced by GraphQL subscriptions over Redis PubSub |
| Galaxy logs                               | CloudWatch Logs with structured log filtering                        |
| One key pair for all environments         | Unique RSA key pairs per environment (dev / staging / production)    |

---

## 1. AWS Infrastructure Overview

The full production topology for the enterprise-todo monorepo:

```
Internet
    │
    ▼
Route 53
    ├─ api.yourdomain.com       → ALB → ECS Service: api        (port 3333)
    ├─ portal.yourdomain.com    → ALB → ECS Service: portal-api (port 3334)
    └─ app.yourdomain.com       → Vercel / Amplify (Next.js)

VPC (private subnets only)
    ├─ ECS Fargate tasks        (api + portal-api containers)
    ├─ RDS PostgreSQL 15        (Multi-AZ, private subnet group)
    └─ ElastiCache Redis 7.x    (single node, private subnet group)

ECR                             (Docker image registry, per-app repositories)
Secrets Manager                 (all env vars: RSA keys, DB passwords, API secrets)
CloudWatch Logs                 (structured logs from LoggingInterceptor)
S3 + CloudFront                 (media library — configured in Part 17)
```

**Everything except the ALB lives in private subnets.** There is no public IP on any ECS task, RDS instance, or ElastiCache node. The only entry point from the public internet is the Application Load Balancer on port 443. Any attempt to connect directly to RDS or Redis from outside the VPC will time out — the security group rules enforce this at the network layer.

The ALB terminates TLS using an ACM certificate. Traffic between the ALB and ECS tasks is plain HTTP inside the VPC. Traffic between ECS tasks and ElastiCache uses TLS (Redis 7 in-transit encryption). Traffic between ECS tasks and RDS is TLS by default on PostgreSQL 15.

This topology is deliberately minimal for a first production deployment. It does not include a NAT Gateway per AZ (one NAT Gateway is sufficient to start), does not use ECS Service Connect, and does not use Aurora. Add those when the workload justifies the cost.

### Verify: Account Prerequisites

Before proceeding, confirm:

```bash
aws sts get-caller-identity
# Expected: JSON with Account, UserId, Arn — confirms credentials are working

aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query 'Vpcs[0].VpcId' --output text
# Expected: vpc-xxxxxxxx — note this ID, you will use it in security group rules

aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=<your-vpc-id>" \
  --query 'Subnets[*].[SubnetId,AvailabilityZone,MapPublicIpOnLaunch]' \
  --output table
# Expected: list of subnets — identify at least 2 private subnets in different AZs
```

---

## 2. Environment-Specific RSA Key Pairs

This step is the most frequently skipped and the most dangerous to get wrong. The architecture uses RS256 JWT with separate key pairs for the user API and the portal API. If all environments share the same key pair, a staging-issued JWT can authenticate against the production API. That is a security boundary violation, not just a configuration smell.

**Required key files:**

| Environment | User API                                               | Portal API                                                 |
| ----------- | ------------------------------------------------------ | ---------------------------------------------------------- |
| Local dev   | `user_private_dev.pem` / `user_public_dev.pem`         | `portal_private_dev.pem` / `portal_public_dev.pem`         |
| Staging     | `user_private_staging.pem` / `user_public_staging.pem` | `portal_private_staging.pem` / `portal_public_staging.pem` |
| Production  | `user_private_prod.pem` / `user_public_prod.pem`       | `portal_private_prod.pem` / `portal_public_prod.pem`       |

That is 12 files total. Generate them once per environment. Never reuse across environments.

### 2.1 Generate Key Pairs

Run once for each environment (shown for production):

```bash
# User API key pair
openssl genrsa 4096 | openssl pkcs8 -topk8 -nocrypt -out user_private_prod.pem
openssl rsa -in user_private_prod.pem -pubout -out user_public_prod.pem

# Portal API key pair (must be different from user API)
openssl genrsa 4096 | openssl pkcs8 -topk8 -nocrypt -out portal_private_prod.pem
openssl rsa -in portal_private_prod.pem -pubout -out portal_public_prod.pem
```

Never commit these files. Add them to `.gitignore` immediately:

```bash
echo "*.pem" >> .gitignore
```

### 2.2 Store in AWS Secrets Manager

Store each key as its own secret. The multiline PEM content is stored as the raw secret string value:

```bash
# User API keys
aws secretsmanager create-secret \
  --name "enterprise-todo/production/JWT_PRIVATE_KEY" \
  --description "User API RS256 private key — production" \
  --secret-string "$(cat user_private_prod.pem)"

aws secretsmanager create-secret \
  --name "enterprise-todo/production/JWT_PUBLIC_KEY" \
  --description "User API RS256 public key — production" \
  --secret-string "$(cat user_public_prod.pem)"

# Portal API keys
aws secretsmanager create-secret \
  --name "enterprise-todo/production/PORTAL_JWT_PRIVATE_KEY" \
  --description "Portal API RS256 private key — production" \
  --secret-string "$(cat portal_private_prod.pem)"

aws secretsmanager create-secret \
  --name "enterprise-todo/production/PORTAL_JWT_PUBLIC_KEY" \
  --description "Portal API RS256 public key — production" \
  --secret-string "$(cat portal_public_prod.pem)"
```

Repeat for staging with path `enterprise-todo/staging/...`. The ECS task definition references secrets by ARN, so each environment's task definition naturally reads its own keys.

### 2.3 Update to Latest Version

When you rotate keys (do this at least annually), create a new version of the existing secret rather than a new secret — the ARN stays stable and task definitions do not need updating:

```bash
aws secretsmanager put-secret-value \
  --secret-id "enterprise-todo/production/JWT_PRIVATE_KEY" \
  --secret-string "$(cat user_private_prod_v2.pem)"
```

ECS injects the latest version automatically on the next task launch.

### Verify: Secrets Exist

```bash
aws secretsmanager list-secrets \
  --filter Key=name,Values=enterprise-todo/production \
  --query 'SecretList[*].Name' \
  --output table
# Expected: all four key secrets listed, plus DB_PASSWORD (added in section 4)
```

---

## 3. ECR Repositories and Docker Images

### 3.1 Create ECR Repositories

One repository per app. The tag strategy used here is `git SHA` — immutable, traceable, and safe to use in rolling deployments.

```bash
aws ecr create-repository \
  --repository-name enterprise-todo/api \
  --image-scanning-configuration scanOnPush=true \
  --encryption-configuration encryptionType=AES256

aws ecr create-repository \
  --repository-name enterprise-todo/portal-api \
  --image-scanning-configuration scanOnPush=true \
  --encryption-configuration encryptionType=AES256

aws ecr create-repository \
  --repository-name enterprise-todo/migrator \
  --image-scanning-configuration scanOnPush=true \
  --encryption-configuration encryptionType=AES256
```

Enable lifecycle policy to prevent unbounded image accumulation:

```bash
aws ecr put-lifecycle-policy \
  --repository-name enterprise-todo/api \
  --lifecycle-policy-text '{
    "rules": [{
      "rulePriority": 1,
      "description": "Keep last 20 images",
      "selection": {
        "tagStatus": "any",
        "countType": "imageCountMoreThan",
        "countNumber": 20
      },
      "action": { "type": "expire" }
    }]
  }'
```

Apply the same lifecycle policy to `portal-api` and `migrator`.

### 3.2 Production Dockerfile for api

The multi-stage Dockerfile from Part 19 extended for production with a health check:

```dockerfile
# apps/api/Dockerfile
FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile --production=false

COPY . .
RUN yarn api:build

# ---- production image ----
FROM node:20-alpine AS production
WORKDIR /app

ENV NODE_ENV=production

COPY --from=builder /app/dist/apps/api ./dist
COPY --from=builder /app/node_modules ./node_modules

EXPOSE 3333

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD wget -q -O- "http://localhost:3333/graphql?query=%7Bhealth%7D" || exit 1

CMD ["node", "dist/main.js"]
```

The `--start-period=60s` flag tells ECS not to count health check failures during the first 60 seconds. NestJS takes 10–20 seconds to start; without a start period, ECS will kill the task before it has finished booting.

### 3.3 portal-api Dockerfile

```dockerfile
# apps/portal-api/Dockerfile
FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile --production=false

COPY . .
RUN yarn portal-api:build

FROM node:20-alpine AS production
WORKDIR /app

ENV NODE_ENV=production

COPY --from=builder /app/dist/apps/portal-api ./dist
COPY --from=builder /app/node_modules ./node_modules

EXPOSE 3334

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD wget -q -O- "http://localhost:3334/graphql?query=%7Bhealth%7D" || exit 1

CMD ["node", "dist/main.js"]
```

### 3.4 Migrator Dockerfile

The migrator is a separate image that runs migrations and exits. It uses the same builder stage as `api` to avoid rebuilding `node_modules`.

```dockerfile
# apps/api/Dockerfile.migrator
FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile --production=false

COPY . .
RUN yarn api:build

FROM node:20-alpine AS migrator
WORKDIR /app

ENV NODE_ENV=production

COPY --from=builder /app/dist/apps/api ./dist
COPY --from=builder /app/node_modules ./node_modules

# No HEALTHCHECK — this is a one-shot task
CMD ["node", "dist/migration-runner.js"]
```

### 3.5 Migration Runner Entry Point

```typescript
// apps/api/src/migration-runner.ts
import "reflect-metadata";
import { AppDataSource } from "./app/ormconfig";

async function runMigrations(): Promise<void> {
  console.log("Initialising data source...");
  await AppDataSource.initialize();

  const pending = await AppDataSource.showMigrations();
  if (!pending) {
    console.log("No pending migrations — exiting.");
    await AppDataSource.destroy();
    process.exit(0);
  }

  console.log("Running pending migrations...");
  const executed = await AppDataSource.runMigrations({ transaction: "each" });
  console.log(`Executed ${executed.length} migration(s):`);
  executed.forEach(m => console.log(`  - ${m.name}`));

  await AppDataSource.destroy();
  console.log("Migrations complete.");
  process.exit(0);
}

runMigrations().catch(err => {
  console.error("Migration failed:", err);
  process.exit(1);
});
```

> **The missing piece — `ormconfig.ts`:** The migrator imports `AppDataSource` from a dedicated TypeORM datasource config. This is the same connection config as your NestJS `TypeOrmModule.forRootAsync` but as a plain TypeORM `DataSource` object (TypeORM CLI requirement — it can't use NestJS's DI).
> 
> Create `apps/backend/src/app/ormconfig.ts`:
> ```typescript
> import { DataSource } from 'typeorm';
> import { SnakeNamingStrategy } from 'typeorm-naming-strategies';
> import * as dotenv from 'dotenv';
> dotenv.config();
> 
> export const AppDataSource = new DataSource({
>   type: 'postgres',
>   host: process.env.PROJECT_DB_HOST,
>   port: Number(process.env.PROJECT_DB_PORT),
>   username: process.env.PROJECT_DB_USERNAME,
>   password: process.env.PROJECT_DB_PASSWORD,
>   database: process.env.PROJECT_DB_DATABASE,
>   ssl: process.env.NODE_ENV === 'production' ? { rejectUnauthorized: true } : false,
>   namingStrategy: new SnakeNamingStrategy(),
>   entities: [/* explicit entity list — no globs (Webpack bundles to main.js) */],
>   migrations: ['apps/backend/src/migrations/*.ts'],
>   synchronize: false,
> });
> ```
> Add every entity explicitly to the `entities[]` array.

Register `migration-runner.ts` as a separate webpack entry point in `apps/api/project.json` so Nx compiles it alongside `main.ts`:

```json
// apps/api/project.json (targets.build.options excerpt)
{
  "main": "apps/api/src/main.ts",
  "additionalEntryPoints": ["apps/api/src/migration-runner.ts"]
}
```

### Verify: Local Docker Build

```bash
docker build -f apps/api/Dockerfile -t enterprise-todo-api:local .
docker run --rm -p 3333:3333 \
  -e NODE_ENV=development \
  -e PROJECT_DB_HOST=host.docker.internal \
  -e PROJECT_DB_PORT=5432 \
  -e PROJECT_DB_USER=postgres \
  -e PROJECT_DB_PASSWORD=postgres \
  -e PROJECT_DB_NAME=enterprise_todo \
  -e JWT_PRIVATE_KEY="$(cat user_private_dev.pem)" \
  -e JWT_PUBLIC_KEY="$(cat user_public_dev.pem)" \
  enterprise-todo-api:local
# Expected: NestJS starts, GraphQL playground available at http://localhost:3333/graphql
```

---

## 4. RDS PostgreSQL 15

### 4.1 Subnet Group

RDS must be placed in a subnet group that spans at least two AZs for Multi-AZ to work:

```bash
aws rds create-db-subnet-group \
  --db-subnet-group-name enterprise-todo-db-subnets \
  --db-subnet-group-description "Private subnets for enterprise-todo RDS" \
  --subnet-ids subnet-aaa111 subnet-bbb222
  # Use the private subnet IDs identified in section 1
```

### 4.2 Security Group

```bash
# Create security group for RDS — allow only ECS tasks
aws ec2 create-security-group \
  --group-name enterprise-todo-rds-sg \
  --description "Allow PostgreSQL from ECS tasks only" \
  --vpc-id vpc-xxxxxxxx

# Allow port 5432 from the ECS task security group (create ecs-sg first, then reference it)
aws ec2 authorize-security-group-ingress \
  --group-id sg-rds-xxxxxxxx \
  --protocol tcp \
  --port 5432 \
  --source-group sg-ecs-xxxxxxxx
```

Never authorise `0.0.0.0/0` on port 5432. If you need to run migrations or queries from a developer workstation, use AWS Systems Manager Session Manager to start a port-forwarding session to an EC2 bastion, or use RDS Proxy with IAM authentication.

### 4.3 Create the RDS Instance

```bash
# Generate and store DB password before creating instance
DB_PASSWORD=$(openssl rand -base64 32 | tr -d '=/+' | head -c 32)
aws secretsmanager create-secret \
  --name "enterprise-todo/production/DB_PASSWORD" \
  --secret-string "$DB_PASSWORD"

# Create RDS instance
aws rds create-db-instance \
  --db-instance-identifier enterprise-todo-prod \
  --db-instance-class db.t4g.medium \
  --engine postgres \
  --engine-version 15.6 \
  --master-username etadmin \
  --master-user-password "$DB_PASSWORD" \
  --db-name enterprise_todo \
  --allocated-storage 100 \
  --storage-type gp3 \
  --storage-encrypted \
  --multi-az \
  --no-publicly-accessible \
  --vpc-security-group-ids sg-rds-xxxxxxxx \
  --db-subnet-group-name enterprise-todo-db-subnets \
  --backup-retention-period 7 \
  --deletion-protection \
  --tags Key=Project,Value=enterprise-todo Key=Environment,Value=production
```

Key settings explained:

| Setting                   | Value            | Reason                                                                                                    |
| ------------------------- | ---------------- | --------------------------------------------------------------------------------------------------------- |
| `db.t4g.medium`           | 2 vCPU, 4 GB RAM | Adequate for most production workloads under ~200 concurrent users; upgrade to `r7g.large` if you see OOM |
| `multi-az`                | true             | RDS automatically fails over to standby replica on hardware failure; RPO ~1 min, RTO ~1–2 min             |
| `storage-encrypted`       | true             | KMS-encrypted at rest; required for most compliance frameworks                                            |
| `deletion-protection`     | true             | Prevents accidental `aws rds delete-db-instance`; must be disabled explicitly before deletion             |
| `backup-retention-period` | 7                | 7-day automated backups; increase to 35 for financial or compliance workloads                             |

For staging, use `db.t4g.micro`, `--no-multi-az`, and `--backup-retention-period 1` to reduce cost.

### 4.4 Connection String

After the instance reaches `available` status:

```bash
aws rds describe-db-instances \
  --db-instance-identifier enterprise-todo-prod \
  --query 'DBInstances[0].Endpoint.Address' \
  --output text
# Returns: enterprise-todo-prod.abc123def456.ap-southeast-1.rds.amazonaws.com
```

This value goes into the `PROJECT_DB_HOST` environment variable in the ECS task definition (not in Secrets Manager — it is not a secret, just a hostname).

### Verify: RDS Reachability from ECS

After deploying the first ECS task (section 6), check CloudWatch Logs for the NestJS startup sequence. A successful TypeORM connection looks like:

```
[TypeORM] Connection to postgres established on enterprise-todo-prod.abc123...
[NestApplication] Nest application successfully started
```

A failed connection produces:

```
[TypeORM] Unable to connect to the database. Retrying (1)...
```

If you see retries, verify: (a) the security group allows port 5432 from the ECS task SG, (b) `PROJECT_DB_HOST` is set correctly in the task definition, (c) `PROJECT_DB_PASSWORD` is the correct Secrets Manager ARN.

---

## 5. ElastiCache Redis

### 5.1 Subnet Group

```bash
aws elasticache create-cache-subnet-group \
  --cache-subnet-group-name enterprise-todo-redis-subnets \
  --cache-subnet-group-description "Private subnets for enterprise-todo Redis" \
  --subnet-ids subnet-aaa111 subnet-bbb222
```

### 5.2 Security Group

```bash
aws ec2 create-security-group \
  --group-name enterprise-todo-redis-sg \
  --description "Allow Redis from ECS tasks only" \
  --vpc-id vpc-xxxxxxxx

aws ec2 authorize-security-group-ingress \
  --group-id sg-redis-xxxxxxxx \
  --protocol tcp \
  --port 6379 \
  --source-group sg-ecs-xxxxxxxx
```

### 5.3 Create the Cache Cluster

```bash
aws elasticache create-replication-group \
  --replication-group-id enterprise-todo-prod \
  --replication-group-description "enterprise-todo production Redis" \
  --cache-node-type cache.t4g.small \
  --engine redis \
  --engine-version 7.1 \
  --num-cache-clusters 1 \
  --cache-subnet-group-name enterprise-todo-redis-subnets \
  --security-group-ids sg-redis-xxxxxxxx \
  --at-rest-encryption-enabled \
  --transit-encryption-enabled \
  --transit-encryption-mode preferred \
  --tags Key=Project,Value=enterprise-todo Key=Environment,Value=production
```

Cluster mode is disabled (single node). Bull queues are ephemeral — if Redis restarts, in-flight jobs that have not been acknowledged are requeued on next connection. This is safe as long as Bull job handlers are idempotent, which they should be by design (see performance rules).

### 5.4 TLS in BullModule and RedisPubSub

ElastiCache with `transit-encryption-enabled` requires TLS from the client. Update `AppModule`:

```typescript
// apps/api/src/app/app.module.ts (BullModule excerpt)
BullModule.forRootAsync({
  inject: [ConfigService],
  useFactory: (config: ConfigService) => ({
    redis: {
      host: config.get<string>('REDIS_BULL_HOST'),
      port: config.get<number>('REDIS_BULL_PORT'),
      tls: process.env.NODE_ENV === 'production' ? {} : undefined,
    },
  }),
}),
```

Update `RedisPubSub` in the subscriptions module:

```typescript
// apps/api/src/app/pubsub.provider.ts
import { RedisPubSub } from "graphql-redis-subscriptions";
import { ConfigService } from "@nestjs/config";

export const PubSubProvider = {
  provide: "PUB_SUB",
  inject: [ConfigService],
  useFactory: (config: ConfigService) => {
    const tlsOptions = process.env.NODE_ENV === "production" ? { tls: {} } : {};
    return new RedisPubSub({
      connection: {
        host: config.get<string>("REDIS_PUBSUB_HOST"),
        port: config.get<number>("REDIS_PUBSUB_PORT"),
        ...tlsOptions,
      },
    });
  },
};
```

`REDIS_BULL_HOST` and `REDIS_PUBSUB_HOST` both point to the ElastiCache primary endpoint:

```bash
aws elasticache describe-replication-groups \
  --replication-group-id enterprise-todo-prod \
  --query 'ReplicationGroups[0].NodeGroups[0].PrimaryEndpoint.Address' \
  --output text
# Returns: enterprise-todo-prod.abc123.use1.cache.amazonaws.com
```

### Verify: Redis Connectivity

After the first successful ECS task deployment, submit a job (for example, a password reset request). Check CloudWatch Logs for:

```
[BullWorker] Job email:send 12345 started
[BullWorker] Job email:send 12345 completed in 145ms
```

If jobs queue but never process, Redis TLS configuration is usually the cause. Check the `tls` flag is being applied and that the security group allows port 6379 from the ECS task SG.

---

## 6. ECS Task Definitions

### 6.1 IAM Task Execution Role

ECS needs a task execution role to pull secrets from Secrets Manager and images from ECR:

```bash
# Create the role
aws iam create-role \
  --role-name enterprise-todo-ecs-execution-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": { "Service": "ecs-tasks.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach the managed execution policy (ECR + CloudWatch Logs)
aws iam attach-role-policy \
  --role-name enterprise-todo-ecs-execution-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# Add Secrets Manager read permission
aws iam put-role-policy \
  --role-name enterprise-todo-ecs-execution-role \
  --policy-name SecretsManagerRead \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:ap-southeast-1:123456789:secret:enterprise-todo/production/*"
    }]
  }'
```

### 6.2 api Task Definition

Save as `infra/task-definitions/api.json`. Replace `123456789` with your AWS account ID and the RDS hostname with the value from section 4.4.

```json
{
  "family": "enterprise-todo-api",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::123456789:role/enterprise-todo-ecs-execution-role",
  "containerDefinitions": [
    {
      "name": "api",
      "image": "123456789.dkr.ecr.ap-southeast-1.amazonaws.com/enterprise-todo/api:latest",
      "essential": true,
      "portMappings": [{ "containerPort": 3333, "protocol": "tcp" }],
      "secrets": [
        {
          "name": "JWT_PRIVATE_KEY",
          "valueFrom": "arn:aws:secretsmanager:ap-southeast-1:123456789:secret:enterprise-todo/production/JWT_PRIVATE_KEY"
        },
        {
          "name": "JWT_PUBLIC_KEY",
          "valueFrom": "arn:aws:secretsmanager:ap-southeast-1:123456789:secret:enterprise-todo/production/JWT_PUBLIC_KEY"
        },
        {
          "name": "PROJECT_DB_PASSWORD",
          "valueFrom": "arn:aws:secretsmanager:ap-southeast-1:123456789:secret:enterprise-todo/production/DB_PASSWORD"
        }
      ],
      "environment": [
        { "name": "NODE_ENV", "value": "production" },
        { "name": "PROJECT_PORT", "value": "3333" },
        {
          "name": "PROJECT_DB_HOST",
          "value": "enterprise-todo-prod.abc123def456.ap-southeast-1.rds.amazonaws.com"
        },
        { "name": "PROJECT_DB_PORT", "value": "5432" },
        { "name": "PROJECT_DB_USER", "value": "etadmin" },
        { "name": "PROJECT_DB_NAME", "value": "enterprise_todo" },
        {
          "name": "REDIS_BULL_HOST",
          "value": "enterprise-todo-prod.abc123.use1.cache.amazonaws.com"
        },
        { "name": "REDIS_BULL_PORT", "value": "6379" },
        {
          "name": "REDIS_PUBSUB_HOST",
          "value": "enterprise-todo-prod.abc123.use1.cache.amazonaws.com"
        },
        { "name": "REDIS_PUBSUB_PORT", "value": "6379" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/enterprise-todo-api",
          "awslogs-region": "ap-southeast-1",
          "awslogs-stream-prefix": "api",
          "awslogs-create-group": "true"
        }
      },
      "healthCheck": {
        "command": [
          "CMD-SHELL",
          "wget -q -O- 'http://localhost:3333/graphql?query=%7Bhealth%7D' || exit 1"
        ],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 60
      }
    }
  ]
}
```

Register the task definition:

```bash
aws ecs register-task-definition \
  --cli-input-json file://infra/task-definitions/api.json
```

### 6.3 portal-api Task Definition

`portal-api` gets an identical structure with different port, image, and secrets. Save as `infra/task-definitions/portal-api.json`:

```json
{
  "family": "enterprise-todo-portal-api",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::123456789:role/enterprise-todo-ecs-execution-role",
  "containerDefinitions": [
    {
      "name": "portal-api",
      "image": "123456789.dkr.ecr.ap-southeast-1.amazonaws.com/enterprise-todo/portal-api:latest",
      "essential": true,
      "portMappings": [{ "containerPort": 3334, "protocol": "tcp" }],
      "secrets": [
        {
          "name": "JWT_PRIVATE_KEY",
          "valueFrom": "arn:aws:secretsmanager:ap-southeast-1:123456789:secret:enterprise-todo/production/PORTAL_JWT_PRIVATE_KEY"
        },
        {
          "name": "JWT_PUBLIC_KEY",
          "valueFrom": "arn:aws:secretsmanager:ap-southeast-1:123456789:secret:enterprise-todo/production/PORTAL_JWT_PUBLIC_KEY"
        },
        {
          "name": "PROJECT_DB_PASSWORD",
          "valueFrom": "arn:aws:secretsmanager:ap-southeast-1:123456789:secret:enterprise-todo/production/DB_PASSWORD"
        }
      ],
      "environment": [
        { "name": "NODE_ENV", "value": "production" },
        { "name": "PROJECT_PORT", "value": "3334" },
        {
          "name": "PROJECT_DB_HOST",
          "value": "enterprise-todo-prod.abc123def456.ap-southeast-1.rds.amazonaws.com"
        },
        { "name": "PROJECT_DB_PORT", "value": "5432" },
        { "name": "PROJECT_DB_USER", "value": "etadmin" },
        { "name": "PROJECT_DB_NAME", "value": "enterprise_todo" },
        {
          "name": "REDIS_BULL_HOST",
          "value": "enterprise-todo-prod.abc123.use1.cache.amazonaws.com"
        },
        { "name": "REDIS_BULL_PORT", "value": "6379" },
        {
          "name": "REDIS_PUBSUB_HOST",
          "value": "enterprise-todo-prod.abc123.use1.cache.amazonaws.com"
        },
        { "name": "REDIS_PUBSUB_PORT", "value": "6379" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/enterprise-todo-portal-api",
          "awslogs-region": "ap-southeast-1",
          "awslogs-stream-prefix": "portal-api",
          "awslogs-create-group": "true"
        }
      },
      "healthCheck": {
        "command": [
          "CMD-SHELL",
          "wget -q -O- 'http://localhost:3334/graphql?query=%7Bhealth%7D' || exit 1"
        ],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 60
      }
    }
  ]
}
```

### 6.4 Migrator Task Definition

The migrator uses the same execution role and secrets as the api, but has no port mapping and no health check — it is a one-shot task:

```json
{
  "family": "enterprise-todo-migrator",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "arn:aws:iam::123456789:role/enterprise-todo-ecs-execution-role",
  "containerDefinitions": [
    {
      "name": "migrator",
      "image": "123456789.dkr.ecr.ap-southeast-1.amazonaws.com/enterprise-todo/migrator:latest",
      "essential": true,
      "secrets": [
        {
          "name": "PROJECT_DB_PASSWORD",
          "valueFrom": "arn:aws:secretsmanager:ap-southeast-1:123456789:secret:enterprise-todo/production/DB_PASSWORD"
        }
      ],
      "environment": [
        { "name": "NODE_ENV", "value": "production" },
        {
          "name": "PROJECT_DB_HOST",
          "value": "enterprise-todo-prod.abc123def456.ap-southeast-1.rds.amazonaws.com"
        },
        { "name": "PROJECT_DB_PORT", "value": "5432" },
        { "name": "PROJECT_DB_USER", "value": "etadmin" },
        { "name": "PROJECT_DB_NAME", "value": "enterprise_todo" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/enterprise-todo-migrator",
          "awslogs-region": "ap-southeast-1",
          "awslogs-stream-prefix": "migrator",
          "awslogs-create-group": "true"
        }
      }
    }
  ]
}
```

### Verify: Task Definitions Registered

```bash
aws ecs list-task-definitions \
  --family-prefix enterprise-todo \
  --query 'taskDefinitionArns' \
  --output table
# Expected: enterprise-todo-api:1, enterprise-todo-portal-api:1, enterprise-todo-migrator:1
```

---

## 7. ECS Cluster and Services

### 7.1 Create the Cluster

```bash
aws ecs create-cluster \
  --cluster-name enterprise-todo-prod \
  --capacity-providers FARGATE FARGATE_SPOT \
  --default-capacity-provider-strategy \
    capacityProvider=FARGATE,weight=1,base=1 \
  --tags key=Project,value=enterprise-todo key=Environment,value=production
```

Using `FARGATE` as the base provider with `FARGATE_SPOT` available allows cost optimisation for non-critical tasks (migrator, background workers) while guaranteeing on-demand capacity for the api services.

### 7.2 ECS Service for api

```bash
aws ecs create-service \
  --cluster enterprise-todo-prod \
  --service-name enterprise-todo-api \
  --task-definition enterprise-todo-api:1 \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={
    subnets=[subnet-private-aaa111,subnet-private-bbb222],
    securityGroups=[sg-ecs-xxxxxxxx],
    assignPublicIp=DISABLED
  }" \
  --load-balancers "targetGroupArn=arn:aws:elasticloadbalancing:...:targetgroup/enterprise-todo-api/...,containerName=api,containerPort=3333" \
  --health-check-grace-period-seconds 90 \
  --deployment-configuration "minimumHealthyPercent=50,maximumPercent=200" \
  --tags key=Project,value=enterprise-todo
```

`desired-count=2` means two tasks are always running. The rolling deployment configuration (`minimumHealthyPercent=50,maximumPercent=200`) allows ECS to spin up 2 new tasks before terminating the old ones — at peak changeover, 4 tasks run briefly, then settle back to 2. This is zero-downtime with no request drops.

Create an identical service for `portal-api` with `--desired-count 1` (portal traffic is lower; scale up if needed).

### Verify: Services Running

```bash
aws ecs describe-services \
  --cluster enterprise-todo-prod \
  --services enterprise-todo-api enterprise-todo-portal-api \
  --query 'services[*].[serviceName,runningCount,desiredCount,status]' \
  --output table
# Expected: both services show runningCount == desiredCount == 2/1, status ACTIVE
```

---

## 8. Application Load Balancer

### 8.1 ALB Setup

```bash
# Create ALB
aws elbv2 create-load-balancer \
  --name enterprise-todo-alb \
  --subnets subnet-public-aaa111 subnet-public-bbb222 \
  --security-groups sg-alb-xxxxxxxx \
  --scheme internet-facing \
  --type application \
  --ip-address-type ipv4 \
  --tags Key=Project,Value=enterprise-todo

# Create target groups
aws elbv2 create-target-group \
  --name enterprise-todo-api \
  --protocol HTTP \
  --port 3333 \
  --vpc-id vpc-xxxxxxxx \
  --target-type ip \
  --health-check-path "/graphql?query=%7Bhealth%7D" \
  --health-check-interval-seconds 30 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 3 \
  --matcher HttpCode=200

aws elbv2 create-target-group \
  --name enterprise-todo-portal \
  --protocol HTTP \
  --port 3334 \
  --vpc-id vpc-xxxxxxxx \
  --target-type ip \
  --health-check-path "/graphql?query=%7Bhealth%7D" \
  --health-check-interval-seconds 30 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 3 \
  --matcher HttpCode=200
```

### 8.2 HTTPS Listener with Host-Based Routing

```bash
# Create HTTPS listener (ACM certificate must already exist and be validated)
LISTENER_ARN=$(aws elbv2 create-listener \
  --load-balancer-arn $ALB_ARN \
  --protocol HTTPS \
  --port 443 \
  --certificates CertificateArn=$ACM_CERT_ARN \
  --default-actions Type=fixed-response,FixedResponseConfig='{StatusCode=404,ContentType=text/plain,MessageBody=Not Found}' \
  --query 'Listeners[0].ListenerArn' \
  --output text)

# Add rule: api.yourdomain.com → api target group
aws elbv2 create-rule \
  --listener-arn $LISTENER_ARN \
  --priority 10 \
  --conditions '[{"Field":"host-header","Values":["api.yourdomain.com"]}]' \
  --actions '[{"Type":"forward","TargetGroupArn":"'$API_TG_ARN'"}]'

# Add rule: portal.yourdomain.com → portal target group
aws elbv2 create-rule \
  --listener-arn $LISTENER_ARN \
  --priority 20 \
  --conditions '[{"Field":"host-header","Values":["portal.yourdomain.com"]}]' \
  --actions '[{"Type":"forward","TargetGroupArn":"'$PORTAL_TG_ARN'"}]'
```

**Critical reminder:** `HealthResolver` must have `@SkipThrottle()` (added in Part 15). The ALB health check runs every 30 seconds against every registered target. With two api tasks, that is 4 health check requests per minute — above the default throttler limit. Without `@SkipThrottle()`, the ALB will start receiving 429 responses, mark targets as unhealthy, and deregister them.

```typescript
// apps/api/src/modules/health/health.resolver.ts
import { SkipThrottle } from "@nestjs/throttler";

@SkipThrottle()
@Resolver()
export class HealthResolver {
  @Query(() => String)
  health(): string {
    return "ok";
  }
}
```

### 8.3 HTTP to HTTPS Redirect

Add a port 80 listener that redirects all traffic to HTTPS:

```bash
aws elbv2 create-listener \
  --load-balancer-arn $ALB_ARN \
  --protocol HTTP \
  --port 80 \
  --default-actions '[{
    "Type": "redirect",
    "RedirectConfig": {
      "Protocol": "HTTPS",
      "Port": "443",
      "StatusCode": "HTTP_301"
    }
  }]'
```

### Verify: ALB Health Checks Pass

```bash
aws elbv2 describe-target-health \
  --target-group-arn $API_TG_ARN \
  --query 'TargetHealthDescriptions[*].[Target.Id,TargetHealth.State,TargetHealth.Description]' \
  --output table
# Expected: all targets show State=healthy
# If State=unhealthy, check Description for the specific failure reason
```

---

## 9. Zero-Downtime Migrations as One-Off ECS Tasks

This is the most important production operations pattern for TypeORM + NestJS on ECS. Never run `runMigrations()` from the application's `onApplicationBootstrap` hook. The reason is race conditions: when ECS launches two new api tasks simultaneously during a rolling deployment, both tasks will attempt to run migrations concurrently. TypeORM does not use advisory locks by default. Two tasks running the same migration produces duplicate key errors or partial schema states depending on which queries interleave.

The correct pattern:

1. Build and push all images (api, portal-api, migrator) tagged with the current git SHA.
2. Run the migrator as a one-off ECS task against the live database. Wait for it to exit 0.
3. Only if the migrator succeeds, trigger the rolling deployment of the api and portal-api services with the new image.
4. The new api containers start against a schema that is already migrated. They never run migrations themselves.

This sequence means there is a brief window (between step 2 and step 3) where the old api version is running against the new schema. This is acceptable because TypeORM migrations are additive-only — new columns are nullable or have defaults, dropped columns are removed in a follow-up migration after the code that references them is already deployed. Never perform destructive schema changes in the same deployment as the code change that removes the column reference.

### 9.1 Run Migrator as One-Off Task

```bash
# Launch migrator task and capture task ARN
TASK_ARN=$(aws ecs run-task \
  --cluster enterprise-todo-prod \
  --task-definition enterprise-todo-migrator \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={
    subnets=[subnet-private-aaa111,subnet-private-bbb222],
    securityGroups=[sg-ecs-xxxxxxxx],
    assignPublicIp=DISABLED
  }" \
  --query 'tasks[0].taskArn' \
  --output text)

echo "Migrator task ARN: $TASK_ARN"

# Wait for the task to stop (exit)
aws ecs wait tasks-stopped \
  --cluster enterprise-todo-prod \
  --tasks "$TASK_ARN"

# Check the exit code
EXIT_CODE=$(aws ecs describe-tasks \
  --cluster enterprise-todo-prod \
  --tasks "$TASK_ARN" \
  --query 'tasks[0].containers[0].exitCode' \
  --output text)

echo "Migrator exit code: $EXIT_CODE"

if [ "$EXIT_CODE" != "0" ]; then
  echo "Migration failed — aborting deployment"
  exit 1
fi

echo "Migration succeeded — proceeding with deployment"
```

`aws ecs wait tasks-stopped` polls every 6 seconds with a maximum wait of 10 minutes. If your migrations take longer than 10 minutes, the wait will time out with an error before the task finishes. In that case, replace the `wait` with a polling loop checking `lastStatus`.

### 9.2 Update Services After Successful Migration

```bash
# Update api service — force new deployment with the latest task definition
aws ecs update-service \
  --cluster enterprise-todo-prod \
  --service enterprise-todo-api \
  --task-definition enterprise-todo-api \
  --force-new-deployment

aws ecs update-service \
  --cluster enterprise-todo-prod \
  --service enterprise-todo-portal-api \
  --task-definition enterprise-todo-portal-api \
  --force-new-deployment

# Wait for both services to reach steady state
aws ecs wait services-stable \
  --cluster enterprise-todo-prod \
  --services enterprise-todo-api enterprise-todo-portal-api
```

`aws ecs wait services-stable` polls until `runningCount == desiredCount` and all health checks pass. This is safe to run in CI — it blocks the workflow until the deployment is complete or times out.

### Verify: Migrator Logs

```bash
aws logs get-log-events \
  --log-group-name /ecs/enterprise-todo-migrator \
  --log-stream-name "migrator/migrator/$(echo $TASK_ARN | cut -d'/' -f3)" \
  --query 'events[*].message' \
  --output text
# Expected: "Initialising data source...", "Running pending migrations...",
#           "Executed N migration(s):", "  - <MigrationName>", "Migrations complete."
```

---

## 10. GitHub Actions CD Pipeline

This extends the CI pipeline from Part 19. The CI pipeline runs on every push; this CD pipeline runs on push to `main` only.

### 10.1 OIDC IAM Role for GitHub Actions

Never store long-lived AWS access keys in GitHub Secrets. Use OIDC — GitHub exchanges a short-lived token for temporary AWS credentials with no secret storage required.

```bash
# Create OIDC identity provider for GitHub Actions
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

# Create the deployment role
aws iam create-role \
  --role-name enterprise-todo-github-actions-deploy \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::123456789:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:your-org/enterprise-todo:*"
        }
      }
    }]
  }'
```

Attach the deployment policy:

```bash
aws iam put-role-policy \
  --role-name enterprise-todo-github-actions-deploy \
  --policy-name DeployPolicy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload"
        ],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": [
          "ecs:UpdateService",
          "ecs:RunTask",
          "ecs:DescribeTasks",
          "ecs:DescribeServices",
          "ecs:RegisterTaskDefinition"
        ],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": "iam:PassRole",
        "Resource": "arn:aws:iam::123456789:role/enterprise-todo-ecs-execution-role"
      },
      {
        "Effect": "Allow",
        "Action": [
          "logs:GetLogEvents",
          "logs:DescribeLogStreams"
        ],
        "Resource": "arn:aws:logs:ap-southeast-1:123456789:log-group:/ecs/enterprise-todo-*"
      }
    ]
  }'
```

`iam:PassRole` is required because `ecs:RunTask` and `ecs:RegisterTaskDefinition` accept an `executionRoleArn` — AWS verifies that the caller has permission to pass the specified role before accepting the task definition.

### 10.2 Full CD Workflow

```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on:
  push:
    branches: [main]

env:
  AWS_REGION: ap-southeast-1
  ECR_REGISTRY: 123456789.dkr.ecr.ap-southeast-1.amazonaws.com
  ECS_CLUSTER: enterprise-todo-prod

permissions:
  id-token: write # required for OIDC
  contents: read

jobs:
  build-and-push:
    name: Build and push Docker images
    runs-on: ubuntu-latest
    outputs:
      image-tag: ${{ steps.meta.outputs.tag }}

    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::123456789:role/enterprise-todo-github-actions-deploy
          aws-region: ${{ env.AWS_REGION }}

      - name: Login to ECR
        uses: aws-actions/amazon-ecr-login@v2

      - name: Set image tag
        id: meta
        run: echo "tag=${{ github.sha }}" >> $GITHUB_OUTPUT

      - name: Build and push api image
        run: |
          docker build \
            -f apps/api/Dockerfile \
            -t $ECR_REGISTRY/enterprise-todo/api:${{ steps.meta.outputs.tag }} \
            -t $ECR_REGISTRY/enterprise-todo/api:latest \
            .
          docker push $ECR_REGISTRY/enterprise-todo/api:${{ steps.meta.outputs.tag }}
          docker push $ECR_REGISTRY/enterprise-todo/api:latest

      - name: Build and push portal-api image
        run: |
          docker build \
            -f apps/portal-api/Dockerfile \
            -t $ECR_REGISTRY/enterprise-todo/portal-api:${{ steps.meta.outputs.tag }} \
            -t $ECR_REGISTRY/enterprise-todo/portal-api:latest \
            .
          docker push $ECR_REGISTRY/enterprise-todo/portal-api:${{ steps.meta.outputs.tag }}
          docker push $ECR_REGISTRY/enterprise-todo/portal-api:latest

      - name: Build and push migrator image
        run: |
          docker build \
            -f apps/api/Dockerfile.migrator \
            -t $ECR_REGISTRY/enterprise-todo/migrator:${{ steps.meta.outputs.tag }} \
            -t $ECR_REGISTRY/enterprise-todo/migrator:latest \
            .
          docker push $ECR_REGISTRY/enterprise-todo/migrator:${{ steps.meta.outputs.tag }}
          docker push $ECR_REGISTRY/enterprise-todo/migrator:latest

  migrate:
    name: Run database migrations
    runs-on: ubuntu-latest
    needs: build-and-push

    steps:
      - name: Configure AWS credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::123456789:role/enterprise-todo-github-actions-deploy
          aws-region: ${{ env.AWS_REGION }}

      - name: Run migrator ECS task
        id: run-migrator
        run: |
          TASK_ARN=$(aws ecs run-task \
            --cluster $ECS_CLUSTER \
            --task-definition enterprise-todo-migrator \
            --launch-type FARGATE \
            --network-configuration "awsvpcConfiguration={
              subnets=[subnet-private-aaa111,subnet-private-bbb222],
              securityGroups=[sg-ecs-xxxxxxxx],
              assignPublicIp=DISABLED
            }" \
            --query 'tasks[0].taskArn' \
            --output text)

          echo "task-arn=$TASK_ARN" >> $GITHUB_OUTPUT
          echo "Migrator task: $TASK_ARN"

          aws ecs wait tasks-stopped \
            --cluster $ECS_CLUSTER \
            --tasks "$TASK_ARN"

          EXIT_CODE=$(aws ecs describe-tasks \
            --cluster $ECS_CLUSTER \
            --tasks "$TASK_ARN" \
            --query 'tasks[0].containers[0].exitCode' \
            --output text)

          echo "Migrator exit code: $EXIT_CODE"

          if [ "$EXIT_CODE" != "0" ]; then
            echo "Migration failed — dumping logs"
            STREAM=$(aws logs describe-log-streams \
              --log-group-name /ecs/enterprise-todo-migrator \
              --order-by LastEventTime \
              --descending \
              --max-items 1 \
              --query 'logStreams[0].logStreamName' \
              --output text)
            aws logs get-log-events \
              --log-group-name /ecs/enterprise-todo-migrator \
              --log-stream-name "$STREAM" \
              --query 'events[*].message' \
              --output text
            exit 1
          fi

  deploy:
    name: Deploy api and portal-api
    runs-on: ubuntu-latest
    needs: migrate

    steps:
      - name: Configure AWS credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::123456789:role/enterprise-todo-github-actions-deploy
          aws-region: ${{ env.AWS_REGION }}

      - name: Update api task definition with new image
        id: api-task-def
        uses: aws-actions/amazon-ecs-render-task-definition@v1
        with:
          task-definition: infra/task-definitions/api.json
          container-name: api
          image: 123456789.dkr.ecr.ap-southeast-1.amazonaws.com/enterprise-todo/api:${{ needs.build-and-push.outputs.image-tag }}

      - name: Deploy api to ECS
        uses: aws-actions/amazon-ecs-deploy-task-definition@v2
        with:
          task-definition: ${{ steps.api-task-def.outputs.task-definition }}
          service: enterprise-todo-api
          cluster: ${{ env.ECS_CLUSTER }}
          wait-for-service-stability: true

      - name: Update portal-api task definition with new image
        id: portal-task-def
        uses: aws-actions/amazon-ecs-render-task-definition@v1
        with:
          task-definition: infra/task-definitions/portal-api.json
          container-name: portal-api
          image: 123456789.dkr.ecr.ap-southeast-1.amazonaws.com/enterprise-todo/portal-api:${{ needs.build-and-push.outputs.image-tag }}

      - name: Deploy portal-api to ECS
        uses: aws-actions/amazon-ecs-deploy-task-definition@v2
        with:
          task-definition: ${{ steps.portal-task-def.outputs.task-definition }}
          service: enterprise-todo-portal-api
          cluster: ${{ env.ECS_CLUSTER }}
          wait-for-service-stability: true
```

The `amazon-ecs-render-task-definition` action substitutes only the image URI in the task definition JSON and writes an updated file. The `amazon-ecs-deploy-task-definition` action registers the updated task definition and calls `update-service`. Both actions are official AWS GitHub Actions — prefer them over raw `aws ecs` CLI calls in CD workflows because they handle task definition ARN resolution and service wait logic reliably.

### Verify: Deployment End-to-End

After a push to `main`:

```bash
# Watch the GitHub Actions workflow
gh run watch

# After the workflow completes, confirm new tasks are running
aws ecs describe-services \
  --cluster enterprise-todo-prod \
  --services enterprise-todo-api \
  --query 'services[0].deployments[*].[status,runningCount,desiredCount,taskDefinition]' \
  --output table
# Expected: PRIMARY status with runningCount == desiredCount, new task definition revision

# Confirm the new image SHA is deployed
aws ecs describe-tasks \
  --cluster enterprise-todo-prod \
  --tasks $(aws ecs list-tasks --cluster enterprise-todo-prod --service-name enterprise-todo-api --query 'taskArns[0]' --output text) \
  --query 'tasks[0].containers[0].image' \
  --output text
# Expected: image URI ending in :$GITHUB_SHA
```

---

## 11. CloudWatch Logs and Alarms

### 11.1 Log Groups

The task definition `awslogs-create-group: "true"` creates the log groups automatically on first task launch. Optionally set a retention policy to avoid unbounded log storage costs:

```bash
aws logs put-retention-policy \
  --log-group-name /ecs/enterprise-todo-api \
  --retention-in-days 30

aws logs put-retention-policy \
  --log-group-name /ecs/enterprise-todo-portal-api \
  --retention-in-days 30

aws logs put-retention-policy \
  --log-group-name /ecs/enterprise-todo-migrator \
  --retention-in-days 90
```

30 days covers most incident investigations. 90 days for the migrator ensures migration history is retained for auditing.

### 11.2 Metric Filter for ERROR Logs

The `LoggingInterceptor` from Part 15 writes structured logs. When `NODE_ENV=production`, NestJS's built-in logger writes to stdout in a format that includes the log level. Create a metric filter that counts lines containing `[ERROR]`:

```bash
aws logs put-metric-filter \
  --log-group-name /ecs/enterprise-todo-api \
  --filter-name api-error-count \
  --filter-pattern "[timestamp, requestId, level=ERROR, ...]" \
  --metric-transformations \
    metricName=ApiErrorCount,metricNamespace=EnterpriseToDoApp,metricValue=1,defaultValue=0
```

### 11.3 CloudWatch Alarm on Error Rate

```bash
# Alarm fires if more than 10 errors occur in a 5-minute window, two evaluation periods in a row
aws cloudwatch put-metric-alarm \
  --alarm-name "enterprise-todo-api-high-error-rate" \
  --alarm-description "API error log count exceeds threshold" \
  --metric-name ApiErrorCount \
  --namespace EnterpriseToDoApp \
  --statistic Sum \
  --period 300 \
  --threshold 10 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --evaluation-periods 2 \
  --datapoints-to-alarm 2 \
  --treat-missing-data notBreaching \
  --alarm-actions "arn:aws:sns:ap-southeast-1:123456789:enterprise-todo-alerts"
```

### 11.4 ALB 5xx Alarm

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "enterprise-todo-alb-5xx" \
  --alarm-description "ALB returning 5xx responses" \
  --metric-name HTTPCode_Target_5XX_Count \
  --namespace AWS/ApplicationELB \
  --dimensions Name=LoadBalancer,Value=$ALB_SUFFIX \
  --statistic Sum \
  --period 60 \
  --threshold 5 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --evaluation-periods 3 \
  --datapoints-to-alarm 2 \
  --treat-missing-data notBreaching \
  --alarm-actions "arn:aws:sns:ap-southeast-1:123456789:enterprise-todo-alerts"
```

Create the SNS topic and subscribe your email or Slack webhook:

```bash
aws sns create-topic --name enterprise-todo-alerts
aws sns subscribe \
  --topic-arn arn:aws:sns:ap-southeast-1:123456789:enterprise-todo-alerts \
  --protocol email \
  --notification-endpoint ops@yourdomain.com
```

### Verify: Alarm State

```bash
aws cloudwatch describe-alarms \
  --alarm-names "enterprise-todo-api-high-error-rate" "enterprise-todo-alb-5xx" \
  --query 'MetricAlarms[*].[AlarmName,StateValue,StateReason]' \
  --output table
# Expected: both alarms in OK state
# If INSUFFICIENT_DATA, wait a few minutes for the first metrics to arrive
```

---

## 12. Production Go-Live Checklist

Work through this checklist before routing real traffic to production.

**Identity and Keys**

- [ ] Unique RSA key pairs generated per environment — user API and portal API keys are different
- [ ] 12 key files exist (user private + user public + portal private + portal public) x (dev / staging / prod)
- [ ] All 12 files stored in Secrets Manager, never committed to git
- [ ] Staging task definitions reference `enterprise-todo/staging/` secrets
- [ ] Production task definitions reference `enterprise-todo/production/` secrets

**Database**

- [ ] RDS Multi-AZ enabled on production instance
- [ ] RDS deletion protection enabled
- [ ] DB password stored in Secrets Manager (not in task definition `environment` array)
- [ ] Security group allows port 5432 only from ECS task security group — not from 0.0.0.0/0
- [ ] Migration one-off task tested on staging and exited 0
- [ ] `migration:revert` tested locally before deploying to staging

**Cache and Queues**

- [ ] ElastiCache TLS enabled (`transit-encryption-enabled`)
- [ ] `BullModule` configured with `tls: {}` in production
- [ ] `RedisPubSub` configured with `tls: {}` in production
- [ ] Security group allows port 6379 only from ECS task security group

**Networking**

- [ ] ALB HTTPS listener with valid ACM certificate
- [ ] HTTP to HTTPS redirect on port 80
- [ ] ECS tasks in private subnets with no public IP
- [ ] RDS and ElastiCache in private subnets

**Application**

- [ ] `NODE_ENV=production` in all ECS task definitions — disables GraphQL playground, enables full Helmet CSP
- [ ] `HealthResolver` has `@SkipThrottle()` — ALB health checks will not hit rate limiter
- [ ] `TWOFA_BYPASS_PASSWORD` is NOT set in any production environment variable or secret
- [ ] `PortalJwtStrategy` is NOT registered in the `api` task definition — portal strategy is portal-api only
- [ ] `RequestPlatformInterceptor` mounted in both `apps/api` (platform `'user'`) and `apps/portal-api` (platform `'portal'`)
- [ ] JWT payloads include `platform` claim — tokens cannot cross platform boundaries

**Deployment**

- [ ] GitHub Actions OIDC role configured — no long-lived access keys in GitHub Secrets
- [ ] CD pipeline runs migrator before deploying api and portal-api
- [ ] `aws ecs wait services-stable` at the end of deploy job — workflow fails if deployment does not stabilise

**Observability**

- [ ] CloudWatch log groups created with 30-day retention
- [ ] Error rate metric filter created for `/ecs/enterprise-todo-api`
- [ ] CloudWatch alarms configured and in OK state
- [ ] SNS topic subscribed and email confirmed

**Media (from Part 17)**

- [ ] S3 bucket has `Block Public Access` enabled — only CloudFront can read objects
- [ ] CloudFront distribution using ACM certificate for `media.yourdomain.com`
- [ ] Signed URL TTL appropriate for your use case (15 minutes for user-uploaded content)

---

## Summary: Before vs After

| Concern           | Local Docker Compose                           | Production AWS                                                        |
| ----------------- | ---------------------------------------------- | --------------------------------------------------------------------- |
| Container runtime | Docker Desktop on developer machine            | ECS Fargate (managed, auto-scaling)                                   |
| Database          | PostgreSQL 15 container, data in Docker volume | RDS PostgreSQL 15 Multi-AZ, automated backups                         |
| Cache / queues    | Redis container, ephemeral                     | ElastiCache Redis 7.x with TLS, private subnet                        |
| Secrets           | `.env` file on disk                            | AWS Secrets Manager, injected at task launch                          |
| RSA keys          | Single dev key pair                            | Unique key pairs per environment × per app                            |
| Image registry    | Local Docker daemon                            | ECR with image scanning and lifecycle policy                          |
| Deployments       | `docker-compose up --build`                    | GitHub Actions CD: build → migrate → rolling deploy                   |
| Migrations        | `yarn api:migration:run` in terminal           | One-off ECS task before traffic routes to new image                   |
| Load balancing    | Not applicable (single container)              | ALB with host-based routing, HTTPS, ACM certificate                   |
| Observability     | `docker-compose logs -f`                       | CloudWatch Logs with metric filters and alarms                        |
| Network access    | All ports exposed to localhost                 | Only ALB accessible from internet; everything else in private subnets |

---

## What You Have Now

With the complete backend deployed and running in production, Part 21 — Claude Code AI Development Layer shows how to 10x your development speed now that you understand the architecture deeply. Parts 21–24 form the AI capstone of the series.

The complete enterprise-grade fullstack NestJS stack is now deployed and production-ready:

**The Complete Enterprise-Grade Fullstack NestJS Stack**

**Foundation**

- **`apps/api/src/main.ts`** — NestJS user API with global pipes, guards, interceptors, filters, and Helmet
- **`apps/portal-api/src/main.ts`** — NestJS admin portal API with separate auth strategy and platform interceptor
- **`apps/web/`** — Next.js 16 App Router frontend with Apollo Client v4 and Tailwind CSS v4
- **`libs/core/`** — Shared Joi validation schema, typed `AppConfig`, queue name constants
- **`libs/contracts/`** — Shared TypeScript types across api and web

**Data Layer**

- **TypeORM 1.x** with `SnakeNamingStrategy` — all columns snake_case, no magic
- **`AbstractEntity`** from `nestjs-dev-utilities` — `id`, `createdAt`, `updatedAt` on every entity
- **`AbstractDto`** — DTO base with `fromEntity` mapper
- **`AuditSubscriber`** — automatic audit log on every entity mutation
- **Migrations** — every schema change tracked, reversible, and tested before production

**CQRS Architecture**

- **`nestjs-typed-cqrs`** — type-safe `TypedCommand<T>` and `TypedQuery<T>` buses throughout
- **9-step module pattern** — Entity → Constants → DTOs → Inputs → Handlers → Index → Service → Resolver → Module
- **Handlers are one-liners** — all business logic lives in services, never handlers or resolvers
- **`TypeOrmQueryService<Entity>`** as service base — auto-implements find, findOne, create, update, delete with filtering

**GraphQL API**

- **Apollo Server v5** — code-first schema with `@Resolver`, `@Query`, `@Mutation`, `@ResolveField`
- **Relay cursor pagination** — `Connection` types on all list queries
- **DataLoader** with `Scope.REQUEST` — N+1 queries eliminated for all relation fields
- **Subscriptions** over Redis PubSub — real-time updates without in-process state

**Auth and Permissions**

- **Passport JWT RS256** — asymmetric key pairs, separate strategies for user and portal APIs
- **`AccessTokenFactory` / `PortalAccessTokenFactory`** — tokens stamped with `platform` claim
- **`RequestPlatformInterceptor`** — cross-platform token usage rejected at the boundary
- **`ACPermissionGuard`** with `@UseACGuard('MODULE', ['slug'])` — role-based permissions seeded and enforced
- **`PortalJwtStrategy`** isolated to `apps/portal-api` only — cannot leak into user API

**Security**

- **Helmet** — full CSP in production, relaxed for GraphQL sandbox in development
- **`@nestjs/throttler`** — rate limiting on all public endpoints
- **`ValidationPipe`** with `forbidNonWhitelisted: true` — unknown fields rejected globally
- **`AllExceptionsFilter`** — consistent error shapes, stack traces in logs only
- **Single-use tokens** claimed immediately — no replay attacks on password reset or email verification
- **API keys stored as SHA-256 hashes** — raw key never persisted

**Async and Performance**

- **Bull queues backed by Redis** — email, notifications, and heavy computation are always async
- **`graphql-depth-limit`** (max 7) and complexity guard (max 50) — DoS protection in production
- **`@Index`** on all filtered columns — no sequential scans on hot query paths
- **Running number service** with pessimistic write lock — no duplicate sequence numbers under concurrent load

**Media and Storage**

- **S3 + CloudFront** — media uploads with signed URLs, TTL-controlled access, no public bucket exposure
- **`S3MediaService`** behind interface — SDK never embedded in business logic directly

**Email**

- **`nodemailer`** with direct transport — all transactional email via Bull queue for async delivery
- **`requestPasswordReset` always returns true** — no user enumeration via email existence check

**Two-Factor Authentication**

- **`otplib` TOTP** — RFC 6238 compliant, 30-second windows, QR code provisioning
- **`TWOFA_BYPASS_PASSWORD`** for test environments only — hard-blocked from staging and production

**Production Infrastructure**

- **ECS Fargate** — containerised, auto-scaling, no server management
- **RDS PostgreSQL 15 Multi-AZ** — automated failover, 7-day backups, deletion protection
- **ElastiCache Redis 7.x** — TLS in-transit and at-rest, private subnet
- **ALB with host-based routing** — separate subdomains for api and portal-api, HTTPS enforced
- **AWS Secrets Manager** — all secrets including RSA keys, never in environment arrays
- **Unique RSA key pairs per environment** — staging tokens cannot authenticate against production
- **One-off ECS migration tasks** — no race conditions, no `synchronize: true` in any environment
- **GitHub Actions CD with OIDC** — no long-lived access keys, migrate → deploy sequence enforced
- **CloudWatch Logs + alarms** — structured logs from `LoggingInterceptor` with metric filters and SNS alerts

The stack covers every layer of a real production application: data integrity, type safety, auth separation, async processing, media handling, two-factor auth, and cloud deployment. The patterns established here — CQRS with typed buses, permission guards with seeded slugs, platform-separated JWT strategies, one-off migration tasks — scale from the current single-tenant Nx monorepo to a multi-tenant, multi-region deployment without architectural rewrites.
