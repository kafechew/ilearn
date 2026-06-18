---
author: Kai
pubDatetime: 2026-05-09T09:00:00+08:00
title: Extended Auth — Email Service, Secured Tokens & Two-Factor Authentication
featured: false
draft: false
slug: 6109-extended-auth-email-secured-tokens-2fa
tags:
  - deeptech
  - meteorjs
  - nestjs
  - security
  - auth
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/09-extended-auth-email-secured-tokens-2fa.png"
description: Add transactional email via Bull queues, a single-use SecuredToken module for password reset and email verification, and TOTP two-factor authentication with otplib and qrcode.
---

In Part 8 we built JWT RS256 auth with guards. Now we extend it with email verification, password reset via single-use tokens, and TOTP 2FA before moving to the case studies.

## What This Part Covers

- Transactional email via `nodemailer` queued through Bull — never block an HTTP response for email delivery
- `SecuredTokenEntity` — single-use, expiring tokens for password reset and email verification
- Password reset flow: request token → email link → verify token → update password
- Email verification flow: signup → verify email → activate account
- Two-factor authentication (TOTP) with `otplib`, QR codes with `qrcode`
- `TWOFA_BYPASS_PASSWORD` environment variable for local development and testing
- Login gate: unverified accounts cannot authenticate

---

## Meteor Equivalents

| Concern               | Meteor way                                                           | Enterprise NestJS                                                   |
| --------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Send email            | `accounts-sendEmail`, blocking inline `Email.send()`                 | `nodemailer` inside a Bull job — non-blocking, retries on failure   |
| Password reset tokens | `Accounts.sendResetPasswordEmail()` — tokens stored in user document | `SecuredTokenEntity` — separate table, single-use, hard expiry      |
| Email verification    | `Accounts.sendVerificationEmail()`                                   | Same `SecuredTokenEntity` pattern, type `EMAIL_VERIFICATION`        |
| Two-factor auth       | No native 2FA in Meteor — third-party packages only                  | `otplib` TOTP + QR code binding flow, stored secret on `UserEntity` |
| Token expiry          | Manual `expiresAt` field in user document                            | `expiresAt` on `SecuredTokenEntity`, enforced in every query        |
| Background jobs       | `Meteor.setTimeout` / `synced-cron` — in-memory, lost on restart     | Bull queue — Redis-backed, retried, survives pod crashes            |
| Schema definition     | Schema-less MongoDB document (`new Mongo.Collection`)                | `@Entity()` class — schema enforced at DB and TypeScript level      |
| Method routing        | Logic mixed into `Meteor.methods` body                               | CQRS: Command/Query classes routed via `CommandBus` / `QueryBus`    |
| Schema migrations     | No migrations — schema changes happen silently                       | TypeORM migrations — every change versioned, reversible, reviewable |
| Auth token signing    | DDP session token — opaque string, no cryptographic claims           | RS256 JWT — private key signs, public key verifies, cannot be forged|

Meteor's `Accounts` package handled all of this in one opaque bundle you could not extend. The NestJS pattern breaks it into composable, testable pieces — each with a clear responsibility.

---

## 1. Email Service via Bull Queue

### 1.1 Why Bull for Email

Sending email inside a resolver or service method is a hidden time bomb:

```
Without a queue:
  register() ──→ save user ──→ send email (300ms, external SMTP) ──→ return response
                                           ^^^
                                           If SMTP is slow, user waits
                                           If SMTP fails, register() throws

With a queue:
  register() ──→ save user ──→ enqueue job (2ms) ──→ return response (fast)
                                    │
                                    ▼  (background worker)
                               Bull job ──→ nodemailer ──→ retry on failure
```

Bull jobs survive process restarts. If your API pod crashes between enqueue and delivery, the job is still in Redis waiting to be processed.

> **Bull Queue — kitchen ticket rail:** The waiter (web process) takes your order, clips the ticket to the rail, and immediately returns to serve the next table. The chef (worker) processes tickets at their own pace. The web process never stands next to the stove watching the email send — it enqueues and returns in 2ms.

> **From Meteor?** `Meteor.setTimeout` and `synced-cron` were the closest patterns in Meteor — but both were in-memory and lost jobs on restart. Bull gives you: retry with backoff, job priorities, dead-letter queues, job progress tracking, and a Bull Board UI — all backed by Redis so jobs survive pod restarts.

**Memory hook:** Bull Queue = ticket rail. Web enqueues and returns immediately. Worker processes async. Redis-backed = survives restarts.

### 1.2 Install Dependencies

```bash
yarn add nodemailer @types/nodemailer
```

You also need Bull from Part 11 (`@nestjs/bull`, `bull`) already installed. If not:

```bash
yarn add @nestjs/bull bull
yarn add -D @types/bull
```

### 1.3 Local SMTP with Mailpit

For local development, use Mailpit — a zero-config SMTP catcher with a web UI. Add it to your `docker-compose.dev.yml`:

```yaml
mailpit:
  image: axllent/mailpit
  container_name: enterprise-todo-mailpit
  restart: unless-stopped
  ports:
    - "8025:8025" # Web UI — open http://localhost:8025 to read emails
    - "1025:1025" # SMTP — point nodemailer here
```

Run it:

```bash
yarn docker:dev
```

All outbound email is now captured locally. Nothing reaches a real inbox.

### 1.4 Add Email Config to the Config Mapper

Extend your config mapper at `apps/api/src/config/config.mapper.ts`:

```typescript
// apps/api/src/config/config.mapper.ts
import { registerAs } from "@nestjs/config";

export interface AppConfig {
  port: number;
  database: {
    host: string;
    port: number;
    name: string;
    user: string;
    password: string;
  };
  jwt: {
    privateKey: string;
    publicKey: string;
    refreshPrivateKey: string;
    refreshPublicKey: string;
  };
  email: {
    host: string;
    port: number;
    user: string | undefined;
    pass: string | undefined;
    from: string;
  };
  webUrl: string;
}

export const emailConfig = registerAs("email", () => ({
  host: process.env.SMTP_HOST || "localhost",
  port: parseInt(process.env.SMTP_PORT || "1025", 10),
  user: process.env.SMTP_USER || undefined,
  pass: process.env.SMTP_PASS || undefined,
  from:
    process.env.SMTP_FROM || '"Enterprise Todo" <noreply@enterprise-todo.dev>',
}));

export const appConfig = registerAs("app", () => ({
  webUrl: process.env.WEB_URL || "http://localhost:3000",
}));
```

Add to your `.env`:

```
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_USER=
SMTP_PASS=
SMTP_FROM="Enterprise Todo" <noreply@enterprise-todo.dev>
WEB_URL=http://localhost:3000
```

### 1.5 EmailService

```typescript
// apps/api/src/modules/email/email.service.ts
import { Injectable, Logger } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import * as nodemailer from "nodemailer";

@Injectable()
export class EmailService {
  private readonly logger = new Logger(EmailService.name);
  private readonly transporter: nodemailer.Transporter;
  private readonly from: string;

  constructor(private readonly configService: ConfigService) {
    const host = this.configService.get<string>("email.host") ?? "localhost";
    const port = this.configService.get<number>("email.port") ?? 1025;
    const user = this.configService.get<string | undefined>("email.user");
    const pass = this.configService.get<string | undefined>("email.pass");
    this.from =
      this.configService.get<string>("email.from") ??
      '"Enterprise Todo" <noreply@enterprise-todo.dev>';

    this.transporter = nodemailer.createTransport({
      host,
      port,
      secure: port === 465,
      auth: user ? { user, pass } : undefined,
    });
  }

  async sendPasswordReset(to: string, resetUrl: string): Promise<void> {
    await this.transporter.sendMail({
      from: this.from,
      to,
      subject: "Reset your password",
      html: `
        <p>You requested a password reset for your Enterprise Todo account.</p>
        <p><a href="${resetUrl}">Click here to reset your password</a></p>
        <p>This link expires in 1 hour. If you did not request this, ignore this email.</p>
      `,
    });
    this.logger.log(`Password reset email sent to ${to}`);
  }

  async sendEmailVerification(to: string, verifyUrl: string): Promise<void> {
    await this.transporter.sendMail({
      from: this.from,
      to,
      subject: "Verify your email address",
      html: `
        <p>Welcome to Enterprise Todo. Please verify your email address.</p>
        <p><a href="${verifyUrl}">Click here to verify your email</a></p>
        <p>This link expires in 24 hours.</p>
      `,
    });
    this.logger.log(`Verification email sent to ${to}`);
  }
}
```

### 1.6 Email Queue Processor

```typescript
// apps/api/src/modules/email/email.processor.ts
import { Process, Processor } from "@nestjs/bull";
import { Logger } from "@nestjs/common";
import { Job } from "bull";
import { EmailService } from "./email.service";

export const EMAIL_QUEUE = "email";

export interface SendPasswordResetJobData {
  to: string;
  resetUrl: string;
}

export interface SendEmailVerificationJobData {
  to: string;
  verifyUrl: string;
}

@Processor(EMAIL_QUEUE)
export class EmailProcessor {
  private readonly logger = new Logger(EmailProcessor.name);

  constructor(private readonly emailService: EmailService) {}

  @Process("send-password-reset")
  async handlePasswordReset(job: Job<SendPasswordResetJobData>): Promise<void> {
    this.logger.debug(`Processing password reset email for ${job.data.to}`);
    await this.emailService.sendPasswordReset(job.data.to, job.data.resetUrl);
  }

  @Process("send-email-verification")
  async handleEmailVerification(
    job: Job<SendEmailVerificationJobData>
  ): Promise<void> {
    this.logger.debug(`Processing email verification for ${job.data.to}`);
    await this.emailService.sendEmailVerification(
      job.data.to,
      job.data.verifyUrl
    );
  }
}
```

### 1.7 EmailModule

```typescript
// apps/api/src/modules/email/email.module.ts
import { BullModule } from "@nestjs/bull";
import { Module } from "@nestjs/common";
import { EMAIL_QUEUE } from "./email.processor";
import { EmailProcessor } from "./email.processor";
import { EmailService } from "./email.service";

@Module({
  imports: [
    BullModule.registerQueue({
      name: EMAIL_QUEUE,
      defaultJobOptions: {
        attempts: 3,
        backoff: { type: "exponential", delay: 5000 },
        removeOnComplete: 100,
        removeOnFail: 200,
      },
    }),
  ],
  providers: [EmailService, EmailProcessor],
  exports: [EmailService, BullModule],
})
export class EmailModule {}
```

Register `EmailModule` and the `emailConfig` in `AppModule`. Also register the queue in `BullModule.forRootAsync()` (already set up in Part 11 with your Redis config).

### 1.8 Boot Test

Start the stack:

```bash
yarn docker:dev
yarn api:dev
```

Open GraphQL Playground at `http://localhost:3333/graphql`. Run a registration mutation (from Part 8). Open `http://localhost:8025` — the verification email should appear within a second or two. The API response should return immediately without waiting for delivery.

---

## 2. SecuredToken Entity

A `SecuredTokenEntity` is a single-use, time-limited token that authorises one specific action — resetting a password or verifying an email. Using a separate table (rather than storing tokens on the user row) lets you:

- Issue multiple outstanding tokens per user (e.g. resend verification without invalidating the old one)
- Query by token string efficiently with a unique index
- Claim (not delete) tokens, preserving an audit trail
- Cascade-delete tokens automatically when the user is deleted

### 2.1 Enums

```typescript
// apps/api/src/modules/secured-token/secured-token.constant.ts
import { registerEnumType } from "@nestjs/graphql";

export enum SecuredTokenType {
  PASSWORD_RESET = "PASSWORD_RESET",
  EMAIL_VERIFICATION = "EMAIL_VERIFICATION",
}

export enum SecuredTokenStatus {
  ACTIVE = "ACTIVE",
  CLAIMED = "CLAIMED",
  EXPIRED = "EXPIRED",
}

export enum SecuredTokenMedium {
  EMAIL = "EMAIL",
  SMS = "SMS",
}

export const SECURED_TOKEN_PASSWORD_RESET_EXPIRY_MINUTES = 60;
export const SECURED_TOKEN_EMAIL_VERIFICATION_EXPIRY_MINUTES = 60 * 24; // 24 hours

registerEnumType(SecuredTokenType, { name: "SecuredTokenType" });
registerEnumType(SecuredTokenStatus, { name: "SecuredTokenStatus" });
registerEnumType(SecuredTokenMedium, { name: "SecuredTokenMedium" });
```

### 2.2 Entity

```typescript
// apps/api/src/modules/secured-token/secured-token.entity.ts
import { Column, Entity, Index, ManyToOne, RelationId } from "typeorm";
import { AbstractEntity } from "nestjs-dev-utilities";
import { UserEntity } from "../user/user.entity";
import {
  SecuredTokenMedium,
  SecuredTokenStatus,
  SecuredTokenType,
} from "./secured-token.constant";

@Entity({ name: "secured_token" })
export class SecuredTokenEntity extends AbstractEntity {
  @Index()
  @Column({ unique: true })
  token: string;

  @Column({ type: "enum", enum: SecuredTokenType })
  type: SecuredTokenType;

  @Column({
    type: "enum",
    enum: SecuredTokenStatus,
    default: SecuredTokenStatus.ACTIVE,
  })
  status: SecuredTokenStatus;

  @Column({
    type: "enum",
    enum: SecuredTokenMedium,
    default: SecuredTokenMedium.EMAIL,
  })
  medium: SecuredTokenMedium;

  @Column({ type: "timestamptz" })
  expiresAt: Date;

  @ManyToOne(() => UserEntity, { onDelete: "CASCADE", nullable: false })
  user: UserEntity;

  @RelationId((st: SecuredTokenEntity) => st.user)
  @Index()
  @Column()
  userId: number;
}
```

`onDelete: 'CASCADE'` means deleting a user deletes all their pending tokens. The `token` column is unique — no two rows can hold the same token string. The `@Index()` on `userId` speeds up "find all tokens for this user" queries.

> **Entity — official record template:** Every field is defined — name, type, required, max length. Every filled-in form (database row) must match. `SecuredTokenEntity` is the official record template; each issued token is a completed copy on file. When the hospital revises the template (migration), all future records follow the new version.

> **AbstractEntity — company letterhead:** `SecuredTokenEntity` extends `AbstractEntity`, which pre-prints `id`, `createdAt`, `updatedAt`, and `deletedAt` on every entity. No one types the letterhead from scratch — each entity just adds its unique content.

> **From Meteor?** In Meteor, password reset tokens lived as nested fields on the user document — no type system, no expiry enforcement, no audit trail. `SecuredTokenEntity` is a separate table with typed enums, a hard `expiresAt` column, a `CLAIMED` status for audit, and `ON DELETE CASCADE` for clean teardown when a user is removed.

**Memory hook:** Entity = official record template. Schema + TypeScript type in one class. Never `synchronize: true` in prod.

---

## 3. SecuredToken Module (Full 9-Step Pattern)

### 3.1 DTOs

> **AbstractDto — standard response envelope:** `SecuredTokenDto` extends `AbstractDto`, which pre-prints `id`, `createdAt`, and `updatedAt` as `@Field()` on every response type. The client always knows where to find the id and timestamps — they're on every envelope. The raw `token` string is intentionally excluded from `@Field()` so it never appears in the GraphQL schema.

```typescript
// apps/api/src/modules/secured-token/dto/secured-token.dto.ts
import { Field, ID, ObjectType } from "@nestjs/graphql";
import { AbstractDto } from "nestjs-dev-utilities";
import {
  SecuredTokenMedium,
  SecuredTokenStatus,
  SecuredTokenType,
} from "../secured-token.constant";

@ObjectType("SecuredToken")
export class SecuredTokenDto extends AbstractDto {
  @Field(() => SecuredTokenType)
  type: SecuredTokenType;

  @Field(() => SecuredTokenStatus)
  status: SecuredTokenStatus;

  @Field(() => SecuredTokenMedium)
  medium: SecuredTokenMedium;

  @Field()
  expiresAt: Date;

  @Field(() => ID)
  userId: number;

  // token is intentionally NOT a @Field() — never expose the raw token string via GraphQL
}
```

```typescript
// apps/api/src/modules/secured-token/dto/secured-token.input.ts
import { InputType, Field } from "@nestjs/graphql";
import { IsEnum, IsInt, IsPositive } from "class-validator";
import {
  SecuredTokenMedium,
  SecuredTokenType,
} from "../secured-token.constant";

@InputType()
export class CreateSecuredTokenInput {
  @Field(() => SecuredTokenType)
  @IsEnum(SecuredTokenType)
  type: SecuredTokenType;

  @Field(() => SecuredTokenMedium, { defaultValue: SecuredTokenMedium.EMAIL })
  @IsEnum(SecuredTokenMedium)
  medium: SecuredTokenMedium;

  @Field()
  @IsInt()
  @IsPositive()
  userId: number;
}
```

**Memory hook:** AbstractDto = response envelope. Pairs with AbstractEntity. All output DTOs extend it. Sensitive fields (like raw tokens) stay off `@Field()`.

### 3.2 CQRS Inputs

> **CQRS — two separate kitchens:** `CreateOneSecuredTokenCommand` and `ClaimSecuredTokenCommand` are the order kitchen — they mutate state. `FindOneActiveSecuredTokenQuery` is the reading kitchen — it only describes what exists without changing anything. Neither kitchen touches the other's stove.

> **CommandBus / QueryBus — postal sorting facility:** The resolver drops a Command or Query object into the bus. The bus reads the class name, routes it to the registered handler, and delivers the result. The resolver never imports the handler directly — it just drops the letter in the slot.

> **From Meteor?** `Meteor.methods` mixed the routing, the logic, and the database call in one block. CQRS separates these into three distinct files: the input class (the message), the handler (routing), and the service (logic). Each is independently testable.

**Memory hook:** CQRS = two kitchens. Commands mutate, Queries read. Handlers are thin one-liners. Logic lives in the Service.

```typescript
// apps/api/src/modules/secured-token/cqrs/secured-token.cqrs.input.ts
import { TypedCommand, TypedQuery } from "nestjs-typed-cqrs";
import { CreateSecuredTokenInput } from "../dto/secured-token.input";
import { SecuredTokenEntity } from "../secured-token.entity";
import { SecuredTokenType } from "../secured-token.constant";

// ── Commands ───────────────────────────────────────────────────────────────

export class CreateOneSecuredTokenCommand extends TypedCommand<SecuredTokenEntity> {
  constructor(public readonly args: { input: CreateSecuredTokenInput }) {
    super();
  }
}

export class ClaimSecuredTokenCommand extends TypedCommand<void> {
  constructor(public readonly args: { token: string }) {
    super();
  }
}

// ── Queries ────────────────────────────────────────────────────────────────

export class FindOneActiveSecuredTokenQuery extends TypedQuery<SecuredTokenEntity | null> {
  constructor(public readonly args: { token: string; type: SecuredTokenType }) {
    super();
  }
}
```

### 3.3 CQRS Handlers

```typescript
// apps/api/src/modules/secured-token/cqrs/secured-token.cqrs.handler.ts
import {
  CommandHandler,
  ICommandHandler,
  QueryHandler,
  IQueryHandler,
} from "@nestjs/cqrs";
import { SecuredTokenService } from "../secured-token.service";
import {
  ClaimSecuredTokenCommand,
  CreateOneSecuredTokenCommand,
  FindOneActiveSecuredTokenQuery,
} from "./secured-token.cqrs.input";

@CommandHandler(CreateOneSecuredTokenCommand)
export class CreateOneSecuredTokenCommandHandler implements ICommandHandler<CreateOneSecuredTokenCommand> {
  constructor(private readonly securedTokenService: SecuredTokenService) {}

  execute(message: CreateOneSecuredTokenCommand) {
    return this.securedTokenService.createOneSecuredToken(message.args.input);
  }
}

@CommandHandler(ClaimSecuredTokenCommand)
export class ClaimSecuredTokenCommandHandler implements ICommandHandler<ClaimSecuredTokenCommand> {
  constructor(private readonly securedTokenService: SecuredTokenService) {}

  execute(message: ClaimSecuredTokenCommand) {
    return this.securedTokenService.claimSecuredToken(message.args.token);
  }
}

@QueryHandler(FindOneActiveSecuredTokenQuery)
export class FindOneActiveSecuredTokenQueryHandler implements IQueryHandler<FindOneActiveSecuredTokenQuery> {
  constructor(private readonly securedTokenService: SecuredTokenService) {}

  execute(message: FindOneActiveSecuredTokenQuery) {
    return this.securedTokenService.findOneActiveSecuredToken(
      message.args.token,
      message.args.type
    );
  }
}
```

### 3.4 CQRS Index

```typescript
// apps/api/src/modules/secured-token/cqrs/index.ts
export * from "./secured-token.cqrs.input";
export * from "./secured-token.cqrs.handler";

export const SecuredTokenCqrsHandlers = [
  CreateOneSecuredTokenCommandHandler,
  ClaimSecuredTokenCommandHandler,
  FindOneActiveSecuredTokenQueryHandler,
];
```

### 3.5 Service

The service does three things: create a token with an expiry, find an active unexpired token, and claim a token.

> **Service — the specialist doctor:** `SecuredTokenService` examines the request, diagnoses the expiry and type, and prescribes the right action. It never answers the front desk phone (no HTTP concepts) and never does intake paperwork (no GraphQL concerns). It does the medicine: create tokens, find active tokens, claim them.

> **From Meteor?** In Meteor, this logic would live scattered across method bodies — no clear "this is where token logic lives" file. In NestJS, "where is the token logic?" is always `secured-token.service.ts`.

```typescript
// apps/api/src/modules/secured-token/secured-token.service.ts
import { Injectable, NotFoundException } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { LessThan, MoreThan, Repository } from "typeorm";
import * as crypto from "crypto";
import { SecuredTokenEntity } from "./secured-token.entity";
import {
  SECURED_TOKEN_EMAIL_VERIFICATION_EXPIRY_MINUTES,
  SECURED_TOKEN_PASSWORD_RESET_EXPIRY_MINUTES,
  SecuredTokenStatus,
  SecuredTokenType,
} from "./secured-token.constant";
import { CreateSecuredTokenInput } from "./dto/secured-token.input";

@Injectable()
export class SecuredTokenService {
  constructor(
    @InjectRepository(SecuredTokenEntity)
    private readonly securedTokenRepo: Repository<SecuredTokenEntity>
  ) {}

  async createOneSecuredToken(
    input: CreateSecuredTokenInput
  ): Promise<SecuredTokenEntity> {
    const expiryMinutes =
      input.type === SecuredTokenType.PASSWORD_RESET
        ? SECURED_TOKEN_PASSWORD_RESET_EXPIRY_MINUTES
        : SECURED_TOKEN_EMAIL_VERIFICATION_EXPIRY_MINUTES;

    const expiresAt = new Date(Date.now() + expiryMinutes * 60 * 1000);
    const token = crypto.randomUUID();

    const entity = this.securedTokenRepo.create({
      token,
      type: input.type,
      medium: input.medium,
      status: SecuredTokenStatus.ACTIVE,
      expiresAt,
      userId: input.userId,
    });

    return this.securedTokenRepo.save(entity);
  }

  async findOneActiveSecuredToken(
    token: string,
    type: SecuredTokenType
  ): Promise<SecuredTokenEntity | null> {
    return this.securedTokenRepo.findOne({
      where: {
        token,
        type,
        status: SecuredTokenStatus.ACTIVE,
        expiresAt: MoreThan(new Date()),
      },
      relations: ["user"],
    });
  }

  async claimSecuredToken(token: string): Promise<void> {
    const result = await this.securedTokenRepo.update(
      { token },
      { status: SecuredTokenStatus.CLAIMED }
    );

    if (result.affected === 0) {
      throw new NotFoundException("Token not found");
    }
  }
}
```

**Memory hook:** Service = specialist doctor. All business logic lives here. Never imports HTTP or GraphQL objects.

### 3.6 Module

> **Module — hospital wing:** `SecuredTokenModule` owns its internal staff (`SecuredTokenService`, the CQRS handlers) and borrows the database connection via `TypeOrmModule.forFeature`. It lends `SecuredTokenService` via `exports` so `AuthModule` can import and use it without knowing how tokens are created internally.

> **From Meteor?** In Meteor, token logic would be a global function available everywhere. In NestJS, `SecuredTokenModule` makes a deliberate decision: only `exports: [SecuredTokenService]`. The CQRS handlers are internal staff — other modules cannot access them directly.

**Memory hook:** Module = hospital wing. `imports` borrows, `providers` owns staff, `exports` lends. One feature = one module.

```typescript
// apps/api/src/modules/secured-token/secured-token.module.ts
import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { SecuredTokenEntity } from "./secured-token.entity";
import { SecuredTokenService } from "./secured-token.service";
import { SecuredTokenCqrsHandlers } from "./cqrs";

@Module({
  imports: [TypeOrmModule.forFeature([SecuredTokenEntity])],
  providers: [SecuredTokenService, ...SecuredTokenCqrsHandlers],
  exports: [SecuredTokenService],
})
export class SecuredTokenModule {}
```

Add `SecuredTokenEntity` to `AppModule`'s `entities[]` array and import `SecuredTokenModule` into `AuthModule`.

### 3.7 Migration

```bash
yarn api:migration:generate apps/api/src/migrations/CreateSecuredTokenTable
```

Review the generated SQL — it should create a `secured_token` table with `token VARCHAR UNIQUE`, three enum columns, `expires_at TIMESTAMPTZ`, and a FK to `user` with `ON DELETE CASCADE`.

> **Migration — git commit for the database:** This migration is `up()` = create the `secured_token` table, `down()` = drop it. Every schema change is a reversible commit in your database's history. Never edit old migrations — add a new one.

> **From Meteor?** MongoDB has no migrations — schema changes just happen (or silently don't). When you have 50,000 users and need to add a required column, no-migration becomes a production incident. Every NestJS schema change is visible, reversible, and reviewable.

**Memory hook:** Migration = git commit for DB. `up()` applies, `down()` reverts. Never edit old migrations. Test both directions.

```bash
yarn api:migration:run
```

Also test the revert:

```bash
yarn api:migration:revert
yarn api:migration:run
```

### 3.8 Boot Test

```bash
yarn api:dev
```

Check that the server starts without `EntityMetadataNotFoundError`. If you see that error, `SecuredTokenEntity` is missing from `AppModule`'s `entities[]`.

---

## 4. Password Reset Flow

The password reset flow has three mutations. A critical security principle runs through all three: **never reveal whether an email address is registered**. Disclosing "no account found for this email" lets attackers enumerate your user base.

### 4.1 Request Password Reset

```typescript
// In AuthResolver — add this mutation:
@Mutation(() => Boolean)
async requestPasswordReset(
  @Args('email') email: string,
): Promise<boolean> {
  await this.authService.requestPasswordReset(email);
  return true; // always true — do not reveal if email exists
}
```

```typescript
// In AuthService:
async requestPasswordReset(email: string): Promise<void> {
  const user = await this.userRepo.findOne({ where: { email } });

  // If user does not exist, return silently — do not throw
  if (!user) return;

  const securedToken = await this.securedTokenService.createOneSecuredToken({
    type: SecuredTokenType.PASSWORD_RESET,
    medium: SecuredTokenMedium.EMAIL,
    userId: user.id,
  });

  const resetUrl = `${this.configService.get('app.webUrl')}/reset-password?token=${securedToken.token}`;

  await this.emailQueue.add('send-password-reset', {
    to: user.email,
    resetUrl,
  });
}
```

Inject `@InjectQueue(EMAIL_QUEUE) private readonly emailQueue: Queue` and the `SecuredTokenService` into `AuthService`.

### 4.2 Verify Token (pre-flight check for the UI)

This lets the frontend validate the token before showing the "enter new password" form — avoiding a bad UX where the user fills out a form and only then learns the link expired.

```typescript
// In AuthResolver:
@Query(() => Boolean)
async verifyPasswordResetToken(
  @Args('token') token: string,
): Promise<boolean> {
  const found = await this.securedTokenService.findOneActiveSecuredToken(
    token,
    SecuredTokenType.PASSWORD_RESET,
  );
  return found !== null;
}
```

### 4.3 Reset Password

```typescript
// In AuthResolver:
@Mutation(() => Boolean)
async resetPassword(
  @Args('token') token: string,
  @Args('newPassword') newPassword: string,
): Promise<boolean> {
  await this.authService.resetPassword(token, newPassword);
  return true;
}
```

```typescript
// In AuthService:
async resetPassword(token: string, newPassword: string): Promise<void> {
  const securedToken = await this.securedTokenService.findOneActiveSecuredToken(
    token,
    SecuredTokenType.PASSWORD_RESET,
  );

  if (!securedToken) {
    throw new UnauthorizedException('Invalid or expired reset token');
  }

  const hashedPassword = await bcrypt.hash(newPassword, 12);

  await this.userRepo.update(securedToken.userId, { password: hashedPassword });

  await this.securedTokenService.claimSecuredToken(token);
}
```

The token is claimed (not deleted) after use. Attempting to reuse it will fail because `findOneActiveSecuredToken` filters for `status: ACTIVE`.

### 4.4 Smoke Test — Password Reset

Open GraphQL Playground at `http://localhost:3333/graphql`.

**Step 1 — Request reset:**

```graphql
mutation {
  requestPasswordReset(email: "user@example.com")
}
```

Open `http://localhost:8025`. The password reset email should appear. Copy the token from the reset URL in the email body.

**Step 2 — Verify token:**

```graphql
query {
  verifyPasswordResetToken(token: "your-token-here")
}
```

Should return `true`.

**Step 3 — Reset password:**

```graphql
mutation {
  resetPassword(token: "your-token-here", newPassword: "NewSecurePassword123!")
}
```

Should return `true`. Attempt to log in with the new password to confirm.

**Step 4 — Verify token is spent:**
Re-run `verifyPasswordResetToken` with the same token. Should return `false`.

---

## 5. Email Verification on Signup

Users who register start as `status: INACTIVE` and cannot log in until they click the verification link. This prevents throwaway registrations and ensures you have a valid email on file.

### 5.1 Update UserEntity Default Status

The `UserEntity` already has `status` with `default: UserStatus.ACTIVE`. Change the default to `INACTIVE`:

```typescript
// apps/api/src/modules/user/user.entity.ts
@Column({ type: 'enum', enum: UserStatus, default: UserStatus.INACTIVE })
status: UserStatus;
```

Generate and run a migration for this default change:

```bash
yarn api:migration:generate apps/api/src/migrations/UserStatusDefaultInactive
yarn api:migration:run
```

### 5.2 Update register() in AuthService

```typescript
// apps/api/src/modules/auth/auth.service.ts — register() method
async register(input: RegisterInput): Promise<UserEntity> {
  const existing = await this.userRepo.findOne({ where: { email: input.email } });
  if (existing) {
    throw new ConflictException('Email already registered');
  }

  const hashedPassword = await bcrypt.hash(input.password, 12);

  const user = this.userRepo.create({
    email: input.email,
    username: input.username,
    fullname: input.fullname,
    password: hashedPassword,
    status: UserStatus.INACTIVE, // explicit — requires email verification
  });

  const savedUser = await this.userRepo.save(user);

  // Issue verification token and enqueue email — fire and forget
  const securedToken = await this.securedTokenService.createOneSecuredToken({
    type: SecuredTokenType.EMAIL_VERIFICATION,
    medium: SecuredTokenMedium.EMAIL,
    userId: savedUser.id,
  });

  const verifyUrl = `${this.configService.get('app.webUrl')}/verify-email?token=${securedToken.token}`;

  await this.emailQueue.add('send-email-verification', {
    to: savedUser.email,
    verifyUrl,
  });

  return savedUser;
}
```

### 5.3 Gate Login on ACTIVE Status

> **Guard — gate officer:** The status checks below are the login gate equivalent of a guard. Before the ward (token generation), every visitor must pass: valid credentials, active account, not suspended. The checks are explicit, ordered, and individually readable — no implicit Meteor magic.

> **From Meteor?** Meteor's `Accounts` package handled status gating inside an opaque bundle you could not inspect. Here each gate is an explicit `if` statement in `auth.service.ts` — readable, testable, and extendable.

**Memory hook:** Guard = gate officer. Returns true or throws. Chain them in order. Every gate is visible in code.

```typescript
// apps/api/src/modules/auth/auth.service.ts — login() method
async login(input: LoginInput): Promise<AuthTokensDto> {
  const user = await this.userRepo.findOne({ where: { email: input.email } });

  if (!user || !(await bcrypt.compare(input.password, user.password))) {
    throw new UnauthorizedException('Invalid credentials');
  }

  if (user.status === UserStatus.INACTIVE) {
    throw new UnauthorizedException('Please verify your email address before logging in');
  }

  if (user.status === UserStatus.SUSPENDED) {
    throw new UnauthorizedException('This account has been suspended');
  }

  // ... continue to generate tokens
}
```

### 5.4 Verify Email Mutation

```typescript
// In AuthResolver:
@Mutation(() => Boolean)
async verifyEmail(
  @Args('token') token: string,
): Promise<boolean> {
  await this.authService.verifyEmail(token);
  return true;
}
```

```typescript
// In AuthService:
async verifyEmail(token: string): Promise<void> {
  const securedToken = await this.securedTokenService.findOneActiveSecuredToken(
    token,
    SecuredTokenType.EMAIL_VERIFICATION,
  );

  if (!securedToken) {
    throw new UnauthorizedException('Invalid or expired verification token');
  }

  await this.userRepo.update(securedToken.userId, { status: UserStatus.ACTIVE });

  await this.securedTokenService.claimSecuredToken(token);
}
```

### 5.5 Smoke Test — Email Verification

**Step 1 — Register:**

```graphql
mutation {
  register(
    input: {
      email: "newuser@example.com"
      username: "newuser"
      fullname: "New User"
      password: "SecurePassword123!"
    }
  ) {
    id
    email
    status
  }
}
```

`status` should be `INACTIVE`.

**Step 2 — Attempt login before verification:**

```graphql
mutation {
  login(
    input: { email: "newuser@example.com", password: "SecurePassword123!" }
  ) {
    accessToken
  }
}
```

Should throw `"Please verify your email address before logging in"`.

**Step 3 — Get token from Mailpit, verify:**

```graphql
mutation {
  verifyEmail(token: "your-token-here")
}
```

Should return `true`.

**Step 4 — Login now succeeds:**

```graphql
mutation {
  login(
    input: { email: "newuser@example.com", password: "SecurePassword123!" }
  ) {
    accessToken
    refreshToken
  }
}
```

---

## 6. Two-Factor Authentication (TOTP)

TOTP (Time-based One-Time Password) is the standard behind authenticator apps like Google Authenticator, Authy, and 1Password. The server and the user's device share a secret. Every 30 seconds, both sides derive a 6-digit code from `HMAC(secret, floor(timestamp / 30))`. The codes match without any network call.

### 6.1 Install Dependencies

```bash
yarn add otplib qrcode
yarn add -D @types/qrcode
```

`otplib` handles TOTP secret generation and code verification. `qrcode` generates the QR code the user scans with their authenticator app.

### 6.2 The 2FA Flow

```
1. User requests 2FA setup
       │
       ▼
2. Server generates a random secret, returns it + a QR code data URL
       │
       ▼
3. User scans QR code with their authenticator app
       │
       ▼
4. User submits the first 6-digit code to CONFIRM binding
       │   (this proves the scan worked before we persist the secret)
       ▼
5. Server verifies the code, saves secret to user.twoFactorSecret
       │
       ▼
6. On future logins: password check → if twoFactorSecret set → require TOTP code
```

Binding requires a verification step (Step 4) because if you persist the secret before the user verifies the scan, they can lock themselves out with an unreadable QR code.

### 6.3 Generate 2FA Secret and QR Code

```typescript
// apps/api/src/modules/auth/auth.service.ts — add these methods:
import { authenticator } from 'otplib';
import { toDataURL } from 'qrcode';

async generateTwoFactorSecret(
  userId: number,
): Promise<{ secret: string; qrCodeUrl: string }> {
  const user = await this.userRepo.findOneOrFail({ where: { id: userId } });

  const secret = authenticator.generateSecret();
  const otpAuthUrl = authenticator.keyuri(user.email, 'Enterprise Todo', secret);
  const qrCodeUrl = await toDataURL(otpAuthUrl);

  // Store as a PENDING secret — not yet active until the user verifies the first code.
  // In production you may prefer a separate pendingTwoFactorSecret column.
  // For simplicity, we store it directly and rely on the bind step.
  return { secret, qrCodeUrl };
}
```

> **Production gap — recovery codes:** This implementation doesn't generate TOTP recovery codes. In production, when `setup2FA` is called, generate 8–10 single-use codes (e.g. `crypto.randomBytes(4).toString('hex')` × 10), store them hashed in a `UserRecoveryCodeEntity`, and return them once to the user. If they lose their authenticator app, recovery codes are the only way back in. Without them, locked-out users require manual DB intervention.

```typescript
// apps/api/src/modules/auth/dto/two-factor.dto.ts
import { Field, ObjectType } from "@nestjs/graphql";

@ObjectType("TwoFactorSetup")
export class TwoFactorSetupDto {
  @Field()
  secret: string;

  @Field()
  qrCodeUrl: string;
}
```

```typescript
// In AuthResolver:
@UseGuards(AuthJwtGuard)
@Query(() => TwoFactorSetupDto)
async generateTwoFactor(
  @CurrentUser() user: UserEntity,
): Promise<TwoFactorSetupDto> {
  return this.authService.generateTwoFactorSecret(user.id);
}
```

### 6.4 Bind 2FA (Confirm Setup)

The user scans the QR code, then submits the first TOTP code from their app along with the secret returned from `generateTwoFactor`. Verifying before persisting ensures the scan succeeded.

```typescript
// In AuthService:
async bindTwoFactor(userId: number, secret: string, code: string): Promise<boolean> {
  const isValid = authenticator.verify({ token: code, secret });

  if (!isValid) {
    throw new UnauthorizedException('Invalid TOTP code — please try again');
  }

  await this.userRepo.update(userId, { twoFactorSecret: secret });

  return true;
}
```

```typescript
// In AuthResolver:
@UseGuards(AuthJwtGuard)
@Mutation(() => Boolean)
async bindTwoFactor(
  @CurrentUser() user: UserEntity,
  @Args('secret') secret: string,
  @Args('code') code: string,
): Promise<boolean> {
  return this.authService.bindTwoFactor(user.id, secret, code);
}
```

### 6.5 Unbind 2FA

Removing 2FA requires a valid TOTP code to prevent an attacker with a stolen session from disabling 2FA silently.

```typescript
// In AuthService:
async unbindTwoFactor(userId: number, code: string): Promise<boolean> {
  const user = await this.userRepo.findOneOrFail({ where: { id: userId } });

  if (!user.twoFactorSecret) {
    throw new UnauthorizedException('Two-factor authentication is not enabled');
  }

  const isValid = authenticator.verify({ token: code, secret: user.twoFactorSecret });

  if (!isValid) {
    throw new UnauthorizedException('Invalid TOTP code');
  }

  await this.userRepo.update(userId, { twoFactorSecret: null });

  return true;
}
```

```typescript
// In AuthResolver:
@UseGuards(AuthJwtGuard)
@Mutation(() => Boolean)
async unbindTwoFactor(
  @CurrentUser() user: UserEntity,
  @Args('code') code: string,
): Promise<boolean> {
  return this.authService.unbindTwoFactor(user.id, code);
}
```

### 6.6 Update Login to Require TOTP

When `twoFactorSecret` is set, the login flow must not issue a full access token on password alone. The standard approach is a two-step response:

> **RS256 JWT — the king's wax seal:** The auth service holds the private key (the signet ring) and signs the pre-auth `twoFactorToken`. Any downstream service can verify the seal using only the public key — but they cannot forge a new one. The pre-auth token has `typ: 'twofa'` in its payload, which is cryptographically protected. Even if an attacker intercepts it, they cannot modify the claim without breaking the seal.

> **From Meteor?** Meteor's DDP session token was a simple opaque string — no cryptographic claims, no expiry enforcement, no multi-service verification. RS256 JWTs carry signed claims that any service can verify independently without a central auth lookup.

**Memory hook:** RS256 = king's wax seal. Private key signs (auth service only), public key verifies (anyone). A downstream breach cannot forge tokens.

1. Password correct + 2FA enabled → return a short-lived "pre-auth" token with a restricted claim (`typ: 'twofa'`)
2. User submits TOTP code with the pre-auth token → returns a full access token

```typescript
// apps/api/src/modules/auth/dto/auth-tokens.dto.ts — extend:
import { Field, ObjectType } from "@nestjs/graphql";

@ObjectType("AuthTokens")
export class AuthTokensDto {
  @Field({ nullable: true })
  accessToken?: string;

  @Field({ nullable: true })
  refreshToken?: string;

  @Field({ nullable: true })
  twoFactorToken?: string; // set when 2FA is required; accessToken is null

  @Field()
  requiresTwoFactor: boolean;
}
```

```typescript
// In AuthService — update login():
async login(input: LoginInput): Promise<AuthTokensDto> {
  const user = await this.userRepo.findOne({ where: { email: input.email } });

  if (!user || !(await bcrypt.compare(input.password, user.password))) {
    throw new UnauthorizedException('Invalid credentials');
  }

  if (user.status === UserStatus.INACTIVE) {
    throw new UnauthorizedException('Please verify your email address before logging in');
  }

  if (user.status === UserStatus.SUSPENDED) {
    throw new UnauthorizedException('This account has been suspended');
  }

  if (user.twoFactorSecret) {
    // Issue a restricted pre-auth token
    const twoFactorToken = this.jwtService.sign(
      { sub: user.id, typ: 'twofa' },
      {
        privateKey: this.configService.getOrThrow('JWT_PRIVATE_KEY'),
        algorithm: 'RS256',
        expiresIn: '5m', // short-lived — user must complete 2FA quickly
      },
    );
    return { twoFactorToken, requiresTwoFactor: true };
  }

  return this.generateTokens(user);
}
```

```typescript
// In AuthService — add verifyTwoFactorLogin():
async verifyTwoFactorLogin(twoFactorToken: string, code: string): Promise<AuthTokensDto> {
  let payload: { sub: number; typ: string };

  try {
    payload = this.jwtService.verify(twoFactorToken, {
      publicKey: this.configService.getOrThrow('JWT_PUBLIC_KEY'),
      algorithms: ['RS256'],
    });
  } catch {
    throw new UnauthorizedException('Invalid or expired two-factor token');
  }

  if (payload.typ !== 'twofa') {
    throw new UnauthorizedException('Invalid token type');
  }

  const user = await this.userRepo.findOneOrFail({ where: { id: payload.sub } });

  if (!user.twoFactorSecret) {
    throw new UnauthorizedException('Two-factor authentication is not configured');
  }

  // Check bypass password for development/testing — never active in production
  const bypassPassword = this.configService.get<string>('TWOFA_BYPASS_PASSWORD');
  const isValid =
    (process.env.NODE_ENV !== 'production' && bypassPassword && code === bypassPassword) ||
    authenticator.verify({ token: code, secret: user.twoFactorSecret });

  if (!isValid) {
    throw new UnauthorizedException('Invalid TOTP code');
  }

  return this.generateTokens(user);
}
```

```typescript
// In AuthResolver:
@Mutation(() => AuthTokensDto)
async verifyTwoFactor(
  @Args('twoFactorToken') twoFactorToken: string,
  @Args('code') code: string,
): Promise<AuthTokensDto> {
  return this.authService.verifyTwoFactorLogin(twoFactorToken, code);
}
```

### 6.7 TWOFA_BYPASS_PASSWORD

Add to your `.env`:

```
TWOFA_BYPASS_PASSWORD=dev-bypass-123
```

This is a static code that, when presented as the TOTP code, bypasses the TOTP check entirely. It is only checked when the env var is set — never set it in staging or production. This pattern prevents 2FA from blocking end-to-end tests or local development flows.

### 6.8 Smoke Test — Two-Factor Authentication

**Step 1 — Log in as a verified user (get accessToken first):**

```graphql
mutation {
  login(input: { email: "user@example.com", password: "password" }) {
    accessToken
    requiresTwoFactor
  }
}
```

`requiresTwoFactor` should be `false` (2FA not yet bound). Copy `accessToken`.

**Step 2 — Generate 2FA setup (requires auth header `Authorization: Bearer <token>`):**

```graphql
query {
  generateTwoFactor {
    secret
    qrCodeUrl
  }
}
```

Copy the `secret`. The `qrCodeUrl` is a base64-encoded PNG data URL — paste it into a browser address bar to view the QR code. Scan it with Google Authenticator or Authy.

**Step 3 — Bind 2FA:**

```graphql
mutation {
  bindTwoFactor(secret: "YOUR_SECRET", code: "123456")
}
```

Use the 6-digit code from your authenticator app. Should return `true`.

**Step 4 — Login now returns twoFactorToken:**

```graphql
mutation {
  login(input: { email: "user@example.com", password: "password" }) {
    twoFactorToken
    requiresTwoFactor
  }
}
```

`requiresTwoFactor` should be `true`. Copy `twoFactorToken`.

**Step 5 — Complete login with TOTP code:**

```graphql
mutation {
  verifyTwoFactor(twoFactorToken: "YOUR_TWO_FACTOR_TOKEN", code: "654321")
}
```

Returns `accessToken` and `refreshToken` on success.

**Step 6 — Test bypass (development only):**

```graphql
mutation {
  verifyTwoFactor(
    twoFactorToken: "YOUR_TWO_FACTOR_TOKEN"
    code: "dev-bypass-123"
  )
}
```

Returns full tokens without needing the authenticator app.

---

## Quick Reference

| Concept | Analogy | Meteor equivalent | The one rule |
|---------|---------|-------------------|--------------|
| Bull Queue | Kitchen ticket rail — waiter clips ticket, chef processes async | `Meteor.setTimeout` / `synced-cron` — in-memory, lost on restart | Web enqueues and returns immediately. Worker processes in background. Redis-backed. |
| Entity | Official record template — every field typed at DB and TypeScript level | Schema-less MongoDB document | Never `synchronize: true` in production. Use migrations. |
| AbstractEntity | Company letterhead — id + timestamps pre-printed | Manual `_id`, `createdAt` fields per collection | All entities extend it. Never repeat those columns. |
| AbstractDto | Standard response envelope — id + timestamps as `@Field()` | N/A | All output DTOs extend it. Sensitive fields (raw token) stay off `@Field()`. |
| CQRS | Two separate kitchens — Commands mutate, Queries read, no shared stove | `Meteor.methods` body (routing + logic + DB in one block) | Handlers are thin one-liners. All logic lives in the Service. |
| CommandBus / QueryBus | Postal sorting facility — drop the letter, facility routes it | Direct method call inside a Meteor method | Resolver never imports the handler directly. |
| Service | Specialist doctor — examines, diagnoses, prescribes | Logic inside `Meteor.methods` | All business logic lives here. Never touches HTTP objects. |
| Module | Hospital wing — owns staff, lends via `exports` | `meteor add` — global, implicit | `imports` borrows, `providers` owns, `exports` lends. One feature = one module. |
| Migration | Git commit for the database — `up()` applies, `down()` reverts | No migrations in MongoDB | Never edit old migrations. Test both directions. |
| Guard | Gate officer — returns true or throws | `.allow()` / `.deny()` — ran at DB layer after your code | Explicit, ordered, runs before handler. Chain them left to right. |
| RS256 JWT | King's wax seal — private key signs, public key verifies, cannot be forged | DDP session token — opaque string, no cryptographic claims | Auth service signs with private key. Any service verifies with public key. Downstream breach cannot forge. |

---

## 7. Summary

### What You Have Now

```
[✅] nodemailer EmailService — transactional email with Mailpit for local dev
[✅] Bull email queue — non-blocking delivery, retries on failure
[✅] SecuredTokenEntity — single-use, expiring tokens with audit trail
[✅] Password reset flow — 3-step: request → verify → reset
[✅] Email verification — account starts INACTIVE, activates on click
[✅] Login gate — INACTIVE and SUSPENDED users cannot authenticate
[✅] TOTP 2FA — bind, unbind, login gate with pre-auth token
[✅] TWOFA_BYPASS_PASSWORD — safe local dev escape hatch
[✅] Migrations for SecuredToken table and UserStatus default change
```

### Meteor vs Enterprise NestJS

| Concern                     | Meteor                                  | Enterprise NestJS                                             |
| --------------------------- | --------------------------------------- | ------------------------------------------------------------- |
| Transactional email         | `Email.send()` blocking the method      | `nodemailer` inside a Bull job — async, retried               |
| Password reset tokens       | Stored in user document, no type system | `SecuredTokenEntity` — typed, single-use, expires, claimed    |
| Email verification          | `Accounts.sendVerificationEmail()`      | Same `SecuredTokenEntity` pattern, `type: EMAIL_VERIFICATION` |
| Token expiry enforcement    | Manual check at point of use            | `expiresAt: MoreThan(new Date())` in every token query        |
| Two-factor auth             | Not available natively                  | `otplib` TOTP, QR code binding, pre-auth JWT flow             |
| 2FA dev bypass              | N/A                                     | `TWOFA_BYPASS_PASSWORD` env var, production-safe              |
| Security: email enumeration | Varies — often reveals existence        | `requestPasswordReset` always returns `true`                  |

### The Compose

All the pieces from Parts 8 through 9 now compose:

```
Login request
     │
     ▼
AuthService.login()
     │── password check (bcrypt)
     │── status check (INACTIVE → reject, SUSPENDED → reject)
     │── 2FA check (twoFactorSecret set → return twoFactorToken only)
     │── no 2FA → generateTokens() → return accessToken + refreshToken
     │
     ▼ (if 2FA required)
AuthService.verifyTwoFactorLogin()
     │── verify twofa JWT
     │── verify TOTP code (or bypass in dev)
     │── generateTokens()
     │
     ▼
Full access token issued
```

Every gate is explicit, ordered, and individually testable. No implicit Meteor magic — each check is a method call you can trace, mock, and reason about.

In Part 10 — Case Study 1: Tag Module — you will apply everything from Parts 1–9 to build a complete module from scratch following the 9-step checklist end-to-end with tests.
