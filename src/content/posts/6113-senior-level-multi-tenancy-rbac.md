---
author: Kai
pubDatetime: 2026-05-13T09:00:00+08:00
title: Multi-tenancy & Role-Based Access Control (RBAC)
featured: false
draft: false
slug: 6113-senior-level-multi-tenancy-rbac
tags:
  - deeptech
  - meteorjs
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/13-senior-level-multi-tenancy-rbac.png"
description: By the end of this part, you will learn multi-tenancy, tenantId pattern, TenantGuard, RBAC, Dual-auth architecture, @Authorize and promoting a module to multi-tenant.  

---

## What This Part Covers

- What multi-tenancy is and why it matters at enterprise scale
- The `tenantId` pattern: every domain entity carries a tenant FK
- `TenantGuard` and tenant context injection
- Role-Based Access Control (RBAC): roles, permissions, and the `@Authorize` decorator
- Dual-auth architecture: user JWT vs admin portal JWT
- `@Authorize` from `nestjs-query` for row-level authorization
- How the pieces compose: tenant isolation + role checks + row-level auth
- Checklist for promoting a module to multi-tenant

---

## Meteor Equivalent

Meteor had no native multi-tenancy or RBAC story. Common approaches:

| Concern | Meteor (DIY) | Enterprise NestJS |
|---------|-------------|-------------------|
| Tenant isolation | Manually add `organizationId` to every query | `tenantId` FK on entity + `TenantGuard` + handler filter |
| Row-level auth | Manual `if user._id !== doc.userId` checks | `@Authorize` decorator from `nestjs-query` |
| Roles | `alanning:roles` package | `RolesGuard` + `@Roles()` decorator |
| Admin vs user auth | Same system, different user flag | Separate JWT key pairs + `PortalAuthJwtGuard` |

The Meteor pattern scattered auth logic across Methods — easy to miss one. The NestJS pattern centralizes it in guards and decorators that compose without the developer thinking about it.

---

## 1. What is Multi-tenancy?

A multi-tenant system serves multiple independent organizations from a single running application. Each organization is a "tenant". Their data must be completely isolated — Tenant A can never see Tenant B's todos.

```
Single-tenant (traditional):              Multi-tenant:
  App ──→ Database                          App ──→ Database
  One org per deployment                    Many orgs, one deployment
  Simple but expensive to scale             Complex but cost-efficient
```

**Three strategies** (we use the simplest that's suitable for most B2B SaaS):

| Strategy | How | Best for |
|---------|-----|---------|
| Separate databases | Each tenant gets a DB | Regulatory compliance, very large tenants |
| Separate schemas | Same DB, each tenant a PostgreSQL schema | Medium tenants, simpler than separate DBs |
| Shared tables + `tenantId` | Single table, filter by column | Most B2B SaaS — simplest, cheapest |

We implement **shared tables + `tenantId`** — add a `tenantId` column to every domain entity.

---

## 2. Tenant Entity

```typescript
// apps/api/src/modules/tenant/tenant.entity.ts
import { Column, Entity, Index } from 'typeorm';
import { AbstractEntity } from 'nestjs-dev-utilities';

@Entity('tenant')
export class TenantEntity extends AbstractEntity {
  @Column({ unique: true })
  slug: string;

  @Column()
  name: string;

  @Column({ default: true })
  isActive: boolean;
}
```

---

## 3. tenantId on Every Domain Entity

Every entity that belongs to a tenant (everything except `User` and `Tenant` themselves) gets a `tenantId` FK.

```typescript
// Pattern applied to every domain entity:

@Entity('todo')
export class TodoEntity extends AbstractEntity {
  @Column()
  title: string;

  // ... other fields

  // ── Tenant FK ──────────────────────────────────────────────────
  @ManyToOne(() => TenantEntity, { onDelete: 'RESTRICT' })
  tenant: TenantEntity;

  @RelationId((todo: TodoEntity) => todo.tenant)
  @Index()                       // every WHERE tenantId = ? uses this
  @Column()
  tenantId: number;

  // ── Owner FK ───────────────────────────────────────────────────
  @ManyToOne(() => UserEntity, { onDelete: 'SET NULL' })
  user: UserEntity | null;

  @RelationId((todo: TodoEntity) => todo.user)
  @Index()
  @Column({ nullable: true })
  userId: number | null;
}
```

**`tenantId` comes from the JWT** — just like `userId`. Neither is ever accepted as a client-provided field.

---

## 4. Tenant in the JWT

When a user signs in, their JWT payload includes both `userId` and `tenantId`:

```typescript
// apps/api/src/modules/auth/auth.service.ts
async generateTokens(user: UserEntity): Promise<AuthTokensDto> {
  const payload: JwtPayload = {
    sub: user.id,
    username: user.username,
    tenantId: user.tenantId,    // always in the token
    roles: user.roles,
  };

  const accessToken = this.jwtService.sign(payload, {
    privateKey: this.config.getOrThrow('JWT_PRIVATE_KEY'),
    algorithm: 'RS256',
    expiresIn: '15m',
  });

  // ... refresh token

  return { accessToken, refreshToken };
}
```

`JwtStrategy.validate()` extracts this and attaches to `req.user`:

```typescript
async validate(payload: JwtPayload): Promise<RequestUser> {
  const user = await this.userRepo.findOne({ where: { id: payload.sub } });
  if (!user || !user.isActive) throw new UnauthorizedException();
  return { ...user, tenantId: payload.tenantId };
}
```

---

## 5. TenantGuard — Automatic Tenant Injection

The `TenantGuard` reads `tenantId` from the JWT and stores it in a request-scoped service so every handler can access it without boilerplate.

```typescript
// apps/api/src/shared/tenant.guard.ts
import { CanActivate, ExecutionContext, Injectable } from '@nestjs/common';
import { GqlExecutionContext } from '@nestjs/graphql';
import { TenantContext } from './tenant.context';

@Injectable()
export class TenantGuard implements CanActivate {
  constructor(private readonly tenantContext: TenantContext) {}

  canActivate(context: ExecutionContext): boolean {
    const ctx = GqlExecutionContext.create(context);
    const { user } = ctx.getContext().req;

    if (user?.tenantId) {
      this.tenantContext.tenantId = user.tenantId;
    }
    return true;  // doesn't reject — just sets context
  }
}
```

```typescript
// apps/api/src/shared/tenant.context.ts
import { Injectable, Scope } from '@nestjs/common';

@Injectable({ scope: Scope.REQUEST })   // must be REQUEST scope
export class TenantContext {
  tenantId: number;
}
```

Register both in `AppModule` providers. Apply `TenantGuard` globally — after `AuthJwtGuard`:

```typescript
// app.module.ts
{
  provide: APP_GUARD,
  useClass: AuthJwtGuard,      // first: verify token
},
{
  provide: APP_GUARD,
  useClass: TenantGuard,       // second: extract tenantId
},
```

---

## 6. Using tenantId in Handlers

Every handler that creates or queries domain entities injects `TenantContext`:

```typescript
// In every CQRS command/query handler for a domain entity:
@CommandHandler(CreateOneTodoCommand)
export class CreateOneTodoCommandHandler implements ICommandHandler<CreateOneTodoCommand> {
  constructor(
    private readonly todoService: TodoService,
    private readonly tenantContext: TenantContext,
  ) {}

  execute(message: CreateOneTodoCommand) {
    return this.todoService.createOne({
      ...message.args,
      tenantId: this.tenantContext.tenantId,  // always from JWT, never from client
    });
  }
}
```

And every service query is scoped:

```typescript
// TodoService.findMany — ALWAYS includes tenantId filter
async findMany({ query }: FindManyTodoCqrsInput['args']) {
  const results = await this.filterQueryBuilder
    .select({
      ...query,
      filter: {
        ...query?.filter,
        tenantId: { eq: this.tenantContext.tenantId },  // non-negotiable
      },
    })
    .getMany();

  return results;
}
```

If you forget `tenantId` in the filter, Tenant A can read Tenant B's data. This is why the rule is enforced architecturally (code review + the checklist at the end of this part) rather than relying on developers to remember.

---

## 7. RBAC — Roles & Permissions

### 7.1 Roles Enum

```typescript
// libs/core/src/enums/role.enum.ts
export enum UserRole {
  OWNER = 'owner',
  ADMIN = 'admin',
  MEMBER = 'member',
  VIEWER = 'viewer',
}
```

### 7.2 Roles on the User Entity

```typescript
@Entity('user')
export class UserEntity extends AbstractEntity {
  // ... other fields

  @Column({ type: 'simple-array', default: UserRole.MEMBER })
  roles: UserRole[];
}
```

### 7.3 RolesGuard

```typescript
// apps/api/src/shared/roles.guard.ts
import { CanActivate, ExecutionContext, Injectable } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { GqlExecutionContext } from '@nestjs/graphql';
import { UserRole } from '@enterprise-todo/core';

export const ROLES_KEY = 'roles';
export const Roles = (...roles: UserRole[]) => SetMetadata(ROLES_KEY, roles);

@Injectable()
export class RolesGuard implements CanActivate {
  constructor(private reflector: Reflector) {}

  canActivate(context: ExecutionContext): boolean {
    const requiredRoles = this.reflector.getAllAndOverride<UserRole[]>(ROLES_KEY, [
      context.getHandler(),
      context.getClass(),
    ]);

    if (!requiredRoles?.length) return true;  // no roles required → open

    const ctx = GqlExecutionContext.create(context);
    const { user } = ctx.getContext().req;

    return requiredRoles.some((role) => user?.roles?.includes(role));
  }
}
```

### 7.4 Using @Roles on Resolvers

```typescript
@Mutation(() => TagDto)
@UseGuards(AuthJwtGuard, RolesGuard)
@Roles(UserRole.ADMIN, UserRole.OWNER)
async createTag(
  @Args('input') input: CreateTagInput,
): Promise<TagDto> {
  return this.commandBus.execute(new CreateOneTagCommand({ input }));
}
```

---

## 8. Row-Level Authorization with @Authorize

`nestjs-query`'s `@Authorize` decorator is the most powerful authorization tool in this stack. It attaches a dynamic filter to every query and mutation at the **query builder level** — not application level. You can't bypass it by crafting a clever GraphQL request.

```typescript
// apps/api/src/modules/todo/dto/todo.authorizer.ts
import { Injectable } from '@nestjs/common';
import { AuthorizationContext, CustomAuthorizer } from '@ptc-org/nestjs-query-graphql';
import { TodoEntity } from '../todo.entity';
import { TenantContext } from '../../shared/tenant.context';

@Injectable()
export class TodoAuthorizer implements CustomAuthorizer<TodoEntity> {
  constructor(private readonly tenantContext: TenantContext) {}

  authorize(_context: AuthorizationContext): Promise<Filter<TodoEntity>> {
    // This filter is MERGED into every query this type participates in
    return Promise.resolve({
      tenantId: { eq: this.tenantContext.tenantId },
    });
  }

  authorizeRelation(_relationName: string, _context: AuthorizationContext) {
    return this.authorize(_context);
  }
}
```

Register on the DTO:

```typescript
// apps/api/src/modules/todo/dto/todo.dto.ts
@Authorize(TodoAuthorizer)
@ObjectType('Todo')
export class TodoDto extends AbstractDto {}
```

Now even if a handler forgets to add `tenantId` to its filter, the `@Authorize` decorator injects it at the TypeORM query builder level. **Defense in depth.**

---

## 9. Dual-Auth: User JWT vs Admin Portal JWT

Enterprise B2B SaaS products have two distinct portals:

```
User Portal: users@your-app.com
  → Client uses their credentials
  → Reads/writes ONLY their tenant's data
  → AuthJwtGuard (RS256, User key pair)

Admin Portal: internal.admin@your-company.com
  → Your support/operations team
  → Can read any tenant's data (filtered by tenantId passed as arg)
  → PortalAuthJwtGuard (RS256, DIFFERENT key pair)
```

Two separate key pairs enforces that a user JWT cannot elevate to admin actions — even if the user inspects the JWT payload and crafts a similar token, they don't have the Admin private key.

```typescript
// apps/api/src/shared/portal-auth-jwt.guard.ts
import { AuthGuard } from '@nestjs/passport';
import { Injectable } from '@nestjs/common';

@Injectable()
export class PortalAuthJwtGuard extends AuthGuard('portal-jwt') {}
```

```typescript
// apps/api/src/modules/auth/portal-jwt.strategy.ts
@Injectable()
export class PortalJwtStrategy extends PassportStrategy(Strategy, 'portal-jwt') {
  constructor(config: ConfigService) {
    super({
      jwtFromRequest: ExtractJwt.fromAuthHeaderAsBearerToken(),
      secretOrKey: config.getOrThrow('ADMIN_JWT_PUBLIC_KEY'),   // different key
      algorithms: ['RS256'],
    });
  }

  validate(payload: PortalJwtPayload) {
    return payload;  // portal users don't map to UserEntity
  }
}
```

Admin resolver example:

```typescript
@Mutation(() => TodoDto)
@UseGuards(PortalAuthJwtGuard)   // ← different guard
async adminDeleteTodo(
  @Args('id', { type: () => Int }) id: number,
  @Args('tenantId', { type: () => Int }) tenantId: number,  // admin CAN pass tenantId
): Promise<boolean> {
  return this.commandBus.execute(new AdminDeleteOneTodoCommand({ id, tenantId }));
}
```

Notice the admin mutation accepts `tenantId` as an argument — admins need to operate across tenants. Regular user mutations NEVER expose `tenantId` as a `@Field()`.

---

## 10. The Multi-tenant + RBAC Compose

All the pieces compose automatically because they're guards and decorators:

```
GraphQL Request
     │
     ▼
AuthJwtGuard           → verifies JWT signature (RS256), rejects if expired/invalid
     │
     ▼
TenantGuard            → extracts tenantId from JWT, stores in TenantContext (REQUEST scope)
     │
     ▼
RolesGuard             → checks user.roles against @Roles() on the resolver method
     │
     ▼
Resolver method        → @CurrentUser() injects user, CommandBus dispatches
     │
     ▼
Handler                → injects TenantContext, adds tenantId to command args
     │
     ▼
Service                → business logic, queries always include tenantId filter
     │
     ▼
@Authorize decorator   → nestjs-query merges tenantId filter into query builder
     │
     ▼
TypeORM query          → WHERE tenant_id = $1 AND ... (tenant isolation guaranteed)
```

A developer building a new module only needs to:
1. Add `tenantId` FK to the entity
2. Inject `TenantContext` in the handler
3. Pass `tenantId` in `createOne` input
4. Add `TodoAuthorizer`-style authorizer to the DTO

The guards run automatically because they're globally registered.

---

## 11. Multi-tenant Module Promotion Checklist

When you build a new module, run through this before submitting the PR:

```
Entity:
[✅] tenantId @Column() + @RelationId() + @Index() present
[✅] Migration generated and reviewed (includes tenantId column)

Handler:
[✅] TenantContext injected
[✅] tenantId: this.tenantContext.tenantId set on createOne input
[✅] findMany/findOne queries include tenantId filter
[✅] updateOne filter includes tenantId (prevents cross-tenant update)
[✅] deleteOne filter includes tenantId (prevents cross-tenant delete)

DTO:
[✅] @Authorize(XxxAuthorizer) on the @ObjectType DTO
[✅] @FilterableField() NOT on tenantId (tenantId must not be filterable by clients)
[✅] CreateXxxInput has NO tenantId @Field() — it's never client-provided

Auth:
[✅] @UseGuards(AuthJwtGuard) on every mutation and sensitive query
[✅] Admin-only operations use PortalAuthJwtGuard, not AuthJwtGuard

RBAC:
[✅] Admin/owner-only mutations have @Roles(UserRole.ADMIN, UserRole.OWNER)
[✅] Viewer-only operations are idempotent GET-equivalent resolvers (no mutations)

Tests:
[✅] E2E test includes: user from Tenant A cannot access Tenant B's data
[✅] E2E test includes: viewer cannot call admin mutation
```

---

## 12. Complete Architecture in One Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         NestJS Application                        │
│                                                                   │
│  HTTP/WS  ─→  GraphQL API (Apollo)                               │
│                    │                                              │
│              ┌─────▼──────────────────────────────────────────┐  │
│              │                Guard Pipeline                    │  │
│              │  AuthJwtGuard (RS256) → TenantGuard → RolesGuard│  │
│              └─────┬──────────────────────────────────────────┘  │
│                    │                                              │
│              ┌─────▼──────────────────────────────────────────┐  │
│              │              Resolver Layer                      │  │
│              │  @Resolver → @Query / @Mutation / @Subscription │  │
│              │  @CurrentUser() injects user from JWT           │  │
│              └─────┬──────────────────────────────────────────┘  │
│                    │                                              │
│              ┌─────▼──────────────────────────────────────────┐  │
│              │         CQRS Bus (nestjs-typed-cqrs)            │  │
│              │  CommandBus / QueryBus                          │  │
│              └─────┬──────────────────────────────────────────┘  │
│                    │                                              │
│              ┌─────▼──────────────────────────────────────────┐  │
│              │         Thin Handlers                            │  │
│              │  One-liner: service.method(message.args)        │  │
│              │  + tenantId from TenantContext (REQUEST scope)  │  │
│              └─────┬──────────────────────────────────────────┘  │
│                    │                                              │
│              ┌─────▼──────────────────────────────────────────┐  │
│              │         Service Layer                            │  │
│              │  Business logic + FilterQueryBuilder            │  │
│              │  Publishes to RedisPubSub                       │  │
│              │  Enqueues Bull jobs                             │  │
│              └─────┬──────────────────────────────────────────┘  │
│                    │                                              │
│              ┌─────▼──────────────────────────────────────────┐  │
│              │         TypeORM + PostgreSQL                     │  │
│              │  @Authorize merges tenantId filter              │  │
│              │  WHERE tenant_id = $1 always                    │  │
│              └────────────────────────────────────────────────┘  │
│                                                                   │
│  Bull Queues (Redis)    Redis PubSub    DataLoaders (REQUEST)     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Where You Stand Now

You've built from zero to enterprise. Here's the full progression:

| Part | What you can do now |
|------|-------------------|
| 01 | Explain WHY explicit over implicit, map Meteor → NestJS concepts |
| 02 | Set up a production-grade Nx monorepo from scratch |
| 03 | Understand DI, request lifecycle, write a NestJS module |
| 04 | Model data in TypeORM, write migrations, never use synchronize |
| 05 | Write typed CQRS with thin handlers, understand why |
| 06 | Build full GraphQL API + cursor pagination + Next.js frontend |
| 07 | Implement RS256 JWT auth, @CurrentUser, refresh tokens |
| 08 | Complete a module from scratch: Tag with all 9 steps |
| 09 | FK relations, DataLoader, ownership enforcement |
| 10 | Unit tests (mock repos) + E2E tests (real DB) |
| 11 | Bull queues for async work, Redis PubSub for real-time |
| 12 | CI/CD pipeline, multi-stage Docker, production migration strategy |
| 13 | Multi-tenancy, RBAC, @Authorize, dual-auth portals |

The codebase patterns you've learned map directly to production-grade enterprise NestJS backends. Every system in this series is a deliberate choice, not a convenience shortcut — and now you know the tradeoff behind each one.
