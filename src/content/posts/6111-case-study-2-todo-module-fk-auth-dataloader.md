---
author: Kai
pubDatetime: 2026-05-11T09:00:00+08:00
title: Case Study 2 - Todo Module (FK + Auth + DataLoader)
featured: false
draft: false
slug: 6111-case-study-2-todo-module-fk-auth-dataloader
tags:
  - deeptech
  - meteorjs
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/11-case-study-2-todo-module-fk-auth-dataloader.png"
description: By the end of this part, you will be building a module with a foreign key to another entity (Todo → User) and learn about solving N+1 problem with DataLoader.

---

## What This Part Covers

- Building a module with a **foreign key** to another entity (Todo → User)
- The **ownership scoping pattern**: filtering all operations by the authenticated user's ID
- `@RelationId` — reading FK values without loading related entities
- The **N+1 problem** explained with a real example
- **DataLoader** — the solution, with `Scope.REQUEST` explained
- `@ResolveField` — resolving nested GraphQL types
- The complete Todo module following the 9-step pattern

---

## Meteor Equivalents

| Meteor | NestJS | What changed |
|--------|--------|--------------|
| `userId: String` on a collection document | `@ManyToOne(() => UserEntity)` + `@RelationId` | FK enforced at DB level with a real constraint |
| `find({ userId: this.userId })` in a publication | `userId: { eq: currentUser.user.id }` filter in resolver | Ownership enforced at API layer, not publication layer |
| Any client could pass `userId` in a method call | No `@Field()` on `userId` in `CreateTodoInput` | Server assigns `userId` from JWT — clients cannot supply it |
| N+1 invisible (client-side Minimongo joins) | N+1 is a real DB problem — solved with DataLoader | Server-side GraphQL resolves each field separately |
| No equivalent — Minimongo holds all data | DataLoader batches N user lookups into 1 SQL query | Critical for performance at scale |
| No concept | `Scope.REQUEST` — fresh DataLoader instance per request | Prevents cross-user data leaks from cached results |
| Automatic DDP reactive joins | `@ResolveField` + DataLoader | Explicit, typed, and batch-optimised |
| `.allow()` / `.deny()` at the collection level | `@UseGuards(AuthJwtGuard)` at the resolver level | Guards run before your handler, not after |
| DDP session token | RS256 JWT in `Authorization` header | Cryptographically verifiable, stateless |

In Meteor with `autopublish` removed:

```javascript
// Publication: only publish tasks owned by the current user
Meteor.publish('tasks', function () {
  if (!this.userId) return this.ready();
  return TasksCollection.find({ userId: this.userId });  // ownership filter
});

// Client subscription
const { tasks } = useTracker(() => {
  Meteor.subscribe('tasks');
  return { tasks: TasksCollection.find().fetch() };
});
```

In the enterprise stack, ownership is enforced at three levels:
1. The JWT guard verifies the user exists
2. `@CurrentUser()` extracts the verified user ID
3. Every query and command filters by `userId: { eq: currentUser.user.id }`

---

## 1. The N+1 Problem

Before building the Todo module, you need to understand the problem that DataLoader solves.

Suppose you have a GraphQL query:

```graphql
query {
  getTodos {
    nodes {
      id
      text
      user {
        fullname   # ← each todo needs to load its owner
      }
    }
  }
}
```

Without DataLoader, the server executes:

```sql
-- Query 1: fetch 10 todos
SELECT * FROM todo WHERE user_id = 5 LIMIT 10;

-- Then for EACH todo, a separate query:
SELECT * FROM user WHERE id = 5;  -- todo 1's owner
SELECT * FROM user WHERE id = 5;  -- todo 2's owner (same user! queried again)
SELECT * FROM user WHERE id = 5;  -- todo 3's owner
SELECT * FROM user WHERE id = 7;  -- todo 4's owner (different user)
SELECT * FROM user WHERE id = 5;  -- todo 5's owner (first user, again)
-- ... 10 separate user queries for 10 todos
-- Total: 11 queries. 100 todos = 101 queries.
```

This is the **N+1 problem**: 1 query to fetch N records, then N additional queries to fetch related data. With 100 todos = 101 DB queries. With 1000 todos = 1001 queries. The system gets slower as it grows.

> **The warehouse trip problem:** Imagine a café where every customer causes the barista to run to the warehouse for coffee beans — one trip per cup. 100 customers = 100 warehouse trips. **DataLoader** is the barista who waits until the morning rush settles, writes down all 100 orders, makes **one warehouse trip** with the complete list, and fills all cups. 100 customers, 1 trip. This is the batch-and-deduplicate pattern that eliminates N+1.

> **Meteor analogy:** Meteor's `autopublish` sends everything to the client, where Minimongo handles joins in memory. You never noticed the N+1 problem because all the data was already on the client. In a server-side GraphQL API, each field resolution is a potential DB query.

### DataLoader: The Solution

DataLoader **batches** all `.load(userId)` calls that happen within one event loop tick, then fires one SQL query:

```sql
-- Query 1: fetch 10 todos
SELECT * FROM todo WHERE user_id = 5 LIMIT 10;

-- Query 2: ONE batched query for ALL unique user IDs
SELECT * FROM user WHERE id IN (5, 7);
-- Total: 2 queries, regardless of N.
```

DataLoader also **deduplicates**: if 8 out of 10 todos belong to user 5, DataLoader only queries for user 5 once — it caches the result within the request.

### Why `Scope.REQUEST` Is Non-Negotiable

NestJS providers are singletons by default — created once at app startup, shared across all requests. A singleton DataLoader would:

1. Accumulate cached user data across all requests
2. Serve User A's data to User B (if their requests overlap and share cached IDs)
3. Never invalidate stale data

> **Fresh coffee per visitor:** Think of provider scopes as coffee service styles. `DEFAULT` (singleton) = one communal coffee maker in the office kitchen, shared by the whole company — fine for stateless services. `REQUEST` scope = a fresh cup brewed for each visitor as they arrive, then discarded when they leave. A DataLoader **must** be `REQUEST`-scoped because its per-request cache must never leak between different users' requests. If user A's data ends up in user B's cache, that's a data breach.

`Scope.REQUEST` creates a fresh DataLoader instance for each incoming HTTP request. The cache lives only for the duration of that one request (collecting batches within the resolver tree), then is garbage-collected.

```typescript
@Injectable({ scope: Scope.REQUEST })  // ← CRITICAL — never omit this
export class UserLoader { ... }
```

---

## 2. Design Phase

### DB Schema

```
todo
├── id          SERIAL PRIMARY KEY
├── text        VARCHAR NOT NULL
├── is_checked  BOOLEAN DEFAULT false
├── status      ENUM('ACTIVE', 'ARCHIVED') DEFAULT 'ACTIVE'
├── user_id     INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE
├── created_at  TIMESTAMPTZ
└── updated_at  TIMESTAMPTZ
```

### GraphQL Operations

```graphql
# Auth required — all operations scoped to current user
query todo(id: Int!): Todo
query getTodos(filter: TodoFilter, paging: CursorPaging, sorting: [TodoSort!]): TodoConnection!

mutation createTodo(input: CreateTodoInput!): Todo!
mutation updateTodo(id: Int!, input: UpdateTodoInput!): Todo!
mutation deleteTodo(id: Int!): Boolean!

# Nested field — resolves via DataLoader
type Todo {
  user: User   # ← resolved with DataLoader, NOT N+1
}
```

---

## 3. Entity (`todo.entity.ts`)

> **Entity = government form template:** A TypeORM Entity is a TypeScript class where each property maps to a database column. Every filled-in form (database row) must match the template. When the government revises the form (migration), all future submissions follow the new version. `AbstractEntity` is the **company letterhead** — every entity is printed on paper that already has the logo (`id`), address (`createdAt`, `updatedAt`), and date field (`deletedAt`) pre-printed. Each entity just adds its unique content.

> **From Meteor?** `new Mongo.Collection('todo')` is schema-less — any shape goes in. `@Entity()` enforces a schema at the database level AND at the TypeScript level. A field that doesn't match the entity declaration won't compile.

```typescript
// apps/api/src/modules/todo/todo.entity.ts
import { Column, Entity, Index, JoinColumn, ManyToOne, RelationId } from 'typeorm';
import { AbstractEntity } from 'nestjs-dev-utilities';
import { UserEntity } from '../user/user.entity';
import { TodoStatus } from './todo.constant';

@Entity({ name: 'todo' })
export class TodoEntity extends AbstractEntity {
  @Column()
  text: string;

  @Column({ default: false })
  isChecked: boolean;

  @Column({ type: 'enum', enum: TodoStatus, default: TodoStatus.ACTIVE })
  status: TodoStatus;

  // FK value as a plain integer — always populated, no JOIN needed
  @Index()     // ← ALWAYS index columns used in WHERE clauses
  @Column()
  @RelationId((todo: TodoEntity) => todo.user)
  userId: number;

  // Full relation — requires JOIN or eager load to access
  @ManyToOne(() => UserEntity, { onDelete: 'CASCADE' })
  @JoinColumn()
  user: UserEntity;
}
```

**`@RelationId` explained:**

```typescript
// After fetching a todo:
const todo = await repo.findOne({ where: { id: 1 } });
todo.userId;  // → 5 (always available — just reading the FK column)
todo.user;    // → undefined (NOT loaded — would require JOIN)

// To load the full user:
const todo = await repo.findOne({ where: { id: 1 }, relations: ['user'] });
todo.user.fullname;  // → "Alice" (loaded via JOIN)
```

You use `userId` for filtering and ownership checks (cheap). You use DataLoader to load `user` only when the client requests nested user fields.

**Memory hook:** Entity = government form template. `@RelationId` gives you the FK integer cheaply (no JOIN). `@Index()` on every column used in `WHERE`. Never `synchronize: true` in production.

---

## 4. Constants (`todo.constant.ts`)

```typescript
// apps/api/src/modules/todo/todo.constant.ts
import { registerEnumType } from '@nestjs/graphql';

export enum TodoStatus {
  ACTIVE = 'ACTIVE',
  ARCHIVED = 'ARCHIVED',
}
registerEnumType(TodoStatus, { name: 'TodoStatus' });
```

---

## 5. DTOs

> **AbstractDto = standard response envelope:** If `AbstractEntity` is the company letterhead for DB rows, `AbstractDto` is the standard response envelope for API responses. The client always knows where to find `id`, `createdAt`, and `updatedAt` — they're on every envelope. `TodoDto extends AbstractDto` gets those fields as `@Field()` for free.

> **From Meteor?** Meteor had no formal DTO layer — data returned from `Meteor.methods` or publications could be any shape. `@ObjectType` DTOs with `@Field()` define the exact API contract: only decorated fields are visible to GraphQL clients. Undeclared fields are invisible.

### Read DTO (`dto/todo.dto.ts`)

```typescript
// apps/api/src/modules/todo/dto/todo.dto.ts
import { Field, ObjectType } from '@nestjs/graphql';
import { FilterableField } from '@ptc-org/nestjs-query-graphql';
import { AbstractDto } from 'nestjs-dev-utilities';
import { UserDto } from '../user/dto/user.dto';
import { TodoStatus } from './todo.constant';

@ObjectType('Todo')
export class TodoDto extends AbstractDto {
  @FilterableField()
  text: string;

  @FilterableField()
  isChecked: boolean;

  @FilterableField(() => TodoStatus)
  status: TodoStatus;

  // userId is NOT exposed — internal FK, not for clients to filter on
  // (would enable enumeration: "give me all todos for user 999")

  // The nested user object — resolved via @ResolveField + DataLoader
  // nullable: true because user could theoretically be deleted
  @Field(() => UserDto, { nullable: true })
  user?: UserDto;
}
```

### Input DTOs (`dto/todo.input.ts`)

```typescript
// apps/api/src/modules/todo/dto/todo.input.ts
import { Field, InputType } from '@nestjs/graphql';
import { IsBoolean, IsEnum, IsNotEmpty, IsOptional, IsString, MaxLength } from 'class-validator';
import { TodoStatus } from '../todo.constant';

@InputType()
export class CreateTodoInput {
  @Field()
  @IsString()
  @IsNotEmpty({ message: 'Todo text cannot be empty' })
  @MaxLength(500)
  text: string;

  @Field({ nullable: true, defaultValue: false })
  @IsBoolean()
  @IsOptional()
  isChecked?: boolean;

  // NO @Field() — userId is injected server-side from the JWT
  // Clients cannot send userId — Apollo rejects unknown fields
  userId?: number;
}

@InputType()
export class UpdateTodoInput {
  @Field({ nullable: true })
  @IsString()
  @IsNotEmpty()
  @MaxLength(500)
  text?: string;

  @Field({ nullable: true })
  @IsBoolean()
  isChecked?: boolean;

  @Field({ nullable: true })
  @IsEnum(TodoStatus)
  status?: TodoStatus;
}
```

### Query Args DTO (`dto/todo.query.ts`)

```typescript
// apps/api/src/modules/todo/dto/todo.query.ts
import { ArgsType } from '@nestjs/graphql';
import { SortDirection } from '@ptc-org/nestjs-query-core';
import { PagingStrategies, QueryArgsType } from '@ptc-org/nestjs-query-graphql';
import { TodoDto } from './todo.dto';

@ArgsType()
export class TodosQuery extends QueryArgsType(TodoDto, {
  defaultSort: [{ field: 'createdAt', direction: SortDirection.DESC }],
  pagingStrategy: PagingStrategies.CURSOR,
  enableTotalCount: true,
}) {}

export const TodoQueryConnection = TodosQuery.ConnectionType;
```

**Memory hook:** AbstractDto = response envelope. `userId` never gets a `@Field()` on a create input — server-assigned only. Only `@FilterableField()` fields can be filtered by clients.

---

## 6. CQRS Inputs, Index, and Handlers

Follow the exact same pattern as the Tag module. Create:

**`cqrs/todo.cqrs.input.ts`** — identical structure to Tag's inputs, substituting `TodoEntity` and `CreateTodoInput`:

```typescript
// apps/api/src/modules/todo/cqrs/todo.cqrs.input.ts
import { Query } from '@ptc-org/nestjs-query-core';
import {
  AbstractCqrsCommandInput,
  AbstractCqrsQueryInput,
  RecordMutateOptions,
  RecordQueryWithJoinOptions,
} from 'nestjs-typed-cqrs';
import { CreateTodoInput, UpdateTodoInput } from '../dto/todo.input';
import { TodoEntity } from '../todo.entity';

export class FindOneTodoQuery extends AbstractCqrsQueryInput<TodoEntity, undefined, RecordQueryWithJoinOptions, TodoEntity> {}
export class FindManyTodoQuery extends AbstractCqrsQueryInput<TodoEntity, undefined, RecordQueryWithJoinOptions, TodoEntity[]> {}
export class CountTodoQuery extends AbstractCqrsQueryInput<TodoEntity, Query<TodoEntity>['filter'], undefined, number> {}

export class CreateOneTodoCommand extends AbstractCqrsCommandInput<TodoEntity, CreateTodoInput & { userId: number }> {}
export class UpdateOneTodoCommand extends AbstractCqrsCommandInput<TodoEntity, UpdateTodoInput, true, RecordMutateOptions, { before: TodoEntity; updated: TodoEntity }> {}
export class DeleteOneTodoCommand extends AbstractCqrsCommandInput<TodoEntity, { id: number; userId: number }> {}
```

**`cqrs/index.ts`** and **`cqrs/todo.cqrs.handler.ts`** — same one-liner pattern as Tag. (See Part 10 for the template — substitute `Tag` → `Todo`.)

> **CommandBus/QueryBus = postal sorting facility:** Drop a command or query object into the bus. The facility reads the class name, routes it to the registered handler. The resolver never imports the handler directly — it never knows which driver was used. The letter always arrives.

> **From Meteor?** `Meteor.methods({ createTodo: function() { ... } })` is the method body — handler AND service AND repo call in one block. CQRS separates these into three distinct files: handler (route), service (logic), repository (data). Each independently testable.

**Memory hook:** CommandBus/QueryBus = postal facility. Drop the object, bus routes it. Handlers are thin one-liners — all logic goes in the service.

---

## 7. Service (`todo.service.ts`)

> **Service = doctor:** The service is where the actual work happens. Business rules, ownership validation, repository calls — all in `*.service.ts`. The doctor examines, diagnoses, and prescribes. She does not answer phones (resolver's job) or file paperwork. She never touches HTTP concepts like `@Req()` or `@Res()`.

> **From Meteor?** Meteor methods mixed routing, validation, and DB calls in one block. "Where is the business logic?" in NestJS → `*.service.ts`. Always. Every time.

The Todo service adds one important concern: **ownership validation** on update and delete.

```typescript
// apps/api/src/modules/todo/todo.service.ts
import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { TypeOrmQueryService } from '@ptc-org/nestjs-query-typeorm';
import { CqrsCommandFunc, CqrsQueryFunc } from 'nestjs-typed-cqrs';
import { Repository } from 'typeorm';

import {
  CountTodoQuery, CreateOneTodoCommand, DeleteOneTodoCommand,
  FindManyTodoQuery, FindOneTodoQuery, UpdateOneTodoCommand,
} from './cqrs/todo.cqrs.input';
import { TodoEntity } from './todo.entity';

@Injectable()
export class TodoService extends TypeOrmQueryService<TodoEntity> {
  constructor(
    @InjectRepository(TodoEntity)
    repo: Repository<TodoEntity>, // no `private readonly` — parent sets this.repo
  ) {
    super(repo); // sets this.repo and this.filterQueryBuilder via TypeOrmQueryService
  }

  findOneTodo: CqrsQueryFunc<FindOneTodoQuery, FindOneTodoQuery['args']> = async ({ query, options }) => {
    const nullable = options?.nullable ?? true;
    try {
      const result = await this.filterQueryBuilder.select(query).getOne();
      if (!nullable && !result) throw new Error('Todo not found');
      return { success: true, data: result };
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };

  findManyTodo: CqrsQueryFunc<FindManyTodoQuery, FindManyTodoQuery['args']> = async ({ query }) => {
    try {
      const results = await this.filterQueryBuilder.select(query).getMany();
      return { success: true, data: results };
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };

  countTodo: CqrsQueryFunc<CountTodoQuery, CountTodoQuery['args']> = async ({ query }) => {
    try {
      return this.repo.count({ where: query as any });
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };

  createOneTodo: CqrsCommandFunc<CreateOneTodoCommand, CreateOneTodoCommand['args']> = async ({ input }) => {
    try {
      // Business rule: no duplicate text for same user
      const duplicate = await this.repo.findOne({
        where: { text: input.text, userId: input.userId },
      });
      if (duplicate) throw new Error('You already have a todo with that text');

      const todo = this.repo.create(input);
      const data = await this.repo.save(todo);
      return { success: true, data };
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };

  updateOneTodo: CqrsCommandFunc<UpdateOneTodoCommand, UpdateOneTodoCommand['args']> = async ({ query, input }) => {
    try {
      const before = await this.filterQueryBuilder.select(query).getOne();
      if (!before) throw new NotFoundException('Todo not found or access denied');
      // Note: ownership is enforced by the query filter (userId: { eq: currentUser.id })
      // If the todo belongs to another user, the filter finds nothing → NotFoundException

      const updated = await this.repo.save({ ...before, ...input });
      return { success: true, data: { before, updated } };
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };

  deleteOneTodo: CqrsCommandFunc<DeleteOneTodoCommand, DeleteOneTodoCommand['args']> = async ({ input: { id, userId } }) => {
    try {
      const todo = await this.repo.findOne({ where: { id, userId } });
      if (!todo) throw new NotFoundException('Todo not found');
      await this.repo.remove(todo);
      return { success: true, data: todo };
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };
}
```

**Memory hook:** Service = doctor. All `if` statements with business meaning live here. Ownership check (query filter with `userId: { eq: currentUser.user.id }`) is a service-level concern, not a resolver concern.

---

## 8. DataLoader (`todo-user.loader.ts`)

Create the DataLoader for loading todo owners.

```typescript
// apps/api/src/modules/todo/todo-user.loader.ts
import { Injectable, Scope } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import DataLoader from 'dataloader';
import { UserEntity } from '../user/user.entity';

@Injectable({ scope: Scope.REQUEST })  // ← CRITICAL: fresh instance per request
export class TodoUserLoader {
  constructor(
    @InjectRepository(UserEntity)
    private readonly userRepo: Repository<UserEntity>,
  ) {}

  // The DataLoader instance — batches all .load(userId) calls in one event loop tick
  private readonly loader = new DataLoader<number, UserEntity | null>(
    async (userIds: readonly number[]) => {
      // ONE query for ALL requested user IDs
      const users = await this.userRepo.findByIds([...userIds]);

      // DataLoader requires the result array to be in the SAME ORDER as the input keys
      // If a userId has no matching user, return null for that position
      return userIds.map((id) => users.find((u) => u.id === id) ?? null);
    },
  );

  // Called by the resolver's @ResolveField
  load(userId: number): Promise<UserEntity | null> {
    return this.loader.load(userId);
  }
}
```

**Why the result must be in the same order as the input keys:**

DataLoader maps input `[1, 2, 3]` to output `[user1, user2, user3]` by index position. If you return `[user3, user1]` (sorted differently), DataLoader maps the wrong user to the wrong ID. Always use `.map((id) => users.find((u) => u.id === id))`.

**Memory hook:** DataLoader = one warehouse trip for 100 orders. `Scope.REQUEST` is non-negotiable — singleton DataLoader = cross-user data leak. Result array must be in exact same order as input keys.

Install dataloader:

```bash
yarn add dataloader
```

---

## 9. Resolver with `@ResolveField` (`todo.resolver.ts`)

> **Resolver = receptionist + personal shopper:** The resolver is the entry point for every GraphQL operation. Like the receptionist at a clinic, it takes the request, routes it to the right handler, and returns the answer. It does not examine or prescribe. As a personal shopper, it lets the client ask for exactly the fields it needs — `user { fullname }` is only fetched when the client asks for it. If a resolver method has business logic, move it to the service.

> **From Meteor?** `Meteor.methods({ createTodo })` handled both routing and logic in one body. `@Mutation() createTodo()` is routing only — `@UseGuards` for auth, `@CurrentUser()` to extract the user, then dispatch to `commandBus`. The separation is strict and visible.

```typescript
// apps/api/src/modules/todo/todo.resolver.ts
import { Args, Int, Mutation, Parent, Query, ResolveField, Resolver } from '@nestjs/graphql';
import { UseGuards } from '@nestjs/common';
import { CommandBus, QueryBus } from '@nestjs/cqrs';

import { TodoDto } from './dto/todo.dto';
import { CreateTodoInput, UpdateTodoInput } from './dto/todo.input';
import { TodoQueryConnection, TodosQuery } from './dto/todo.query';
import { TodoUserLoader } from './todo-user.loader';
import { AuthJwtGuard } from '../auth/guards/auth-jwt.guard';
import { CurrentUser } from '../auth/decorators/current-user.decorator';
import { AccessTokenUser } from '../auth/auth.interface';
import { UserDto } from '../user/dto/user.dto';
import {
  CountTodoQuery, CreateOneTodoCommand, DeleteOneTodoCommand,
  FindManyTodoQuery, FindOneTodoQuery, UpdateOneTodoCommand,
} from './cqrs';

@Resolver(() => TodoDto)
export class TodoResolver {
  constructor(
    private readonly queryBus: QueryBus,
    private readonly commandBus: CommandBus,
    private readonly userLoader: TodoUserLoader,  // injected DataLoader
  ) {}

  // ── Queries ────────────────────────────────────────────────────

  // Auth required — users can only see their own todos
  @UseGuards(AuthJwtGuard)
  @Query(() => TodoDto, { nullable: true })
  async todo(
    @CurrentUser() currentUser: AccessTokenUser,
    @Args('id', { type: () => Int }) id: number,
  ): Promise<TodoDto | null> {
    const { data } = await this.queryBus.execute(
      new FindOneTodoQuery({
        query: {
          // Ownership filter: id AND userId must both match
          filter: { id: { eq: id }, userId: { eq: currentUser.user.id } },
        },
      }),
    );
    return data as TodoDto;
  }

  @UseGuards(AuthJwtGuard)
  @Query(() => TodoQueryConnection)
  async getTodos(
    @CurrentUser() currentUser: AccessTokenUser,
    @Args() query: TodosQuery,
  ) {
    // Always AND the userId filter — clients cannot override this
    const ownershipFilter = { userId: { eq: currentUser.user.id } };

    return TodoQueryConnection.createFromPromise(
      async (q) => {
        const { data } = await this.queryBus.execute(new FindManyTodoQuery({ query: q }));
        return data as TodoDto[];
      },
      {
        ...query,
        filter: query.filter
          ? { and: [query.filter, ownershipFilter] }
          : ownershipFilter,
      },
      async (filter) => {
        const count = await this.queryBus.execute(new CountTodoQuery({ query: filter }));
        return count as number;
      },
    );
  }

  // ── Mutations ───────────────────────────────────────────────────

  @UseGuards(AuthJwtGuard)
  @Mutation(() => TodoDto)
  async createTodo(
    @CurrentUser() currentUser: AccessTokenUser,
    @Args('input') input: CreateTodoInput,
  ): Promise<TodoDto> {
    const { data } = await this.commandBus.execute(
      new CreateOneTodoCommand({
        // userId injected from JWT — client cannot supply this
        input: { ...input, userId: currentUser.user.id },
      }),
    );
    return data as TodoDto;
  }

  @UseGuards(AuthJwtGuard)
  @Mutation(() => TodoDto)
  async updateTodo(
    @CurrentUser() currentUser: AccessTokenUser,
    @Args('id', { type: () => Int }) id: number,
    @Args('input') input: UpdateTodoInput,
  ): Promise<TodoDto> {
    const { data } = await this.commandBus.execute(
      new UpdateOneTodoCommand({
        // Ownership filter in the query — can only update OWN todos
        query: { filter: { id: { eq: id }, userId: { eq: currentUser.user.id } } },
        input,
      }),
    );
    return data.updated as TodoDto;
  }

  @UseGuards(AuthJwtGuard)
  @Mutation(() => Boolean)
  async deleteTodo(
    @CurrentUser() currentUser: AccessTokenUser,
    @Args('id', { type: () => Int }) id: number,
  ): Promise<boolean> {
    return this.commandBus.execute(
      new DeleteOneTodoCommand({ input: { id, userId: currentUser.user.id } }),
    );
  }

  // ── Relation Field Resolver ────────────────────────────────────

  // This method is called once per todo in the response — DataLoader batches them
  @ResolveField(() => UserDto, { nullable: true })
  async user(@Parent() todo: TodoDto): Promise<UserDto | null> {
    // todos[0].userId → loader.load(5)
    // todos[1].userId → loader.load(5)  ← same user, batched together
    // todos[2].userId → loader.load(7)
    // Result: ONE query: SELECT * FROM user WHERE id IN (5, 7)
    return this.userLoader.load(todo.userId) as Promise<UserDto | null>;
  }
}
```

**How `@ResolveField` works:**

When a client requests:

```graphql
{ getTodos { nodes { id text user { fullname } } } }
```

Apollo calls `TodoResolver.getTodos()` to get the todo list, then for each todo that has `user { ... }` requested, calls `TodoResolver.user(todo)`. Without DataLoader, this is N separate DB queries. With DataLoader, all `userLoader.load(userId)` calls in the same event loop tick are batched into one query.

**Memory hook:** Resolver = receptionist. `@ResolveField` is called once per parent object — DataLoader batches all those calls into one query. `@UseGuards` is explicit and mandatory on every mutation.

---

## 10. Module (`todo.module.ts`)

> **Module = department in a company:** `TodoModule` owns its own workers (`providers`) — the resolver, service, DataLoader, and CQRS handlers. It borrows from other departments (`imports`) — `TypeOrmModule.forFeature` for the repositories. It lends `TodoService` to any module that needs it (`exports`). `UserEntity` must be in `imports` because `TodoUserLoader` needs the `UserEntity` repository — you cannot access another department's tools without formally requesting them.

```typescript
// apps/api/src/modules/todo/todo.module.ts
import { Module } from '@nestjs/common';
import { CqrsModule } from '@nestjs/cqrs';
import { TypeOrmModule } from '@nestjs/typeorm';
import { NestjsQueryTypeOrmModule } from '@ptc-org/nestjs-query-typeorm';

import { TodoEntity } from './todo.entity';
import { TodoResolver } from './todo.resolver';
import { TodoService } from './todo.service';
import { TodoUserLoader } from './todo-user.loader';
import { TodoCommandHandlers, TodoEventHandlers, TodoQueryHandlers } from './cqrs';
import { UserEntity } from '../user/user.entity';

@Module({
  imports: [
    // CqrsModule is NOT imported here — it is registered globally via CqrsModule.forRoot() in AppModule
    TypeOrmModule.forFeature([TodoEntity, UserEntity]),   // UserEntity needed by TodoUserLoader
    NestjsQueryTypeOrmModule.forFeature([TodoEntity]),
  ],
  providers: [
    TodoResolver,
    TodoService,
    TodoUserLoader,    // DataLoader — Scope.REQUEST is set on the class itself
    ...TodoQueryHandlers,
    ...TodoCommandHandlers,
    ...TodoEventHandlers,
  ],
  exports: [TodoService],
})
export class TodoModule {}
```

**Memory hook:** Module = department. `imports` borrows · `providers` owns · `exports` lends. `TodoUserLoader` needs `UserEntity` in `imports` — always declare what your providers need.

---

## 11. Migration, Registration, and Smoke Tests

Register in `AppModule` (add `TodoEntity` to entities, `TodoModule` to imports), generate and run the migration:

```bash
yarn api:migration:generate apps/api/src/migrations/CreateTodoTable
# Review the generated SQL — check FK constraint and index on user_id
yarn api:migration:run
```

Verify in Adminer:
- `todo` table exists
- `user_id` column has an index (`IDX_todo_user_id`)
- FK constraint to `user.id` exists

**Playground smoke tests:**

```graphql
# Create a todo (auth required)
mutation {
  createTodo(input: { text: "Buy groceries" }) {
    id text isChecked status createdAt
    user { id fullname }  # ← resolved via DataLoader
  }
}
```

```graphql
# Get my todos with ownership filter automatically applied
query {
  getTodos(
    filter: { isChecked: { is: false } }
    sorting: [{ field: createdAt, direction: DESC }]
    paging: { first: 10 }
  ) {
    totalCount
    edges {
      node {
        id text isChecked status
        user { fullname }
      }
      cursor
    }
    pageInfo { hasNextPage endCursor }
  }
}
```

```graphql
# Toggle completion
mutation {
  updateTodo(id: 1, input: { isChecked: true }) {
    id text isChecked updatedAt
  }
}
```

```graphql
# Try to access another user's todo (should return null, not an error)
query {
  todo(id: 999) {
    id text
  }
}
# → { "data": { "todo": null } }  ← not found because userId filter didn't match
```

---

## 12. Ownership Enforcement: The Three Layers

> **Guard = bouncer at the club door:** `AuthJwtGuard` is the first bouncer — it checks your wristband (JWT). No valid JWT = 401, execution stops here. It runs before your resolver method ever starts.

> **RS256 JWT = king's wax seal:** The auth service signs tokens with a private key. Any service can verify the signature using the public key. Even if an attacker steals a downstream service's code, they cannot forge a token — the private key never leaves the auth service. HS256 would be a master key: anyone who has it can both lock and unlock.

> **From Meteor?** `.allow({ remove: fn })` ran at the database layer — after your method body had already executed. Guards run at the API entry point, before any handler starts. `this.userId` inside a Meteor method is the rough equivalent of `@CurrentUser()` — but NestJS's version is JWT-verified and typed.

Review the complete ownership chain for a `deleteTodo` call:

```
Layer 1: JWT Guard
  @UseGuards(AuthJwtGuard)
  → verifies the Bearer token is valid RS256 JWT
  → if invalid: 401 Unauthorized — execution stops here

Layer 2: @CurrentUser()
  → extracts verified { user: UserEntity } from req.user
  → userId is NEVER taken from client input

Layer 3: Query filter in resolver/service
  new FindOneTodoQuery({
    query: { filter: { id: { eq: id }, userId: { eq: currentUser.user.id } } }
  })
  → the SQL: WHERE id = ? AND user_id = ?
  → if todo belongs to another user: WHERE id = 999 AND user_id = 5
  → → no row matches → returns null → throws "Todo not found or access denied"
```

A malicious user who authenticates as user 5 and sends `id: 999` (another user's todo) will always get null — they cannot delete, update, or even read another user's records.

**Memory hook:** Guard = bouncer (Layer 1 — JWT). `@CurrentUser()` = extract verified identity (Layer 2). Query filter with `userId` = row-level ownership (Layer 3). All three layers must be present.

---

## 13. Unit Tests for the Todo Module

```typescript
// apps/api/src/modules/todo/test/todo.service.spec.ts
import { BadRequestException } from '@nestjs/common';
import { Test, TestingModule } from '@nestjs/testing';
import { getRepositoryToken } from '@nestjs/typeorm';
import { getQueryServiceToken } from '@ptc-org/nestjs-query-core';
import { TodoEntity } from '../todo.entity';
import { TodoService } from '../todo.service';
import { TodoStatus } from '../todo.constant';

const mockRepo = {
  findOne: jest.fn(),
  create: jest.fn(),
  save: jest.fn(),
  remove: jest.fn(),
  count: jest.fn(),
};

describe('TodoService', () => {
  let service: TodoService;

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      providers: [
        TodoService,
        { provide: getRepositoryToken(TodoEntity), useValue: mockRepo },
        { provide: getQueryServiceToken(TodoEntity), useValue: {} },
      ],
    }).compile();

    service = module.get<TodoService>(TodoService);
    jest.clearAllMocks();
  });

  describe('createOne', () => {
    const userId = 1;
    const input = { text: 'Buy groceries', userId, isChecked: false };

    it('should create a todo for the authenticated user', async () => {
      const savedTodo: Partial<TodoEntity> = {
        id: 1,
        text: 'Buy groceries',
        userId,
        isChecked: false,
        status: TodoStatus.ACTIVE,
        createdAt: new Date(),
      };
      mockRepo.findOne.mockResolvedValue(null);   // no duplicate
      mockRepo.create.mockReturnValue(input);
      mockRepo.save.mockResolvedValue(savedTodo);

      const result = await service.createOne({ input });

      expect(result.success).toBe(true);
      expect(result.data).toEqual(savedTodo);
      // Verify userId is part of the record
      expect(mockRepo.save).toHaveBeenCalledWith(expect.objectContaining({ userId }));
    });

    it('should throw BadRequestException for duplicate text per user', async () => {
      mockRepo.findOne.mockResolvedValue({ id: 1, text: 'Buy groceries', userId });

      await expect(service.createOne({ input })).rejects.toThrow(BadRequestException);
      expect(mockRepo.save).not.toHaveBeenCalled();
    });
  });

  describe('deleteOne', () => {
    it('should delete the todo', async () => {
      const todo: Partial<TodoEntity> = { id: 1, userId: 1 };
      mockRepo.findOne.mockResolvedValue(todo);
      mockRepo.remove.mockResolvedValue(todo);

      const result = await service.deleteOne({ input: 1 });

      expect(result.success).toBe(true);
      expect(mockRepo.remove).toHaveBeenCalledWith(todo);
    });

    it('should throw when todo not found', async () => {
      mockRepo.findOne.mockResolvedValue(null);

      await expect(service.deleteOne({ input: 999 })).rejects.toThrow(BadRequestException);
    });
  });
});
```

---

## Quick Reference

| Concept | Analogy | Meteor equivalent | The one rule |
|---------|---------|-------------------|--------------|
| Entity | Government form template | `new Mongo.Collection('todo')` — schema-less | Extend `AbstractEntity`. Never `synchronize: true` in prod. |
| AbstractEntity | Company letterhead | No equivalent | Provides `id` + timestamps. All entities extend it. |
| AbstractDto | Standard response envelope | No equivalent | Pairs with AbstractEntity. All output DTOs extend it. |
| `@RelationId` | FK value on the form | `userId: String` field (unvalidated) | Cheap integer — use for filtering. Load full relation only when needed. |
| Service | Doctor | Logic mixed into `Meteor.methods` body | All business logic here. Never touches HTTP objects. |
| Resolver | Receptionist + personal shopper | `Meteor.methods` entry — routing only | Routes and returns. Two lines max. No business logic. |
| `@ResolveField` | Personal shopper fetching nested items | Automatic via DDP reactive joins | Called once per parent object — always pair with DataLoader. |
| Module | Department in a company | Implicit file loading | `imports` borrows · `providers` owns · `exports` lends. |
| CommandBus/QueryBus | Postal sorting facility | Single method body doing everything | Drop the object; bus routes to handler. Handlers are one-liners. |
| DataLoader | One warehouse trip for 100 orders | No equivalent (client-side joins in Minimongo) | Must be `Scope.REQUEST`. Result order must match input key order. |
| `Scope.REQUEST` | Fresh cup brewed per visitor | No concept | Cascades up the dependency tree — use deliberately. |
| Guard (`AuthJwtGuard`) | Bouncer at the club door | `.allow()` / `.deny()` — but at DB layer | Returns `true` or throws. Runs before pipes and handler. |
| RS256 JWT | King's wax seal | DDP session token | Private key signs, public key verifies. Use RS256, never HS256. |
| Ownership filter | Unit number on every query | `find({ userId: this.userId })` in publish | `userId: { eq: currentUser.user.id }` on every query and mutation. |

---

## Summary

| Concept | What you built | Meteor equivalent |
|---------|---------------|-------------------|
| FK to User | `@ManyToOne(() => UserEntity)` + `@RelationId` | `userId: String` field (unvalidated) |
| Ownership filter | `userId: { eq: currentUser.user.id }` in every query | `Meteor.publish('tasks', function() { find({ userId: this.userId }) })` |
| userId never from client | No `@Field()` on `userId` in CreateTodoInput | No enforcement — anyone could pass any userId |
| N+1 problem | 10 todos + 10 user queries = 11 queries | No concern (client-side joins in Minimongo) |
| DataLoader | Batches user lookups: 10 todos = 2 queries | No equivalent |
| `Scope.REQUEST` | Fresh DataLoader per request | No concept |
| `@ResolveField` | `user(@Parent() todo)` → `userLoader.load(todo.userId)` | Automatic via DDP reactive joins |

In Part 12 — Testing — you will write unit, integration, and e2e tests for the modules built so far.
