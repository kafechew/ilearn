---
author: Kai
pubDatetime: 2026-05-12T09:00:00+08:00
title: Testing - Unit + E2E
featured: false
draft: false
slug: 6112-testing-unit-e2e
tags:
  - deeptech
  - meteorjs
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/12-testing-unit-e2e.png"
description: By the end of this part, you will learn the enterprise testing philosophy, Unit tests, mock TypeORM correctly, E2E tests and run tests in CI. 

---

## What This Part Covers

- The enterprise testing philosophy: what to test at each layer
- Unit tests: service logic, handler delegation, mock patterns
- `getRepositoryToken` and `getQueryServiceToken` — how to mock TypeORM correctly
- E2E tests: why a real database is required
- Global setup and teardown for E2E
- Writing a complete E2E test suite for the Tag and Todo APIs
- Running tests in CI

---

## Meteor Equivalent

Meteor's testing story was fragmented — Velocity, practicalmeteor:mocha, chimp. Tests were slow (required a running Meteor server), hard to isolate (global `Meteor` object everywhere), and rarely comprehensive.

In this stack:

| Test type | Tool | Runs in | Speed |
|-----------|------|---------|-------|
| Unit | Jest | Node only — no NestJS bootstrap | ~50ms per file |
| E2E | Jest + real NestJS app | Full NestJS server + PostgreSQL | ~2-5s per suite |

---

## 1. The Testing Philosophy

### What to test at each layer

```
Resolver ─── NOT unit-tested as a unit
              The resolver is thin: extract args, call bus, return DTO.
              No business logic → nothing to verify in isolation.
              Covered by E2E tests.

Handler  ─── Thin handlers deserve thin tests
              Verify: does execute() call the right service method with query.args?
              Nothing more.

Service  ─── Most important unit to test
              All business logic lives here.
              Test: happy path, error cases, edge cases.
              Mock the repository — never hit a real DB in unit tests.

E2E      ─── Full stack, real database
              Test the complete HTTP request → DB → response cycle.
              Catches: TypeORM query bugs, migration mismatches,
              FK violations, auth guard integration.
```

### The Golden Rule for Unit Tests

> **Two kinds of truth:** Unit tests verify one doctor's diagnostic decisions in a mock clinic — no real patients, no real equipment, just the decision logic under controlled conditions. E2E tests run the full clinic with real patients: real building, real reception desk, real lab equipment (PostgreSQL), real pharmacy (Redis). The unit test catches the wrong diagnosis. The E2E test catches the broken door that prevents the patient from reaching the doctor at all.

**Test your code, not the framework.**

Don't test:
- That NestJS injects dependencies correctly (the framework does this)
- That TypeORM's `save()` saves to the DB (TypeORM does this)
- That `class-validator` validates `@IsString()` (the library does this)

Do test:
- Your business rule: "throw if slug already exists"
- Your service logic: "set userId from input, not from the JWT in the service"
- Your handler: "delegates to service.findOne with the correct args"

---

## 2. Unit Test Setup

NestJS's `Test.createTestingModule()` creates a minimal DI container with only what you register — no HTTP server, no database, no real dependencies unless you add them.

```typescript
const module: TestingModule = await Test.createTestingModule({
  providers: [
    TagService,                                              // ← the class under test
    { provide: getRepositoryToken(TagEntity), useValue: mockRepo },  // ← mock repository
    { provide: getQueryServiceToken(TagEntity), useValue: {} },      // ← mock query service
  ],
}).compile();

const service = module.get<TagService>(TagService);
```

> **The staffing agency in test mode:** `Test.createTestingModule()` is the staffing agency in test mode. Instead of the real `UserRepository` (which needs a database), the agency sends a stand-in — a `jest.fn()` mock that returns whatever you tell it to. The class under test (`TagService`) never knows the difference. It receives what looks like a repository, calls its methods, and your assertions verify the decisions made with those responses.

**Why `getRepositoryToken(TagEntity)` instead of `Repository<TagEntity>`?**

NestJS registers the TypeORM repository under a generated token (not the class itself). `getRepositoryToken(TagEntity)` returns that token. Using it ensures your `provide` key matches what `@InjectRepository(TagEntity)` expects.

---

## 3. Complete Service Unit Test — TagService

```typescript
// apps/api/src/modules/tag/test/tag.service.spec.ts
import { BadRequestException, NotFoundException } from '@nestjs/common';
import { Test, TestingModule } from '@nestjs/testing';
import { getRepositoryToken } from '@nestjs/typeorm';
import { getQueryServiceToken } from '@ptc-org/nestjs-query-core';
import { TagEntity } from '../tag.entity';
import { TagService } from '../tag.service';

// ── Mock factory helpers ─────────────────────────────────────────

const makeTag = (overrides: Partial<TagEntity> = {}): TagEntity =>
  ({
    id: 1,
    name: 'Work',
    slug: 'work',
    color: '#3b82f6',
    createdAt: new Date('2024-01-01'),
    updatedAt: new Date('2024-01-01'),
    ...overrides,
  } as TagEntity);

const mockRepo = {
  findOne: jest.fn(),
  create: jest.fn(),
  save: jest.fn(),
  remove: jest.fn(),
  count: jest.fn(),
};

// ── Test suite ───────────────────────────────────────────────────

describe('TagService', () => {
  let service: TagService;

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      providers: [
        TagService,
        { provide: getRepositoryToken(TagEntity), useValue: mockRepo },
        { provide: getQueryServiceToken(TagEntity), useValue: {} },
      ],
    }).compile();

    service = module.get<TagService>(TagService);
    jest.clearAllMocks();
  });

  // ── createOne ──────────────────────────────────────────────────

  describe('createOne', () => {
    const input = { name: 'Work', slug: 'work', color: '#3b82f6' };

    it('creates and returns a new tag when slug is unique', async () => {
      const savedTag = makeTag();
      mockRepo.findOne.mockResolvedValue(null);   // slug not taken
      mockRepo.create.mockReturnValue(input);
      mockRepo.save.mockResolvedValue(savedTag);

      const { success, data } = await service.createOne({ input });

      expect(success).toBe(true);
      expect(data).toEqual(savedTag);
      expect(mockRepo.findOne).toHaveBeenCalledWith({ where: { slug: 'work' } });
      expect(mockRepo.create).toHaveBeenCalledWith(input);
      expect(mockRepo.save).toHaveBeenCalledWith(input);
    });

    it('throws BadRequestException when slug already exists', async () => {
      mockRepo.findOne.mockResolvedValue(makeTag());  // slug is taken

      await expect(service.createOne({ input })).rejects.toThrow(BadRequestException);
      await expect(service.createOne({ input })).rejects.toThrow(
        'A tag with slug "work" already exists',
      );
      expect(mockRepo.save).not.toHaveBeenCalled();
    });
  });

  // ── updateOne ──────────────────────────────────────────────────

  describe('updateOne', () => {
    it('updates name and returns before/updated pair', async () => {
      const before = makeTag({ name: 'Work' });
      const updated = makeTag({ name: 'Work Tasks' });

      // filterQueryBuilder.select(query).getOne() — mock the chain
      const mockBuilder = { getOne: jest.fn().mockResolvedValue(before) };
      jest.spyOn(service['filterQueryBuilder'], 'select').mockReturnValue(mockBuilder as any);
      mockRepo.save.mockResolvedValue(updated);

      const { success, data } = await service.updateOne({
        query: { filter: { id: { eq: 1 } } },
        input: { name: 'Work Tasks' },
      });

      expect(success).toBe(true);
      expect(data.before).toEqual(before);
      expect(data.updated).toEqual(updated);
      expect(mockRepo.save).toHaveBeenCalledWith({ ...before, name: 'Work Tasks' });
    });

    it('throws when tag not found', async () => {
      const mockBuilder = { getOne: jest.fn().mockResolvedValue(null) };
      jest.spyOn(service['filterQueryBuilder'], 'select').mockReturnValue(mockBuilder as any);

      await expect(
        service.updateOne({ query: { filter: { id: { eq: 999 } } }, input: { name: 'X' } }),
      ).rejects.toThrow(BadRequestException);
      expect(mockRepo.save).not.toHaveBeenCalled();
    });

    it('throws when new slug is already taken by another tag', async () => {
      const current = makeTag({ id: 1, slug: 'work' });
      const conflicting = makeTag({ id: 2, slug: 'personal' });

      const mockBuilder = { getOne: jest.fn().mockResolvedValue(current) };
      jest.spyOn(service['filterQueryBuilder'], 'select').mockReturnValue(mockBuilder as any);
      mockRepo.findOne.mockResolvedValue(conflicting);  // slug 'personal' is taken

      await expect(
        service.updateOne({
          query: { filter: { id: { eq: 1 } } },
          input: { slug: 'personal' },
        }),
      ).rejects.toThrow(BadRequestException);
    });
  });

  // ── deleteOne ──────────────────────────────────────────────────

  describe('deleteOne', () => {
    it('removes the tag and returns its id', async () => {
      const tag = makeTag();
      mockRepo.findOne.mockResolvedValue(tag);
      mockRepo.remove.mockResolvedValue(tag);

      const { success, data } = await service.deleteOne({ input: 1 });

      expect(success).toBe(true);
      expect(data).toBe(1);
      expect(mockRepo.remove).toHaveBeenCalledWith(tag);
    });

    it('throws BadRequestException when tag not found', async () => {
      mockRepo.findOne.mockResolvedValue(null);

      await expect(service.deleteOne({ input: 999 })).rejects.toThrow(BadRequestException);
      expect(mockRepo.remove).not.toHaveBeenCalled();
    });
  });

  // ── count ──────────────────────────────────────────────────────

  describe('count', () => {
    it('returns the correct count', async () => {
      mockRepo.count.mockResolvedValue(5);

      const result = await service.count({ query: {} });
      expect(result).toBe(5);
    });
  });
});
```

---

## 4. Handler Unit Test Pattern

Handler tests verify the thin delegation rule — nothing more.

```typescript
// apps/api/src/modules/tag/test/tag.cqrs.spec.ts
import {
  CountTagQueryHandler,
  CreateOneTagCommandHandler,
  DeleteOneTagCommandHandler,
  FindManyTagQueryHandler,
  FindOneTagQueryHandler,
  UpdateOneTagCommandHandler,
} from '../cqrs/tag.cqrs.handler';
import {
  CountTagQuery,
  CreateOneTagCommand,
  DeleteOneTagCommand,
  FindManyTagQuery,
  FindOneTagQuery,
  UpdateOneTagCommand,
} from '../cqrs/tag.cqrs.input';
import { TagService } from '../tag.service';

// Create a mock for each service method
const mockService = {
  findOne: jest.fn(),
  findMany: jest.fn(),
  count: jest.fn(),
  createOne: jest.fn(),
  updateOne: jest.fn(),
  deleteOne: jest.fn(),
} as unknown as TagService;

describe('Tag CQRS Handlers', () => {
  beforeEach(() => jest.clearAllMocks());

  const cases = [
    {
      name: 'FindOneTagQueryHandler',
      HandlerClass: FindOneTagQueryHandler,
      QueryClass: FindOneTagQuery,
      serviceMethod: 'findOne',
      args: { query: { filter: { id: { eq: 1 } } } },
    },
    {
      name: 'FindManyTagQueryHandler',
      HandlerClass: FindManyTagQueryHandler,
      QueryClass: FindManyTagQuery,
      serviceMethod: 'findMany',
      args: { query: {} },
    },
    {
      name: 'CountTagQueryHandler',
      HandlerClass: CountTagQueryHandler,
      QueryClass: CountTagQuery,
      serviceMethod: 'count',
      args: { query: {} },
    },
    {
      name: 'CreateOneTagCommandHandler',
      HandlerClass: CreateOneTagCommandHandler,
      QueryClass: CreateOneTagCommand,
      serviceMethod: 'createOne',
      args: { input: { name: 'Work', slug: 'work' } },
    },
    {
      name: 'UpdateOneTagCommandHandler',
      HandlerClass: UpdateOneTagCommandHandler,
      QueryClass: UpdateOneTagCommand,
      serviceMethod: 'updateOne',
      args: { query: { filter: { id: { eq: 1 } } }, input: { name: 'New Name' } },
    },
    {
      name: 'DeleteOneTagCommandHandler',
      HandlerClass: DeleteOneTagCommandHandler,
      QueryClass: DeleteOneTagCommand,
      serviceMethod: 'deleteOne',
      args: { input: 1 },
    },
  ];

  cases.forEach(({ name, HandlerClass, QueryClass, serviceMethod, args }) => {
    describe(name, () => {
      it(`delegates to service.${serviceMethod}(message.args) and returns the result`, async () => {
        const expectedResult = { success: true, data: {} };
        (mockService[serviceMethod as keyof TagService] as jest.Mock).mockResolvedValue(expectedResult);

        const handler = new (HandlerClass as any)(mockService);
        const message = new (QueryClass as any)(args);
        const result = await handler.execute(message);

        expect(mockService[serviceMethod as keyof TagService]).toHaveBeenCalledWith(message.args);
        expect(result).toEqual(expectedResult);
      });
    });
  });
});
```

---

## 5. E2E Test Setup

E2E tests use a **real NestJS application** connected to a **real test database**. They verify the complete stack — guards, pipes, bus routing, service logic, TypeORM queries, and PostgreSQL constraints — all together.

### 5.1 Global Setup

```typescript
// apps/api-e2e/src/support/global-setup.ts
import { Test } from '@nestjs/testing';
import { INestApplication, ValidationPipe } from '@nestjs/common';
import { AppModule } from '../../../apps/api/src/app/app.module';
import { DataSource } from 'typeorm';

let app: INestApplication;
let dataSource: DataSource;

export async function setup() {
  const moduleRef = await Test.createTestingModule({
    imports: [AppModule],
  }).compile();

  app = moduleRef.createNestApplication();

  // Same global pipes as main.ts — critical for accurate E2E
  app.useGlobalPipes(
    new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true }),
  );

  await app.init();

  dataSource = app.get(DataSource);

  // Expose globally for tests
  global.__APP__ = app;
  global.__DATA_SOURCE__ = dataSource;

  // Create an authenticated user and token for tests
  const authResponse = await makeRequest(app, {
    query: `mutation {
      register(input: {
        fullname: "E2E Test User"
        username: "e2etestuser"
        email: "e2e@test.com"
        password: "Secret123!"
      }) { accessToken }
    }`,
  });
  global.__TOKEN__ = authResponse.data?.register?.accessToken;
}

export async function teardown() {
  await app.close();
}

// Helper: send a GraphQL request to the test app
async function makeRequest(app: INestApplication, body: object) {
  const { default: request } = await import('supertest');
  const response = await request(app.getHttpServer())
    .post('/graphql')
    .send(body)
    .set('Content-Type', 'application/json');
  return response.body;
}
```

### 5.2 Test Database Reset

```typescript
// apps/api-e2e/src/support/reset-db.ts
import { DataSource } from 'typeorm';

export async function resetTestDb(dataSource: DataSource) {
  // Truncate in the right order (respect FK constraints)
  await dataSource.query(`
    TRUNCATE TABLE todo, tag RESTART IDENTITY CASCADE
  `);
  // Don't truncate the user table — we need the test user created in global-setup
}
```

### 5.3 Jest Configuration for E2E

```javascript
// jest.e2e.config.js
module.exports = {
  moduleFileExtensions: ['js', 'json', 'ts'],
  rootDir: '.',
  testEnvironment: 'node',
  testRegex: '.e2e-spec.ts$',
  transform: { '^.+\\.(t|j)s$': 'ts-jest' },
  globalSetup: './apps/api-e2e/src/support/global-setup.ts',
  globalTeardown: './apps/api-e2e/src/support/global-teardown.ts',
  testTimeout: 30000,  // E2E tests can be slower
};
```

---

## 6. Complete E2E Test: Tag Module

```typescript
// apps/api-e2e/src/api/tag.e2e-spec.ts
import * as request from 'supertest';

const graphql = (query: string, variables?: object, token?: string) =>
  request(global.__APP__.getHttpServer())
    .post('/graphql')
    .send({ query, variables })
    .set('Content-Type', 'application/json')
    .set('Authorization', token ? `Bearer ${token}` : '');

describe('Tag API (e2e)', () => {
  let createdTagId: number;

  beforeEach(async () => {
    await resetTestDb(global.__DATA_SOURCE__);
  });

  // ── createTag ─────────────────────────────────────────────────

  describe('createTag mutation', () => {
    it('creates a tag when authenticated', async () => {
      const response = await graphql(
        `mutation CreateTag($input: CreateTagInput!) {
           createTag(input: $input) { id name slug color createdAt }
         }`,
        { input: { name: 'Work', slug: 'work', color: '#3b82f6' } },
        global.__TOKEN__,
      );

      expect(response.status).toBe(200);
      expect(response.body.errors).toBeUndefined();

      const tag = response.body.data.createTag;
      expect(tag.id).toBeDefined();
      expect(tag.name).toBe('Work');
      expect(tag.slug).toBe('work');
      expect(tag.color).toBe('#3b82f6');
      createdTagId = tag.id;
    });

    it('returns Unauthorized when not authenticated', async () => {
      const response = await graphql(
        `mutation { createTag(input: { name: "Fail", slug: "fail" }) { id } }`,
      );
      // No token → 401
      expect(response.body.errors[0].message).toMatch(/unauthorized/i);
    });

    it('returns 400 for invalid slug format', async () => {
      const response = await graphql(
        `mutation CreateTag($input: CreateTagInput!) {
           createTag(input: $input) { id }
         }`,
        { input: { name: 'Bad Slug', slug: 'BAD SLUG!' } },
        global.__TOKEN__,
      );
      expect(response.body.errors).toBeDefined();
      expect(response.body.errors[0].message).toMatch(/slug/i);
    });

    it('returns 400 for duplicate slug', async () => {
      // Create first tag
      await graphql(
        `mutation CreateTag($input: CreateTagInput!) { createTag(input: $input) { id } }`,
        { input: { name: 'Work', slug: 'work' } },
        global.__TOKEN__,
      );

      // Try to create duplicate
      const response = await graphql(
        `mutation CreateTag($input: CreateTagInput!) { createTag(input: $input) { id } }`,
        { input: { name: 'Work 2', slug: 'work' } },  // same slug
        global.__TOKEN__,
      );
      expect(response.body.errors[0].message).toMatch(/already exists/i);
    });
  });

  // ── getTags ───────────────────────────────────────────────────

  describe('getTags query', () => {
    beforeEach(async () => {
      // Seed some tags
      for (const tag of [
        { name: 'Work', slug: 'work' },
        { name: 'Personal', slug: 'personal' },
        { name: 'Urgent', slug: 'urgent', color: '#ef4444' },
      ]) {
        await graphql(
          `mutation CreateTag($input: CreateTagInput!) { createTag(input: $input) { id } }`,
          { input: tag },
          global.__TOKEN__,
        );
      }
    });

    it('returns paginated tags without authentication', async () => {
      const response = await graphql(`
        query {
          getTags(paging: { first: 10 }) {
            totalCount
            edges { node { id name slug } cursor }
            pageInfo { hasNextPage }
          }
        }
      `);

      expect(response.body.errors).toBeUndefined();
      const { totalCount, edges } = response.body.data.getTags;
      expect(totalCount).toBe(3);
      expect(edges).toHaveLength(3);
    });

    it('filters tags by name', async () => {
      const response = await graphql(`
        query {
          getTags(filter: { name: { like: "%ork%" } }) {
            totalCount
            edges { node { name } }
          }
        }
      `);

      expect(response.body.data.getTags.totalCount).toBe(1);
      expect(response.body.data.getTags.edges[0].node.name).toBe('Work');
    });

    it('returns next page using cursor', async () => {
      const firstPage = await graphql(`
        query { getTags(paging: { first: 2 }) {
          edges { cursor node { name } }
          pageInfo { hasNextPage endCursor }
        }}
      `);

      const { hasNextPage, endCursor } = firstPage.body.data.getTags.pageInfo;
      expect(hasNextPage).toBe(true);

      const secondPage = await graphql(`
        query GetTags($after: ConnectionCursor!) {
          getTags(paging: { first: 2, after: $after }) {
            edges { node { name } }
            pageInfo { hasNextPage }
          }
        }
      `, { after: endCursor });

      expect(secondPage.body.data.getTags.edges).toHaveLength(1);
      expect(secondPage.body.data.getTags.pageInfo.hasNextPage).toBe(false);
    });
  });

  // ── updateTag ─────────────────────────────────────────────────

  describe('updateTag mutation', () => {
    it('updates a tag when authenticated', async () => {
      // Create tag
      const created = await graphql(
        `mutation CreateTag($input: CreateTagInput!) { createTag(input: $input) { id } }`,
        { input: { name: 'Work', slug: 'work' } },
        global.__TOKEN__,
      );
      const id = created.body.data.createTag.id;

      // Update
      const response = await graphql(
        `mutation UpdateTag($id: Int!, $input: UpdateTagInput!) {
           updateTag(id: $id, input: $input) { id name color updatedAt }
         }`,
        { id, input: { name: 'Work Tasks', color: '#2563eb' } },
        global.__TOKEN__,
      );

      expect(response.body.errors).toBeUndefined();
      const updated = response.body.data.updateTag;
      expect(updated.name).toBe('Work Tasks');
      expect(updated.color).toBe('#2563eb');
    });

    it('returns 400 for non-existent tag', async () => {
      const response = await graphql(
        `mutation { updateTag(id: 99999, input: { name: "X" }) { id } }`,
        {},
        global.__TOKEN__,
      );
      expect(response.body.errors[0].message).toMatch(/not found/i);
    });
  });

  // ── deleteTag ─────────────────────────────────────────────────

  describe('deleteTag mutation', () => {
    it('deletes a tag and returns true', async () => {
      const created = await graphql(
        `mutation CreateTag($input: CreateTagInput!) { createTag(input: $input) { id } }`,
        { input: { name: 'Delete Me', slug: 'delete-me' } },
        global.__TOKEN__,
      );
      const id = created.body.data.createTag.id;

      const deleteResponse = await graphql(
        `mutation DeleteTag($id: Int!) { deleteTag(id: $id) }`,
        { id },
        global.__TOKEN__,
      );
      expect(deleteResponse.body.data.deleteTag).toBe(true);

      // Verify it's gone
      const getResponse = await graphql(`query { tag(id: ${id}) { id } }`);
      expect(getResponse.body.data.tag).toBeNull();
    });
  });
});
```

---

## 7. E2E Test: Auth Guard Integration

```typescript
// apps/api-e2e/src/api/auth.e2e-spec.ts
describe('Auth (e2e)', () => {
  describe('register mutation', () => {
    it('registers a new user and returns tokens', async () => {
      const response = await graphql(`
        mutation {
          register(input: {
            fullname: "New User"
            username: "newuser123"
            email: "newuser@test.com"
            password: "Secret123!"
          }) {
            accessToken
            refreshToken
          }
        }
      `);

      expect(response.body.errors).toBeUndefined();
      expect(response.body.data.register.accessToken).toBeDefined();
      expect(response.body.data.register.refreshToken).toBeDefined();

      // Tokens should be JWT format (3 dot-separated base64 segments)
      const parts = response.body.data.register.accessToken.split('.');
      expect(parts).toHaveLength(3);
    });

    it('returns 400 for weak password', async () => {
      const response = await graphql(`
        mutation {
          register(input: {
            fullname: "User"
            username: "weakpassuser"
            email: "weak@test.com"
            password: "weak"
          }) { accessToken }
        }
      `);
      expect(response.body.errors).toBeDefined();
    });

    it('returns 400 for duplicate username', async () => {
      // e2etestuser already exists from global-setup
      const response = await graphql(`
        mutation {
          register(input: {
            fullname: "Dupe"
            username: "e2etestuser"
            email: "dupe@test.com"
            password: "Secret123!"
          }) { accessToken }
        }
      `);
      expect(response.body.errors[0].message).toMatch(/username/i);
    });
  });

  describe('me query', () => {
    it('returns current user when authenticated', async () => {
      const response = await graphql(
        `query { me { id fullname email status } }`,
        {},
        global.__TOKEN__,
      );
      expect(response.body.errors).toBeUndefined();
      expect(response.body.data.me.fullname).toBe('E2E Test User');
      expect(response.body.data.me.email).toBe('e2e@test.com');
    });

    it('returns Unauthorized without token', async () => {
      const response = await graphql(`query { me { id } }`);
      expect(response.body.errors[0].message).toMatch(/unauthorized/i);
    });
  });
});
```

---

## 8. Running Tests

```bash
# Unit tests (fast, no DB)
yarn api:test

# Unit tests with coverage
yarn api:test --coverage

# Watch mode (re-runs affected tests on file change)
yarn api:test --watch

# E2E tests (requires Docker containers running)
yarn docker:dev
yarn api:e2e

# Run a single test file
npx jest apps/api/src/modules/tag/test/tag.service.spec.ts

# Run tests matching a pattern
npx jest --testNamePattern="createOne"
```

### Expected CI Output

```
PASS apps/api/src/modules/tag/test/tag.service.spec.ts
  TagService
    createOne
      ✓ creates and returns a new tag when slug is unique (4ms)
      ✓ throws BadRequestException when slug already exists (2ms)
    updateOne
      ✓ updates name and returns before/updated pair (3ms)
      ✓ throws when tag not found (1ms)
      ✓ throws when new slug is already taken by another tag (1ms)
    deleteOne
      ✓ removes the tag and returns its id (1ms)
      ✓ throws BadRequestException when tag not found (1ms)
    count
      ✓ returns the correct count (1ms)

PASS apps/api/src/modules/tag/test/tag.cqrs.spec.ts
  Tag CQRS Handlers
    FindOneTagQueryHandler
      ✓ delegates to service.findOne(message.args) and returns the result (2ms)
    ... (all handlers pass)

PASS apps/api-e2e/src/api/tag.e2e-spec.ts
  Tag API (e2e)
    createTag mutation
      ✓ creates a tag when authenticated (312ms)
      ✓ returns Unauthorized when not authenticated (89ms)
      ✓ returns 400 for invalid slug format (95ms)
      ✓ returns 400 for duplicate slug (210ms)
    getTags query
      ✓ returns paginated tags without authentication (145ms)
      ✓ filters tags by name (98ms)
      ✓ returns next page using cursor (176ms)
    ...
```

---

## 9. Testing Checklist for Every New Module

```
Unit tests:
[✅] service.spec.ts — happy path for every public method
[✅] service.spec.ts — error case: record not found
[✅] service.spec.ts — error case: unique constraint violation
[✅] cqrs.spec.ts   — each handler delegates to correct service method
[✅] cqrs.spec.ts   — each handler passes message.args (not the full message)

E2E tests:
[✅] create — success with auth
[✅] create — 401 without auth
[✅] create — 400 for invalid input
[✅] create — 400 for business rule violation (duplicate, FK not found)
[✅] list   — paginated response shape
[✅] list   — filter works
[✅] list   — cursor pagination (second page)
[✅] update — success
[✅] update — 404 for non-existent record
[✅] delete — success, record is gone
[✅] auth   — ownership: cannot access another user's records
```

---

## Summary

| Layer | Test type | Mock strategy | When it breaks |
|-------|-----------|--------------|----------------|
| Handler | Unit | Mock `TagService` with `jest.fn()` | Handler contains logic |
| Service | Unit | Mock TypeORM repo with `jest.fn()` | Business rule regression |
| Resolver + full stack | E2E | Real NestJS app + real PostgreSQL | Auth guard broken, migration wrong, FK violated |

The key distinction:
- **Unit tests** verify logic quickly (milliseconds, no infrastructure)
- **E2E tests** verify integration (seconds, requires Docker) — catches the failures unit tests cannot
