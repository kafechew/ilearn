---
author: Kai
pubDatetime: 2026-05-06T09:00:00+08:00
title: GraphQL API + Next.js Frontend
featured: false
draft: false
slug: 6106-graphql-api-nextjs-frontend
tags:
  - deeptech
  - meteorjs
  - nestjs
  - nextjs
  - graphql
  - api
  - typescript
  - shadcn-ui
  - apollo
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/06-graphql-api-nextjs-frontend.png"
description: By the end of this part, you will learn DTOs, @Field, @FilterableField, class-validator, resolver anatomy, QueryArgsType, ConnectionType, and FilterQueryBuilder for backend. As well as Next.js, Shadcn UI, Apollo, witing GraphQL queries and mutations.
---

## What This Part Covers

**Backend:**

- DTOs: `@ObjectType` (what GraphQL returns), `@InputType` (what clients send)
- `@Field` vs `@FilterableField` — and the security implications
- `class-validator` decorators for input validation
- The resolver anatomy: `@Query`, `@Mutation`, `@Args`
- `QueryArgsType` and `ConnectionType` — automatic filtering, sorting, and cursor pagination
- `FilterQueryBuilder` — how `nestjs-query` bridges GraphQL filters to SQL

**Frontend:**

- Setting up Next.js 14 with the App Router in the Nx workspace
- Shadcn UI initialization
- Apollo Client setup
- Writing GraphQL queries and mutations
- Building the todo list component with real data

---

## 1. DTOs — The API Contract

DTOs (Data Transfer Objects) define the shape of data at the API boundary. They are separate from entities because the API contract and the database schema are different concerns:

- The entity is the DB schema — it has all columns, FKs, internal fields
- The DTO is the API shape — it exposes only what clients should see

```
Client request → InputDTO → (validated, transformed) → Service → Entity → Database
Database → Entity → (mapped) → OutputDTO → Client response
```

### 1.1 Output DTO (`@ObjectType`)

The `@ObjectType` DTO defines what GraphQL returns to clients.

```typescript
// apps/api/src/modules/todo/dto/todo.dto.ts
import { Field, Int, ObjectType } from "@nestjs/graphql";
import { FilterableField } from "@ptc-org/nestjs-query-graphql";
import { AbstractDto } from "nestjs-dev-utilities";
import { TodoStatus } from "../todo.constant";

@ObjectType("Todo") // ← 'Todo' is the name in the GraphQL schema
export class TodoDto extends AbstractDto {
  // AbstractDto provides: id (Int!), createdAt (DateTime!), updatedAt (DateTime!)

  @FilterableField() // ← clients can filter by text: { text: { like: "%milk%" } }
  text: string;

  @FilterableField() // ← clients can filter by isChecked: { isChecked: { is: true } }
  isChecked: boolean;

  @FilterableField(() => TodoStatus) // ← clients can filter by status
  status: TodoStatus;

  // userId is NOT exposed as a @Field — it's an internal column
  // Clients should not be able to filter todos by arbitrary userId
  // Security: exposing userId enables enumeration of other users' data
}
```

**`@Field` vs `@FilterableField`:**

| Decorator            | What it does                                                                                                                          | When to use                                                                     |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `@Field()`           | Exposes the field in GraphQL responses. Clients can request it but cannot filter by it.                                               | Fields that are returned but shouldn't be filterable (e.g., color, description) |
| `@FilterableField()` | Exposes the field AND registers it with nestjs-query's filter system. Clients can use it in `filter: { fieldName: { eq: "value" } }`. | Fields you want to support filtering on                                         |

> **Security rule:** Only add `@FilterableField` to columns you explicitly support filtering on. Never add it to internal columns like `password`, `twoFactorSecret`, or FK IDs that expose data from other tenants.

### 1.2 Input DTOs (`@InputType`)

Input DTOs define what clients send in mutations. `class-validator` decorators enforce validation before the resolver method runs.

```typescript
// apps/api/src/modules/todo/dto/todo.input.ts
import { Field, InputType, Int } from "@nestjs/graphql";
import {
  IsBoolean,
  IsEnum,
  IsInt,
  IsNotEmpty,
  IsOptional,
  IsString,
  MaxLength,
} from "class-validator";
import { TodoStatus } from "../todo.constant";

@InputType()
export class CreateTodoInput {
  @Field()
  @IsString()
  @IsNotEmpty({ message: "Todo text cannot be empty" })
  @MaxLength(500, { message: "Todo text cannot exceed 500 characters" })
  text: string;

  // Part 07: userId removed from @Field and injected from JWT instead
  @Field(() => Int)
  @IsInt()
  userId: number;
}

@InputType()
export class UpdateTodoInput {
  @Field({ nullable: true })
  @IsOptional()
  @IsString()
  @IsNotEmpty()
  @MaxLength(500)
  text?: string;

  @Field({ nullable: true })
  @IsOptional()
  @IsBoolean()
  isChecked?: boolean;

  @Field(() => TodoStatus, { nullable: true })
  @IsOptional()
  @IsEnum(TodoStatus)
  status?: TodoStatus;
}
```

> **Note: `userId` is a `@Field()` for now — Part 07 fixes this.**
>
> In production, exposing `userId` as a client-supplied field is a security risk: a malicious client could send `userId: 999` and create todos that appear to belong to another user. Part 07 adds JWT authentication — at that point `userId` is removed from `@Field()` and injected server-side from the verified token instead. For this part, the endpoints are public and `userId` is passed explicitly so you can test without auth.

### 1.3 Query Args DTO (`@ArgsType`)

For list queries with filtering, sorting, and pagination, `nestjs-query` generates a complete filter/sort/pagination argument type automatically:

```typescript
// apps/api/src/modules/todo/dto/todo.query.ts
import { ArgsType } from "@nestjs/graphql";
import { SortDirection } from "@ptc-org/nestjs-query-core";
import { PagingStrategies, QueryArgsType } from "@ptc-org/nestjs-query-graphql";
import { TodoDto } from "./todo.dto";

@ArgsType()
export class TodosQuery extends QueryArgsType(TodoDto, {
  defaultSort: [{ field: "createdAt", direction: SortDirection.DESC }],
  pagingStrategy: PagingStrategies.CURSOR, // Relay cursor pagination
  enableTotalCount: true,
}) {}

// This exports the Connection type for use in the resolver return type
export const TodoQueryConnection = TodosQuery.ConnectionType;
```

`QueryArgsType(TodoDto)` auto-generates a GraphQL argument type that includes:

- `filter: TodoFilter` — filter by any `@FilterableField` (nested AND/OR, operators: eq, like, in, between, gt, lt...)
- `sorting: [TodoSort!]` — sort by any `@FilterableField`, ASC or DESC
- `paging: CursorPaging` — cursor-based pagination (first, after, last, before)

This means you get **free filtering, sorting, and pagination** on every list query — with zero extra code.

---

## 2. Cursor Pagination vs Offset Pagination

The query above uses `PagingStrategies.CURSOR`. This is important to understand.

### Offset Pagination (the Meteor/SQL beginner way)

```sql
SELECT * FROM todo WHERE user_id = 1 ORDER BY created_at DESC LIMIT 10 OFFSET 100;
```

The database must scan and discard 100 rows before returning the next 10. On 10 million rows, page 1000 scans 10,000 rows. Gets exponentially slower as you go deeper.

### Cursor Pagination (the enterprise way)

```sql
SELECT * FROM todo WHERE user_id = 1 AND created_at < '2024-01-15T10:00:00Z'
ORDER BY created_at DESC LIMIT 10;
```

The database uses the index to jump directly to the cursor position. Constant cost regardless of how deep into the list you are.

The Relay cursor response shape:

```graphql
{
  getTodos {
    totalCount # total matching records
    edges {
      cursor # opaque string encoding this record's position
      node {
        id
        text
        isChecked
      }
    }
    pageInfo {
      hasNextPage
      hasPreviousPage
      startCursor
      endCursor
    }
  }
}
```

To get the next page, pass `endCursor` as `after`:

```graphql
{
  getTodos(paging: { first: 10, after: "eyJpZCI6MTB9" }) {
    edges {
      node {
        id
        text
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
```

---

## 3. The Resolver

The resolver is the GraphQL entry point — the Meteor Method and Publication combined into one class, but separated into `@Query` (reads) and `@Mutation` (writes).

> **Part 06 vs Part 07:** This resolver has no auth guards. All endpoints are publicly accessible. Part 07 adds JWT authentication: `@UseGuards(AuthJwtGuard)` is added to protected queries/mutations, `@CurrentUser()` replaces the explicit `userId` input field, and per-user data isolation is enforced via userId filters.

```typescript
// apps/api/src/modules/todo/todo.resolver.ts
import { Args, Int, Mutation, Query, Resolver } from "@nestjs/graphql";
import { CommandBus, QueryBus } from "@nestjs/cqrs";

import { TodoDto } from "./dto/todo.dto";
import { CreateTodoInput, UpdateTodoInput } from "./dto/todo.input";
import { TodosQuery, TodoQueryConnection } from "./dto/todo.query";
import {
  CountTodoQuery,
  CreateOneTodoCommand,
  DeleteOneTodoCommand,
  FindManyTodoQuery,
  FindOneTodoQuery,
  UpdateOneTodoCommand,
} from "./cqrs";

@Resolver(() => TodoDto)
export class TodoResolver {
  constructor(
    private readonly queryBus: QueryBus,
    private readonly commandBus: CommandBus
  ) {}

  // ── Queries (reads) ─────────────────────────────────────────────

  @Query(() => TodoDto, { nullable: true })
  async todo(
    @Args("id", { type: () => Int }) id: number
  ): Promise<TodoDto | null> {
    const { data } = await this.queryBus.execute(
      new FindOneTodoQuery({ query: { filter: { id: { eq: id } } } })
    );
    return data as TodoDto;
  }

  @Query(() => TodoQueryConnection)
  async getTodos(@Args() query: TodosQuery) {
    return TodoQueryConnection.createFromPromise(
      async q => {
        const { data } = await this.queryBus.execute(
          new FindManyTodoQuery({ query: q })
        );
        return data as TodoDto[];
      },
      query,
      async filter => {
        const { data: count } = await this.queryBus.execute(
          new CountTodoQuery({ query: filter })
        );
        return count as number;
      }
    );
  }

  // ── Mutations (writes) ──────────────────────────────────────────

  @Mutation(() => TodoDto)
  async createTodo(@Args("input") input: CreateTodoInput): Promise<TodoDto> {
    const { data } = await this.commandBus.execute(
      new CreateOneTodoCommand({ input })
    );
    return data as TodoDto;
  }

  @Mutation(() => TodoDto)
  async updateTodo(
    @Args("id", { type: () => Int }) id: number,
    @Args("input") input: UpdateTodoInput
  ): Promise<TodoDto> {
    const { data } = await this.commandBus.execute(
      new UpdateOneTodoCommand({
        query: { filter: { id: { eq: id } } },
        input,
      })
    );
    return data.updated as TodoDto;
  }

  @Mutation(() => Boolean)
  async deleteTodo(
    @Args("id", { type: () => Int }) id: number
  ): Promise<boolean> {
    await this.commandBus.execute(new DeleteOneTodoCommand({ input: id }));
    return true;
  }
}
```

**What Part 07 changes in `updateTodo`:**

After auth is added, the filter will be:

```typescript
query: { filter: { id: { eq: id }, userId: { eq: currentUser.user.id } } }
```

The `userId` filter is included alongside `id`. If a malicious user sends `id: 999` (another user's todo), the database query is `WHERE id = 999 AND user_id = <their user id>` — which returns nothing. The update silently finds no record and fails safe.

---

## 4. FilterQueryBuilder

`FilterQueryBuilder` from `@ptc-org/nestjs-query-typeorm` translates GraphQL filter objects into TypeORM query builder calls:

```typescript
// A GraphQL filter:
const graphqlFilter = {
  filter: {
    and: [{ status: { eq: "ACTIVE" } }, { text: { like: "%milk%" } }],
  },
  sorting: [{ field: "createdAt", direction: "DESC" }],
};

// FilterQueryBuilder translates this to:
// SELECT * FROM todo
// WHERE status = 'ACTIVE'
//   AND text ILIKE '%milk%'
// ORDER BY created_at DESC
```

You instantiate it in the service constructor:

```typescript
this.filterQueryBuilder = new FilterQueryBuilder<TodoEntity>(this.repo);

// Then use it:
const builder = this.filterQueryBuilder.select(query); // query = { filter, sorting }
const results = await builder.getMany();
const single = await builder.getOne();
```

The `select(query)` method handles all the filter/sort translation automatically. You never write `queryBuilder.where('text LIKE :text', { text })` by hand.

---

## 5. Frontend — Next.js Setup

With the backend GraphQL API in place, you now build the frontend that consumes it.

### 5.1 Verify Next.js App Exists

From the Nx workspace root, `apps/web` should already exist from Part 02. If not:

```bash
npx nx g @nx/next:app apps/web --src=true --appDir=true --style=tailwind
```

### 5.2 Install Frontend Dependencies

```bash
# From workspace root:
yarn add @apollo/client graphql@16
yarn add --dev @graphql-codegen/cli@5 @graphql-codegen/typescript @graphql-codegen/typescript-operations @graphql-codegen/typescript-react-apollo
```

### 5.3 Initialize Shadcn UI (Nx Monorepo)

> **Nx gotcha:** `apps/web` has no `package.json` — deps are managed at the workspace root. Running `npx shadcn init` directly from `apps/web` detects no `package.json` and scaffolds a brand-new standalone Next.js project inside it. Do not do this.

The correct approach is four manual steps.

**Step 1 — Install runtime deps at the workspace root:**

```bash
# From workspace root:
yarn add @base-ui/react class-variance-authority clsx lucide-react tailwind-merge
```

**Step 2 — Create `apps/web/components.json`:**

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "base-nova",
  "rsc": true,
  "tsx": true,
  "tailwind": {
    "config": "",
    "css": "src/app/global.css",
    "baseColor": "neutral",
    "cssVariables": true,
    "prefix": ""
  },
  "iconLibrary": "lucide",
  "rtl": false,
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  }
}
```

**Step 3 — Add `@/*` path alias to `apps/web/tsconfig.json`:**

```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  }
}
```

**Step 4 — Generate components via a temp subdir, then transplant:**

Shadcn's CLI needs a `package.json` to install deps. The trick: let it scaffold inside `apps/web`, generate all components at once, copy the source files to `src/`, then delete the temp folder.

```bash
cd apps/web
npx shadcn@latest init -d          # creates apps/web/enterprise-todo-ui/
cd enterprise-todo-ui
npx shadcn@latest add button input card checkbox badge
cd ..

# Copy component source files into the real Nx app
mkdir -p src/components/ui src/lib src/hooks
cp enterprise-todo-ui/components/ui/*.tsx src/components/ui/
cp enterprise-todo-ui/lib/utils.ts src/lib/utils.ts

# Delete the temp scaffold
rm -rf enterprise-todo-ui
cd ../..  # back to workspace root
```

You now have `apps/web/src/components/ui/` with button, input, card, checkbox, and badge. These are **your** components — you own the code and can customize them freely. Unlike traditional component libraries, Shadcn ships source code, not compiled packages.

> **Meteor analogy:** Instead of PicoCSS providing global semantic styles, Shadcn gives you pre-built accessible component primitives (Button, Input, Card, Checkbox) built on Base UI primitives, styled with Tailwind. You compose them to build your UI.

---

## 6. Apollo Client Setup

```typescript
// apps/web/src/lib/apollo-client.ts
import {
  ApolloClient,
  InMemoryCache,
  createHttpLink,
  from,
} from "@apollo/client";
import { onError } from "@apollo/client/link/error";

const httpLink = createHttpLink({
  uri: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:3333/graphql",
});

// Log errors in development
const errorLink = onError(({ graphQLErrors, networkError }) => {
  if (process.env.NODE_ENV === "development") {
    graphQLErrors?.forEach(({ message, locations, path }) =>
      console.error(`GraphQL error: ${message}`, { locations, path })
    );
    if (networkError) console.error("Network error:", networkError);
  }
});

// Part 07: adds an authLink that reads localStorage.getItem('accessToken')
// and injects Authorization: Bearer <token> into every request

export const apolloClient = new ApolloClient({
  link: from([errorLink, httpLink]),
  cache: new InMemoryCache({
    typePolicies: {
      Query: {
        fields: {
          getTodos: {
            // Merge paginated results into a single list
            keyArgs: ["filter", "sorting"],
            merge(existing, incoming) {
              return {
                ...incoming,
                edges: [...(existing?.edges ?? []), ...(incoming?.edges ?? [])],
              };
            },
          },
        },
      },
    },
  }),
});
```

### 6.1 Apollo Provider

Wrap your root layout in the Apollo provider:

```typescript
// apps/web/src/app/providers.tsx
'use client';

import { ApolloProvider } from '@apollo/client';
import { apolloClient } from '../lib/apollo-client';

export function Providers({ children }: { children: React.ReactNode }) {
  return <ApolloProvider client={apolloClient}>{children}</ApolloProvider>;
}
```

```typescript
// apps/web/src/app/layout.tsx
import { Providers } from './providers';

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
```

---

## 7. GraphQL Operations (Frontend)

Define your queries and mutations as typed constants. With GraphQL Code Generator (configured below), these generate TypeScript types automatically.

```typescript
// apps/web/src/graphql/todo.operations.ts
import { gql } from "@apollo/client";

export const GET_TODOS = gql`
  query GetTodos(
    $filter: TodoFilter
    $paging: CursorPaging
    $sorting: [TodoSort!]
  ) {
    getTodos(filter: $filter, paging: $paging, sorting: $sorting) {
      totalCount
      edges {
        cursor
        node {
          id
          text
          isChecked
          status
          createdAt
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
`;

// Part 07: userId removed from CreateTodoInput (injected from JWT instead)
export const CREATE_TODO = gql`
  mutation CreateTodo($input: CreateTodoInput!) {
    createTodo(input: $input) {
      id
      text
      isChecked
      status
      createdAt
    }
  }
`;

export const UPDATE_TODO = gql`
  mutation UpdateTodo($id: Int!, $input: UpdateTodoInput!) {
    updateTodo(id: $id, input: $input) {
      id
      text
      isChecked
      status
      updatedAt
    }
  }
`;

export const DELETE_TODO = gql`
  mutation DeleteTodo($id: Int!) {
    deleteTodo(id: $id)
  }
`;
```

---

## 8. The Todo List Component

```typescript
// apps/web/src/components/todo-list.tsx
'use client';

import { useState } from 'react';
import { useMutation, useQuery } from '@apollo/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import {
  CREATE_TODO,
  DELETE_TODO,
  GET_TODOS,
  UPDATE_TODO,
} from '../graphql/todo.operations';

export function TodoList() {
  const [newTodoText, setNewTodoText] = useState('');

  // Fetch todos with Apollo useQuery
  // Meteor equivalent: useTracker(() => TasksCollection.find().fetch())
  const { data, loading, error } = useQuery(GET_TODOS, {
    variables: {
      filter: { status: { eq: 'ACTIVE' } },
      sorting: [{ field: 'createdAt', direction: 'DESC' }],
      paging: { first: 20 },
    },
    fetchPolicy: 'cache-and-network',
  });

  // Create mutation
  // Meteor equivalent: Meteor.callAsync('createTask', text)
  const [createTodo, { loading: creating }] = useMutation(CREATE_TODO, {
    refetchQueries: [{ query: GET_TODOS }],  // refetch list after mutation
    onError: (error) => console.error('Create failed:', error.message),
  });

  // Toggle completion
  const [updateTodo] = useMutation(UPDATE_TODO, {
    optimisticResponse: ({ id, input }) => ({
      updateTodo: { __typename: 'Todo', id, ...input },
    }),
  });

  // Delete
  const [deleteTodo] = useMutation(DELETE_TODO, {
    refetchQueries: [{ query: GET_TODOS }],
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTodoText.trim()) return;
    // Part 07: userId comes from JWT — hardcoded to 1 for Part 06 demo
    await createTodo({ variables: { input: { text: newTodoText.trim(), userId: 1 } } });
    setNewTodoText('');
  };

  const handleToggle = async (id: number, isChecked: boolean) => {
    await updateTodo({ variables: { id, input: { isChecked: !isChecked } } });
  };

  const handleDelete = async (id: number) => {
    await deleteTodo({ variables: { id } });
  };

  const todos = data?.getTodos?.edges?.map((edge: any) => edge.node) ?? [];
  const totalCount = data?.getTodos?.totalCount ?? 0;

  if (loading && !data) return <div className="text-center p-8">Loading...</div>;
  if (error) return <div className="text-center p-8 text-red-500">Error: {error.message}</div>;

  return (
    <Card className="w-full max-w-md mx-auto shadow-lg">
      <CardHeader>
        <CardTitle className="text-2xl font-bold text-center">
          Enterprise Todo
        </CardTitle>
        <p className="text-sm text-center text-muted-foreground">
          {totalCount} todo{totalCount !== 1 ? 's' : ''}
        </p>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Add new todo form */}
        <form onSubmit={handleSubmit} className="flex gap-2">
          <Input
            value={newTodoText}
            onChange={(e) => setNewTodoText(e.target.value)}
            placeholder="What needs to be done?"
            disabled={creating}
            className="flex-1"
          />
          <Button type="submit" disabled={creating || !newTodoText.trim()}>
            {creating ? 'Adding...' : 'Add'}
          </Button>
        </form>

        {/* Todo list */}
        <div className="space-y-2">
          {todos.length === 0 && (
            <p className="text-center text-muted-foreground py-4">
              No todos yet. Add one above.
            </p>
          )}

          {todos.map((todo: any) => (
            <div
              key={todo.id}
              className="flex items-center gap-3 p-3 rounded-lg border bg-card"
            >
              {/* Checkbox — toggles isChecked via mutation */}
              <Checkbox
                id={`todo-${todo.id}`}
                checked={todo.isChecked}
                onCheckedChange={() => handleToggle(todo.id, todo.isChecked)}
              />

              {/* Todo text */}
              <label
                htmlFor={`todo-${todo.id}`}
                className={`flex-1 text-sm cursor-pointer ${
                  todo.isChecked ? 'line-through text-muted-foreground' : ''
                }`}
              >
                {todo.text}
              </label>

              {/* Status badge */}
              <Badge variant={todo.isChecked ? 'secondary' : 'default'}>
                {todo.isChecked ? 'Done' : 'Active'}
              </Badge>

              {/* Delete button */}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handleDelete(todo.id)}
                className="text-destructive hover:text-destructive"
              >
                ×
              </Button>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
```

### 8.1 Main Page

```typescript
// apps/web/src/app/page.tsx
import { TodoList } from '../components/todo-list';

export default function HomePage() {
  return (
    <main className="min-h-screen bg-background p-8">
      <TodoList />
    </main>
  );
}
```

---

## 9. GraphQL Code Generation (Type Safety)

TypeScript types for your GraphQL operations are generated automatically from the schema.

Create `codegen.ts` at the workspace root:

```typescript
// codegen.ts
import type { CodegenConfig } from "@graphql-codegen/cli";

const config: CodegenConfig = {
  schema: "http://localhost:3333/graphql", // fetch schema from running server
  documents: ["apps/web/src/**/*.ts", "apps/web/src/**/*.tsx"],
  generates: {
    "apps/web/src/graphql/generated.ts": {
      plugins: [
        "typescript",
        "typescript-operations",
        "typescript-react-apollo",
      ],
      config: {
        withHooks: true, // generate useQuery/useMutation hooks
        withComponent: false,
        withHOC: false,
      },
    },
  },
};

export default config;
```

Add a script to `package.json`:

```json
{
  "scripts": {
    "codegen": "graphql-codegen --config codegen.ts"
  }
}
```

Run code generation (with the API running):

```bash
yarn codegen
```

This generates `apps/web/src/graphql/generated.ts` with:

- TypeScript types for every GraphQL type
- Typed `useGetTodosQuery()`, `useCreateTodoMutation()` hooks
- Full autocomplete in your IDE

Then import from generated:

```typescript
// Before code generation:
const { data } = useQuery(GET_TODOS);
data?.getTodos?.edges?.[0]?.node?.text; // TypeScript: any

// After code generation:
import { useGetTodosQuery } from '../graphql/generated';
const { data } = useGetTodosQuery({ variables: { ... } });
data?.getTodos?.edges?.[0]?.node?.text; // TypeScript: string ← fully typed!
```

---

## 10. Running the Full Stack

Start both the backend and frontend:

```bash
# Terminal 1: start the NestJS backend
yarn api:dev

# Terminal 2: start the Next.js frontend
cd apps/web && npx next dev --port 4200
# Or via Nx: npx nx serve web
```

Open:

- `http://localhost:3333/graphql` — GraphQL Playground (backend)
- `http://localhost:4200` — Next.js app (frontend)

### GraphQL Playground Smoke Test

No auth header needed for Part 06 — all endpoints are public. Open `http://localhost:3333/graphql` and run each step in order. Note the `id` returned in step 1 and use it in steps 3–4.

**Step 1 — Create** (verifies mutation + input validation + service business rule)

```graphql
mutation {
  createTodo(input: { text: "Buy milk", userId: 1 }) {
    id
    text
    isChecked
    status
    createdAt
  }
}
```

Expected: `{ id: 1, text: "Buy milk", isChecked: false, status: "ACTIVE", createdAt: "..." }`

---

**Step 2 — Query list** (verifies cursor pagination, `ConnectionType`, `totalCount`)

```graphql
query {
  getTodos(
    sorting: [{ field: createdAt, direction: DESC }]
    paging: { first: 10 }
  ) {
    totalCount
    edges {
      node {
        id
        text
        isChecked
        status
        createdAt
      }
      cursor
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
```

Expected: `totalCount: 1`, one edge with the todo from step 1, `hasNextPage: false`.

---

**Step 3 — Update** (verifies mutation + `FilterQueryBuilder` ownership filter)

```graphql
mutation {
  updateTodo(id: 1, input: { isChecked: true }) {
    id
    isChecked
    updatedAt
  }
}
```

Expected: `{ id: 1, isChecked: true, updatedAt: "..." }` (timestamp newer than `createdAt`).

---

**Step 4 — Delete** (verifies Boolean scalar mutation)

```graphql
mutation DeleteTodo {
  deleteTodo(id: 1)
}
```

Expected: `{ "data": { "deleteTodo": true } }`

> **Apollo Sandbox quirk:** `deleteTodo` returns `Boolean` (a scalar, not an object). Apollo Studio Sandbox sometimes rejects anonymous scalar-return mutations with a spurious "syntax error: invalid number" error. Naming the operation (`mutation DeleteTodo { ... }`) fixes it. If the Sandbox still misbehaves, verify directly with curl:
>
> ```bash
> curl -s -X POST http://localhost:3333/graphql \
>   -H "Content-Type: application/json" \
>   -d '{"query":"mutation { deleteTodo(id: 1) }"}'
> # → {"data":{"deleteTodo":true}}
> ```

---

**Step 5 — Filter** (verifies `@FilterableField` wiring and `FilterQueryBuilder` SQL translation)

Re-create a todo first (the one from step 1 was deleted), then:

```graphql
mutation {
  createTodo(input: { text: "Filter test todo", userId: 1 }) {
    id
    status
  }
}
```

```graphql
query {
  getTodos(
    filter: { status: { eq: ACTIVE } }
    sorting: [{ field: createdAt, direction: DESC }]
    paging: { first: 10 }
  ) {
    totalCount
    edges {
      node {
        id
        text
        status
      }
    }
  }
}
```

Expected: only todos with `status: ACTIVE` are returned. If you also create one with `status: ARCHIVED`, it should be excluded.

---

All five steps passing means the resolver, DTOs, `FilterQueryBuilder`, cursor pagination, and `ConnectionType` are all correctly wired. The backend is ready for the Next.js frontend.

> **What Part 07 changes here:** `createTodo` will drop `userId` from the input (injected from JWT), and `getTodos` will only return the authenticated user's todos. The Playground will require an `Authorization: Bearer <token>` header.

---

## 11. Architecture Review

Here is how the frontend and backend communicate:

```
┌────────────────────────────────────────────┐
│  Next.js (apps/web, :4200)                 │
│                                            │
│  Apollo useQuery(GET_TODOS)                │
│    └── POST http://localhost:3333/graphql  │
│         { query: "...", variables: {...} } │
└────────────────────────────────────────────┘
              ↕ HTTP/GraphQL
┌────────────────────────────────────────────┐
│  NestJS (apps/api, :3333)                  │
│                                            │
│  Apollo Server                             │
│  └── TodoResolver.getTodos()               │
│       └── QueryBus → Handler → Service     │
│            └── TypeORM → PostgreSQL        │
└────────────────────────────────────────────┘
```

**There is no DDP.** There is no Minimongo. There is no reactive data sync. The frontend explicitly fetches data when it needs it (`useQuery`) and explicitly triggers writes (`useMutation`). Apollo Client caches results and `refetchQueries` triggers re-fetches after mutations.

This is less magical than Meteor's reactive subscriptions — and far more predictable, scalable, and debuggable.

---

## Summary

**Backend GraphQL:**

| Concept                    | Decorator/Tool                     | Meteor equivalent           |
| -------------------------- | ---------------------------------- | --------------------------- |
| Return type                | `@ObjectType()`                    | Minimongo document shape    |
| Input type                 | `@InputType()`                     | Method argument             |
| Filterable field           | `@FilterableField()`               | Minimongo query key         |
| List query with pagination | `QueryArgsType` + `ConnectionType` | `find()` cursor             |
| Cursor pagination          | `PagingStrategies.CURSOR`          | No equivalent               |
| SQL filter translation     | `FilterQueryBuilder`               | Minimongo's query operators |
| Auth guard (Part 07)       | `@UseGuards(AuthJwtGuard)`         | `Meteor.userId()` check     |

**Frontend:**

| Concept       | Tool                       | Meteor equivalent                     |
| ------------- | -------------------------- | ------------------------------------- |
| Data fetching | `useQuery(GET_TODOS)`      | `useTracker(() => Collection.find())` |
| Mutations     | `useMutation(CREATE_TODO)` | `Meteor.callAsync('method', data)`    |
| Client cache  | Apollo InMemoryCache       | Minimongo                             |
| Type safety   | GraphQL Code Generator     | None (Meteor was untyped)             |
| UI components | Shadcn UI + Tailwind       | PicoCSS global styles                 |
