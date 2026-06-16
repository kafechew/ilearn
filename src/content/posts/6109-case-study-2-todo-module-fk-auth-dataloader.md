---
author: Kai
pubDatetime: 2026-05-09T09:00:00+08:00
title: Case Study 2 - Todo Module (FK + Auth + DataLoader)
featured: false
draft: false
slug: 6109-case-study-2-todo-module-fk-auth-dataloader
tags:
  - deeptech
  - meteorjs
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/09-case-study-2-todo-module-fk-auth-dataloader.png"
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

## Meteor Equivalent

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
export class DeleteOneTodoCommand extends AbstractCqrsCommandInput<TodoEntity, number> {}
```

**`cqrs/index.ts`** and **`cqrs/todo.cqrs.handler.ts`** — same one-liner pattern as Tag. (See Part 08 for the template — substitute `Tag` → `Todo`.)

---

## 7. Service (`todo.service.ts`)

The Todo service adds one important concern: **ownership validation** on update and delete.

```typescript
// apps/api/src/modules/todo/todo.service.ts
import { BadRequestException, ForbiddenException, Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { InjectQueryService, QueryService } from '@ptc-org/nestjs-query-core';
import { FilterQueryBuilder } from '@ptc-org/nestjs-query-typeorm/src/query';
import { CqrsCommandFunc, CqrsQueryFunc } from 'nestjs-typed-cqrs';
import { Repository } from 'typeorm';

import {
  CountTodoQuery, CreateOneTodoCommand, DeleteOneTodoCommand,
  FindManyTodoQuery, FindOneTodoQuery, UpdateOneTodoCommand,
} from './cqrs/todo.cqrs.input';
import { TodoEntity } from './todo.entity';

@Injectable()
export class TodoService {
  private readonly filterQueryBuilder: FilterQueryBuilder<TodoEntity>;

  constructor(
    @InjectRepository(TodoEntity)
    private readonly repo: Repository<TodoEntity>,
    @InjectQueryService(TodoEntity)
    private readonly queryService: QueryService<TodoEntity>,
  ) {
    this.filterQueryBuilder = new FilterQueryBuilder<TodoEntity>(this.repo);
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

Install dataloader:

```bash
yarn add dataloader
```

---

## 9. Resolver with `@ResolveField` (`todo.resolver.ts`)

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
    // First verify ownership
    const { data: todo } = await this.queryBus.execute(
      new FindOneTodoQuery({
        query: { filter: { id: { eq: id }, userId: { eq: currentUser.user.id } } },
      }),
    );
    if (!todo) throw new Error('Todo not found or access denied');

    await this.commandBus.execute(new DeleteOneTodoCommand({ input: id }));
    return true;
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

---

## 10. Module (`todo.module.ts`)

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

---

## 11. Migration, Registration, and Smoke Tests

Register in `AppModule` (add `TodoEntity` to entities, `TodoModule` to imports), generate and run the migration:

```bash
yarn api:migration:generate --name=create-todo-table
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
