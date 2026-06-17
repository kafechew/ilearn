---
author: Kai
pubDatetime: 2026-05-04T09:00:00+08:00
title: Database - PostgreSQL, TypeORM, Entities & Migrations
featured: false
draft: false
slug: 6104-database-postgresql-typeorm-entities-migrations
tags:
  - deeptech
  - meteorjs
  - nestjs
  - typescript
  - backend
  - code
  - database
  - typeorm
  - postgresql
  - mongodb
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/04-database-postgresql-typeorm-entities-migrations.png"
description: By the end of this part, you will learn PostgreSQL, TypeORM, AbstractEntity, SnakeNamingStrategy, migration lifecycle and verify your schema in Adminer.
---

## What This Part Covers

- Why PostgreSQL instead of MongoDB
- TypeORM: the ORM that bridges TypeScript classes and SQL
- `AbstractEntity` — the base class every entity extends
- Writing a complete entity with columns, relations, and indexes
- `SnakeNamingStrategy` — how TypeScript camelCase becomes SQL snake_case
- The migration lifecycle: generate → review → run → revert
- How to verify your schema in Adminer

---

## Meteor Equivalent

```javascript
// Meteor: one line, no schema, no migrations
const TasksCollection = new Mongo.Collection("tasks");

// To "define" the schema (optional):
TasksCollection.schema = new SimpleSchema({
  text: { type: String },
  userId: { type: String },
});
```

```typescript
// Enterprise NestJS: explicit, typed, migrations-tracked
@Entity({ name: "todo" })
export class TodoEntity extends AbstractEntity {
  @Column()
  text: string;

  @Column({ default: false })
  isChecked: boolean;

  @Column()
  userId: number;
}
// Then: yarn api:migration:generate apps/api/src/migrations/CreateTodoTable
// Then: review the SQL, then: yarn api:migration:run
```

The difference: PostgreSQL enforces the schema. Every field must exist in the table. Adding a field without a migration crashes the app. This sounds harsh — and it protects you from the MongoDB chaos of half-migrated documents.

---

## 1. Why PostgreSQL?

MongoDB is document-based: each record is a JSON-like object with no guaranteed shape. This is fast to start with and painful to maintain.

PostgreSQL is relational: each row in a table has a fixed, typed schema. You define columns once. Every row conforms. The database enforces this.

**What you gain with PostgreSQL:**

| Concern            | MongoDB                                    | PostgreSQL                                      |
| ------------------ | ------------------------------------------ | ----------------------------------------------- |
| Schema enforcement | Optional (SimpleSchema is opt-in)          | Mandatory — columns must exist                  |
| Foreign keys       | No native FK constraints                   | `FOREIGN KEY` constraints prevent orphaned data |
| Transactions       | Multi-document transactions (v4+, complex) | ACID transactions — built-in, simple            |
| Migrations         | None (schema-less)                         | TypeORM migrations — versioned, reversible      |
| Joins              | `$lookup` aggregation                      | SQL `JOIN` — optimized, indexes work            |
| Type safety        | Documents are `any`                        | TypeScript entity maps exactly to table columns |
| Full-text search   | Text index                                 | `tsvector` + GIN index (PostGIS for geo)        |

> **The real-world argument:** Your database is your last line of defense against bad data. A MongoDB collection lets you save `{ isChecked: "yes" }` when you expected `boolean`. A PostgreSQL `BOOLEAN` column will reject it with an error. In production, bad data corrupts reports, breaks features, and is expensive to clean up.

---

## 2. TypeORM: The Object-Relational Mapper

TypeORM maps TypeScript classes to PostgreSQL tables. The class **is** the schema.

```typescript
@Entity({ name: "todo" }) // ← creates/references the "todo" table in PostgreSQL
export class TodoEntity {
  @PrimaryGeneratedColumn() // ← id SERIAL PRIMARY KEY
  id: number;

  @Column() // ← text VARCHAR NOT NULL
  text: string;

  @Column({ default: false }) // ← is_checked BOOLEAN DEFAULT false
  isChecked: boolean;

  @CreateDateColumn({ name: "created_at" }) // ← created_at TIMESTAMPTZ
  createdAt: Date;
}
```

TypeORM translates this class to SQL:

```sql
CREATE TABLE "todo" (
  "id"          SERIAL PRIMARY KEY,
  "text"        CHARACTER VARYING NOT NULL,
  "is_checked"  BOOLEAN NOT NULL DEFAULT false,
  "created_at"  TIMESTAMP WITH TIME ZONE DEFAULT now()
);
```

You write TypeScript. TypeORM writes SQL.

---

## 3. `AbstractEntity` — The Base Class

Every entity in this codebase extends `AbstractEntity` from [`nestjs-dev-utilities`](https://github.com/louiskhenghao/nestjs-dev-utilities). It provides three columns that every entity needs:

```typescript
// From nestjs-dev-utilities (simplified for illustration):
export abstract class AbstractEntity {
  @PrimaryGeneratedColumn()
  id: number;

  @CreateDateColumn({ name: "created_at", type: "timestamp with time zone" })
  createdAt: Date;

  @UpdateDateColumn({ name: "updated_at", type: "timestamp with time zone" })
  updatedAt: Date;
}
```

**Why extend it instead of writing your own?**

- `id`, `created_at`, `updated_at` are on every table. Repeating these three columns in every entity is noise.
- The column names `created_at` and `updated_at` are **hardcoded** with `name: 'created_at'` — they will always be snake_case regardless of the naming strategy. This is intentional. (More on this in §5.)
- `@UpdateDateColumn` automatically updates the timestamp whenever the row is saved. You never set it manually.

```typescript
// Your entity:
@Entity({ name: "todo" })
export class TodoEntity extends AbstractEntity {
  // id, createdAt, updatedAt come FREE from AbstractEntity
  // You only declare the fields unique to this entity:

  @Column()
  text: string;

  @Column({ default: false })
  isChecked: boolean;
}
```

> **Think of an entity as a government form template.** The template defines every field — name, type, whether it's required, the maximum length. Every filled-in form (database row) must match the template exactly. When the government revises the form (migration), all future submissions follow the new version. TypeORM reads these class definitions and generates the actual SQL for you.

---

## 4. `AbstractDto` — The Base DTO

Similar to `AbstractEntity`, there is `AbstractDto` for your read-facing DTOs. It exposes `id`, `createdAt`, `updatedAt` in the GraphQL schema:

```typescript
// From nestjs-dev-utilities (simplified):
@ObjectType()
export abstract class AbstractDto {
  @FilterableField(() => Int)
  id: number;

  @Field()
  createdAt: Date;

  @Field()
  updatedAt: Date;
}
```

Your DTO extends it:

```typescript
@ObjectType("Todo")
export class TodoDto extends AbstractDto {
  // id, createdAt, updatedAt come from AbstractDto
  @FilterableField()
  text: string;

  @FilterableField()
  isChecked: boolean;
}
```

---

## 5. SnakeNamingStrategy

TypeScript convention: `camelCase` for properties.
SQL convention: `snake_case` for column names.

Without `SnakeNamingStrategy`:

```typescript
@Column()
isChecked: boolean;
// → column name: "isChecked" (TypeScript name, bad SQL convention)
```

With `SnakeNamingStrategy`:

```typescript
@Column()
isChecked: boolean;
// → column name: "is_checked" (correct SQL convention)
```

Add it to your TypeORM config:

```typescript
// In app.module.ts TypeOrmModule.forRootAsync:
import { SnakeNamingStrategy } from "typeorm-naming-strategies";

TypeOrmModule.forRootAsync({
  useFactory: (config: ConfigService) => ({
    // ... other config ...
    namingStrategy: new SnakeNamingStrategy(),
  }),
});
```

Install the package:

```bash
yarn add typeorm-naming-strategies
```

> **Already done if you followed Part 02.** The `typeorm-naming-strategies` package and the `namingStrategy` line in `app.module.ts` were added as part of the environment setup. This section explains _why_ it exists.

**The exception:** `AbstractEntity` hardcodes `name: 'created_at'` in the `@CreateDateColumn` decorator. This means `createdAt` always maps to `created_at` regardless of any naming strategy. Why? To guarantee consistency — even if you swap naming strategies later, audit columns never change their DB name.

**Rule: your entity columns follow the naming strategy. `created_at` and `updated_at` are always `created_at` and `updated_at`.**

---

## 6. Column Types Reference

```typescript
@Entity({ name: "todo" })
export class TodoEntity extends AbstractEntity {
  // Basic string (VARCHAR NOT NULL)
  @Column()
  text: string;

  // String with length limit
  @Column({ length: 100 })
  slug: string;

  // String that can be null
  @Column({ nullable: true })
  description: string | null;

  // Boolean with default
  @Column({ default: false })
  isChecked: boolean;

  // Integer
  @Column({ type: "int" })
  priority: number;

  // Decimal (e.g. price)
  @Column({ type: "decimal", precision: 10, scale: 2 })
  price: number;

  // Enum column
  @Column({ type: "enum", enum: TodoStatus, default: TodoStatus.ACTIVE })
  status: TodoStatus;

  // JSON column
  @Column({ type: "jsonb", nullable: true })
  metadata: Record<string, unknown> | null;

  // Indexed column (add @Index to columns used in WHERE clauses)
  @Index()
  @Column()
  userId: number;
}
```

> **Performance rule:** Add `@Index()` to every column you use in a `WHERE` clause. PostgreSQL will scan the entire table for `WHERE user_id = ?` without an index. With an index, it jumps directly. On 1 million rows the difference is milliseconds vs. seconds.

---

## 7. Relations

Relations define how tables relate to each other. This replaces MongoDB's embedding or manual `userId` lookups.

### Foreign Key (ManyToOne)

A todo belongs to one user. One user has many todos.

```typescript
import { ManyToOne, JoinColumn, RelationId } from "typeorm";
import { UserEntity } from "../user/user.entity";

@Entity({ name: "todo" })
export class TodoEntity extends AbstractEntity {
  @Column()
  text: string;

  // The FK relationship — joins to UserEntity
  @ManyToOne(() => UserEntity, { onDelete: "CASCADE" })
  @JoinColumn()
  user: UserEntity;

  // The FK value as a plain number — no join needed to read this
  @Column()
  @RelationId((todo: TodoEntity) => todo.user)
  userId: number;
}
```

**Why both `@ManyToOne` and `@RelationId`?**

- `@ManyToOne` defines the actual relationship (the `user_id` foreign key column in the DB, the ability to JOIN)
- `@RelationId` creates a TypeScript property (`userId`) that always contains the raw FK integer, without requiring a JOIN

```typescript
// Read just the ID (cheap, no JOIN):
const todo = await repo.findOne({ where: { id: 1 } });
console.log(todo.userId); // → 5  (always available, no extra query)

// Read the full user object (needs a JOIN):
const todo = await repo.findOne({ where: { id: 1 }, relations: ["user"] });
console.log(todo.user.fullname); // → "Alice"
```

You will use `userId` constantly (for filtering, ownership checks). You will only load `todo.user` when you actually need to display user data — and even then, DataLoader batches the query (Part 09).

### ManyToMany

A todo can have many tags. A tag can be on many todos.

```typescript
import { ManyToMany, JoinTable } from "typeorm";
import { TagEntity } from "../tag/tag.entity";

@Entity({ name: "todo" })
export class TodoEntity extends AbstractEntity {
  @ManyToMany(() => TagEntity, { cascade: true })
  @JoinTable({
    name: "todo_tag", // the join table name
    joinColumn: { name: "todo_id" },
    inverseJoinColumn: { name: "tag_id" },
  })
  tags: TagEntity[];
}
```

TypeORM automatically manages the `todo_tag` join table. You never write SQL for it.

---

## 8. Create the UserEntity Stub

> **The librarian:** In the enterprise pattern, the repository is the only layer allowed to talk to the database. Services don't write TypeORM queries directly — they ask the repository, which translates the request and returns typed results. You (the service) say "I need the user with this email." You don't go into the stacks yourself. The librarian (repository) fetches it. You don't care if it came from shelf 3 or a cache — you just get the result.

`TodoEntity` has a `@ManyToOne` relation to `UserEntity`. That import must resolve before the build succeeds — but `UserEntity` is fully built in Part 07 (Authentication).

Create the stub now so the build works. You will flesh it out in Part 07.

```typescript
// apps/api/src/modules/user/user.constant.ts
import { registerEnumType } from '@nestjs/graphql';

export enum UserStatus {
  ACTIVE = 'ACTIVE',
  INACTIVE = 'INACTIVE',
  SUSPENDED = 'SUSPENDED',
}

registerEnumType(UserStatus, { name: 'UserStatus' });
```

```typescript
// apps/api/src/modules/user/user.entity.ts
import { Column, Entity, Index } from 'typeorm';
import { AbstractEntity } from 'nestjs-dev-utilities';
import { UserStatus } from './user.constant';

@Entity({ name: 'user' })
export class UserEntity extends AbstractEntity {
  @Column()
  fullname: string;

  @Index()
  @Column({ unique: true })
  username: string;

  @Index()
  @Column({ unique: true })
  email: string;

  // NEVER expose this field in any DTO — it is never sent to clients
  @Column()
  password: string;

  @Column({ type: 'enum', enum: UserStatus, default: UserStatus.ACTIVE })
  status: UserStatus;

  @Column({ nullable: true })
  twoFactorSecret: string | null;
}
```

> Part 07 adds auth logic (hashing, JWT, guards) on top of this entity. The shape will not change — only the surrounding module wiring.

---

## 9. Full Entity Example: TodoEntity

Here is the complete `TodoEntity` for the enterprise-todo app:

```typescript
// apps/api/src/modules/todo/todo.entity.ts
import {
  Column,
  Entity,
  Index,
  ManyToOne,
  JoinColumn,
  RelationId,
} from "typeorm";
import { AbstractEntity } from "nestjs-dev-utilities";
import { UserEntity } from "../user/user.entity";
import { TodoStatus } from "./todo.constant";

@Entity({ name: "todo" })
export class TodoEntity extends AbstractEntity {
  // The todo text
  @Column()
  text: string;

  // Completion state
  @Column({ default: false })
  isChecked: boolean;

  // Status enum
  @Column({ type: "enum", enum: TodoStatus, default: TodoStatus.ACTIVE })
  status: TodoStatus;

  // FK to the user who owns this todo
  // @Index because we always query "WHERE user_id = ?"
  @Index()
  @Column()
  @RelationId((todo: TodoEntity) => todo.user)
  userId: number;

  @ManyToOne(() => UserEntity, { onDelete: "CASCADE" })
  @JoinColumn()
  user: UserEntity;
}
```

**`todo.constant.ts`:**

```typescript
// apps/api/src/modules/todo/todo.constant.ts
import { registerEnumType } from "@nestjs/graphql";

export enum TodoStatus {
  ACTIVE = "ACTIVE",
  ARCHIVED = "ARCHIVED",
}

// Tell GraphQL about this enum so it appears in the schema
registerEnumType(TodoStatus, { name: "TodoStatus" });
```

> **Why `registerEnumType`?** GraphQL needs to know about TypeScript enums. Without this call, Apollo won't include `TodoStatus` in the generated schema, and resolvers will fail to serialize it. Always call `registerEnumType` for any enum used in a `@Field`.

---

## 10. The Migration System

Migrations are versioned SQL scripts that track every schema change. They are the enterprise equivalent of "my MongoDB collection just grew a new field" — except explicit, reversible, and reviewable.

### Why Migrations?

In Meteor, adding a field to a MongoDB document is invisible: old documents just don't have it. In PostgreSQL, you cannot add a column to a live table without an explicit `ALTER TABLE` statement. Migrations automate and version this.

> **Migrations are git commits for your database schema.** Every migration file adds a reversible change with an `up()` and `down()` method. You can see the full history. You can roll back to any point. You never modify a past migration in production — you write a new one that undoes the problem. Breaking this rule is like rewriting git history on a shared branch: it corrupts everyone else's understanding of the timeline.

```
Without migrations:
  - Dev adds @Column() to entity
  - Runs app locally with synchronize: true → works
  - Deploys to production → crashes (table doesn't have the column)
  - Panic.

With migrations:
  - Dev adds @Column() to entity
  - Runs: yarn api:migration:generate apps/api/src/migrations/AddStatusToTodo
  - Checks the generated SQL
  - Runs: yarn api:migration:run
  - Commits the migration file
  - CI/CD runs migrations in production before routing traffic to new container
  - Zero-downtime deploy.
```

### Step 1 — Install peer dependencies

`@ptc-org/nestjs-query-graphql` (pulled in by `nestjs-dev-utilities`) has peer deps that are not installed by default. The TypeORM CLI loads entity files, which loads the full module tree, which requires these packages:

```bash
yarn add graphql-subscriptions ts-morph
```

### Step 2 — Create `apps/api/ormconfig.ts`

Used by the TypeORM CLI tool only — separate from the NestJS runtime config in `app.module.ts`:

```typescript
// apps/api/ormconfig.ts
import { DataSource } from 'typeorm';
import { config } from 'dotenv';
import { SnakeNamingStrategy } from 'typeorm-naming-strategies';

config({ path: '.env' }); // load .env

export const AppDataSource = new DataSource({
  type: 'postgres',
  host: process.env.PROJECT_DB_HOST,
  port: Number(process.env.PROJECT_DB_PORT),
  username: process.env.PROJECT_DB_USERNAME,
  password: process.env.PROJECT_DB_PASSWORD,
  database: process.env.PROJECT_DB_DATABASE,
  namingStrategy: new SnakeNamingStrategy(),
  entities: ['apps/api/src/**/*.entity.ts'],
  migrations: ['apps/api/src/migrations/*.ts'],
  synchronize: false, // NEVER true — always use migrations
});
```

Also create the migrations directory:

```bash
mkdir -p apps/api/src/migrations
```

### Step 3 — Create `tsconfig.typeorm.json`

The TypeORM CLI runs `ts-node` from the workspace root. Nx uses `tsconfig.base.json` — there is no `tsconfig.json` at the root, so `ts-node` falls back to TypeScript defaults which have `experimentalDecorators: false`. Every decorator fails.

Create `tsconfig.typeorm.json` at the workspace root:

```json
{
  "extends": "./tsconfig.base.json",
  "compilerOptions": {
    "module": "commonjs",
    "moduleResolution": "node",
    "target": "es2021",
    "experimentalDecorators": true,
    "emitDecoratorMetadata": true,
    "strictPropertyInitialization": false
  }
}
```

### Step 4 — Create `scripts/fix-typeorm-deps.cjs`

`nestjs-dev-utilities` imports `@ptc-org/nestjs-query-graphql`, which does a bare deep import of an `@nestjs/graphql` internal path without the `.js` extension. `@nestjs/graphql@13` added a strict `exports` field — Node.js no longer auto-adds the extension through it, so the require fails even though the file exists.

Create `scripts/fix-typeorm-deps.cjs` at the workspace root:

```js
// Patches Module._resolveFilename so the bare deep import gets .js appended
// before Node.js tries to resolve it through @nestjs/graphql's exports field.
const Module = require('module');
const orig = Module._resolveFilename;
Module._resolveFilename = function (request, ...args) {
  if (request === '@nestjs/graphql/dist/schema-builder/storages/lazy-metadata.storage') {
    return orig.call(this, request + '.js', ...args);
  }
  return orig.call(this, request, ...args);
};
```

### Step 5 — Add migration scripts to `package.json`

Use `node -r` to load the patch hook before ts-node starts, and invoke the TypeORM CLI directly via its Node.js entrypoint:

```json
{
  "scripts": {
    "api:migration:generate": "TS_NODE_PROJECT=tsconfig.typeorm.json node -r ./scripts/fix-typeorm-deps.cjs ./node_modules/typeorm/cli-ts-node-commonjs.js migration:generate -d apps/api/ormconfig.ts",
    "api:migration:run": "TS_NODE_PROJECT=tsconfig.typeorm.json node -r ./scripts/fix-typeorm-deps.cjs ./node_modules/typeorm/cli-ts-node-commonjs.js migration:run -d apps/api/ormconfig.ts",
    "api:migration:revert": "TS_NODE_PROJECT=tsconfig.typeorm.json node -r ./scripts/fix-typeorm-deps.cjs ./node_modules/typeorm/cli-ts-node-commonjs.js migration:revert -d apps/api/ormconfig.ts",
    "api:migration:create": "TS_NODE_PROJECT=tsconfig.typeorm.json node -r ./scripts/fix-typeorm-deps.cjs ./node_modules/typeorm/cli-ts-node-commonjs.js migration:create"
  }
}
```

> **TypeORM v1 CLI change:** `migration:generate` no longer accepts `--name`. Pass the **full output path** (directory + PascalCase class name) as a positional argument:
>
> ```bash
> # ✅ correct — PascalCase, full path
> yarn api:migration:generate apps/api/src/migrations/CreateTodoTable
>
> # ❌ wrong — --name flag does not exist in TypeORM v1
> yarn api:migration:generate --name=create-todo-table
> ```
>
> TypeORM prepends the Unix timestamp automatically. Always run the command as a single unbroken line — a shell line break splits the path into two arguments.

---

## 11. The Migration Lifecycle

### Step 1: Create your entity

Write `todo.entity.ts` as shown above.

### Step 2: Generate the migration

```bash
yarn api:migration:generate apps/api/src/migrations/CreateTodoTable
```

TypeORM compares your entity definitions against the live database schema and generates a SQL diff.

A file is created at `apps/api/src/migrations/<timestamp>-CreateTodoTable.ts`. The actual output for `UserEntity` + `TodoEntity` looks like this (constraint names are auto-generated hashes — do not edit them):

```typescript
import { MigrationInterface, QueryRunner } from "typeorm";

export class CreateTodoTable1781506508967 implements MigrationInterface {
  name = 'CreateTodoTable1781506508967'

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`CREATE TYPE "public"."user_status_enum" AS ENUM('ACTIVE', 'INACTIVE', 'SUSPENDED')`);
    await queryRunner.query(`CREATE TABLE "user" ("id" SERIAL NOT NULL, "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(), "updated_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(), "fullname" character varying NOT NULL, "username" character varying NOT NULL, "email" character varying NOT NULL, "password" character varying NOT NULL, "status" "public"."user_status_enum" NOT NULL DEFAULT 'ACTIVE', "two_factor_secret" character varying, CONSTRAINT "UQ_78a916df40e02a9deb1c4b75edb" UNIQUE ("username"), CONSTRAINT "UQ_e12875dfb3b1d92d7d7c5377e22" UNIQUE ("email"), CONSTRAINT "PK_cace4a159ff9f2512dd42373760" PRIMARY KEY ("id"))`);
    await queryRunner.query(`CREATE INDEX "IDX_78a916df40e02a9deb1c4b75ed" ON "user"  ("username") `);
    await queryRunner.query(`CREATE INDEX "IDX_e12875dfb3b1d92d7d7c5377e2" ON "user"  ("email") `);
    await queryRunner.query(`CREATE TYPE "public"."todo_status_enum" AS ENUM('ACTIVE', 'ARCHIVED')`);
    await queryRunner.query(`CREATE TABLE "todo" ("id" SERIAL NOT NULL, "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(), "updated_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(), "text" character varying NOT NULL, "is_checked" boolean NOT NULL DEFAULT false, "status" "public"."todo_status_enum" NOT NULL DEFAULT 'ACTIVE', "user_id" integer NOT NULL, CONSTRAINT "PK_d429b7114371f6a35c5cb4776a7" PRIMARY KEY ("id"))`);
    await queryRunner.query(`CREATE INDEX "IDX_9cb7989853c4cb7fe427db4b26" ON "todo"  ("user_id") `);
    await queryRunner.query(`ALTER TABLE "todo" ADD CONSTRAINT "FK_9cb7989853c4cb7fe427db4b260" FOREIGN KEY ("user_id") REFERENCES "user"("id") ON DELETE CASCADE ON UPDATE NO ACTION`);
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`ALTER TABLE "todo" DROP CONSTRAINT "FK_9cb7989853c4cb7fe427db4b260"`);
    await queryRunner.query(`DROP INDEX "public"."IDX_9cb7989853c4cb7fe427db4b26"`);
    await queryRunner.query(`DROP TABLE "todo"`);
    await queryRunner.query(`DROP TYPE "public"."todo_status_enum"`);
    await queryRunner.query(`DROP INDEX "public"."IDX_e12875dfb3b1d92d7d7c5377e2"`);
    await queryRunner.query(`DROP INDEX "public"."IDX_78a916df40e02a9deb1c4b75ed"`);
    await queryRunner.query(`DROP TABLE "user"`);
    await queryRunner.query(`DROP TYPE "public"."user_status_enum"`);
  }
}
```

**What to notice in this output:**

- `UserEntity` and `TodoEntity` are both created — TypeORM processes ALL entities in the glob, not just the one you named
- `user` table is created first because `todo.user_id` has a FK constraint to it
- `down()` drops in reverse order: FK → todo index → todo → todo enum → user indexes → user → user enum
- Constraint names are SHA-derived hashes — never edit them manually

### Step 3: Review the generated SQL

**Always read the generated migration file before running it.**

Watch for dangerous operations:

- `DROP TABLE` — data loss (fine if intentional)
- `ALTER COLUMN ... NOT NULL` without a default — will fail on non-empty tables
- `DROP COLUMN` — data loss
- Changes to tables you didn't touch — indicates TypeORM found a schema mismatch elsewhere

```bash
# Open the file
code apps/api/src/migrations/<timestamp>-create-todo-table.ts
```

### Step 4: Run the migration

```bash
yarn api:migration:run
```

TypeORM:

1. Checks the `migrations` table in PostgreSQL (creates it on first run)
2. Runs all pending migration files in timestamp order
3. Records each run in the `migrations` table

### Step 5: Verify in Adminer

Open `http://localhost:8080`, log in, and check:

- The `todo` table exists
- Columns match the entity definition
- The `migrations` table has a row for your migration

### Step 6: Test the revert

```bash
yarn api:migration:revert
# → Reverts the last applied migration (runs `down()`)

yarn api:migration:run
# → Re-applies it
```

Always test both `up` and `down` locally before committing.

---

## 12. Migration vs. Synchronize

```typescript
// NEVER use synchronize: true in production or staging
TypeOrmModule.forRootAsync({
  useFactory: () => ({
    synchronize: true, // ← dangerous: auto-alters tables on startup
  }),
});
```

`synchronize: true` tells TypeORM to automatically ALTER the database to match your entities every time the app starts. This sounds convenient and is genuinely fine for the first hour of a new project. It is dangerous in production because:

- It can DROP columns that exist in the DB but not in the current entity code (data loss)
- It runs ALTER TABLE statements at app startup, causing downtime if the table is large
- It cannot be reviewed or tested — it just happens
- It breaks if two app instances start simultaneously (race condition on schema changes)

**Rule: set `synchronize: false` the moment you have real data, and use migrations from that point.**

---

## 13. Migration Naming Convention

TypeORM auto-timestamps migration filenames. The name you pass becomes the class name suffix:

```
apps/api/src/migrations/1781506508967-CreateTodoTable.ts
                         │             └── PascalCase name you passed
                         └── Unix timestamp (ensures chronological order)
```

Inside the file, the class name and the `name` property both embed the timestamp:

```typescript
export class CreateTodoTable1781506508967 implements MigrationInterface {
  name = 'CreateTodoTable1781506508967'
  ...
}
```

**Always use PascalCase** for the name argument — it becomes the TypeScript class name. Use descriptive names that say what changed:

```bash
yarn api:migration:generate apps/api/src/migrations/CreateUserTable
yarn api:migration:generate apps/api/src/migrations/AddStatusToTodo
yarn api:migration:generate apps/api/src/migrations/AddTagTable
```

**Never rename migration files** — the timestamp is embedded in the class name and `name` property inside the file. Renaming the file but not the class causes TypeORM to lose track of migration state.

---

## 14. Seeding

Seeds insert initial data (default roles, permissions, sample records) after migrations.

`@jorgebodega/typeorm-seeding` was already installed in Part 02. No extra `yarn add` needed.

### Step 1 — Add the seed script to `package.json`

The seeding CLI does **not** register ts-node itself, so you must pass `-r ts-node/register` explicitly. You also need the same patch hook used by the migration CLI to resolve the `@nestjs/graphql` deep-import issue:

```json
{
  "scripts": {
    "api:seed:run": "TS_NODE_PROJECT=tsconfig.typeorm.json node -r ts-node/register -r ./scripts/fix-typeorm-deps.cjs ./node_modules/@jorgebodega/typeorm-seeding/dist/cli.js -d apps/api/ormconfig.ts \"apps/api/src/seeders/*.ts\""
  }
}
```

### Step 2 — Create the seeders

**`apps/api/src/seeders/0-reset.seeder.ts`**

Truncates all tables in FK-safe order (child first, then parent) so re-seeding is always idempotent:

```typescript
import { DataSource } from "typeorm";
import { Seeder } from "@jorgebodega/typeorm-seeding";

export default class ResetSeeder extends Seeder {
  async run(dataSource: DataSource): Promise<void> {
    await dataSource.query("TRUNCATE TABLE todo RESTART IDENTITY CASCADE");
    await dataSource.query('TRUNCATE TABLE "user" RESTART IDENTITY CASCADE');
  }
}
```

**`apps/api/src/seeders/1-user.seeder.ts`**

Creates the seed user. This must run **before** `2-todo.seeder.ts` because the `todo` table has a FK on `user_id`:

```typescript
import { DataSource } from "typeorm";
import { Seeder } from "@jorgebodega/typeorm-seeding";
import * as bcrypt from "bcrypt";
import { UserEntity } from "../modules/user/user.entity";
import { UserStatus } from "../modules/user/user.constant";

export default class UserSeeder extends Seeder {
  async run(dataSource: DataSource): Promise<void> {
    const repo = dataSource.getRepository(UserEntity);
    const password = await bcrypt.hash("Password123!", 10);
    await repo.save([
      {
        fullname: "Kai Chew",
        username: "kai",
        email: "kai@example.com",
        password,
        status: UserStatus.ACTIVE,
        twoFactorSecret: null,
      },
    ]);
  }
}
```

**`apps/api/src/seeders/2-todo.seeder.ts`**

```typescript
import { DataSource } from "typeorm";
import { Seeder } from "@jorgebodega/typeorm-seeding";
import { TodoEntity } from "../modules/todo/todo.entity";
import { TodoStatus } from "../modules/todo/todo.constant";

export default class TodoSeeder extends Seeder {
  async run(dataSource: DataSource): Promise<void> {
    const repo = dataSource.getRepository(TodoEntity);
    await repo.save([
      {
        text: "Buy groceries",
        isChecked: false,
        userId: 1,
        status: TodoStatus.ACTIVE,
      },
      {
        text: "Write tests",
        isChecked: false,
        userId: 1,
        status: TodoStatus.ACTIVE,
      },
      {
        text: "Deploy to production",
        isChecked: true,
        userId: 1,
        status: TodoStatus.ARCHIVED,
      },
    ]);
  }
}
```

### Step 3 — Run the seeders

```bash
yarn api:seed:run
```

Expected output:

```
✔ Seeder ResetSeeder executed
✔ Seeder UserSeeder executed
✔ Seeder TodoSeeder executed
✔ Finished seeding
```

> **Seeder order is enforced by filename prefix.** The glob `apps/api/src/seeders/*.ts` is sorted alphabetically, so `0-reset` runs before `1-user`, which runs before `2-todo`. This order is mandatory — `todo` has a FK on `user_id`, so the user row must exist before any todos can be inserted.

---

## 15. Common Migration Errors

| Error                                                         | Cause                                                               | Fix                                                                                     |
| ------------------------------------------------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `relation "todo" already exists`                              | Migration already ran, running again                                | The `migrations` table should prevent this. Check if migration file was deleted from DB |
| `column "status" of relation "todo" already exists`           | DB has the column but migration doesn't know                        | Someone ran manual SQL. Use `ADD COLUMN IF NOT EXISTS` in the migration                 |
| `null value in column "user_id" violates not-null constraint` | Running `NOT NULL` migration on a non-empty table                   | Add a default or backfill existing rows in the migration `up()`                         |
| `FK_todo_user` constraint failed                              | Inserting a todo with a `userId` that doesn't exist in `user` table | Ensure the user exists first (seeder order)                                             |
| `TypeORM metadata not found for TodoEntity`                   | Entity not in `entities` array                                      | Add to both `forRoot` entities AND `forFeature` in the module                           |

---

## Summary

| Meteor                          | Enterprise NestJS                                                   |
| ------------------------------- | ------------------------------------------------------------------- |
| `new Mongo.Collection('tasks')` | `@Entity({ name: 'todo' }) class TodoEntity extends AbstractEntity` |
| No schema enforcement           | TypeScript types + PostgreSQL column types enforce shape            |
| No migrations                   | TypeORM migrations: generate → review → run → revert                |
| Optional `SimpleSchema`         | `class-validator` on DTOs, enforced globally                        |
| `$set` for updates              | `repo.save({ ...entity, ...updates })`                              |
| `find()` cursor                 | `repo.findMany({ where: { userId } })`                              |
| MongoID (string)                | Auto-increment integer PK from `AbstractEntity`                     |
| No FK constraints               | `@ManyToOne` + FK enforced by PostgreSQL                            |
