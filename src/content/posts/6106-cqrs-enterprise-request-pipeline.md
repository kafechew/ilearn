---
author: Kai
pubDatetime: 2026-05-06T09:00:00+08:00
title: CQRS - The Enterprise Request Pipeline
featured: false
draft: false
slug: 6106-cqrs-enterprise-request-pipeline
tags:
  - deeptech
  - meteorjs
  - nestjs
  - typescript
  - graphql
  - api
  - cqrs
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/06-cqrs-enterprise-request-pipeline.png"
description: By the end of this part, you will learn CQRS, request lifecycle, GraphQL mutation, 9-step module pattern, and index pattern.
---

This is **Part 6 of 24** in the NestJS series. By this point, Part 5 has already applied the production hardening layer — Joi config validation, `LoggingInterceptor`, Helmet, and rate limiting are all in place. This part focuses on the request architecture: how writes and reads are separated through the CQRS pattern so that every feature module is independently testable and maintainable.

## What This Part Covers

- What CQRS is and why it exists (the Meteor method problem at scale)
- The complete request lifecycle: from GraphQL mutation to PostgreSQL and back
- `TypedQuery<T>` and `TypedCommand<T>` — type-safe CQRS
- The thin handler rule — and why violating it is a design defect
- The 9-step module pattern you will use for every feature
- The CQRS index pattern: exporting handler arrays
- A complete, working CQRS setup for the Todo module

---

## Meteor Equivalent

```javascript
// Meteor Methods: the write path
Meteor.methods({
  async createTask(text) {
    if (!this.userId) throw new Meteor.Error("not-authorized");
    if (!text) throw new Meteor.Error("text-required");
    return await TasksCollection.insertAsync({
      text,
      userId: this.userId,
      createdAt: new Date(),
    });
  },
  async deleteTask(taskId) {
    const task = await TasksCollection.findOneAsync(taskId);
    if (task.userId !== this.userId) throw new Meteor.Error("not-authorized");
    return await TasksCollection.removeAsync(taskId);
  },
});

// Meteor Publications: the read path
Meteor.publish("tasks", function () {
  if (!this.userId) return this.ready();
  return TasksCollection.find({ userId: this.userId });
});
```

```typescript
// Enterprise NestJS: CQRS separates writes from reads
// Write path:
@CommandHandler(CreateOneTodoCommand)
class CreateOneTodoCommandHandler {
  async execute(command: CreateOneTodoCommand) {
    return this.todoService.createOne(command.args);
  }
}

// Read path:
@QueryHandler(FindManyTodoQuery)
class FindManyTodoQueryHandler {
  async execute(query: FindManyTodoQuery) {
    return this.todoService.findMany(query.args);
  }
}
```

---

## 1. The Problem With Meteor Methods at Scale

In Meteor, methods are where everything happens. They handle authentication, validation, business logic, and database access — all in one function body. This works for small apps. It breaks badly as the app grows.

Consider a `createTask` method after a year of feature additions:

```javascript
Meteor.methods({
  async createTask(text, projectId, assigneeId, dueDate, priority, tags) {
    // Auth check
    if (!this.userId) throw new Meteor.Error("not-authorized");

    // Validation
    check(text, String);
    if (text.length > 500) throw new Meteor.Error("text-too-long");

    // Business rule: does the project exist?
    const project = await ProjectsCollection.findOneAsync(projectId);
    if (!project) throw new Meteor.Error("project-not-found");

    // Business rule: is the user a member of the project?
    if (!project.memberIds.includes(this.userId))
      throw new Meteor.Error("not-member");

    // Business rule: assignee must be a project member too
    if (assigneeId && !project.memberIds.includes(assigneeId)) {
      throw new Meteor.Error("assignee-not-member");
    }

    // Side effect: create a notification
    await NotificationsCollection.insertAsync({
      userId: assigneeId,
      message: `New task: ${text}`,
    });

    // Side effect: send an email
    Email.send({ to: assignee.email, subject: "New task assigned" });

    // Finally: insert
    return await TasksCollection.insertAsync({
      text,
      projectId,
      assigneeId,
      dueDate,
      priority,
      tags,
      userId: this.userId,
      createdAt: new Date(),
    });
  },
});
```

Problems:

- **Untestable.** Testing this method requires a full Meteor environment, a real database, a real email service.
- **Unmaintainable.** Every business rule is mixed with auth checks, validation, and side effects.
- **Unreusable.** If another method needs to create a task internally, it calls this method and inherits all its auth/validation (which may be wrong in internal context).
- **Single point of failure.** One change can break everything.

---

## 2. What CQRS Solves

> **Two kitchens that never share a stove.** The order kitchen (Commands) accepts new orders, cooks food, and changes the state of the menu. The reading kitchen (Queries) only describes what's available — it never starts the oven. A waiter from the reading kitchen cannot place new orders. There is zero confusion about which kitchen does what. This is CQRS: reads and writes have fundamentally different requirements, so they get separate handlers.

> **From Meteor?** `Meteor.methods({ createTask })` puts auth checks, validation, business logic, and DB access in one function body. CQRS forces those into four separate, independently testable units: Resolver (routing) → CommandBus (dispatching) → Handler (thin delegation) → Service (logic).

CQRS — Command Query Responsibility Segregation — separates **writes** (Commands) from **reads** (Queries). Instead of one `createTask` method that does everything, you have:

- A **Command** class: a typed message representing the _intent_ ("I want to create a todo")
- A **CommandHandler**: a thin class that receives the command and calls the service
- A **Service**: where the business logic lives (fully testable in isolation)
- A **Query** class: a typed message representing a read request
- A **QueryHandler**: thin, delegates to the service

The flow:

```
Resolver (HTTP/GraphQL layer)
    │ dispatches
    ▼
CommandBus.execute(new CreateOneTodoCommand({ input }))
    │ routes to
    ▼
CreateOneTodoCommandHandler.execute(command)
    │ delegates to
    ▼
TodoService.createOne(command.args)
    │ queries
    ▼
TypeORM Repository → PostgreSQL
```

Every layer has one job. Every layer is independently testable.

**Memory hook:** CQRS = two separate restaurant kitchens. Commands mutate state, Queries only read. Handlers are always one-liners — logic belongs in the Service.

---

## 3. The Full Request Lifecycle (Annotated)

Let's trace a `createTodo` mutation from the client to the database and back:

```
GraphQL Client sends:
  POST /graphql
  { mutation: createTodo(input: { text: "Buy milk" }) { id text } }
```

```
Step 1: Apollo Server receives the request
  → Routes to TodoResolver.createTodo()
```

```
Step 2: Guards run (before the resolver method)
  → @UseGuards(AuthJwtGuard) validates the Bearer JWT
  → If invalid/missing: returns 401 UNAUTHORIZED
  → If valid: attaches user to req.user
```

```
Step 3: Pipes run (before the resolver method)
  → ValidationPipe runs class-validator on CreateTodoInput
  → @IsNotEmpty() on text — fails if empty → 400 BAD REQUEST
  → @IsString() on text — fails if not string → 400 BAD REQUEST
```

```
Step 4: Resolver method executes
  → @CurrentUser() extracts currentUser from req.user (set by guard)
  → @Args('input') extracts validated CreateTodoInput
  → Merges: { ...input, userId: currentUser.user.id }
  → Dispatches: commandBus.execute(new CreateOneTodoCommand({ input }))
```

```
Step 5: CommandBus routes to the registered handler
  → @CommandHandler(CreateOneTodoCommand) decorator registered this handler
  → NestJS finds CreateOneTodoCommandHandler
  → Calls handler.execute(command)
```

> **The postal sorting facility:** The CommandBus is like a national postal sorting facility. You write a letter (command object), drop it in the slot, and the facility reads the address (the class name), routes it to the right delivery driver (handler), and delivers it. You don't drive to the destination yourself. You don't know which driver was used. The handler registration via `@CommandHandler(CreateOneTodoCommand)` is the "address label" the sorting facility reads.

```
Step 6: Handler delegates to service (one line)
  → return this.todoService.createOne(command.args)
```

```
Step 7: Service executes business logic
  → Checks: does a todo with this text already exist for this user?
  → Creates: repo.create({ text, isChecked: false, userId, status: ACTIVE })
  → Saves: await repo.save(todo)
  → Returns: { success: true, data: savedTodo }
```

```
Step 8: Result bubbles back up
  → Handler returns { success: true, data: TodoEntity }
  → CommandBus returns it to the resolver
  → Resolver returns data as TodoDto
  → Apollo serializes { id, text, isChecked, createdAt } to JSON
```

```
Client receives:
  { "data": { "createTodo": { "id": 1, "text": "Buy milk", "isChecked": false } } }
```

The key insight: **each step only knows about its own responsibility**. The resolver doesn't know how todos are created. The handler doesn't know about validation. The service doesn't know about JWT or GraphQL. This separation is what makes the system testable, maintainable, and refactorable.

> **From Meteor?** In Meteor, one method body did all nine steps above — auth check, validation, business logic, DB call, and return. In NestJS each step is a separate layer with its own file. Changing Step 7 (the service business rule) never touches Steps 2–4 (guards, pipes, resolver).

**Memory hook:** Request lifecycle = MG²IPHS. Middleware → Guards → Interceptor (pre) → Pipe → Handler → Service. Guards reject, Pipes transform, Handler routes, Service decides.

---

## 4. `nestjs-typed-cqrs` — Type-Safe Commands and Queries

Vanilla `@nestjs/cqrs` has a serious weakness: `queryBus.execute()` and `commandBus.execute()` return `any`. TypeScript cannot check that your handler returns the right shape.

```typescript
// Vanilla CQRS — returns any
const result = await this.queryBus.execute(new FindOneTodoQuery({ id: 1 }));
result.data; // TypeScript: any — no type checking, no autocomplete
result.daat; // TypeScript: still OK (typo goes undetected)
```

`nestjs-typed-cqrs` adds type-safety through generic parameters:

```typescript
// With nestjs-typed-cqrs — fully typed
const result = await this.queryBus.execute(
  new FindOneTodoQuery({ query: { filter: { id: { eq: 1 } } } })
);
result.data; // TypeScript: TodoEntity — full autocomplete
result.daat; // TypeScript ERROR: Property 'daat' does not exist
```

### How Typed CQRS Works

```typescript
// The query class encodes its own return type
export class FindOneTodoQuery extends AbstractCqrsQueryInput<
  TodoEntity, // entity type
  undefined, // filter type (undefined = use default)
  RecordQueryWithJoinOptions, // options type
  TodoEntity // ← return type
> {}

// The handler's return type is INFERRED from the query class
export class FindOneTodoQueryHandler implements IInferredQueryHandler<FindOneTodoQuery> {
  async execute(
    query: FindOneTodoQuery
  ): Promise<QueryResult<FindOneTodoQuery>> {
    // QueryResult<FindOneTodoQuery> resolves to { success: boolean, data: TodoEntity }
    return this.todoService.findOne(query.args);
  }
}
```

At the call site:

```typescript
const { data } = await this.queryBus.execute(new FindOneTodoQuery({ ... }));
//      ^^^^ TypeScript knows this is TodoEntity | null
```

> **From Meteor?** Meteor methods return `any` — a typo in `result.userId` vs `result.useId` goes undetected until runtime. `nestjs-typed-cqrs` makes the return type flow from the Query class definition all the way to the call site, so TypeScript catches the typo at compile time.

**Memory hook:** `nestjs-typed-cqrs` = the return type lives inside the Query/Command class. `QueryResult<T>` resolves to the exact shape — no more `any`.

---

## 5. CQRS Input Classes (Commands & Queries)

Create `apps/api/src/modules/todo/cqrs/todo.cqrs.input.ts`:

```typescript
import { Query } from "@ptc-org/nestjs-query-core";
import {
  AbstractCqrsCommandInput,
  AbstractCqrsQueryInput,
  RecordMutateOptions,
  RecordQueryWithJoinOptions,
} from "nestjs-typed-cqrs";

import { CreateTodoInput, UpdateTodoInput } from "../dto/todo.input";
import { TodoEntity } from "../todo.entity";

/**
 * QUERIES (read operations)
 */

// Find a single todo by filter (e.g., by id)
export class FindOneTodoQuery extends AbstractCqrsQueryInput<
  TodoEntity,
  undefined,
  RecordQueryWithJoinOptions,
  TodoEntity // ← returns one entity (or null)
> {}

// Find many todos by filter (e.g., all todos for a user)
export class FindManyTodoQuery extends AbstractCqrsQueryInput<
  TodoEntity,
  undefined,
  RecordQueryWithJoinOptions,
  TodoEntity[] // ← returns an array
> {}

// Count todos matching a filter
export class CountTodoQuery extends AbstractCqrsQueryInput<
  TodoEntity,
  Query<TodoEntity>["filter"],
  undefined,
  number // ← returns a count
> {}

/**
 * COMMANDS (write operations)
 */

// Create one todo
export class CreateOneTodoCommand extends AbstractCqrsCommandInput<
  TodoEntity,
  CreateTodoInput & { userId: number } // ← input type (userId added server-side)
> {}

// Update one todo
export class UpdateOneTodoCommand extends AbstractCqrsCommandInput<
  TodoEntity,
  UpdateTodoInput,
  true, // ← isUpdateOne = true
  RecordMutateOptions,
  { before: TodoEntity; updated: TodoEntity } // ← returns before and after
> {}

// Delete one todo
export class DeleteOneTodoCommand extends AbstractCqrsCommandInput<
  TodoEntity,
  number // ← input is just the id
> {}
```

**Reading the generic type parameters:**

For `AbstractCqrsQueryInput<Entity, FilterType, OptionsType, ReturnType>`:

- `Entity` — the TypeORM entity this query operates on
- `FilterType` — the filter shape (leave `undefined` to use the default)
- `OptionsType` — query options (joins, eager loading)
- `ReturnType` — what the handler should return (used by `QueryResult<T>`)

For `AbstractCqrsCommandInput<Entity, InputType, isUpdateOne?, OptionsType?, ReturnType?>`:

- `Entity` — the entity being modified
- `InputType` — the input data shape
- `isUpdateOne` — `true` means the command has both a `query` (to find the record) and `input` (the update data)

> **From Meteor?** Meteor has no typed message classes — a method is just a string name. Here, the Command or Query class IS the message. Its generic parameters encode the input shape and return type, so the compiler enforces the contract end-to-end.

**Memory hook:** Command/Query class = the typed letter you drop in the postal slot. Generic parameters = the address and expected reply format. One class per operation.

---

## 6. CQRS Index (`cqrs/index.ts`)

```typescript
// apps/api/src/modules/todo/cqrs/index.ts
import {
  CountTodoQueryHandler,
  CreateOneTodoCommandHandler,
  DeleteOneTodoCommandHandler,
  FindManyTodoQueryHandler,
  FindOneTodoQueryHandler,
  UpdateOneTodoCommandHandler,
} from "./todo.cqrs.handler";

// Arrays spread into module providers
export const TodoQueryHandlers = [
  FindOneTodoQueryHandler,
  FindManyTodoQueryHandler,
  CountTodoQueryHandler,
];

export const TodoCommandHandlers = [
  CreateOneTodoCommandHandler,
  UpdateOneTodoCommandHandler,
  DeleteOneTodoCommandHandler,
];

export const TodoEventHandlers = [];

// Re-export inputs so other files can import from './cqrs' (one import path)
export * from "./todo.cqrs.input";
```

**Why the index pattern?** The module file spreads these arrays into `providers`:

```typescript
// In apps/api/src/modules/todo/todo.module.ts:
providers: [
  TodoResolver,
  TodoService,
  ...TodoQueryHandlers, // spreads all query handlers
  ...TodoCommandHandlers, // spreads all command handlers
];
```

When you add a new handler, you add it to the array in `index.ts`. The module and the bus registration update automatically.

> **From Meteor?** In Meteor you'd add a new method to the methods object. Here you add a handler class to an exported array — the module spreads it in automatically. No manual registration per handler.

**Memory hook:** CQRS index = barrel file. Two arrays: `QueryHandlers` and `CommandHandlers`. Spread them into `providers[]`. Adding a handler = one line in the index.

---

## 7. CQRS Handlers (`cqrs/todo.cqrs.handler.ts`)

Handlers are **always one-liners**. This is not laziness — it is a design rule.

```typescript
// apps/api/src/modules/todo/cqrs/todo.cqrs.handler.ts
import {
  CommandHandler,
  IInferredCommandHandler,
  IInferredQueryHandler,
  QueryHandler,
} from "@nestjs/cqrs";
import { CommandResult, QueryResult } from "nestjs-typed-cqrs";
import { TodoService } from "../todo.service";
import {
  CountTodoQuery,
  CreateOneTodoCommand,
  DeleteOneTodoCommand,
  FindManyTodoQuery,
  FindOneTodoQuery,
  UpdateOneTodoCommand,
} from "./todo.cqrs.input";

// ── Query Handlers ──────────────────────────────────────────

@QueryHandler(FindOneTodoQuery)
export class FindOneTodoQueryHandler implements IInferredQueryHandler<FindOneTodoQuery> {
  constructor(readonly service: TodoService) {}
  async execute(
    query: FindOneTodoQuery
  ): Promise<QueryResult<FindOneTodoQuery>> {
    return this.service.findOneTodo(query.args); // one line — delegate to service
  }
}

@QueryHandler(FindManyTodoQuery)
export class FindManyTodoQueryHandler implements IInferredQueryHandler<FindManyTodoQuery> {
  constructor(readonly service: TodoService) {}
  async execute(
    query: FindManyTodoQuery
  ): Promise<QueryResult<FindManyTodoQuery>> {
    return this.service.findManyTodo(query.args);
  }
}

@QueryHandler(CountTodoQuery)
export class CountTodoQueryHandler implements IInferredQueryHandler<CountTodoQuery> {
  constructor(readonly service: TodoService) {}
  async execute(query: CountTodoQuery): Promise<QueryResult<CountTodoQuery>> {
    return this.service.countTodo(query.args);
  }
}

// ── Command Handlers ────────────────────────────────────────

@CommandHandler(CreateOneTodoCommand)
export class CreateOneTodoCommandHandler implements IInferredCommandHandler<CreateOneTodoCommand> {
  constructor(readonly service: TodoService) {}
  async execute(
    command: CreateOneTodoCommand
  ): Promise<CommandResult<CreateOneTodoCommand>> {
    return this.service.createOneTodo(command.args);
  }
}

@CommandHandler(UpdateOneTodoCommand)
export class UpdateOneTodoCommandHandler implements IInferredCommandHandler<UpdateOneTodoCommand> {
  constructor(readonly service: TodoService) {}
  async execute(
    command: UpdateOneTodoCommand
  ): Promise<CommandResult<UpdateOneTodoCommand>> {
    return this.service.updateOneTodo(command.args);
  }
}

@CommandHandler(DeleteOneTodoCommand)
export class DeleteOneTodoCommandHandler implements IInferredCommandHandler<DeleteOneTodoCommand> {
  constructor(readonly service: TodoService) {}
  async execute(
    command: DeleteOneTodoCommand
  ): Promise<CommandResult<DeleteOneTodoCommand>> {
    return this.service.deleteOneTodo(command.args);
  }
}
```

Every handler follows the exact same pattern:

1. `@QueryHandler(TheQuery)` or `@CommandHandler(TheCommand)` — registers with the bus
2. `implements IInferredQueryHandler<TheQuery>` — TypeScript enforces correct return type
3. Constructor injects the service
4. `execute()` — exactly one line: `return this.service.methodName(query.args)`

**The thin handler rule:** If you find yourself writing logic in a handler (`if` statements, repository calls, calculations), you are doing it wrong. Move it to the service.

> **From Meteor?** The Meteor method body IS the handler AND the service AND the repo call in one block. Here the handler is always exactly one line — `return this.service.methodName(args)`. The service is a separate file. The separation is enforced by convention and code review.

**Memory hook:** Handler = one line. `return this.service.methodName(command.args)`. Any `if` statement in a handler is a bug — move it to the service.

---

## 8. The Service

The service is where work actually happens. All business rules, all database access, all side effects.

> **The doctor:** The service is the **doctor** who examines, diagnoses, and prescribes. The resolver (receptionist) routes the request. The handler passes the note. The service does the actual work — business rules, DB calls, side effects. The doctor never answers the phone.

> **The librarian:** When the service needs data from the database, it asks the repository — the **librarian** who fetches records from the stacks. The service never writes raw SQL. It asks the librarian, and the librarian fetches.

> **From Meteor?** In Meteor, `TasksCollection.insertAsync()` was called directly inside the method body. Here, `this.repo.save()` and `this.repo.findOne()` are called only inside the service. The service is the single place where all DB access happens — making it fully mockable in tests.

`TodoService` **extends `TypeOrmQueryService<TodoEntity>`** from `@ptc-org/nestjs-query-typeorm` (the public API). This does three things at once:

- `this.filterQueryBuilder` — inherited, no need to declare or instantiate it
- `this.repo` — the raw `Repository<TodoEntity>`, inherited for direct TypeORM operations
- A full `QueryService<Entity>` interface (`query()`, `count()`, `findById()`, `createOne()`, `updateOne()`, `deleteOne()`) — available on `this` if needed

The constructor only needs `@InjectRepository` to inject the repository from NestJS DI and pass it to `super()`. No `NestjsQueryTypeOrmModule`, no `@InjectQueryService`, no manual `FilterQueryBuilder` instantiation.

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

@Injectable()
export class TodoService extends TypeOrmQueryService<TodoEntity> {
  constructor(
    @InjectRepository(TodoEntity)
    repo: Repository<TodoEntity>, // no `private readonly` — parent sets this.repo
  ) {
    super(repo); // sets this.repo and this.filterQueryBuilder via TypeOrmQueryService
  }

  // Find one record
  findOneTodo: CqrsQueryFunc<FindOneTodoQuery, FindOneTodoQuery["args"]> =
    async ({ query, options }) => {
      const nullable = options?.nullable ?? true;

      try {
        const builder = this.filterQueryBuilder.select(query);
        const result = await builder.getOne();

        if (!nullable && !result) {
          throw new Error("Todo not found");
        }

        return { success: true, data: result ?? undefined };
      } catch (e) {
        throw new BadRequestException(e.message);
      }
    };

  // Find many records (for paginated list queries)
  findManyTodo: CqrsQueryFunc<FindManyTodoQuery, FindManyTodoQuery["args"]> =
    async ({ query }) => {
      try {
        const builder = this.filterQueryBuilder.select(query);
        const results = await builder.getMany();
        return { success: true, data: results };
      } catch (e) {
        throw new BadRequestException(e.message);
      }
    };

  // Count records (needed for cursor pagination's totalCount)
  countTodo: CqrsQueryFunc<CountTodoQuery, CountTodoQuery["args"]> = async ({
    query,
  }) => {
    try {
      const count = await this.filterQueryBuilder
        .select({ filter: query })
        .getCount();
      return { success: true, data: count };
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };

  // Create one record
  createOneTodo: CqrsCommandFunc<
    CreateOneTodoCommand,
    CreateOneTodoCommand["args"]
  > = async ({ input }) => {
    try {
      // Business rule: no duplicate text per user
      const existing = await this.repo.findOne({
        where: { text: input.text, userId: input.userId },
      });
      if (existing) {
        throw new Error("You already have a todo with that text");
      }

      const todo = this.repo.create(input);
      const data = await this.repo.save(todo);
      return { success: true, data };
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };

  // Update one record
  updateOneTodo: CqrsCommandFunc<
    UpdateOneTodoCommand,
    UpdateOneTodoCommand["args"]
  > = async ({ query, input }) => {
    try {
      const builder = this.filterQueryBuilder.select(query);
      const before = await builder.getOne();
      if (!before) throw new NotFoundException("Todo not found");

      const updated = await this.repo.save({ ...before, ...input });
      return { success: true, data: { before, updated } };
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };

  // Delete one record
  deleteOneTodo: CqrsCommandFunc<
    DeleteOneTodoCommand,
    DeleteOneTodoCommand["args"]
  > = async ({ input: id }) => {
    try {
      const todo = await this.repo.findOne({ where: { id } });
      if (!todo) throw new NotFoundException("Todo not found");
      await this.repo.remove(todo);
      return { success: true, data: todo };
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };
}
```

**Memory hook:** Service = doctor. All `if` statements with business meaning live here. All repo calls live here. It never touches HTTP/GraphQL objects.

---

## 9. The 9-Step Module Pattern

Every feature module follows this exact checklist. Memorise it.

```
Step 1: Entity         → extends AbstractEntity, define columns, relations, indexes
Step 2: Constants      → enums + registerEnumType
Step 3: DTOs           → @ObjectType (read), @InputType (write), @ArgsType (list query)
Step 4: CQRS Inputs    → AbstractCqrsQueryInput / AbstractCqrsCommandInput classes
Step 5: CQRS Handlers  → one-liner delegation to service, thin always
Step 6: CQRS Index     → export handler arrays + re-export inputs
Step 7: Service        → business logic, repository operations
Step 8: Resolver       → GraphQL endpoints, @UseGuards, @CurrentUser
Step 9: Module         → TypeOrmModule.forFeature([Entity]) + providers spread
        Register       → add Module to AppModule, add Entity to AppModule's entities[]
        Migrate        → generate → review SQL → run → verify in Adminer
        Test           → unit tests for service + handlers (Part 10)
```

You will run through this checklist completely in Part 10 (Tag module) and Part 11 (Todo module).

> **From Meteor?** Meteor had no equivalent checklist — a feature was "done" when the method and publication worked. In NestJS, "done" means all 9 steps completed, entity registered in AppModule, migration reviewed and run, and unit tests passing.

**Memory hook:** 9-step pattern = Entity → Constants → DTOs → CQRS Inputs → Handlers → Index → Service → Resolver → Module. Run it in this order every time. Never skip steps.

---

## 10. The Module File

```typescript
// apps/api/src/modules/todo/todo.module.ts
import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";

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
    TypeOrmModule.forFeature([TodoEntity]), // makes Repository<TodoEntity> injectable in this module
    // CqrsModule is NOT imported here — CqrsModule.forRoot() in AppModule registers the buses globally
  ],
  providers: [
    TodoResolver,
    TodoService,
    ...TodoQueryHandlers, // spreads all query handlers
    ...TodoCommandHandlers, // spreads all command handlers
    ...TodoEventHandlers, // spreads all event handlers (empty for now)
  ],
  exports: [TodoService], // export if other modules need to call TodoService
})
export class TodoModule {}
```

Register in `AppModule`. This is the complete, working `app.module.ts` after adding the Todo module:

```typescript
// apps/api/src/app/app.module.ts
import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { TypeOrmModule } from '@nestjs/typeorm';
import { GraphQLModule } from '@nestjs/graphql';
import { ApolloDriver, ApolloDriverConfig } from '@nestjs/apollo';
import { CqrsModule } from '@nestjs/cqrs';
import { AppResolver } from './app.resolver';
import { HealthModule } from '../modules/health/health.module';
import { SnakeNamingStrategy } from 'typeorm-naming-strategies';
import { TodoModule } from '../modules/todo/todo.module';
import { TodoEntity } from '../modules/todo/todo.entity';
import { UserEntity } from '../modules/user/user.entity';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true, envFilePath: '.env' }),

    TypeOrmModule.forRootAsync({
      inject: [ConfigService],
      useFactory: (config: ConfigService) => ({
        type: 'postgres',
        host: config.get('PROJECT_DB_HOST'),
        port: config.get<number>('PROJECT_DB_PORT'),
        username: config.get('PROJECT_DB_USERNAME'),
        password: config.get('PROJECT_DB_PASSWORD'),
        database: config.get('PROJECT_DB_DATABASE'),
        entities: [TodoEntity, UserEntity],
        synchronize: false,
        logging: config.get('PROJECT_DB_DEBUG') === 'true',
        namingStrategy: new SnakeNamingStrategy(),
      }),
    }),

    GraphQLModule.forRootAsync<ApolloDriverConfig>({
      driver: ApolloDriver,
      inject: [ConfigService],
      useFactory: (config: ConfigService) => ({
        autoSchemaFile: true,
        playground: config.get('PROJECT_GRAPHQL_PLAYGROUND') === 'true',
        context: ({ req }) => ({ req }),
      }),
    }),

    CqrsModule.forRoot(),  // registers CommandBus, QueryBus, EventBus globally
    HealthModule,
    TodoModule,
  ],
  providers: [AppResolver],
})
export class AppModule {}
```

**Two things to understand here:**

**1. `entities: [TodoEntity, UserEntity]` — explicit, not a glob**

You might expect to use a glob pattern like `__dirname + '/**/*.entity{.ts,.js}'` to auto-discover entities. That works with `ts-node` directly, but this project uses **Webpack**, which compiles everything into a single `main.js`. At runtime there are no separate `.entity.js` files on disk — the glob finds nothing. TypeORM silently boots with zero entities, and then crashes the moment a query touches any table.

Rule: every entity in every future module must be **explicitly imported and listed** in `AppModule`'s `entities[]`.

**2. `UserEntity` is required even though there is no `UserModule` yet**

`TodoEntity` declares `@ManyToOne(() => UserEntity)`. TypeORM needs every entity in a relationship to be registered in the same DataSource — even if you're not querying `UserEntity` directly. Omitting it produces `EntityMetadataNotFoundError: No metadata for "UserEntity" was found` at startup.

**3. `CqrsModule.forRoot()` here, not in feature modules**

`CqrsModule.forRoot()` registers `CommandBus`, `QueryBus`, and `EventBus` as **global providers**. This is why `TodoModule` does not import `CqrsModule` — the buses are already in scope for the entire application once `AppModule` calls `forRoot()`. Feature modules that import plain `CqrsModule` (without `forRoot`) will get a separate, isolated bus instance that has no handlers registered — a subtle bug that is hard to diagnose.

> **From Meteor?** In Meteor, `Meteor.methods` and `Meteor.publish` were globally registered the moment their file loaded. In NestJS, `CqrsModule.forRoot()` in AppModule is the equivalent global registration point for the buses. Feature modules do not re-register — they just export their handlers.

**Memory hook:** Module file = the wiring diagram. `TypeOrmModule.forFeature([Entity])` registers the repo. Spread handler arrays into `providers[]`. `CqrsModule.forRoot()` lives in AppModule only — never in feature modules.

---

## 11. Naming Conventions

Every name in the CQRS layer follows a strict convention. Consistency means any developer can find any file in any module without looking.

| Type                        | Pattern                              | Example                       |
| --------------------------- | ------------------------------------ | ----------------------------- |
| Query class                 | `FindOne<Entity>Query`               | `FindOneTodoQuery`            |
| Query class (many)          | `FindMany<Entity>Query`              | `FindManyTodoQuery`           |
| Query class (count)         | `Count<Entity>Query`                 | `CountTodoQuery`              |
| Command class (create)      | `CreateOne<Entity>Command`           | `CreateOneTodoCommand`        |
| Command class (update)      | `UpdateOne<Entity>Command`           | `UpdateOneTodoCommand`        |
| Command class (delete)      | `DeleteOne<Entity>Command`           | `DeleteOneTodoCommand`        |
| Query handler               | `FindOne<Entity>QueryHandler`        | `FindOneTodoQueryHandler`     |
| Command handler             | `CreateOne<Entity>CommandHandler`    | `CreateOneTodoCommandHandler` |
| Service method (find one)   | `findOne<Entity>`                    | `findOneTodo`                 |
| Service method (find many)  | `findMany<Entity>`                   | `findManyTodo`                |
| Service method (count)      | `count<Entity>`                      | `countTodo`                   |
| Service method (create)     | `createOne<Entity>`                  | `createOneTodo`               |
| Service method (update)     | `updateOne<Entity>`                  | `updateOneTodo`               |
| Service method (delete)     | `deleteOne<Entity>`                  | `deleteOneTodo`               |
| Event                       | `<Entity><Action>Event`              | `TodoCreatedEvent`            |
| Event handler               | `<Entity><Action>EventHandler`       | `TodoCreatedEventHandler`     |

**Memory hook:** Naming = `<Verb><Entity><Type>`. `FindOneTodoQuery`, `CreateOneTodoCommand`, `TodoCreatedEvent`. Any developer can find any file in any module without opening a directory listing.

---

## 12. CQRS Events (Advanced)

> **The office PA announcement:** Publishing a domain event is like a public announcement over the office PA: "New todo just created!" HR (the email handler) hears it and sends a notification. IT (the audit log handler) hears it and logs the action. The PA operator (command handler) broadcasts the fact and immediately moves on — it never manages who reacted or how.

Commands can emit events after execution. Events are processed asynchronously by event handlers.

```typescript
// An event class
export class TodoCreatedEvent {
  constructor(public readonly todo: TodoEntity) {}
}

// In the command handler (after create):
@CommandHandler(CreateOneTodoCommand)
export class CreateOneTodoCommandHandler {
  constructor(
    readonly service: TodoService,
    private readonly eventBus: EventBus
  ) {}

  async execute(command: CreateOneTodoCommand) {
    const result = await this.service.createOne(command.args);
    // Emit an event — processed asynchronously
    this.eventBus.publish(new TodoCreatedEvent(result.data));
    return result;
  }
}

// An event handler (does side effects: email, notification, etc.)
@EventsHandler(TodoCreatedEvent)
export class TodoCreatedEventHandler implements IEventHandler<TodoCreatedEvent> {
  async handle(event: TodoCreatedEvent) {
    // Send email notification, update counters, etc.
    // This runs asynchronously — the original mutation already returned
    console.log(`Todo created: ${event.todo.text}`);
  }
}
```

Events are used for side effects that should not block the primary operation. Use them for: sending emails, creating notifications, updating analytics, triggering background jobs. You will implement this pattern with Bull queues in Part 13.

> **From Meteor?** In Meteor, side effects (email, notifications) were called directly inside the method body — blocking the response. EventBus events run asynchronously after the command handler returns. The mutation completes immediately; the side effects happen independently.

**Memory hook:** EventBus = office PA. Past-tense name (`TodoCreatedEvent`). Command handler publishes and walks away. Multiple independent handlers react. None of them block the original mutation.

---

## 13. Troubleshooting: `reflect-metadata` Version Conflict

If the application throws this error on startup:

```
UnknownDependenciesException: Nest can't resolve dependencies of the ConfigService (?).
  Symbol(CONFIG_SERVICE) at index [0] in ConfigModule module.
```

The root cause is almost certainly a **`reflect-metadata` version conflict**.

NestJS decorators (`@Module`, `@Injectable`, etc.) store metadata using `reflect-metadata`. Two versions of this library coexist in the dependency tree — v0.1.x (older) and v0.2.x (newer, bundled inside `typeorm`, `nestjs-dev-utilities`, and `@ptc-org/nestjs-query-*`). Each version maintains its own internal `WeakMap`. When v0.2.x loads, it overwrites the global `Reflect` methods to point at its own empty `WeakMap`. Any metadata written earlier by v0.1.x is now inaccessible. NestJS's module scanner calls `Reflect.getMetadata('imports', ConfigModule)` — it now hits v0.2.x's empty map, gets `undefined`, never discovers `ConfigHostModule`, and the DI lookup for `ConfigService` fails.

**The fix** — upgrade the root `reflect-metadata` to v0.2.x so `yarn` (or npm) deduplicates all nested copies down to one version:

```json
// package.json
"dependencies": {
  "reflect-metadata": "^0.2.2",  // was ^0.1.13 — upgrade to force deduplication
  ...
}
```

Then reinstall:

```bash
yarn install
```

Verify there is only one copy:

```bash
find node_modules -path "*/reflect-metadata/package.json" | xargs grep '"version"'
# Should show only one result — the root node_modules copy
```

`@nestjs/common` declares `"peerDependencies": { "reflect-metadata": "^0.1.12 || ^0.2.0" }` so both versions are supported; upgrading is safe.

---

## Quick Reference

| Concept | Analogy | Meteor equivalent | The one rule |
|---------|---------|-------------------|--------------|
| CQRS | Two separate restaurant kitchens | `Meteor.methods` (writes) + `Meteor.publish` (reads) — mixed | Commands mutate, Queries only read. Never share a handler. |
| CommandBus / QueryBus | Postal sorting facility | No equivalent — methods called by string name | Drop the message object; the bus routes to the registered handler. |
| EventBus | Office PA announcement | Inline side effects in a method body | Past-tense event names. Handler publishes and walks away. |
| CQRS Handler | Thin relay runner | `Meteor.methods` body | Always one line: `return this.service.methodName(args)`. Any `if` = wrong layer. |
| Service | Doctor | Logic inside `Meteor.methods` body | All business rules, all repo calls. Never touches HTTP objects. |
| Repository | Librarian | Direct `Collection.insertAsync()` calls | Only layer allowed to touch the database. Mock it to test the service. |
| CQRS Input class | Typed letter for the postal slot | Method name string | Generic parameters encode input shape and return type — TypeScript enforces the contract. |
| CQRS Index | Barrel file with handler arrays | N/A | Spread into `providers[]`. Adding a handler = one array entry. |
| Module file | Wiring diagram | N/A | `TypeOrmModule.forFeature([Entity])` + spread handler arrays. `CqrsModule.forRoot()` in AppModule only. |
| 9-step pattern | Assembly checklist | Ad-hoc feature additions | Entity → Constants → DTOs → Inputs → Handlers → Index → Service → Resolver → Module. In this order. Every time. |
| Request lifecycle | 9-step relay race | Single method body | Each step has one job. Guards reject. Pipes transform. Handler routes. Service decides. |

---

## Summary

You now understand the full CQRS pipeline:

| Concern                                      | Layer                 | Rule                                       |
| -------------------------------------------- | --------------------- | ------------------------------------------ |
| HTTP/GraphQL routing, auth, input extraction | Resolver              | No business logic, no DB access            |
| Message dispatch                             | CommandBus / QueryBus | Never bypassed — always go through the bus |
| Message routing                              | Handler               | One line: call service method              |
| Business logic, DB access, side effects      | Service               | The only place logic lives                 |
| SQL execution                                | TypeORM Repository    | Never called from resolver or handler      |

The 9-step pattern:

```
Entity → Constants → DTOs → CQRS Inputs → CQRS Index →
CQRS Handlers → Service → Resolver → Module → Register → Migrate
```

In Part 07, you will learn how DTOs and resolvers work together with GraphQL and nestjs-query to give you automatic filtering, sorting, pagination, and the frontend that consumes it all.
