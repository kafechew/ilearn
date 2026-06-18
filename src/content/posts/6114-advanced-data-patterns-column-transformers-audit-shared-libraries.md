---
author: Kai
pubDatetime: 2026-05-14T09:00:00+08:00
title: Advanced Data Patterns — Column Transformers, Audit Columns & Shared Libraries
featured: false
draft: false
slug: 6114-advanced-data-patterns-column-transformers-audit-shared-libraries
tags:
  - deeptech
  - nestjs
  - typeorm
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/14-advanced-data-patterns-column-transformers-audit-shared-libraries.png"
description: Add reusable TypeORM column transformers (lowercase, slug), wire up createdBy/updatedBy audit columns via a request-scoped TypeORM subscriber, build a running number service for ordered sequences, and extract shared config into libs/core for multi-app monorepo reuse.
---

## What This Part Covers

This tutorial addresses four architectural refinements that separate toy projects from production-grade systems. None of them are features in the user-visible sense — they are infrastructure decisions that prevent entire classes of bugs and make future development safer.

- **Column transformers** — normalize data at the DB layer so business rules about email casing and slug format are enforced at the type level, not in service code
- **`createdBy` / `updatedBy` audit columns** — automatically populated from the JWT user via a request-scoped TypeORM subscriber, with zero changes to existing service methods
- **Running number service** — ordered, formatted sequence generation per entity type (e.g. `TODO-0001`) with race-condition safety via `SELECT FOR UPDATE`
- **`libs/core` extraction** — moving shared config into a reusable library so a hypothetical second NestJS app (`portal-api`) can import the same config with zero duplication
- **Migration strategy** for adding columns to tables that already have production data

---

## Meteor Equivalents

| Pattern                   | Meteor                                                 | NestJS (this tutorial)                                          |
| ------------------------- | ------------------------------------------------------ | --------------------------------------------------------------- |
| Audit timestamps          | `createdAt` / `updatedAt` auto-added by `collection2`  | `AbstractEntity` provides `created_at` / `updated_at`           |
| Record creator            | `userId` stored manually in method or publication      | `createdBy` via `AuditSubscriber`, automatic                    |
| Email normalization       | App code, or `aldeed:simple-schema` `trim`/`lowercase` | `LowerCaseTransformer` at the entity `@Column` level            |
| Slug fields               | `percolate:synced-cron` + custom transform             | `SlugTransformer` at `@Column`, enforced by TypeORM             |
| Human-readable IDs        | Custom Meteor method with `findOne` + increment        | `RunningNumberService` with `SELECT FOR UPDATE`                 |
| Shared config across apps | Not applicable (single-app model)                      | `libs/core` library, imported by any NestJS app in the monorepo |
| Request-scoped state      | `this.userId` inside a Meteor fiber (implicit)        | `Scope.REQUEST` provider — explicit, per-request, cascades up   |
| Pre-save hooks            | Not available across all collections                   | TypeORM `EntitySubscriber` — fires before every insert/update   |
| Schema changes            | No migrations (MongoDB schema-less)                    | TypeORM migrations — versioned, reversible, reviewable          |
| Monorepo / shared code    | Not applicable (single-app model)                      | `libs/core` with Nx module boundary enforcement                 |

Meteor's `accounts` package automatically tracked `createdAt` and `userId` on documents inserted via `Accounts.createUser`. The NestJS equivalent requires explicit wiring — but it works across all entities, not just user documents.

---

## 1. Column Transformers

### What Problem This Solves

Without transformers, you need to remember to call `.toLowerCase()` on every email address before saving — in the registration handler, in the login handler, in the admin update handler, in every seeder. When you forget once, you get `User@example.com` and `user@example.com` stored as two different users.

A TypeORM `ValueTransformer` moves the normalization to the entity's `@Column` definition. TypeORM calls `to()` before every write and `from()` after every read. It becomes structurally impossible to store an email that violates the invariant.

> **From Meteor?** In Meteor you would call `email.toLowerCase()` inside each method body, or use `aldeed:simple-schema` with a `trim`/`lowercase` option — but both relied on discipline. A new developer adding a mutation could forget. The TypeORM `ValueTransformer` enforces the rule at the column definition; there is no method body to forget.

**Memory hook:** Column transformer = one-way valve on the pipe. `to()` normalizes on write; the invariant is structural, not disciplinary.

### Create the Transformer File

```typescript
// apps/api/src/helpers/transformer.ts
import { ValueTransformer } from "typeorm";

/**
 * Stores strings as lowercase. Applies to: email, username.
 * "USER@EXAMPLE.COM" → stored as "user@example.com"
 */
export class LowerCaseTransformer implements ValueTransformer {
  to(value: string | null): string | null {
    return value?.toLowerCase() ?? null;
  }
  from(value: string | null): string | null {
    return value;
  }
}

/**
 * Converts a label to a URL-safe slug.
 * "My Work Tasks!" → stored as "my-work-tasks"
 */
export class SlugTransformer implements ValueTransformer {
  to(value: string | null): string | null {
    if (!value) return null;
    return value
      .toLowerCase()
      .replace(/\s+/g, "-")
      .replace(/[^a-z0-9-]/g, "");
  }
  from(value: string | null): string | null {
    return value;
  }
}

/**
 * Stores strings as uppercase. Applies to: country codes, currency codes.
 * "usd" → stored as "USD"
 */
export class UpperCaseTransformer implements ValueTransformer {
  to(value: string | null): string | null {
    return value?.toUpperCase() ?? null;
  }
  from(value: string | null): string | null {
    return value;
  }
}
```

The `from()` method on `LowerCaseTransformer` returns the value as-is. There is no need to uppercase it on read — the canonical form is always lowercase. The transformer is one-directional in practice even though TypeORM calls both sides.

### Apply to UserEntity

```typescript
// apps/api/src/modules/user/user.entity.ts
import { Column, Entity, Index } from "typeorm";
import { AbstractEntity } from "nestjs-dev-utilities";
import { UserStatus } from "./user.constant";
import { LowerCaseTransformer } from "../../helpers/transformer";

@Entity({ name: "user" })
export class UserEntity extends AbstractEntity {
  @Column()
  fullname: string;

  @Index()
  @Column({ unique: true, transformer: new LowerCaseTransformer() })
  username: string;

  @Index()
  @Column({ unique: true, transformer: new LowerCaseTransformer() })
  email: string;

  @Column()
  password: string;

  @Column({ type: "enum", enum: UserStatus, default: UserStatus.ACTIVE })
  status: UserStatus;

  @Column({ nullable: true })
  twoFactorSecret: string | null;
}
```

The transformer is passed as an instance (`new LowerCaseTransformer()`), not the class. TypeORM stores a reference to the instance in the column metadata and calls `instance.to()` / `instance.from()` at runtime.

### What Changes in Queries

Before transformers, a case-insensitive login required:

```typescript
// Before: manual normalization in every service method — easy to forget
const user = await this.repo.findOne({
  where: { email: input.email.toLowerCase() },
});
```

After transformers, TypeORM normalizes automatically on write, so standard equality queries just work:

```typescript
// After: the transformer guarantees the stored value is already lowercase
// A query for 'USER@EXAMPLE.COM' passes through transformer.to() first
const user = await this.repo.findOne({
  where: { email: input.email },
});
```

TypeORM also applies the `to()` transformer when building `WHERE` clauses via `findOne`, so `{ email: 'USER@EXAMPLE.COM' }` is transparently normalized before the SQL is issued.

### Apply to TagEntity

The `TagEntity` from tutorial 6108 has a `slug` column. Apply the `SlugTransformer` so that creating a tag with `name: "My Work Tasks!"` automatically generates slug `my-work-tasks`:

```typescript
// apps/api/src/modules/tag/tag.entity.ts  (relevant columns only)
import { SlugTransformer } from '../../helpers/transformer';

@Column({ unique: true, transformer: new SlugTransformer() })
slug: string;
```

The GraphQL mutation `createTag(input: { name: "Work", slug: "My Work Tasks!" })` now stores `my-work-tasks` regardless of what the client sends.

### Migration: Schema vs Data

Adding a transformer does not change the column type or constraints in the database. TypeORM does not know about transformers at the schema level — it is purely a runtime concern. Running `api:migration:generate` after adding a transformer produces an **empty migration**. No schema migration is needed.

However, existing data that was saved before the transformer was applied may be uppercase. To normalize existing rows, write a one-off data migration:

```bash
yarn api:migration:create apps/api/src/migrations/NormalizeEmailCase
```

```typescript
// apps/api/src/migrations/1718000000000-NormalizeEmailCase.ts
import { MigrationInterface, QueryRunner } from "typeorm";

export class NormalizeEmailCase1718000000000 implements MigrationInterface {
  public async up(queryRunner: QueryRunner): Promise<void> {
    // Normalize existing data to match the new transformer invariant
    await queryRunner.query(`
      UPDATE "user"
      SET email    = LOWER(email),
          username = LOWER(username)
      WHERE email != LOWER(email)
         OR username != LOWER(username)
    `);
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    // Data migration is irreversible — original casing is lost
    // down() is a no-op; document this in your team's migration log
  }
}
```

Use `migration:create` (not `migration:generate`) for data-only migrations. The `generate` command diffs entity definitions against the DB schema; since there is no schema change here, it would produce nothing.

### Smoke Test: Column Transformer

```bash
# Start the stack
yarn docker:dev
yarn api:dev

# Open GraphQL Playground: http://localhost:3333/graphql

# Register with mixed-case email
mutation {
  register(input: {
    fullname: "Test User"
    username: "TESTUSER"
    email: "TEST@EXAMPLE.COM"
    password: "password123"
  }) {
    id
    email
    username
  }
}
# Expected response: email "test@example.com", username "testuser"

# Open Adminer: http://localhost:8080
# Table: user — verify email column stores "test@example.com", not "TEST@EXAMPLE.COM"
```

---

## 2. Audit Columns (createdBy / updatedBy)

### What Problem This Solves

"Who created this record?" is a universal audit requirement in enterprise systems. Without a subscriber, you would call `runningNumberService.getNext()` and set `input.createdBy = currentUser.id` in every single mutation handler. When a new developer adds a mutation and forgets the audit field, the record is saved without it. A TypeORM `EntitySubscriber` fires before every insert and update across all entities — the audit fields are set in one place, automatically, without touching any handler or service.

### Understanding the Dependency Problem

The subscriber needs to know the current user's ID. But TypeORM's `DataSource` is a singleton — it has no concept of an HTTP request. The current user lives in the request context (extracted from the JWT by the `AuthJwtGuard`).

The solution is a **request-scoped context holder**: a tiny injectable class whose instance is created fresh for each HTTP request and disposed afterward. The interceptor writes the current user's ID into it; the subscriber reads from it.

```
HTTP Request
  │
  ├─ AuthJwtGuard ──────────────────────► validates JWT, sets req.user
  │
  ├─ AuditInterceptor ──────────────────► reads req.user, writes to UserContext
  │                                         (UserContext is Scope.REQUEST)
  │
  └─ Resolver → Handler → Service
       │
       └─ TypeORM save() / update()
            │
            └─ AuditSubscriber.beforeInsert()
                 └─ reads UserContext.userId → sets entity.createdBy
```

### Step 1 — Create UserContext (Request-Scoped)

```typescript
// apps/api/src/interceptors/user-context.ts
import { Injectable, Scope } from "@nestjs/common";

/**
 * Request-scoped holder for the authenticated user's ID.
 * A fresh instance is created for each HTTP request.
 * The AuditInterceptor writes to it; the AuditSubscriber reads from it.
 */
@Injectable({ scope: Scope.REQUEST })
export class UserContext {
  userId: number | null = null;
}
```

`Scope.REQUEST` is the critical annotation. Without it, `UserContext` would be a singleton shared across all requests — a data leak waiting to happen.

> **Scope.REQUEST analogy:** `Scope.DEFAULT` is a **shared coffee maker in the office kitchen** — one machine, everyone uses it, state is shared. `Scope.REQUEST` is a **fresh cup brewed per visitor** — each HTTP request gets its own `UserContext` instance, filled with that request's user ID, discarded when the request ends. Using `DEFAULT` here would mean Request A's user ID overwrites Request B's mid-flight.

> **From Meteor?** Meteor's `this.userId` inside a method was implicitly request-scoped — each fiber (coroutine) had its own `this`. NestJS has no implicit fiber context; you must explicitly declare `Scope.REQUEST` to get the same per-request isolation.

**Memory hook:** `Scope.REQUEST` = fresh cup per visitor. Use it for anything that holds per-request state. It cascades — every class that injects a REQUEST-scoped provider becomes REQUEST-scoped too.

### Step 2 — Create AuditInterceptor

```typescript
// apps/api/src/interceptors/audit.interceptor.ts
import {
  CallHandler,
  ExecutionContext,
  Injectable,
  NestInterceptor,
} from "@nestjs/common";
import { GqlExecutionContext } from "@nestjs/graphql";
import { Observable } from "rxjs";
import { UserContext } from "./user-context";

@Injectable()
export class AuditInterceptor implements NestInterceptor {
  constructor(private readonly userContext: UserContext) {}

  intercept(context: ExecutionContext, next: CallHandler): Observable<any> {
    const gqlCtx = GqlExecutionContext.create(context);
    const { req } = gqlCtx.getContext<{ req: any }>();

    // req.user is set by AuthJwtGuard after JWT validation
    // Structure: { user: { id: number, email: string, ... } }
    if (req?.user?.user?.id) {
      this.userContext.userId = req.user.user.id;
    }

    return next.handle();
  }
}
```

The interceptor runs before the resolver. By the time TypeORM's subscriber fires (during `repo.save()`), `userContext.userId` is already populated.

> **Interceptor analogy:** The `AuditInterceptor` is the **top slice of a sandwich** — it runs before the handler executes (top bread), writes the user ID into `UserContext`, then `next.handle()` lets the handler and TypeORM subscriber run (filling), and the sandwich closes. The subscriber reads what the top bread prepared.

**Memory hook:** Interceptor = sandwich. Code before `next.handle()` = top bread. `AuditInterceptor` writes to `UserContext` in the top bread so the subscriber can read it during the filling.

### Step 3 — Create AuditSubscriber

```typescript
// apps/api/src/subscribers/audit.subscriber.ts
import {
  DataSource,
  EntitySubscriberInterface,
  InsertEvent,
  UpdateEvent,
} from "typeorm";
import { Injectable } from "@nestjs/common";
import { InjectDataSource } from "@nestjs/typeorm";
import { UserContext } from "../interceptors/user-context";

/**
 * TypeORM subscriber that automatically sets createdBy / updatedBy
 * before every insert or update, using the request-scoped UserContext.
 *
 * Registered by pushing to dataSource.subscribers in the constructor —
 * this is the NestJS DI-compatible way; TypeORM's own subscriber
 * registration bypasses the DI container.
 */
@Injectable()
export class AuditSubscriber implements EntitySubscriberInterface {
  constructor(
    @InjectDataSource() private readonly dataSource: DataSource,
    private readonly userContext: UserContext
  ) {
    // Self-register — TypeORM looks at dataSource.subscribers at runtime
    this.dataSource.subscribers.push(this);
  }

  beforeInsert(event: InsertEvent<any>): void {
    if (this.userContext.userId) {
      event.entity.createdBy = this.userContext.userId;
      event.entity.updatedBy = this.userContext.userId;
    }
  }

  beforeUpdate(event: UpdateEvent<any>): void {
    if (this.userContext.userId && event.entity) {
      event.entity.updatedBy = this.userContext.userId;
    }
  }
}
```

The subscriber has no `listenTo()` method, which means TypeORM applies it to all entities. You can optionally add `listenTo() { return TodoEntity; }` to scope it to a single entity type.

> **From Meteor?** In Meteor you would set `createdBy: this.userId` manually inside every `Meteor.method` that inserted a document — there was no hook that ran automatically across all collections. The TypeORM `EntitySubscriber` fires before every `save()` across all entities without touching a single handler.

**Memory hook:** `EntitySubscriber` = silent co-worker who stamps every document before it's filed. One place, zero handler changes.

> **Scope gotcha:** `AuditSubscriber` uses `Scope.REQUEST` DI to access `ClsService`. But TypeORM subscribers are registered globally at datasource level. If the NestJS DI container creates a new subscriber instance per request (via CLS integration) and it keeps pushing to `dataSource.subscribers`, you'll accumulate duplicate subscribers. Verify your integration registers the subscriber once at module init, not once per request — if using `@EventSubscriber()` with TypeORM's decorator, TypeORM manages the lifecycle and avoids duplicates automatically.

### Step 4 — Add Audit Columns to Entities

If `AbstractEntity` from `nestjs-dev-utilities` does not already include `createdBy` and `updatedBy`, add them directly to the entities that need auditing. Check first:

```bash
# Check if AbstractEntity already has these columns
node -e "
  const { AbstractEntity } = require('./node_modules/nestjs-dev-utilities');
  const cols = Reflect.getMetadata('columns', AbstractEntity.prototype) ?? [];
  console.log(cols.map(c => c.propertyName));
"
```

> **Nx gotcha:** This `node -e` command runs in Node module resolution mode, not in the Nx TypeScript context. If you get a `Cannot find module` error, skip this step — the integration is verified by running a migration and inspecting the generated SQL instead.

If not present, add to `TodoEntity`:

```typescript
// apps/api/src/modules/todo/todo.entity.ts  (add these columns)
import {
  Column,
  Entity,
  Index,
  JoinColumn,
  ManyToOne,
  RelationId,
} from "typeorm";
import { AbstractEntity } from "nestjs-dev-utilities";
import { UserEntity } from "../user/user.entity";
import { TodoStatus } from "./todo.constant";

@Entity({ name: "todo" })
export class TodoEntity extends AbstractEntity {
  @Column()
  text: string;

  @Column({ default: false })
  isChecked: boolean;

  @Column({ type: "enum", enum: TodoStatus, default: TodoStatus.ACTIVE })
  status: TodoStatus;

  @Index()
  @Column()
  @RelationId((todo: TodoEntity) => todo.user)
  userId: number;

  @ManyToOne(() => UserEntity, { onDelete: "CASCADE" })
  @JoinColumn()
  user: UserEntity;

  // Audit columns — populated automatically by AuditSubscriber
  @Column({ nullable: true })
  createdBy: number | null;

  @Column({ nullable: true })
  updatedBy: number | null;
}
```

Both columns are nullable. Records created before the audit subscriber existed (e.g. seeded records) will have `null`, which is correct and expected.

### Step 5 — Generate and Run the Migration

```bash
yarn api:migration:generate apps/api/src/migrations/AddAuditColumns
yarn api:migration:run
```

Review the generated SQL before running. It should add two nullable integer columns to the `todo` table (and any other entity you added them to):

```sql
ALTER TABLE "todo" ADD "created_by" integer;
ALTER TABLE "todo" ADD "updated_by" integer;
```

Test `migration:revert` locally before pushing:

```bash
yarn api:migration:revert
# Verify columns are gone in Adminer, then re-apply
yarn api:migration:run
```

### Step 6 — Register in AppModule and main.ts

```typescript
// apps/api/src/app/app.module.ts
import { Module } from "@nestjs/common";
import { APP_INTERCEPTOR } from "@nestjs/core";
// ... existing imports ...
import { AuditInterceptor } from "../interceptors/audit.interceptor";
import { UserContext } from "../interceptors/user-context";
import { AuditSubscriber } from "../subscribers/audit.subscriber";

@Module({
  imports: [
    // ... existing imports unchanged ...
  ],
  providers: [
    AppResolver,
    // Request-scoped context holder
    UserContext,
    // Global interceptor — populates UserContext from JWT on every request
    {
      provide: APP_INTERCEPTOR,
      useClass: AuditInterceptor,
    },
    // TypeORM subscriber — sets createdBy/updatedBy before every save
    AuditSubscriber,
  ],
})
export class AppModule {}
```

Using `APP_INTERCEPTOR` with the NestJS `provide` token registers `AuditInterceptor` globally — it applies to every resolver without decorating each one. The `APP_INTERCEPTOR` provider uses the DI container, which means `UserContext` is injected correctly with request scope propagated.

### Smoke Test: Audit Columns

```bash
# In GraphQL Playground, first authenticate to get a token
mutation {
  login(input: { email: "test@example.com", password: "password123" }) {
    accessToken
  }
}

# Set the token in HTTP headers:
# { "Authorization": "Bearer <your_token>" }

# Create a todo
mutation {
  createTodo(input: { text: "Test audit columns", userId: 1 }) {
    id
    text
    createdBy
    updatedBy
  }
}
# Expected: createdBy and updatedBy both equal your user ID (e.g. 1)

# Open Adminer → table: todo
# Verify created_by and updated_by columns are populated
```

If `createdBy` is `null`, confirm the `AuditInterceptor` is registered via `APP_INTERCEPTOR` in `AppModule`, and that the resolver uses `@UseGuards(AuthJwtGuard)` so `req.user` is populated before the interceptor runs.

---

## 3. Running Number Service

### What Problem This Solves

Auto-increment PKs are invisible to users and non-portable across tables. Enterprise systems often need human-readable, sequential identifiers: `TODO-0001`, `INV-2024-001`, `ORD-00042`. These cannot come from the PK column because:

1. PKs restart from different seeds per table
2. PKs are not formatted
3. Gaps appear when records are deleted (PK 3 deleted → jump from 2 to 4)

A `running_number` table stores the current counter per module name and increments it atomically using a transaction with `SELECT FOR UPDATE`. The lock ensures no two concurrent requests get the same number.

### Step 1 — RunningNumberEntity

```typescript
// apps/api/src/modules/running-number/running-number.entity.ts
import { Column, Entity, PrimaryGeneratedColumn } from "typeorm";

@Entity({ name: "running_number" })
export class RunningNumberEntity {
  @PrimaryGeneratedColumn()
  id: number;

  /**
   * Module key — uniquely identifies the counter.
   * Examples: 'TODO', 'INVOICE', 'ORDER'
   */
  @Column({ unique: true })
  module: string;

  /** Current counter value. The next generated number will be current + increment. */
  @Column({ default: 0 })
  current: number;

  /** How much to add per call. Default 1 for simple sequences. */
  @Column({ default: 1 })
  increment: number;
}
```

### Step 2 — RunningNumberService

```typescript
// apps/api/src/modules/running-number/running-number.service.ts
import { Injectable } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { Repository } from "typeorm";
import { RunningNumberEntity } from "./running-number.entity";

@Injectable()
export class RunningNumberService {
  constructor(
    @InjectRepository(RunningNumberEntity)
    private readonly repo: Repository<RunningNumberEntity>
  ) {}

  /**
   * Returns the next formatted number for the given module.
   *
   * Uses a database transaction with SELECT FOR UPDATE to prevent race
   * conditions. Two concurrent calls for 'TODO' cannot both get 'TODO-0001'.
   *
   * @param module - The module key, e.g. 'TODO'
   * @param padLength - Zero-padding width. Default 4 → 'TODO-0001'
   * @returns Formatted string, e.g. 'TODO-0001'
   */
  async getNext(module: string, padLength = 4): Promise<string> {
    return this.repo.manager.transaction(async em => {
      // Lock the row for this module — other transactions wait until we commit
      let record = await em.findOne(RunningNumberEntity, {
        where: { module },
        lock: { mode: "pessimistic_write" },
      });

      if (!record) {
        // First call for this module — create the record inside the transaction
        record = em.create(RunningNumberEntity, {
          module,
          current: 0,
          increment: 1,
        });
      }

      record.current += record.increment;
      await em.save(record);

      return `${module}-${String(record.current).padStart(padLength, "0")}`;
    });
  }
}
```

The `pessimistic_write` lock mode maps to `SELECT ... FOR UPDATE` in PostgreSQL. The transaction blocks any other transaction that tries to lock the same row until the first one commits. This guarantees sequential, gap-free numbers even under concurrent load.

> **From Meteor?** A common Meteor pattern was `findOne({ module })` + `update({ $inc: { current: 1 } })` in a method. Under concurrent load two requests could read the same value before either incremented it — both would get `TODO-0001`. The `SELECT FOR UPDATE` transaction makes that race condition impossible.

**Memory hook:** `SELECT FOR UPDATE` = one cashier drawer, one customer at a time. The next request waits for the lock to release before reading the counter.

### Step 3 — RunningNumberModule

```typescript
// apps/api/src/modules/running-number/running-number.module.ts
import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { RunningNumberEntity } from "./running-number.entity";
import { RunningNumberService } from "./running-number.service";

@Module({
  imports: [TypeOrmModule.forFeature([RunningNumberEntity])],
  providers: [RunningNumberService],
  exports: [RunningNumberService],
})
export class RunningNumberModule {}
```

> **Module analogy:** `RunningNumberModule` is its own **department in a company** — it owns the `RunningNumberEntity` table access and the `RunningNumberService` worker. By exporting `RunningNumberService`, it lends that worker to any other module (like `TodoModule`) that imports it. `TodoModule` borrows without knowing how the service is implemented internally.

**Memory hook:** Module = department. `exports` lends a worker to another department. The borrowing module never sees the internals — only the exported interface.

### Step 4 — Add referenceNumber to TodoEntity

```typescript
// apps/api/src/modules/todo/todo.entity.ts  (add this column)
@Column({ nullable: true })
referenceNumber: string | null;
```

The column is nullable because existing todos were created without it. After generating and running the migration, existing records will have `null`. New todos will get a reference number assigned in the service.

### Step 5 — Update TodoService to Generate Reference Numbers

First, import `RunningNumberModule` in `TodoModule`:

```typescript
// apps/api/src/modules/todo/todo.module.ts
import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { RunningNumberModule } from "../running-number/running-number.module";
import { TodoEntity } from "./todo.entity";
import { TodoResolver } from "./todo.resolver";
import { TodoService } from "./todo.service";
import {
  TodoCommandHandlers,
  TodoEventHandlers,
  TodoQueryHandlers,
} from "./cqrs";

@Module({
  imports: [
    TypeOrmModule.forFeature([TodoEntity]),
    RunningNumberModule, // ← inject RunningNumberService
  ],
  providers: [
    TodoResolver,
    TodoService,
    ...TodoQueryHandlers,
    ...TodoCommandHandlers,
    ...TodoEventHandlers,
  ],
  exports: [TodoService],
})
export class TodoModule {}
```

Update `TodoService.createOneTodo` to call `getNext`:

```typescript
// apps/api/src/modules/todo/todo.service.ts
import {
  BadRequestException,
  Injectable,
  NotFoundException,
} from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { TypeOrmQueryService } from "@ptc-org/nestjs-query-typeorm";
import { CqrsCommandFunc, CqrsQueryFunc } from "nestjs-typed-cqrs";
import { Repository } from "typeorm";

import {
  CountTodoQuery,
  CreateOneTodoCommand,
  DeleteOneTodoCommand,
  FindManyTodoQuery,
  FindOneTodoQuery,
  UpdateOneTodoCommand,
} from "./cqrs/todo.cqrs.input";
import { TodoEntity } from "./todo.entity";
import { RunningNumberService } from "../running-number/running-number.service";

@Injectable()
export class TodoService extends TypeOrmQueryService<TodoEntity> {
  constructor(
    @InjectRepository(TodoEntity)
    repo: Repository<TodoEntity>,
    private readonly runningNumberService: RunningNumberService
  ) {
    super(repo);
  }

  // ... findOneTodo, findManyTodo, countTodo unchanged ...

  createOneTodo: CqrsCommandFunc<
    CreateOneTodoCommand,
    CreateOneTodoCommand["args"]
  > = async ({ input }) => {
    try {
      const existing = await this.repo.findOne({
        where: { text: input.text, userId: input.userId },
      });
      if (existing) {
        throw new Error("You already have a todo with that text");
      }

      // Generate reference number before saving
      const referenceNumber = await this.runningNumberService.getNext("TODO");

      const todo = this.repo.create({ ...input, referenceNumber });
      const data = await this.repo.save(todo);
      return { success: true, data };
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };

  // ... updateOneTodo, deleteOneTodo unchanged ...
}
```

### Step 6 — Register RunningNumberEntity in AppModule

The CLAUDE.md gotcha applies: every entity must be explicitly listed in `AppModule`'s `entities[]`:

```typescript
// apps/api/src/app/app.module.ts  (entities array update)
import { RunningNumberEntity } from '../modules/running-number/running-number.entity';

// Inside TypeOrmModule.forRootAsync useFactory:
entities: [TodoEntity, UserEntity, RunningNumberEntity],
```

### Step 7 — Generate Migration

```bash
yarn api:migration:generate apps/api/src/migrations/AddRunningNumberAndTodoReference
yarn api:migration:run
```

The generated migration creates the `running_number` table and adds `reference_number` to `todo`.

### Smoke Test: Running Numbers

```bash
# Create three todos in sequence (authenticated)

mutation {
  createTodo(input: { text: "First todo", userId: 1 }) {
    id
    text
    referenceNumber
  }
}
# Expected: referenceNumber "TODO-0001"

mutation {
  createTodo(input: { text: "Second todo", userId: 1 }) {
    id
    text
    referenceNumber
  }
}
# Expected: referenceNumber "TODO-0002"

mutation {
  createTodo(input: { text: "Third todo", userId: 1 }) {
    id
    text
    referenceNumber
  }
}
# Expected: referenceNumber "TODO-0003"

# Adminer → table: running_number
# Row: module="TODO", current=3, increment=1

# Adminer → table: todo
# Three rows with reference_number: TODO-0001, TODO-0002, TODO-0003
```

---

## 4. libs/core Extraction

### What Problem This Solves

Currently, the `ConfigModule` setup — with its Joi validation schema and `configuration()` factory — lives entirely inside `apps/api`. When you add a second NestJS app to the monorepo (a common progression: you might add `apps/portal-api` for admin endpoints, `apps/jobs-worker` for Bull queue consumers, or `apps/webhooks` for incoming webhook handling), that app needs identical database config, identical Redis config, identical JWT config.

Duplicating the config setup across two apps means updates to environment variable names must be made in two places. `libs/core` is the escape hatch: shared infrastructure code that any app in the monorepo can import.

> **Nx monorepo analogy:** The monorepo is an **apartment building with strict bylaws**. Each app (`apps/api`, `apps/portal-api`) is a locked unit — tenants cannot enter each other's units directly. Shared items travel through `libs/core`, which acts as the **building intercom** — the only legal channel between apps. The Nx module boundary rule is the alarm that triggers if anyone tries to climb through a window instead.

> **ConfigModule analogy:** `CoreConfigModule` is the **company policy handbook in a locked cabinet**. Instead of each developer keeping private sticky notes with environment variable names, one handbook that all apps consult. Before the company opens each morning (app startup), the Joi validation schema checks the handbook is complete — a missing required variable keeps the office closed until it is fixed.

> **From Meteor?** `Meteor.settings` was a single-app concept — there was no monorepo, no second app to share config with. `libs/core` solves a problem Meteor never had: giving two independently deployable NestJS apps identical config without copy-paste.

**Memory hook:** `libs/core` = building intercom. The only legal bridge between apps. Config lives here once; both apps read from it.

> **`synchronize: false` note:** The `AppModule` above uses `synchronize: false`. This is correct for any environment beyond local dev throwaway. `synchronize: true` is an **unsupervised contractor** — it makes schema changes without asking, with no undo. Use migrations instead.

### Generate the Library

```bash
npx nx generate @nx/nest:library core \
  --directory=libs/core \
  --importPath=@enterprise-todo/core \
  --buildable
```

This creates:

```
libs/core/
  src/
    lib/
      core.module.ts   ← generated placeholder, will be replaced
    index.ts           ← re-exports
  tsconfig.json
  tsconfig.lib.json
  project.json
```

### Move Config into libs/core

Create the directory structure:

```
libs/core/src/
  config/
    config.mapper.ts
    config.validation.ts
    config.module.ts
  constants/
    index.ts
  index.ts
```

**config.mapper.ts** — the typed config factory:

```typescript
// libs/core/src/config/config.mapper.ts

export interface AppConfig {
  port: number;
  nodeEnv: string;
  db: {
    host: string;
    port: number;
    username: string;
    password: string;
    database: string;
    debug: boolean;
  };
  redis: {
    host: string;
    port: number;
  };
  jwt: {
    publicKey: string;
    privateKey: string;
    expiresIn: string;
  };
  graphql: {
    playground: boolean;
  };
}

/**
 * Maps raw process.env values to a typed AppConfig object.
 * Called by ConfigModule.forRoot({ load: [configuration] }).
 */
export const configuration = (): AppConfig => ({
  port: parseInt(process.env.PROJECT_PORT ?? "3333", 10),
  nodeEnv: process.env.NODE_ENV ?? "development",
  db: {
    host: process.env.PROJECT_DB_HOST ?? "localhost",
    port: parseInt(process.env.PROJECT_DB_PORT ?? "5432", 10),
    username: process.env.PROJECT_DB_USERNAME ?? "postgres",
    password: process.env.PROJECT_DB_PASSWORD ?? "",
    database: process.env.PROJECT_DB_DATABASE ?? "enterprise_todo",
    debug: process.env.PROJECT_DB_DEBUG === "true",
  },
  redis: {
    host: process.env.PROJECT_REDIS_HOST ?? "localhost",
    port: parseInt(process.env.PROJECT_REDIS_PORT ?? "6379", 10),
  },
  jwt: {
    publicKey: process.env.JWT_PUBLIC_KEY ?? "",
    privateKey: process.env.JWT_PRIVATE_KEY ?? "",
    expiresIn: process.env.JWT_EXPIRES_IN ?? "7d",
  },
  graphql: {
    playground: process.env.PROJECT_GRAPHQL_PLAYGROUND === "true",
  },
});
```

**config.validation.ts** — the Joi schema:

```typescript
// libs/core/src/config/config.validation.ts
import * as Joi from "joi";

export const validationSchema = Joi.object({
  NODE_ENV: Joi.string()
    .valid("development", "staging", "production", "test")
    .default("development"),
  PROJECT_PORT: Joi.number().default(3333),

  PROJECT_DB_HOST: Joi.string().required(),
  PROJECT_DB_PORT: Joi.number().default(5432),
  PROJECT_DB_USERNAME: Joi.string().required(),
  PROJECT_DB_PASSWORD: Joi.string().required(),
  PROJECT_DB_DATABASE: Joi.string().required(),
  PROJECT_DB_DEBUG: Joi.boolean().default(false),

  PROJECT_REDIS_HOST: Joi.string().default("localhost"),
  PROJECT_REDIS_PORT: Joi.number().default(6379),

  JWT_PUBLIC_KEY: Joi.string().required(),
  JWT_PRIVATE_KEY: Joi.string().required(),
  JWT_EXPIRES_IN: Joi.string().default("7d"),

  PROJECT_GRAPHQL_PLAYGROUND: Joi.boolean().default(false),
});
```

**config.module.ts** — the wrapper module:

```typescript
// libs/core/src/config/config.module.ts
import { Module } from "@nestjs/common";
import { ConfigModule } from "@nestjs/config";
import { configuration } from "./config.mapper";
import { validationSchema } from "./config.validation";

/**
 * Drop-in replacement for ConfigModule.forRoot(...) in any NestJS app.
 * Imports this module instead of configuring ConfigModule inline.
 *
 * Usage in AppModule:
 *   imports: [CoreConfigModule, ...]
 */
@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      envFilePath: ".env",
      load: [configuration],
      validationSchema,
    }),
  ],
  exports: [ConfigModule],
})
export class CoreConfigModule {}
```

**constants/index.ts** — shared constants:

```typescript
// libs/core/src/constants/index.ts

export const QUEUE_NAMES = {
  EMAIL: "email",
  NOTIFICATION: "notification",
  AUDIT_LOG: "audit-log",
} as const;

export const TOKEN_ISSUER = "enterprise-todo";

export const REDIS_KEYS = {
  USER_SESSION: (userId: number) => `session:user:${userId}`,
  TODO_CACHE: (todoId: number) => `cache:todo:${todoId}`,
} as const;
```

**libs/core/src/index.ts** — public API of the library:

```typescript
// libs/core/src/index.ts
export { CoreConfigModule } from "./config/config.module";
export type { AppConfig } from "./config/config.mapper";
export { configuration } from "./config/config.mapper";
export { validationSchema } from "./config/config.validation";
export * from "./constants";
```

### Update tsconfig.base.json

Add the path mapping so TypeScript resolves `@enterprise-todo/core` to the library source:

```json
// tsconfig.base.json  (paths section)
{
  "compilerOptions": {
    "paths": {
      "@enterprise-todo/contracts": ["./libs/contracts/src/index.ts"],
      "@enterprise-todo/core": ["./libs/core/src/index.ts"]
    }
  }
}
```

The Nx generator may have already added this. Verify with `cat tsconfig.base.json | grep -A5 paths`.

### Update AppModule to Use CoreConfigModule

```typescript
// apps/api/src/app/app.module.ts
import { Module } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { TypeOrmModule } from "@nestjs/typeorm";
import { GraphQLModule } from "@nestjs/graphql";
import { ApolloDriver, ApolloDriverConfig } from "@nestjs/apollo";
import { CqrsModule } from "@nestjs/cqrs";
import { APP_INTERCEPTOR } from "@nestjs/core";
import { SnakeNamingStrategy } from "typeorm-naming-strategies";

// Imported from libs/core — shared across all apps in the monorepo
import { CoreConfigModule } from "@enterprise-todo/core";

import { AppResolver } from "./app.resolver";
import { HealthModule } from "../modules/health/health.module";
import { TodoModule } from "../modules/todo/todo.module";
import { TodoEntity } from "../modules/todo/todo.entity";
import { UserEntity } from "../modules/user/user.entity";
import { RunningNumberEntity } from "../modules/running-number/running-number.entity";
import { AuditInterceptor } from "../interceptors/audit.interceptor";
import { UserContext } from "../interceptors/user-context";
import { AuditSubscriber } from "../subscribers/audit.subscriber";

@Module({
  imports: [
    // Replaces the inline ConfigModule.forRoot — now shared via libs/core
    CoreConfigModule,

    TypeOrmModule.forRootAsync({
      inject: [ConfigService],
      useFactory: (config: ConfigService) => ({
        type: "postgres",
        host: config.get("PROJECT_DB_HOST"),
        port: config.get<number>("PROJECT_DB_PORT"),
        username: config.get("PROJECT_DB_USERNAME"),
        password: config.get("PROJECT_DB_PASSWORD"),
        database: config.get("PROJECT_DB_DATABASE"),
        entities: [TodoEntity, UserEntity, RunningNumberEntity],
        synchronize: false,
        logging: config.get("PROJECT_DB_DEBUG") === "true",
        namingStrategy: new SnakeNamingStrategy(),
      }),
    }),

    GraphQLModule.forRootAsync<ApolloDriverConfig>({
      driver: ApolloDriver,
      inject: [ConfigService],
      useFactory: (config: ConfigService) => ({
        autoSchemaFile: true,
        playground: config.get("PROJECT_GRAPHQL_PLAYGROUND") === "true",
        context: ({ req }) => ({ req }),
      }),
    }),

    CqrsModule.forRoot(),
    HealthModule,
    TodoModule,
  ],
  providers: [
    AppResolver,
    UserContext,
    {
      provide: APP_INTERCEPTOR,
      useClass: AuditInterceptor,
    },
    AuditSubscriber,
  ],
})
export class AppModule {}
```

### What a Second App Would Look Like

To illustrate the value: a hypothetical `apps/portal-api/src/app/app.module.ts` would start with:

```typescript
// apps/portal-api/src/app/app.module.ts  (hypothetical — not created in this tutorial)
import { CoreConfigModule } from "@enterprise-todo/core";
import { QUEUE_NAMES } from "@enterprise-todo/core";

@Module({
  imports: [
    CoreConfigModule, // ← identical config setup, zero duplication
    // ... portal-specific modules ...
  ],
})
export class PortalAppModule {}
```

The `CoreConfigModule`, Joi validation, `AppConfig` type, and queue name constants are all imported from `libs/core`. Any update to environment variable names or validation rules propagates to both apps automatically.

### Smoke Test: libs/core Extraction

```bash
# Build verification — ensures the path alias and imports resolve correctly
yarn api:build
# Expected: build completes without "Cannot find module '@enterprise-todo/core'" errors

# Runtime verification
yarn api:dev
# Expected: "API running at http://localhost:3333" — no ConfigService errors

# Health check
curl http://localhost:3333/graphql -X POST \
  -H "Content-Type: application/json" \
  -d '{"query":"{ health }"}'
# Expected: { "data": { "health": "ok" } }
```

If the build fails with `Cannot find module '@enterprise-todo/core'`, verify that `tsconfig.base.json` has the path entry and that the library's `tsconfig.json` is referenced from the root `tsconfig.json`.

---

## 5. Migration Strategy for Additive Changes

This tutorial added several columns to existing tables. The general strategy for production-safe additive migrations:

> **Migration analogy:** Every migration in this section is a **git commit for the database**. `up()` applies the change; `down()` reverts it. You never edit a migration that has already run in production — you add a new one. The `migration:revert` command is your `git revert`.

> **From Meteor?** MongoDB has no migrations — schema changes just happen (or silently don't). When you need to add a required column to a 50,000-row table in PostgreSQL, no-migration becomes a production incident. Every schema change in NestJS is visible, reversible, and reviewable.

**Memory hook:** Migration = git commit for DB. `up()` applies, `down()` reverts. Never edit old migrations. Test both directions locally first.

### Rule 1: Nullable Columns Are Always Safe

Adding a nullable column to a table with existing data is always backward compatible. Existing rows get `NULL`. No application downtime required.

```typescript
// Always add new columns as nullable first
await queryRunner.addColumn(
  "todo",
  new TableColumn({
    name: "reference_number",
    type: "varchar",
    isNullable: true, // ← safe for existing rows
  })
);
```

### Rule 2: Backfill Before Adding NOT NULL Constraints

If the column will eventually be `NOT NULL`, do it in two steps: add nullable, backfill, then add the constraint. Never add a `NOT NULL` column without a `DEFAULT` to an existing non-empty table — PostgreSQL must update every row, which locks the table.

```typescript
// apps/api/src/migrations/1718100000000-BackfillReferenceNumbers.ts
import { MigrationInterface, QueryRunner, TableColumn } from 'typeorm';

export class BackfillReferenceNumbers1718100000000 implements MigrationInterface {
  public async up(queryRunner: QueryRunner): Promise<void> {
    // Step 1: Add nullable column (safe, no lock)
    await queryRunner.addColumn('todo', new TableColumn({
      name: 'reference_number',
      type: 'varchar',
      isNullable: true,
    }));

    // Step 2: Initialize running_number table for backfill
    await queryRunner.query(`
      INSERT INTO running_number (module, current, increment)
      VALUES ('TODO', 0, 1)
      ON CONFLICT (module) DO NOTHING
    `);

    // Step 3: Backfill existing rows using PostgreSQL row numbering
    await queryRunner.query(`
      UPDATE todo
      SET reference_number = CONCAT('TODO-', LPAD(id::text, 4, '0'))
      WHERE reference_number IS NULL
    `);

    // Step 4 (optional): Add NOT NULL constraint after backfill
    // Only safe to do once ALL rows have a value
    -- await queryRunner.changeColumn('todo', 'reference_number', new TableColumn({
    --   name: 'reference_number',
    --   type: 'varchar',
    --   isNullable: false,
    -- }));
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.dropColumn('todo', 'reference_number');
  }
}
```

For step 4, the backfill approach uses the existing `id` as a proxy. New todos will get sequential numbers from `RunningNumberService`. The gap between backfilled values (based on id) and new values (based on the running_number counter) is intentional — reference numbers are not guaranteed to be contiguous with backfilled records.

### Rule 3: Two Migration Files for Schema + Data Changes

The TypeORM `migration:generate` command produces SQL from entity diffs. Data backfill requires a separate file created with `migration:create`. Never mix schema changes and data changes in the auto-generated file — it makes `migration:revert` difficult to reason about.

```bash
# Schema change (auto-generated from entity diff)
yarn api:migration:generate apps/api/src/migrations/AddReferenceNumberColumn

# Data backfill (manually authored)
yarn api:migration:create apps/api/src/migrations/BackfillReferenceNumbers
```

### Rule 4: Always Test Revert

```bash
yarn api:migration:run     # apply
yarn api:migration:revert  # undo last migration
yarn api:migration:run     # re-apply — verify idempotent
```

Production migrations for this project run as one-off ECS tasks before traffic is routed to the new container. `migration:revert` in production is an emergency procedure — test it locally so you know it works.

---

## 6. Complete Smoke Test Checklist

Run these in order after completing all four sections:

### 1. Column Transformer Verification

```bash
# Start fresh
yarn docker:dev && yarn api:dev

# Register with mixed-case inputs
# POST to GraphQL: register mutation with email "ADMIN@EXAMPLE.COM", username "ADMIN"
# Open Adminer → user table → verify: email = "admin@example.com", username = "admin"
```

**Pass criteria:** Stored values are lowercase. Mixed-case inputs produce identical stored values to lowercase inputs (unique constraint treats them as duplicates).

### 2. Audit Column Verification

```bash
# Login to get JWT token
# Create a todo with Authorization header set
# Adminer → todo table → verify: created_by = <your user id>, updated_by = <your user id>

# Update the todo
# Adminer → verify: created_by unchanged, updated_by = <your user id>
```

**Pass criteria:** `created_by` is set on insert and never overwritten on update. `updated_by` is set on both insert and update.

### 3. Running Number Verification

```bash
# Create three todos sequentially
# Each mutation response should include referenceNumber

# createTodo #1 → referenceNumber: "TODO-0001"
# createTodo #2 → referenceNumber: "TODO-0002"
# createTodo #3 → referenceNumber: "TODO-0003"

# Adminer → running_number table → row: module="TODO", current=3
# Adminer → todo table → three rows with reference_number values
```

**Pass criteria:** Numbers are sequential, zero-padded to 4 digits, prefixed with "TODO-".

### 4. libs/core Build Verification

```bash
# Stop dev server
# Full build to catch import resolution issues
yarn api:build

# Expected output:
# > nx build api
# ✔ Compiled successfully

# Restart dev server
yarn api:dev
# Expected: starts without errors, "API running at http://localhost:3333"

# Verify config still loads
curl http://localhost:3333/graphql -X POST \
  -H "Content-Type: application/json" \
  -d '{"query":"{ health }"}'
# Expected: {"data":{"health":"ok"}}
```

**Pass criteria:** `yarn api:build` and `yarn api:dev` succeed with no module resolution errors.

---

## Quick Reference

| Concept | Analogy | Meteor equivalent | The one rule |
|---------|---------|-------------------|--------------|
| Column Transformer | One-way valve on the column | `aldeed:simple-schema` trim/lowercase — but optional | `to()` normalizes on write; query WHERE clauses are also transformed |
| `AbstractEntity` | Company letterhead | `collection2` auto-timestamps | All entities extend it; never repeat `id` or timestamps |
| `Scope.REQUEST` | Fresh cup brewed per visitor | `this.userId` in Meteor fiber (implicit) | Must be explicit in NestJS; cascades up the dependency tree |
| Interceptor | Sandwich (top bread = before, bottom = after) | No direct equivalent | Code before `next.handle()` runs pre-handler; `.pipe()` runs post-handler |
| TypeORM EntitySubscriber | Silent co-worker who stamps every document | Manual `createdBy = this.userId` in every method | No `listenTo()` = fires on all entities automatically |
| Migration | Git commit for the database | No migrations in Meteor/MongoDB | `up()` applies, `down()` reverts; never edit old migrations |
| `synchronize: true` | Unsupervised contractor | Not applicable | Never in production; use migrations |
| Repository / RunningNumberService | Librarian | `findOne` + manual increment in a method | Only layer touching DB; `SELECT FOR UPDATE` prevents race conditions |
| `RunningNumberModule` | Department in a company | Single-app, no module system | `exports` lends `RunningNumberService`; `TodoModule` imports to borrow |
| Nx monorepo / `libs/core` | Apartment building with strict bylaws | Not applicable (single-app model) | Cross-app sharing only through `libs/`; direct imports between apps are banned |
| `CoreConfigModule` | Company policy handbook in a locked cabinet | `Meteor.settings` — no startup validation | Joi schema fails startup if any required variable is missing |

---

## Summary: Before vs After

| Concern                 | Before (manual patterns)                              | After (automated patterns)                                         |
| ----------------------- | ----------------------------------------------------- | ------------------------------------------------------------------ |
| Email casing            | `input.email.toLowerCase()` in every service method   | `LowerCaseTransformer` on `@Column` — structural guarantee         |
| Who created a record    | Set `input.createdBy = user.id` manually per mutation | `AuditSubscriber` — fires automatically on all entities            |
| Human-readable IDs      | Ad-hoc string concat in service, race condition risk  | `RunningNumberService` with `SELECT FOR UPDATE` transaction        |
| Config for second app   | Copy-paste `ConfigModule.forRoot(...)`                | `import { CoreConfigModule } from '@enterprise-todo/core'`         |
| Adding nullable columns | No strategy                                           | Add nullable → backfill → optional NOT NULL in separate migrations |

---

## What You Have Now

- **`apps/api/src/helpers/transformer.ts`** — `LowerCaseTransformer`, `SlugTransformer`, `UpperCaseTransformer`
- **`apps/api/src/interceptors/user-context.ts`** — Request-scoped `UserContext` holder
- **`apps/api/src/interceptors/audit.interceptor.ts`** — `AuditInterceptor` (global via `APP_INTERCEPTOR`)
- **`apps/api/src/subscribers/audit.subscriber.ts`** — `AuditSubscriber` (auto-sets `createdBy`/`updatedBy`)
- **`apps/api/src/modules/running-number/`** — `RunningNumberEntity`, `RunningNumberService`, `RunningNumberModule`
- **`libs/core/src/config/`** — `CoreConfigModule`, `AppConfig`, `configuration`, `validationSchema`
- **`libs/core/src/constants/`** — `QUEUE_NAMES`, `TOKEN_ISSUER`, `REDIS_KEYS`
- **`libs/core/src/index.ts`** — Public API of `@enterprise-todo/core`
- **Migrations** — audit columns, running_number table, reference_number column, email normalization backfill
- **`tsconfig.base.json`** — `@enterprise-todo/core` path alias registered

Every new entity you add will automatically receive `createdBy`/`updatedBy` audit columns (once added to the entity definition) without touching any handler or service. Every call to `runningNumberService.getNext('INVOICE')` returns a race-condition-safe sequence number. Every NestJS app added to the monorepo imports config from one place.
