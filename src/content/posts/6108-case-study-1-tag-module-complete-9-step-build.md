---
author: Kai
pubDatetime: 2026-05-08T09:00:00+08:00
title: Case Study 1 - Tag Module (Complete 9-Step Build)
featured: false
draft: false
slug: 6108-case-study-1-tag-module-complete-9-step-build
tags:
  - deeptech
  - meteorjs
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/08-case-study-1-tag-module-complete-9-step-build.png"
description: By the end of this part, you follow every step of the 9-step pattern with nothing skipped — from empty directory to running GraphQL queries in the Playground, with unit tests passing. This is your first complete module build from scratch.

---

## What This Part Covers

This is your first complete module build from scratch. You will follow every step of the 9-step pattern with nothing skipped — from empty directory to running GraphQL queries in the Playground, with unit tests passing.

**Why Tags?** A Tag is the simplest possible entity: no foreign keys, no auth complexity on reads, straightforward CRUD. It is the perfect pattern exercise before you tackle entities with relationships and ownership rules.

**What you build:**
- Tags that label content (e.g., "work", "personal", "urgent")
- Public read (anyone can query tags)
- Auth-required write (only logged-in users can create/update/delete)
- Paginated list with filtering and sorting
- Full unit tests

---

## Design Phase (Always First)

Before writing a single file, answer three questions. This is the system design habit that separates senior developers from juniors.

### Q1: What does the DB table look like?

```
tag
├── id          SERIAL PRIMARY KEY       (from AbstractEntity)
├── name        VARCHAR NOT NULL
├── slug        VARCHAR NOT NULL UNIQUE  (url-safe identifier)
├── color       VARCHAR NOT NULL DEFAULT '#6366f1'
├── created_at  TIMESTAMPTZ              (from AbstractEntity)
└── updated_at  TIMESTAMPTZ              (from AbstractEntity)
```

### Q2: What GraphQL operations will we expose?

```graphql
# Public reads — no auth required
query tag(id: Int!): Tag
query getTags(filter: TagFilter, paging: CursorPaging, sorting: [TagSort!]): TagConnection!

# Auth-required writes
mutation createTag(input: CreateTagInput!): Tag!
mutation updateTag(id: Int!, input: UpdateTagInput!): Tag!
mutation deleteTag(id: Int!): Boolean!
```

### Q3: Which existing module is this most like?

The `notification` module from the codebase: simple entity, same service pattern, same CQRS structure. Use it as your mental reference.

---

## Step 1 — Create the Feature Branch

```bash
git checkout main
git pull
git checkout -b feat/tag-module
```

---

## Step 2 — Create the File Structure

```bash
mkdir -p apps/api/src/modules/tag/cqrs
mkdir -p apps/api/src/modules/tag/dto
mkdir -p apps/api/src/modules/tag/test
```

Files you will create:

```
apps/api/src/modules/tag/
├── cqrs/
│   ├── index.ts                  ← exports handler arrays + re-exports inputs
│   ├── tag.cqrs.handler.ts       ← all handlers (thin delegation)
│   └── tag.cqrs.input.ts         ← typed Command and Query classes
├── dto/
│   ├── tag.dto.ts                ← @ObjectType — GraphQL response shape
│   ├── tag.input.ts              ← @InputType — mutation inputs
│   └── tag.query.ts              ← @ArgsType — list query args + connection
├── test/
│   ├── tag.service.spec.ts       ← unit test for TagService
│   └── tag.cqrs.spec.ts          ← unit test for handlers
├── tag.constant.ts               ← enums + registerEnumType
├── tag.entity.ts                 ← TypeORM entity
├── tag.module.ts                 ← NestJS module
├── tag.resolver.ts               ← GraphQL resolver
└── tag.service.ts                ← business logic
```

---

## Step 3 — Entity (`tag.entity.ts`)

The entity is the source of truth for the database schema.

```typescript
// apps/api/src/modules/tag/tag.entity.ts
import { Column, Entity } from 'typeorm';
import { AbstractEntity } from 'nestjs-dev-utilities';

@Entity({ name: 'tag' })
export class TagEntity extends AbstractEntity {
  @Column()
  name: string;

  @Column({ unique: true })
  slug: string;

  @Column({ default: '#6366f1' })
  color: string;
}
```

**What `AbstractEntity` gives you:**
- `id: number` — `SERIAL PRIMARY KEY`
- `createdAt: Date` — `created_at TIMESTAMPTZ DEFAULT now()` (hardcoded column name)
- `updatedAt: Date` — `updated_at TIMESTAMPTZ DEFAULT now()` (auto-updated on save)

Your entity only declares the *additional* columns. The `slug` column has `unique: true` — PostgreSQL will enforce that no two tags share the same slug (e.g., `'work'` can only exist once).

---

## Step 4 — Constants (`tag.constant.ts`)

Tags do not need a complex status enum, but we add one to demonstrate the pattern:

```typescript
// apps/api/src/modules/tag/tag.constant.ts
import { registerEnumType } from '@nestjs/graphql';

export enum TagStatus {
  ACTIVE = 'ACTIVE',
  ARCHIVED = 'ARCHIVED',
}

// Tell GraphQL about this enum — without this, the schema won't include it
registerEnumType(TagStatus, { name: 'TagStatus' });
```

> **Pattern:** Always call `registerEnumType` immediately after defining an enum that will appear in a `@Field`. Missing this call produces a cryptic runtime error when Apollo starts.

---

## Step 5 — DTOs

### Read DTO (`tag.dto.ts`) — what GraphQL sends back

```typescript
// apps/api/src/modules/tag/dto/tag.dto.ts
import { Field, ObjectType } from '@nestjs/graphql';
import { FilterableField } from '@ptc-org/nestjs-query-graphql';
import { AbstractDto } from 'nestjs-dev-utilities';

@ObjectType('Tag')
export class TagDto extends AbstractDto {
  // AbstractDto provides: id (Int!), createdAt, updatedAt

  @FilterableField()   // clients CAN filter: { name: { like: "%work%" } }
  name: string;

  @FilterableField()   // clients CAN filter: { slug: { eq: "work" } }
  slug: string;

  @Field()             // clients CANNOT filter by color — only returned in response
  color: string;
}
```

**Why `@Field()` for color instead of `@FilterableField()`?**
Filtering by color has no business value and would allow clients to enumerate tags by color. Only add `@FilterableField` to fields with real filter use cases.

### Input DTOs (`tag.input.ts`) — what clients send

```typescript
// apps/api/src/modules/tag/dto/tag.input.ts
import { Field, InputType } from '@nestjs/graphql';
import { IsHexColor, IsNotEmpty, IsString, Matches } from 'class-validator';

@InputType()
export class CreateTagInput {
  @Field()
  @IsString()
  @IsNotEmpty({ message: 'Tag name cannot be empty' })
  name: string;

  @Field()
  @IsString()
  @IsNotEmpty()
  @Matches(/^[a-z0-9-]+$/, {
    message: 'Slug must contain only lowercase letters, numbers, and hyphens',
  })
  slug: string;

  @Field({ nullable: true, defaultValue: '#6366f1' })
  @IsHexColor({ message: 'Color must be a valid hex color (e.g. #6366f1)' })
  color?: string;
}

@InputType()
export class UpdateTagInput {
  @Field({ nullable: true })
  @IsString()
  @IsNotEmpty()
  name?: string;

  @Field({ nullable: true })
  @IsString()
  @Matches(/^[a-z0-9-]+$/)
  slug?: string;

  @Field({ nullable: true })
  @IsHexColor()
  color?: string;
}
```

> **Why not `PartialType(CreateTagInput)` for UpdateTagInput?**
> `PartialType` makes all fields optional but keeps them. In the pattern used here, explicit `UpdateTagInput` fields let you add update-specific validation (e.g., slug change requires admin role) without affecting the create path. Both approaches are valid — choose consistency within your project.

### Query Args DTO (`tag.query.ts`) — list query with pagination

```typescript
// apps/api/src/modules/tag/dto/tag.query.ts
import { ArgsType } from '@nestjs/graphql';
import { SortDirection } from '@ptc-org/nestjs-query-core';
import { PagingStrategies, QueryArgsType } from '@ptc-org/nestjs-query-graphql';
import { TagDto } from './tag.dto';

@ArgsType()
export class TagsQuery extends QueryArgsType(TagDto, {
  defaultSort: [{ field: 'createdAt', direction: SortDirection.DESC }],
  pagingStrategy: PagingStrategies.CURSOR,
  enableTotalCount: true,
}) {}

export const TagQueryConnection = TagsQuery.ConnectionType;
```

`QueryArgsType(TagDto)` automatically generates the `TagFilter`, `TagSort`, and pagination args. The `ConnectionType` generates the `TagConnection` response type with `edges`, `pageInfo`, and `totalCount`.

---

## Step 6 — CQRS Inputs (`cqrs/tag.cqrs.input.ts`)

Typed message classes — the envelopes you put data into before dispatching to the bus.

```typescript
// apps/api/src/modules/tag/cqrs/tag.cqrs.input.ts
import { Query } from '@ptc-org/nestjs-query-core';
import {
  AbstractCqrsCommandInput,
  AbstractCqrsQueryInput,
  RecordMutateOptions,
  RecordQueryWithJoinOptions,
} from 'nestjs-typed-cqrs';

import { CreateTagInput, UpdateTagInput } from '../dto/tag.input';
import { TagEntity } from '../tag.entity';

// ── Queries ─────────────────────────────────────────────────

export class FindOneTagQuery extends AbstractCqrsQueryInput<
  TagEntity,
  undefined,
  RecordQueryWithJoinOptions,
  TagEntity        // returns one entity (or null)
> {}

export class FindManyTagQuery extends AbstractCqrsQueryInput<
  TagEntity,
  undefined,
  RecordQueryWithJoinOptions,
  TagEntity[]      // returns an array
> {}

export class CountTagQuery extends AbstractCqrsQueryInput<
  TagEntity,
  Query<TagEntity>['filter'],
  undefined,
  number           // returns a count
> {}

// ── Commands ─────────────────────────────────────────────────

export class CreateOneTagCommand extends AbstractCqrsCommandInput<
  TagEntity,
  CreateTagInput
> {}

export class UpdateOneTagCommand extends AbstractCqrsCommandInput<
  TagEntity,
  UpdateTagInput,
  true,              // isUpdateOne = true (has query + input)
  RecordMutateOptions,
  { before: TagEntity; updated: TagEntity }
> {}

export class DeleteOneTagCommand extends AbstractCqrsCommandInput<
  TagEntity,
  number             // input is just the id
> {}
```

---

## Step 7 — CQRS Index (`cqrs/index.ts`)

```typescript
// apps/api/src/modules/tag/cqrs/index.ts
import {
  CountTagQueryHandler,
  CreateOneTagCommandHandler,
  DeleteOneTagCommandHandler,
  FindManyTagQueryHandler,
  FindOneTagQueryHandler,
  UpdateOneTagCommandHandler,
} from './tag.cqrs.handler';

export const TagQueryHandlers = [
  FindOneTagQueryHandler,
  FindManyTagQueryHandler,
  CountTagQueryHandler,
];

export const TagCommandHandlers = [
  CreateOneTagCommandHandler,
  UpdateOneTagCommandHandler,
  DeleteOneTagCommandHandler,
];

export const TagEventHandlers = [];

// Re-export inputs — other files import from './cqrs' (one path)
export * from './tag.cqrs.input';
```

---

## Step 8 — CQRS Handlers (`cqrs/tag.cqrs.handler.ts`)

Always one line. No logic.

```typescript
// apps/api/src/modules/tag/cqrs/tag.cqrs.handler.ts
import { CommandHandler, IInferredCommandHandler, IInferredQueryHandler, QueryHandler } from '@nestjs/cqrs';
import { CommandResult, QueryResult } from '@nestjs-architects/typed-cqrs';
import { TagService } from '../tag.service';
import {
  CountTagQuery,
  CreateOneTagCommand,
  DeleteOneTagCommand,
  FindManyTagQuery,
  FindOneTagQuery,
  UpdateOneTagCommand,
} from './tag.cqrs.input';

@QueryHandler(FindOneTagQuery)
export class FindOneTagQueryHandler implements IInferredQueryHandler<FindOneTagQuery> {
  constructor(readonly service: TagService) {}
  async execute(query: FindOneTagQuery): Promise<QueryResult<FindOneTagQuery>> {
    return this.service.findOne(query.args);
  }
}

@QueryHandler(FindManyTagQuery)
export class FindManyTagQueryHandler implements IInferredQueryHandler<FindManyTagQuery> {
  constructor(readonly service: TagService) {}
  async execute(query: FindManyTagQuery): Promise<QueryResult<FindManyTagQuery>> {
    return this.service.findMany(query.args);
  }
}

@QueryHandler(CountTagQuery)
export class CountTagQueryHandler implements IInferredQueryHandler<CountTagQuery> {
  constructor(readonly service: TagService) {}
  async execute(query: CountTagQuery): Promise<QueryResult<CountTagQuery>> {
    return this.service.count(query.args);
  }
}

@CommandHandler(CreateOneTagCommand)
export class CreateOneTagCommandHandler implements IInferredCommandHandler<CreateOneTagCommand> {
  constructor(readonly service: TagService) {}
  async execute(command: CreateOneTagCommand): Promise<CommandResult<CreateOneTagCommand>> {
    return this.service.createOne(command.args);
  }
}

@CommandHandler(UpdateOneTagCommand)
export class UpdateOneTagCommandHandler implements IInferredCommandHandler<UpdateOneTagCommand> {
  constructor(readonly service: TagService) {}
  async execute(command: UpdateOneTagCommand): Promise<CommandResult<UpdateOneTagCommand>> {
    return this.service.updateOne(command.args);
  }
}

@CommandHandler(DeleteOneTagCommand)
export class DeleteOneTagCommandHandler implements IInferredCommandHandler<DeleteOneTagCommand> {
  constructor(readonly service: TagService) {}
  async execute(command: DeleteOneTagCommand): Promise<CommandResult<DeleteOneTagCommand>> {
    return this.service.deleteOne(command.args);
  }
}
```

Notice: every handler body is identical in structure. `this.service.methodName(query.args)` — that's it. The handler is a message router, nothing more.

---

## Step 9 — Service (`tag.service.ts`)

This is where all business logic lives.

```typescript
// apps/api/src/modules/tag/tag.service.ts
import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { InjectQueryService, QueryService } from '@ptc-org/nestjs-query-core';
import { FilterQueryBuilder } from '@ptc-org/nestjs-query-typeorm/src/query';
import { CqrsCommandFunc, CqrsQueryFunc } from 'nestjs-typed-cqrs';
import { Repository } from 'typeorm';

import {
  CountTagQuery,
  CreateOneTagCommand,
  DeleteOneTagCommand,
  FindManyTagQuery,
  FindOneTagQuery,
  UpdateOneTagCommand,
} from './cqrs/tag.cqrs.input';
import { TagEntity } from './tag.entity';

@Injectable()
export class TagService {
  private readonly filterQueryBuilder: FilterQueryBuilder<TagEntity>;

  constructor(
    @InjectRepository(TagEntity)
    private readonly repo: Repository<TagEntity>,
    @InjectQueryService(TagEntity)
    private readonly queryService: QueryService<TagEntity>,
  ) {
    this.filterQueryBuilder = new FilterQueryBuilder<TagEntity>(this.repo);
  }

  findOne: CqrsQueryFunc<FindOneTagQuery, FindOneTagQuery['args']> = async ({ query, options }) => {
    const nullable = options?.nullable ?? true;
    try {
      const result = await this.filterQueryBuilder.select(query).getOne();
      if (!nullable && !result) throw new Error('Tag not found');
      return { success: true, data: result };
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };

  findMany: CqrsQueryFunc<FindManyTagQuery, FindManyTagQuery['args']> = async ({ query }) => {
    try {
      const results = await this.filterQueryBuilder.select(query).getMany();
      return { success: true, data: results };
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };

  count: CqrsQueryFunc<CountTagQuery, CountTagQuery['args']> = async ({ query }) => {
    try {
      return this.repo.count({ where: query as any });
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };

  createOne: CqrsCommandFunc<CreateOneTagCommand, CreateOneTagCommand['args']> = async ({ input }) => {
    try {
      // Business rule: slug must be unique
      const existing = await this.repo.findOne({ where: { slug: input.slug } });
      if (existing) throw new Error(`A tag with slug "${input.slug}" already exists`);

      const tag = this.repo.create(input);
      const data = await this.repo.save(tag);
      return { success: true, data };
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };

  updateOne: CqrsCommandFunc<UpdateOneTagCommand, UpdateOneTagCommand['args']> = async ({ query, input }) => {
    try {
      const before = await this.filterQueryBuilder.select(query).getOne();
      if (!before) throw new NotFoundException('Tag not found');

      // If slug is being changed, check uniqueness
      if (input.slug && input.slug !== before.slug) {
        const slugTaken = await this.repo.findOne({ where: { slug: input.slug } });
        if (slugTaken) throw new Error(`Slug "${input.slug}" is already taken`);
      }

      const updated = await this.repo.save({ ...before, ...input });
      return { success: true, data: { before, updated } };
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };

  deleteOne: CqrsCommandFunc<DeleteOneTagCommand, DeleteOneTagCommand['args']> = async ({ input: id }) => {
    try {
      const tag = await this.repo.findOne({ where: { id } });
      if (!tag) throw new NotFoundException('Tag not found');
      await this.repo.remove(tag);
      return { success: true, data: id };
    } catch (e) {
      throw new BadRequestException(e.message);
    }
  };
}
```

---

## Step 10 — Resolver (`tag.resolver.ts`)

```typescript
// apps/api/src/modules/tag/tag.resolver.ts
import { Args, Int, Mutation, Query, Resolver } from '@nestjs/graphql';
import { UseGuards } from '@nestjs/common';
import { CommandBus, QueryBus } from '@nestjs/cqrs';

import { TagDto } from './dto/tag.dto';
import { CreateTagInput, UpdateTagInput } from './dto/tag.input';
import { TagQueryConnection, TagsQuery } from './dto/tag.query';
import { AuthJwtGuard } from '../auth/guards/auth-jwt.guard';
import {
  CountTagQuery,
  CreateOneTagCommand,
  DeleteOneTagCommand,
  FindManyTagQuery,
  FindOneTagQuery,
  UpdateOneTagCommand,
} from './cqrs';

@Resolver(() => TagDto)
export class TagResolver {
  constructor(
    private readonly queryBus: QueryBus,
    private readonly commandBus: CommandBus,
  ) {}

  // Public — no auth needed to read tags
  @Query(() => TagDto, { nullable: true })
  async tag(@Args('id', { type: () => Int }) id: number): Promise<TagDto | null> {
    const { data } = await this.queryBus.execute(
      new FindOneTagQuery({ query: { filter: { id: { eq: id } } } }),
    );
    return data as TagDto;
  }

  // Public list — paginated with automatic filtering and sorting
  @Query(() => TagQueryConnection)
  async getTags(@Args() query: TagsQuery) {
    return TagQueryConnection.createFromPromise(
      async (q) => {
        const { data } = await this.queryBus.execute(new FindManyTagQuery({ query: q }));
        return data as TagDto[];
      },
      query,
      async (filter) => {
        const count = await this.queryBus.execute(new CountTagQuery({ query: filter }));
        return count as number;
      },
    );
  }

  // Auth required — only logged-in users can create tags
  @UseGuards(AuthJwtGuard)
  @Mutation(() => TagDto)
  async createTag(@Args('input') input: CreateTagInput): Promise<TagDto> {
    const { data } = await this.commandBus.execute(new CreateOneTagCommand({ input }));
    return data as TagDto;
  }

  // Auth required — only logged-in users can update tags
  @UseGuards(AuthJwtGuard)
  @Mutation(() => TagDto)
  async updateTag(
    @Args('id', { type: () => Int }) id: number,
    @Args('input') input: UpdateTagInput,
  ): Promise<TagDto> {
    const { data } = await this.commandBus.execute(
      new UpdateOneTagCommand({ query: { filter: { id: { eq: id } } }, input }),
    );
    return data.updated as TagDto;
  }

  // Auth required — only logged-in users can delete tags
  @UseGuards(AuthJwtGuard)
  @Mutation(() => Boolean)
  async deleteTag(@Args('id', { type: () => Int }) id: number): Promise<boolean> {
    await this.commandBus.execute(new DeleteOneTagCommand({ input: id }));
    return true;
  }
}
```

---

## Step 11 — Module (`tag.module.ts`)

```typescript
// apps/api/src/modules/tag/tag.module.ts
import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { NestjsQueryTypeOrmModule } from '@ptc-org/nestjs-query-typeorm';

import { TagEntity } from './tag.entity';
import { TagResolver } from './tag.resolver';
import { TagService } from './tag.service';
import { TagCommandHandlers, TagEventHandlers, TagQueryHandlers } from './cqrs';

@Module({
  imports: [
    // CqrsModule is NOT imported here — it is registered globally via CqrsModule.forRoot() in AppModule
    TypeOrmModule.forFeature([TagEntity]),
    NestjsQueryTypeOrmModule.forFeature([TagEntity]),
  ],
  providers: [
    TagResolver,
    TagService,
    ...TagQueryHandlers,
    ...TagCommandHandlers,
    ...TagEventHandlers,
  ],
  exports: [TagService],
})
export class TagModule {}
```

---

## Step 12 — Register in AppModule

```typescript
// apps/api/src/app/app.module.ts — add to imports and entities
import { TagModule } from '../modules/tag/tag.module';
import { TagEntity } from '../modules/tag/tag.entity';

@Module({
  imports: [
    TypeOrmModule.forRootAsync({
      useFactory: (config: ConfigService) => ({
        entities: [
          TagEntity,   // ← add here
          // ... UserEntity, etc.
        ],
      }),
    }),
    TagModule,         // ← add here
    // ...
  ],
})
export class AppModule {}
```

---

## Step 13 — Migration

```bash
# Generate migration from entity diff
yarn api:migration:generate --name=create-tag-table
```

Review the generated file at `apps/api/src/migrations/<timestamp>-create-tag-table.ts`:

```typescript
// Expected generated SQL (verify this):
async up(queryRunner: QueryRunner): Promise<void> {
  await queryRunner.query(`
    CREATE TABLE "tag" (
      "id"         SERIAL NOT NULL,
      "name"       character varying NOT NULL,
      "slug"       character varying NOT NULL,
      "color"      character varying NOT NULL DEFAULT '#6366f1',
      "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
      "updated_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
      CONSTRAINT "UQ_tag_slug" UNIQUE ("slug"),
      CONSTRAINT "PK_tag" PRIMARY KEY ("id")
    )
  `);
}

async down(queryRunner: QueryRunner): Promise<void> {
  await queryRunner.query(`DROP TABLE "tag"`);
}
```

Check that:
- `slug` has a `UNIQUE` constraint
- `color` has the right default value
- `created_at` and `updated_at` are present (from `AbstractEntity`)

Run the migration:

```bash
yarn api:migration:run
```

Verify in Adminer (`http://localhost:8080`): the `tag` table should now exist with the correct columns.

---

## Step 14 — Smoke Test in GraphQL Playground

Start the server:

```bash
yarn api:dev
```

Open `http://localhost:3333/graphql`. First, get an auth token (for write operations):

```graphql
mutation {
  signIn(input: { username: "testuser", password: "Secret123!" }) {
    accessToken
  }
}
```

Set the Authorization header in Playground HTTP Headers tab:
```json
{ "Authorization": "Bearer <paste_access_token>" }
```

**Create a tag:**

```graphql
mutation {
  createTag(input: { name: "Work", slug: "work", color: "#3b82f6" }) {
    id
    name
    slug
    color
    createdAt
  }
}
```

**Create more tags:**

```graphql
mutation { createTag(input: { name: "Personal", slug: "personal" }) { id name } }
mutation { createTag(input: { name: "Urgent", slug: "urgent", color: "#ef4444" }) { id name } }
```

**Query the paginated list with filter:**

```graphql
query {
  getTags(
    filter: { name: { like: "%%" } }
    sorting: [{ field: createdAt, direction: DESC }]
    paging: { first: 10 }
  ) {
    totalCount
    edges {
      node { id name slug color createdAt }
      cursor
    }
    pageInfo { hasNextPage endCursor }
  }
}
```

**Update a tag:**

```graphql
mutation {
  updateTag(id: 1, input: { name: "Work Tasks", color: "#2563eb" }) {
    id
    name
    color
    updatedAt
  }
}
```

**Delete a tag:**

```graphql
mutation {
  deleteTag(id: 3)
}
```

**Try creating a tag without auth (should fail):**

Remove the Authorization header, then:

```graphql
mutation {
  createTag(input: { name: "Should fail", slug: "fail" }) { id }
}
```

Expected: `{ "errors": [{ "message": "Unauthorized" }] }`

---

## Step 15 — Unit Tests

Unit tests verify your business logic in isolation — no database, no HTTP, no NestJS app bootstrap.

### Service Unit Test (`test/tag.service.spec.ts`)

```typescript
// apps/api/src/modules/tag/test/tag.service.spec.ts
import { BadRequestException } from '@nestjs/common';
import { Test, TestingModule } from '@nestjs/testing';
import { getRepositoryToken } from '@nestjs/typeorm';
import { getQueryServiceToken } from '@ptc-org/nestjs-query-core';

import { TagEntity } from '../tag.entity';
import { TagService } from '../tag.service';

// Mock the TypeORM repository
const mockRepo = {
  findOne: jest.fn(),
  create: jest.fn(),
  save: jest.fn(),
  remove: jest.fn(),
  count: jest.fn(),
  createQueryBuilder: jest.fn().mockReturnValue({
    where: jest.fn().mockReturnThis(),
    getOne: jest.fn(),
    getMany: jest.fn(),
  }),
};

// Mock the nestjs-query QueryService
const mockQueryService = {};

describe('TagService', () => {
  let service: TagService;

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      providers: [
        TagService,
        { provide: getRepositoryToken(TagEntity), useValue: mockRepo },
        { provide: getQueryServiceToken(TagEntity), useValue: mockQueryService },
      ],
    }).compile();

    service = module.get<TagService>(TagService);

    // Reset all mocks before each test
    jest.clearAllMocks();
  });

  describe('createOne', () => {
    it('should create and return a new tag', async () => {
      const input = { name: 'Work', slug: 'work', color: '#3b82f6' };
      const savedTag: Partial<TagEntity> = { id: 1, ...input, createdAt: new Date(), updatedAt: new Date() };

      mockRepo.findOne.mockResolvedValue(null);  // no existing tag with this slug
      mockRepo.create.mockReturnValue(input);
      mockRepo.save.mockResolvedValue(savedTag);

      const result = await service.createOne({ input });

      expect(result.success).toBe(true);
      expect(result.data).toEqual(savedTag);
      expect(mockRepo.findOne).toHaveBeenCalledWith({ where: { slug: 'work' } });
      expect(mockRepo.save).toHaveBeenCalledWith(input);
    });

    it('should throw BadRequestException when slug already exists', async () => {
      const input = { name: 'Work', slug: 'work' };
      mockRepo.findOne.mockResolvedValue({ id: 1, slug: 'work' });  // slug taken

      await expect(service.createOne({ input })).rejects.toThrow(BadRequestException);
      expect(mockRepo.save).not.toHaveBeenCalled();
    });

    it('should throw BadRequestException when name is empty', async () => {
      const input = { name: '', slug: 'work' };
      mockRepo.findOne.mockResolvedValue(null);
      // The service would delegate to the repo and throw
      mockRepo.save.mockRejectedValue(new Error('violates not-null constraint'));

      await expect(service.createOne({ input })).rejects.toThrow(BadRequestException);
    });
  });

  describe('deleteOne', () => {
    it('should delete an existing tag', async () => {
      const tag: Partial<TagEntity> = { id: 1, name: 'Work', slug: 'work' };
      mockRepo.findOne.mockResolvedValue(tag);
      mockRepo.remove.mockResolvedValue(tag);

      const result = await service.deleteOne({ input: 1 });

      expect(result.success).toBe(true);
      expect(mockRepo.remove).toHaveBeenCalledWith(tag);
    });

    it('should throw BadRequestException when tag not found', async () => {
      mockRepo.findOne.mockResolvedValue(null);

      await expect(service.deleteOne({ input: 999 })).rejects.toThrow(BadRequestException);
      expect(mockRepo.remove).not.toHaveBeenCalled();
    });
  });
});
```

### Handler Unit Test (`test/tag.cqrs.spec.ts`)

```typescript
// apps/api/src/modules/tag/test/tag.cqrs.spec.ts
import { CreateOneTagCommandHandler, FindOneTagQueryHandler } from '../cqrs/tag.cqrs.handler';
import { CreateOneTagCommand, FindOneTagQuery } from '../cqrs/tag.cqrs.input';
import { TagService } from '../tag.service';

// Mock the entire TagService
const mockService: Partial<TagService> = {
  findOne: jest.fn(),
  createOne: jest.fn(),
};

describe('Tag CQRS Handlers', () => {
  let findOneHandler: FindOneTagQueryHandler;
  let createOneHandler: CreateOneTagCommandHandler;

  beforeEach(() => {
    jest.clearAllMocks();
    findOneHandler = new FindOneTagQueryHandler(mockService as TagService);
    createOneHandler = new CreateOneTagCommandHandler(mockService as TagService);
  });

  describe('FindOneTagQueryHandler', () => {
    it('should delegate to service.findOne with query.args', async () => {
      const expectedResult = { success: true, data: { id: 1, name: 'Work' } };
      (mockService.findOne as jest.Mock).mockResolvedValue(expectedResult);

      const query = new FindOneTagQuery({ query: { filter: { id: { eq: 1 } } } });
      const result = await findOneHandler.execute(query);

      expect(mockService.findOne).toHaveBeenCalledWith(query.args);
      expect(result).toEqual(expectedResult);
    });
  });

  describe('CreateOneTagCommandHandler', () => {
    it('should delegate to service.createOne with command.args', async () => {
      const input = { name: 'Work', slug: 'work' };
      const expectedResult = { success: true, data: { id: 1, ...input } };
      (mockService.createOne as jest.Mock).mockResolvedValue(expectedResult);

      const command = new CreateOneTagCommand({ input });
      const result = await createOneHandler.execute(command);

      expect(mockService.createOne).toHaveBeenCalledWith(command.args);
      expect(result).toEqual(expectedResult);
    });

    // This test proves the thin handler rule: handler should NOT contain logic
    it('handler body should be exactly one line (delegate to service)', () => {
      // The handler's execute method source code
      const handlerSource = createOneHandler.execute.toString();
      // It should contain exactly one "return this.service" call
      const serviceCallCount = (handlerSource.match(/this\.service\./g) || []).length;
      expect(serviceCallCount).toBe(1);
    });
  });
});
```

### Run Tests

```bash
yarn api:test
```

Expected output:
```
PASS apps/api/src/modules/tag/test/tag.service.spec.ts
  TagService
    createOne
      ✓ should create and return a new tag (5ms)
      ✓ should throw BadRequestException when slug already exists (2ms)
      ✓ should throw BadRequestException when name is empty (1ms)
    deleteOne
      ✓ should delete an existing tag (1ms)
      ✓ should throw BadRequestException when tag not found (1ms)

PASS apps/api/src/modules/tag/test/tag.cqrs.spec.ts
  Tag CQRS Handlers
    FindOneTagQueryHandler
      ✓ should delegate to service.findOne with query.args (2ms)
    CreateOneTagCommandHandler
      ✓ should delegate to service.createOne with command.args (1ms)
      ✓ handler body should be exactly one line (1ms)
```

---

## Step 16 — Commit

```bash
# Stage all new files
git add apps/api/src/modules/tag/
git add apps/api/src/migrations/*-create-tag-table.ts
git add apps/api/src/app/app.module.ts

# Conventional commit via Commitizen
yarn cz
```

In the Commitizen interactive menu:
- Type: `feat`
- Scope: `tag`
- Short description: `add tag module with CRUD GraphQL API`
- Breaking change: `N`
- Issues: leave blank or link ticket

Resulting commit: `feat(tag): add tag module with CRUD GraphQL API`

Husky runs before the commit:
- ESLint checks all staged `.ts` files
- Prettier formats staged files
- commitlint validates the commit message format

If lint fails: `yarn lint:fix` → re-`git add` → `yarn cz`

---

## Complete File Checklist

```
[✅] tag.entity.ts            — extends AbstractEntity, slug UNIQUE
[✅] tag.constant.ts          — TagStatus enum + registerEnumType
[✅] dto/tag.dto.ts           — @ObjectType, @FilterableField on name/slug
[✅] dto/tag.input.ts         — CreateTagInput, UpdateTagInput with class-validator
[✅] dto/tag.query.ts         — TagsQuery + TagQueryConnection (cursor pagination)
[✅] cqrs/tag.cqrs.input.ts   — Find/Count queries, Create/Update/Delete commands
[✅] cqrs/tag.cqrs.handler.ts — All handlers, all one-liners
[✅] cqrs/index.ts            — Handler arrays + re-export inputs
[✅] tag.service.ts           — Business logic: slug uniqueness, findOne/Many/count/create/update/delete
[✅] tag.resolver.ts          — Public reads, auth-required writes
[✅] tag.module.ts            — TypeOrmModule + NestjsQueryTypeOrmModule (no CqrsModule — buses are global)
[✅] AppModule updated        — TagEntity in entities[], TagModule in imports[]
[✅] Migration generated      — create-tag-table
[✅] Migration reviewed       — checked SQL for correctness
[✅] Migration run            — yarn api:migration:run
[✅] Adminer verified         — tag table exists with correct schema
[✅] Playground tested        — create, list, update, delete all work
[✅] Playground auth test     — unauthorized write returns 401
[✅] Unit tests passing       — service + handler specs green
[✅] Committed                — conventional commit via yarn cz
```

---

## Summary

You have built a complete enterprise module from scratch. The pattern you followed:

```
Entity → Constants → DTOs → CQRS Inputs → CQRS Index →
CQRS Handlers → Service → Resolver → Module → Register → Migrate → Test → Commit
```

Every file has one job. Every business rule is in the service. Every handler is a one-liner. The GraphQL API is self-documenting, auto-filters, and cursor-paginates.

In Part 09, you will build the Todo module — which adds foreign keys, auth ownership enforcement, and the DataLoader pattern for resolving related entities without N+1 queries.
