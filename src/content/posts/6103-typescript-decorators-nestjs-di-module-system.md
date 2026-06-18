---
author: Kai
pubDatetime: 2026-05-03T09:00:00+08:00
title: TypeScript Decorators, NestJS DI & the Module System
featured: false
draft: false
slug: 6103-typescript-decorators-nestjs-di-module-system
tags:
  - deeptech
  - meteorjs
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/03-typescript-decorators-nestjs-di-module-system.png"
description: By the end of this part, you will learn TypeScript decorators, NestJS module system and dependency injection, difference between GraphQL and REST, and Writing your first NestJS module by hand.

---

## What This Part Covers

- What TypeScript decorators actually are (and why NestJS is built on them)
- The NestJS module system and dependency injection
- How `@Module`, `@Injectable`, `@Controller`, `@Resolver` relate to each other
- The difference between GraphQL and REST — and why this stack uses GraphQL
- Writing your first NestJS module by hand (a simple Health module)

---

## Meteor Equivalents

| Meteor | NestJS | What changed |
|--------|--------|--------------|
| Implicit package loading | `@Module({ imports: [] })` | You declare every dependency explicitly |
| Global `Meteor` object | Injectable services via DI | Dependencies are injected, not accessed globally |
| `meteor add accounts-base` | `imports: [AuthModule]` in AppModule | Modules are composed, not installed as framework plugins |
| Method/collection files auto-loaded | Only files registered in a module are active | Nothing "just works" — you wire everything |
| No decorator system (`Template.helpers`, `Meteor.methods`) | `@Injectable`, `@Resolver`, `@Module` | NestJS reads labels at startup; no label = invisible to the framework |
| `Meteor.methods({ createTask })` (entry + logic in one block) | `@Resolver` (entry only) → `CommandBus` → `Service` | Entry and logic are always separate files |
| `.allow()` / `.deny()` on collections (runs at DB layer) | `@UseGuards(AuthJwtGuard)` (runs at request entry) | Guards run before your handler starts, not after |
| `check(input, String)` (optional, per-method) | `ValidationPipe` + DTO class (global, automatic) | Every request validated automatically; unknown fields rejected |

---

## 1. TypeScript Decorators

Decorators are the foundation of NestJS. Before you write a single module, you must understand what they are.

A decorator is a function that wraps another function, class, or property. The `@` syntax is just shorthand for calling a higher-order function.

### Plain Example

```typescript
// A decorator is just a function
function Log(target: any, key: string, descriptor: PropertyDescriptor) {
  const original = descriptor.value;
  descriptor.value = function (...args: any[]) {
    console.log(`Calling ${key} with`, args);
    return original.apply(this, args);
  };
  return descriptor;
}

class Calculator {
  @Log  // ← this calls Log(Calculator.prototype, 'add', descriptor)
  add(a: number, b: number) {
    return a + b;
  }
}

const calc = new Calculator();
calc.add(2, 3);
// → Console: "Calling add with [2, 3]"
// → Returns: 5
```

NestJS uses decorators to attach **metadata** to classes. This metadata is read at startup by the NestJS framework to understand: what is this class? What does it need? How should requests reach it?

> **Think of decorators as sticky labels on file folders.** The folder's content doesn't change — the label tells whoever handles it what to do: "HTTP HANDLER", "INJECTABLE", "ADMIN ONLY". NestJS is the handler reading those labels at startup to wire the application.

### NestJS-Specific Decorators

```typescript
@Injectable()           // "This class can be injected as a dependency"
class UserService {}

@Controller('users')    // "This class handles HTTP requests at /users"
class UserController {}

@Resolver(() => UserDto) // "This class handles GraphQL queries/mutations for UserDto"
class UserResolver {}

@Module({               // "This is a NestJS module — a unit of organisation"
  imports: [...],       //   other modules this module depends on
  providers: [...],     //   classes this module registers (services, handlers, resolvers)
  controllers: [...],   //   HTTP controllers (for REST endpoints)
  exports: [...],       //   classes this module makes available to other modules
})
class UserModule {}
```

### Why This Matters

In Meteor, you ran `meteor add accounts-password` and auth "just appeared". In NestJS, `@Injectable()` on a class tells the framework "this can be a dependency". `@Module({ providers: [UserService] })` tells the framework "make UserService available for injection within this module". `imports: [UserModule]` in another module says "I want access to UserModule's exported providers".

Nothing happens implicitly. The decorators are your wiring diagram.

> **From Meteor?** Meteor had no decorator system — `Template.helpers({})`, `Meteor.methods({})`, and `ReactiveVar` wired the app implicitly, through Meteor's own magic. There were no `@` labels. NestJS replaces all that invisible glue with explicit labels that are readable, searchable, and enforced at startup.

**Memory hook:** `@Something` = a sticky label. NestJS reads it at startup and acts on it. No label = invisible to the framework.

---

## 2. Dependency Injection

**Dependency Injection (DI)** is the pattern NestJS uses to provide services to the classes that need them.

### The Problem Without DI

```typescript
// Without DI — you create dependencies manually
class TodoResolver {
  constructor() {
    this.userService = new UserService();     // you create it
    this.todoService = new TodoService();     // you create it
  }
}
```

Problems:
- `TodoResolver` is now responsible for creating its dependencies
- If `UserService` needs a database connection, `TodoResolver` must know how to create it
- Testing `TodoResolver` requires creating real `UserService` instances (or painful mocking)

### With DI

```typescript
// With DI — NestJS creates and injects dependencies
@Resolver(() => TodoDto)
class TodoResolver {
  constructor(
    private readonly userService: UserService,   // NestJS injects this
    private readonly commandBus: CommandBus,     // NestJS injects this
    private readonly queryBus: QueryBus,         // NestJS injects this
  ) {}
}
```

NestJS reads the constructor types, checks the module registry, finds registered instances of `UserService`, `CommandBus`, and `QueryBus`, and injects them. You never call `new UserService()`.

**The result:**
- Each class only knows about its own job
- Testing is trivial: pass mock objects into the constructor
- The same `UserService` instance is shared across the module (singleton by default)

> **The staffing agency:** DI works like a professional staffing agency. A chef (your class) tells the agency: "I need a sous chef, a pastry specialist, and a sommelier." On opening day, the agency sends the right people. The chef focuses entirely on cooking. In the test kitchen, the agency sends stand-ins (mocks). The chef cooks the same way regardless — never knowing whether the sommelier is real or a fake.

> **Meteor analogy:** In Meteor you accessed globals: `Meteor.userId()`, `Accounts`, `TasksCollection`. In NestJS, there are no globals. Every dependency arrives through the constructor — explicit, typed, testable.

**Memory hook:** DI = staffing agency. Constructor lists what it needs; the container delivers. In tests, swap the real service for a fake — the class never knows the difference.

### Singleton vs Request-Scoped

By default, NestJS creates one instance of each provider per module (singleton). For most services this is correct. The exception (covered in Part 09) is DataLoaders, which must be created fresh for each HTTP request using `Scope.REQUEST`.

---

## 3. The Module System

A NestJS module is a class decorated with `@Module()`. It is the unit of organisation — the equivalent of a Meteor package, but explicit and composable.

> **Think of each module as a department in a company.** The HR Department owns its own staff and filing cabinets. It doesn't walk directly into Finance to grab payroll data — it formally requests it through a defined interface. In code: `imports` = what your department borrows, `providers` = your internal workers, `controllers` = your front-desk staff, `exports` = what you're willing to share with other departments.

```typescript
@Module({
  imports: [TypeOrmModule.forFeature([TodoEntity]), CqrsModule],
  providers: [TodoResolver, TodoService, ...CommandHandlers, ...QueryHandlers],
  exports: [TodoService],  // if other modules need TodoService
})
export class TodoModule {}
```

**The four arrays of `@Module`:**

```
imports   → modules this module needs (CqrsModule, TypeOrmModule.forFeature([...]))
providers → classes NestJS manages and injects within this module
controllers → HTTP controllers (we use resolvers for GraphQL instead)
exports   → providers made available to OTHER modules that import this module
```

### Module Hierarchy

```
AppModule (root)
├── ConfigModule (global)
├── TypeOrmModule (global, database connection)
├── GraphQLModule (global, Apollo Server)
├── CqrsModule (global, command/query buses)
├── AuthModule
│   ├── imports: [TypeOrmModule.forFeature([UserEntity]), JwtModule]
│   └── providers: [AuthResolver, AuthService, ...]
├── UserModule
│   ├── imports: [TypeOrmModule.forFeature([UserEntity])]
│   └── providers: [UserResolver, UserService, ...]
└── TodoModule
    ├── imports: [TypeOrmModule.forFeature([TodoEntity])]
    └── providers: [TodoResolver, TodoService, ...]
```

`TypeOrmModule.forRoot()` (in AppModule) creates the database connection. `TypeOrmModule.forFeature([TodoEntity])` (in TodoModule) registers the `Repository<TodoEntity>` for injection within that specific module. This is how NestJS ensures that `TodoService` can only access the `TodoEntity` repository — it must explicitly declare it in its module's `imports`.

> **Meteor analogy:** In Meteor, `TasksCollection` was global — any file anywhere could access it. In NestJS, `Repository<TodoEntity>` is only available inside `TodoModule` (and modules it exports to). This prevents accidental cross-module data access.

**Memory hook:** `@Module` = department. `imports` borrows, `providers` owns internal workers, `exports` lends to others. One feature = one module. Never one giant `AppModule` doing everything.

---

## 4. The Request Lifecycle

Understanding how a request flows through NestJS layers is critical. Every single request follows this path:

```
HTTP Request
    │
    ▼
NestJS HTTP Adapter (Express/Fastify)
    │
    ▼
Global Middleware (CORS, rate limiting)
    │
    ▼
Guards (@UseGuards) ← AuthJwtGuard runs here
    │  If guard returns false → 401 Unauthorized, stop here
    ▼
Interceptors (global: LoggingInterceptor, TransformInterceptor)
    │
    ▼
Pipes (ValidationPipe) ← class-validator runs here
    │  If validation fails → 400 Bad Request, stop here
    ▼
Route Handler (Resolver method)
    │
    ▼
CommandBus / QueryBus
    │
    ▼
Handler → Service → Repository → PostgreSQL
    │
    ▼
Response (serialized GraphQL response)
```

**Guards** (the bouncer) decide if the request is allowed — check credentials, return true or throw. Every patron shows a wristband before reaching the dance floor.
**Pipes** (the water filter) validate and transform input — strip impurities and wrong types before your handler ever sees the data.
**The handler** is where your business logic starts — guards and pipes have already run by the time your `@Query()` or `@Mutation()` method executes.

> **From Meteor?** `.allow()` and `.deny()` on collections are the rough Guard equivalent — but they ran at the database layer, after your code had already executed. Guards run before your handler even starts. `check(input, String)` is the rough Pipe equivalent — but it was optional and per-method. NestJS `ValidationPipe` with `whitelist: true` is global, automatic, and rejects requests with fields you never declared.

---

## 5. GraphQL vs REST: Why GraphQL?

The existing `AppModule` sets up Apollo GraphQL instead of HTTP REST controllers. Here is why.

### The REST Problem

A Blaze template showing a todo list with user names requires:

```
GET /api/todos          → [ {id:1, text:"Buy milk", userId: 5}, ... ]
GET /api/users/5        → { name: "Alice" }
GET /api/users/6        → { name: "Bob" }
... (one request per unique userId)
```

This is the N+1 problem at the API level.

> **REST controller vs GraphQL Resolver:** A REST controller is a **traffic cop at fixed intersections** — every caller must pick one of the preset roads, even if reaching what they need takes three separate trips. A GraphQL Resolver is a **personal shopper**: the client says exactly what it wants ("give me the todo title, the assignee's name, and the last three comments — nothing else"), and the server returns precisely that shape in one round trip. No over-fetching. No under-fetching.

### GraphQL Solution

With GraphQL, the client asks for exactly what it needs in one request:

```graphql
query {
  getTodos {
    nodes {
      id
      text
      isChecked
      user {
        fullname
      }
    }
  }
}
```

One HTTP request. The GraphQL server resolves the user relationship on the backend. The client gets exactly the fields it asked for — nothing more, nothing less.

### The Schema as Contract

The GraphQL schema is auto-generated from your TypeScript decorators. It is:
- **Self-documenting** — the Playground shows every query, mutation, and field with their types
- **Type-safe** — generate TypeScript types from the schema for the frontend
- **Validated** — Apollo rejects queries for fields that don't exist in the schema

```graphql
# Auto-generated from your @ObjectType and @Resolver decorators:
type Todo {
  id: Int!
  text: String!
  isChecked: Boolean!
  createdAt: DateTime!
  user: User
}

type Query {
  getTodo(id: Int!): Todo
  getTodos(filter: TodoFilter, paging: CursorPaging): TodoConnection!
}

type Mutation {
  createTodo(input: CreateTodoInput!): Todo!
  updateTodo(id: Int!, input: UpdateTodoInput!): Todo!
  deleteTodo(id: Int!): Boolean!
}
```

This schema is generated automatically — you never write it by hand. The decorators on your DTOs (`@ObjectType`, `@Field`) and resolvers (`@Query`, `@Mutation`) define it.

---

## 6. Your First Module: Health Check

Let's build a minimal module to verify the pattern. A `HealthModule` with one GraphQL query that returns `"ok"`.

### 6.1 Create the Files

```bash
mkdir -p apps/api/src/modules/health
```

**`apps/api/src/modules/health/health.resolver.ts`:**

```typescript
import { Query, Resolver } from '@nestjs/graphql';

@Resolver()
export class HealthResolver {
  // @Query marks this method as a GraphQL query field
  // () => String tells GraphQL the return type
  @Query(() => String)
  health(): string {
    return 'ok';
  }
}
```

**`apps/api/src/modules/health/health.module.ts`:**

```typescript
import { Module } from '@nestjs/common';
import { HealthResolver } from './health.resolver';

@Module({
  providers: [HealthResolver],  // register the resolver so NestJS manages it
})
export class HealthModule {}
```

### 6.2 Register in AppModule

In `apps/api/src/app/app.module.ts`, add to `imports`:

```typescript
import { HealthModule } from '../modules/health/health.module';

@Module({
  imports: [
    // ... existing imports ...
    HealthModule,  // ← add this
  ],
})
export class AppModule {}
```

### 6.3 Test It

Restart the dev server (`Ctrl+C` then `yarn api:dev`), then open the GraphQL Playground at `http://localhost:3333/graphql` and run:

```graphql
query {
  health
}
```

Expected response:

```json
{
  "data": {
    "health": "ok"
  }
}
```

You have just built and registered a NestJS module. The full flow:

1. `HealthModule` declares `HealthResolver` as a provider
2. `AppModule` imports `HealthModule`
3. NestJS registers `HealthResolver`, reads the `@Resolver()` and `@Query()` decorators
4. Apollo Server adds a `health` field to the GraphQL schema
5. When the query runs, Apollo routes to `HealthResolver.health()`

---

## 7. Understanding the Resolver

The `Resolver` is the GraphQL equivalent of a REST Controller. It is the **entry point** for every GraphQL operation — it receives the request, runs guards, extracts inputs, and dispatches to the bus. That is all it does.

> **The receptionist:** The Resolver is the **receptionist at a doctor's clinic**. She takes your name and reason for visit, decides which doctor to route you to, and hands you the answer. She does not examine you. She does not prescribe treatment. She routes and returns. If a resolver method is longer than a few lines, you are doing the doctor's job at the front desk — move that logic to the Service.

> **Personal shopper vs traffic cop:** Compared to REST, a GraphQL Resolver works like a **personal shopper**. A REST endpoint is a fixed shelf — you take everything on it, or you make three separate trips to three endpoints. A GraphQL Resolver lets the client ask for exactly the fields it needs in one query. The shopper fetches that precise shape in one trip. No over-fetching, no under-fetching.

Let's look at a more realistic resolver:

```typescript
import { Resolver, Query, Mutation, Args, Int } from '@nestjs/graphql';
import { UseGuards } from '@nestjs/common';
import { CommandBus, QueryBus } from '@nestjs/cqrs';

import { TodoDto } from './dto/todo.dto';
import { CreateTodoInput } from './dto/todo.input';
import { AuthJwtGuard } from '../auth/guards/auth-jwt.guard';
import { CurrentUser } from '../auth/decorators/current-user.decorator';
import { AccessTokenUser } from '../auth/auth.interface';
import { CreateOneTodoCommand } from './cqrs/todo.cqrs.input';

@Resolver(() => TodoDto)   // "This resolver handles the TodoDto GraphQL type"
export class TodoResolver {

  // Dependencies are INJECTED — never created with `new`
  constructor(
    private readonly queryBus: QueryBus,
    private readonly commandBus: CommandBus,
  ) {}

  // @Query decorator = GraphQL query (read operation)
  // () => TodoDto = the return type in the GraphQL schema
  @Query(() => TodoDto, { nullable: true })
  async todo(
    @Args('id', { type: () => Int }) id: number,  // @Args extracts the query argument
  ): Promise<TodoDto | null> {
    const { data } = await this.queryBus.execute(
      new FindOneTodoQuery({ query: { filter: { id: { eq: id } } } }),
    );
    return data;
  }

  // @Mutation decorator = GraphQL mutation (write operation)
  // @UseGuards — runs AuthJwtGuard before this method executes
  @UseGuards(AuthJwtGuard)
  @Mutation(() => TodoDto)
  async createTodo(
    @CurrentUser() currentUser: AccessTokenUser,  // injected from JWT by guard
    @Args('input') input: CreateTodoInput,        // validated by ValidationPipe
  ): Promise<TodoDto> {
    const { data } = await this.commandBus.execute(
      new CreateOneTodoCommand({ input: { ...input, userId: currentUser.user.id } }),
    );
    return data;
  }
}
```

**Key things to notice:**

1. **No database access.** The resolver never calls `repo.save()` or `repo.find()`. It dispatches commands and queries to the bus.

2. **No business logic.** The resolver does not validate uniqueness, does not compute anything. It extracts inputs, runs guards, and dispatches.

3. **`@UseGuards(AuthJwtGuard)` is explicit.** You see exactly which mutations require authentication. You cannot accidentally forget it — the code shows it clearly.

4. **`@CurrentUser()`** — this decorator extracts the authenticated user from the request context. It only works because `AuthJwtGuard` ran first and attached the user. If the guard had rejected the request, this method never executes.

> **Meteor analogy:**
> - `@Mutation() createTodo()` → `Meteor.methods({ createTodo() }`
> - `@UseGuards(AuthJwtGuard)` → `if (!this.userId) throw new Meteor.Error('not-authorized')`
> - `@CurrentUser()` → `this.userId` inside a Meteor method
> - `this.commandBus.execute(...)` → `TasksCollection.insertAsync(...)` — but with explicit routing

**Memory hook:** Resolver = receptionist + personal shopper. Dispatches to `CommandBus` or `QueryBus`. If a resolver method has an `if` statement or touches the database, it belongs in the Service.

---

## 8. Services

The service is where business logic lives.

> **The doctor:** The Resolver (the receptionist from Section 7) hands work off to the Service — the **doctor** who actually examines, diagnoses, and prescribes. The doctor does not answer phones or handle paperwork. She does medicine. If a service method references HTTP objects (`@Req`, `@Res`, `Request`) or routes requests to other services, something is in the wrong layer.

> **From Meteor?** Meteor methods often mixed routing, validation, and database calls in one block. In NestJS these are always separate files. "Where is the business logic?" → `*.service.ts`. Every time.

**Memory hook:** Service = doctor. All `if` statements with business meaning live here. All repository calls live here. Never touches HTTP objects.

Nothing else goes in here except:
- Repository calls (read/write to the database)
- Business rules (validation, computation, side effects)
- Calls to external services (email, S3, LLM)

```typescript
@Injectable()
export class TodoService {
  constructor(
    @InjectRepository(TodoEntity)
    private readonly repo: Repository<TodoEntity>,
  ) {}

  async createOne(input: CreateTodoInput & { userId: number }): Promise<{ success: boolean; data: TodoEntity }> {
    // Business rule: todo text cannot be a duplicate for the same user
    const existing = await this.repo.findOne({
      where: { text: input.text, userId: input.userId },
    });
    if (existing) {
      throw new BadRequestException('You already have a todo with that text');
    }

    const todo = this.repo.create(input);
    const data = await this.repo.save(todo);
    return { success: true, data };
  }
}
```

**The rule:** If it accesses the database or contains an `if` statement with business meaning, it belongs in the service. If it routes a request to a service, it belongs in the handler. If it handles HTTP/GraphQL concerns (auth, input extraction, response shaping), it belongs in the resolver.

---

## 9. Putting It Together: The Layer Map

Here is the complete picture of the layers in a NestJS module and what each one's job is:

```
┌─────────────────────────────────────────────────────┐
│  todo.resolver.ts                                   │
│  ● GraphQL entry point                              │
│  ● Runs guards, validates input, extracts user      │
│  ● Dispatches to command/query bus                  │
│  ● Returns DTO                                      │
└────────────────────────┬────────────────────────────┘
                         │ CommandBus.execute()
                         │ QueryBus.execute()
┌────────────────────────▼────────────────────────────┐
│  todo.cqrs.handler.ts                               │
│  ● Registered via @CommandHandler / @QueryHandler   │
│  ● Always a one-liner: calls service method         │
│  ● NEVER contains logic                             │
└────────────────────────┬────────────────────────────┘
                         │ this.service.createOne()
┌────────────────────────▼────────────────────────────┐
│  todo.service.ts                                    │
│  ● All business logic lives here                    │
│  ● Validates rules, calls repo, calls external APIs │
│  ● Returns typed result                             │
└────────────────────────┬────────────────────────────┘
                         │ repo.save() / repo.findOne()
┌────────────────────────▼────────────────────────────┐
│  TypeORM Repository<TodoEntity>                     │
│  ● ORM layer — translates to SQL                    │
│  ● Never called from resolver or handler directly   │
└────────────────────────┬────────────────────────────┘
                         │ SQL
┌────────────────────────▼────────────────────────────┐
│  PostgreSQL                                         │
└─────────────────────────────────────────────────────┘
```

The data types flowing through each layer:

| Layer | Input type | Output type |
|-------|-----------|-------------|
| Resolver | `CreateTodoInput` (validated DTO) | `TodoDto` |
| Handler | `CreateOneTodoCommand` | `{ success: boolean, data: TodoEntity }` |
| Service | `{ text, userId }` | `{ success: boolean, data: TodoEntity }` |
| Repository | `Partial<TodoEntity>` | `TodoEntity` |

---

## 10. Full Module File Structure

Every feature module follows this file structure (the 9-step pattern you'll master in Part 08):

```
apps/api/src/modules/todo/
├── cqrs/
│   ├── index.ts                  ← exports handler arrays + re-exports inputs
│   ├── todo.cqrs.handler.ts      ← all command and query handlers (thin delegation)
│   └── todo.cqrs.input.ts        ← typed Command and Query classes
├── dto/
│   ├── todo.dto.ts               ← @ObjectType — what GraphQL sends back to clients
│   ├── todo.input.ts             ← @InputType — what clients send in mutations
│   └── todo.query.ts             ← @ArgsType — query args for list queries
├── test/
│   ├── todo.service.spec.ts      ← unit tests for TodoService
│   └── todo.cqrs.spec.ts         ← unit tests for handlers
├── todo.constant.ts              ← enums, register with GraphQL
├── todo.entity.ts                ← TypeORM entity (DB schema)
├── todo.module.ts                ← wires everything together
├── todo.resolver.ts              ← GraphQL entry points
└── todo.service.ts               ← business logic
```

Each file has exactly one job. When you need to change validation rules, you look in `dto/`. When you need to change database queries, you look in `*.service.ts`. When you need to add a new GraphQL endpoint, you look in `*.resolver.ts`.

---

## Quick Reference

Scan this when you forget where something belongs. One row per concept.

| Concept | Analogy | Meteor equivalent | The one rule |
|---------|---------|-------------------|--------------|
| Decorator | Sticky label on a file folder | `Template.helpers({})`, `Meteor.methods({})` — implicit | No `@` label = invisible to NestJS |
| `@Module` | Department in a company | `meteor add` — but you wire it manually | `imports` borrows · `providers` owns · `exports` lends |
| `@Injectable` / Provider | Appliance with a plug | Globally imported file | Must be in `providers[]` to be DI-managed |
| DI | Staffing agency | `Meteor.userId()`, `Accounts` globals | Constructor declares needs; container delivers |
| Guard | Bouncer | `.allow()` / `.deny()` — but those run at DB layer | Returns `true` or throws. Runs before Pipe. |
| Pipe | Water filter | `check(input, String)` — but optional | Validates/transforms. Returns 400 on failure. |
| Resolver | Receptionist + personal shopper | `Meteor.methods` entry — but only the routing part | Routes only. Dispatches to bus. Two lines max. |
| Service | Doctor | `Meteor.methods` logic body | All business logic lives here. Every `if` statement. |

---

## Summary

You now understand:

| Concept | What it is | Why it matters |
|---------|-----------|----------------|
| Decorators | Functions that attach metadata to classes | NestJS reads this metadata to wire your app |
| `@Module` | Declares a unit of organisation | Makes dependencies explicit and composable |
| `@Injectable` | Marks a class as a DI-managed service | NestJS creates and injects it automatically |
| `@Resolver` | GraphQL entry point — the **receptionist** (routes and returns, never prescribes) | Client fetches exactly the shape it needs (personal shopper). Zero business logic. |
| Dependency Injection | Constructor parameters are provided by the framework | No globals, fully testable, decoupled |
| Service | Business logic home | Reusable, independently testable, one clear job |
| The layer rule | Resolver routes → Handler delegates → Service operates → Repo queries | Every layer has one job, every bug has one home |

In Part 04, you will define your first database entity and run your first migration.
