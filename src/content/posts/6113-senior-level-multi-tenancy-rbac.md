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

> **The storage unit facility:** A multi-tenant system is a cloud storage unit facility with hundreds of units. All units share the same building, the same staff, the same lock type. Each tenant can only access their own unit. If a staff member accidentally opens Unit 102's door for the Unit 101 tenant — even just to look — that is a catastrophic data breach. Every operation must check the unit number first. Every time. Without exception. The `tenantId` column is the unit number stamped on every item stored in the system.

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

### 7.1 Two-tier Authorization Model

Production apps use two guards in combination:

| Guard | Type | Speed | What it checks |
|-------|------|-------|----------------|
| `RolesGuard` | Coarse, enum-based | Fast (in-memory) | Tenant-level role (ADMIN, OWNER…) |
| `ACPermissionGuard` | Fine-grained, DB-backed | Slightly slower (DB join on login) | Specific action slugs (`create-tag`, `delete-user`…) |

`RolesGuard` answers "what level is this user?" — `ACPermissionGuard` answers "can this user perform this action?". Use `RolesGuard` for coarse tenant-level gates; use `ACPermissionGuard` for feature/action-level gates. Both are guards, so they compose with `@UseGuards()` without coupling to business logic.

> **The VIP wristband system:** Think of RBAC like a nightclub with multiple zones. Your wristband determines which doors open for you: general admission wristband = public areas only, staff wristband = back of house, VIP wristband = the VIP lounge. `RolesGuard` checks your wristband tier (OWNER, ADMIN, MEMBER, VIEWER). `ACPermissionGuard` checks specific door slugs (`create-todo`, `delete-user`). A "Tag Manager" role can have the `create-tag` door without having the full ADMIN wristband.

### 7.2 UserRole Enum

Still used for coarse tenant-level checks (e.g. only OWNER can transfer the tenant):

```typescript
// libs/core/src/enums/role.enum.ts
export enum UserRole {
  OWNER = 'owner',
  ADMIN = 'admin',
  MEMBER = 'member',
  VIEWER = 'viewer',
}
```

### 7.3 PermissionEntity

Permissions are rows in the DB. Each permission has a human-readable `name`, a grouping `module`, and a unique kebab-case `slug` that the guard checks against:

```typescript
// apps/api/src/modules/permission/permission.entity.ts
import { Column, Entity, Index, ManyToMany } from 'typeorm';
import { AbstractEntity } from 'nestjs-dev-utilities';
import { RoleEntity } from '../role/role.entity';

@Entity({ name: 'permission' })
export class PermissionEntity extends AbstractEntity {
  @Column()
  name: string;  // e.g. "Create Todo"

  @Column()
  module: string;  // e.g. "TODO"

  @Index({ unique: true })
  @Column()
  slug: string;  // e.g. "create-todo", "delete-user" — kebab-case, always lowercase

  @ManyToMany(() => RoleEntity, (role) => role.permissions)
  roles: RoleEntity[];
}
```

### 7.4 RoleEntity

A role groups permissions. System roles (like "Super Admin") are marked non-editable so they can't be stripped via the UI:

```typescript
// apps/api/src/modules/role/role.entity.ts
import { Column, Entity, JoinTable, ManyToMany } from 'typeorm';
import { AbstractEntity } from 'nestjs-dev-utilities';
import { PermissionEntity } from '../permission/permission.entity';
import { UserEntity } from '../user/user.entity';

@Entity({ name: 'role' })
export class RoleEntity extends AbstractEntity {
  @Column()
  name: string;  // e.g. "Super Admin", "Todo Manager"

  @Column({ default: true })
  isEditable: boolean;  // system roles (like Super Admin) are not editable

  @ManyToMany(() => PermissionEntity, (permission) => permission.roles, { eager: true })
  @JoinTable({ name: 'role_permission' })
  permissions: PermissionEntity[];

  @ManyToMany(() => UserEntity, (user) => user.roles)
  users: UserEntity[];
}
```

### 7.5 Update UserEntity — Replace simple-array with ManyToMany

Replace the `simple-array` roles column on `UserEntity` with a proper join table:

```typescript
// In UserEntity — replace the simple-array roles column:
@ManyToMany(() => RoleEntity, (role) => role.users, { eager: true })
@JoinTable({ name: 'user_role' })
roles: RoleEntity[];
```

Eager loading on roles means every user fetch also loads their roles + permissions in one query. That's acceptable for auth checks. If you're listing many users (e.g. an admin user list page), use a DataLoader instead to avoid N+1.

### 7.6 ACPermissionGuard

The guard flattens all permission slugs from the user's roles and checks them against the decorator's required slugs:

```typescript
// apps/api/src/shared/guards/ac-permission.guard.ts
import {
  CanActivate, ExecutionContext, Injectable, ForbiddenException, UnauthorizedException,
} from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { GqlExecutionContext } from '@nestjs/graphql';
import { UserStatus } from '../enums/user-status.enum';

export const AC_GUARD_KEY = 'ac_guard';

export interface AcGuardOptions {
  module: string;
  permissions: string[];
  allowGuest?: boolean;
}

export const UseACGuard = (module: string, permissions: string[]) =>
  SetMetadata(AC_GUARD_KEY, { module, permissions, allowGuest: false });

export const AllowGuest = () =>
  SetMetadata(AC_GUARD_KEY, { module: '', permissions: [], allowGuest: true });

@Injectable()
export class ACPermissionGuard implements CanActivate {
  constructor(private readonly reflector: Reflector) {}

  canActivate(context: ExecutionContext): boolean {
    const options = this.reflector.getAllAndOverride<AcGuardOptions>(AC_GUARD_KEY, [
      context.getHandler(),
      context.getClass(),
    ]);

    // No @UseACGuard decorator → open endpoint
    if (!options) return true;

    // @AllowGuest() → skip auth entirely
    if (options.allowGuest) return true;

    const ctx = GqlExecutionContext.create(context);
    const { user } = ctx.getContext().req;

    if (!user) throw new UnauthorizedException('Not authenticated');

    // User must be ACTIVE — suspended/inactive users are rejected even with valid JWT
    if (user.status !== UserStatus.ACTIVE) {
      throw new ForbiddenException('Account is not active');
    }

    // No specific permissions required → authenticated + active is enough
    if (!options.permissions.length) return true;

    // Flatten all permission slugs across all user roles
    const userSlugs = new Set(
      user.roles?.flatMap((role) =>
        role.permissions?.map((p) => p.slug) ?? []
      ) ?? []
    );

    const hasPermission = options.permissions.every((slug) => userSlugs.has(slug));
    if (!hasPermission) {
      throw new ForbiddenException(`Missing permission: ${options.permissions.join(', ')}`);
    }

    return true;
  }
}
```

### 7.7 Using @UseACGuard on Resolvers

```typescript
// Before (RolesGuard only):
@Mutation(() => TagDto)
@UseGuards(AuthJwtGuard, RolesGuard)
@Roles(UserRole.ADMIN, UserRole.OWNER)
async createTag(...) {}

// After (ACPermissionGuard — production pattern):
@Mutation(() => TagDto)
@UseGuards(AuthJwtGuard, ACPermissionGuard)
@UseACGuard('TAG', ['create-tag'])
async createTag(...) {}

// Guest endpoint (public, no auth):
@Query(() => [TagDto])
@UseGuards(ACPermissionGuard)
@AllowGuest()
async publicTags(...) {}
```

The slug `'create-tag'` is seeded into `PermissionEntity`. Any role that holds that permission slug can execute this mutation — regardless of whether they're ADMIN or MEMBER. This decouples authorization from role names: you can create a "Tag Manager" role that has `create-tag` and `delete-tag` without giving that role full ADMIN access.

### 7.8 Seeding Roles and Permissions

Create permissions and the initial "Super Admin" role in a seeder:

```typescript
// apps/api/src/seeders/2-permissions.seeder.ts
export class PermissionSeeder extends Seeder {
  async run(em: EntityManager): Promise<void> {
    const permissions = [
      { name: 'Create Todo', module: 'TODO', slug: 'create-todo' },
      { name: 'Delete Todo', module: 'TODO', slug: 'delete-todo' },
      { name: 'Create Tag',  module: 'TAG',  slug: 'create-tag'  },
      { name: 'Delete Tag',  module: 'TAG',  slug: 'delete-tag'  },
      { name: 'Manage Users', module: 'USER', slug: 'manage-users' },
    ];
    // upsert permissions, create Super Admin role with all permissions
  }
}
```

Each new module adds its permission slugs here. The seeder is idempotent — running it twice doesn't create duplicates.

### 7.9 Migration

```bash
yarn api:migration:generate apps/api/src/migrations/AddRolePermissionTables
yarn api:migration:run
yarn api:seed:run
```

**Verify:** Boot the API. Create a user, assign the "Super Admin" role in Adminer, call the `createTag` mutation → succeeds. Remove the role, retry → `403 Forbidden`.

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

> **The turnstile inside the corridor:** Guards at the front door are your first layer. But `@Authorize` is a **turnstile built into the database corridor itself** — after the guards, before the rows. Even if a handler forgets to add `tenantId` to its filter (a code review miss), the `@Authorize` decorator merges `WHERE tenant_id = $1` at the TypeORM query builder level. It is impossible to bypass by crafting a clever GraphQL query. You cannot bribe a turnstile.

---

## 9. Dual-Auth: User JWT vs Admin Portal JWT

Enterprise B2B SaaS products have two distinct portals:

```
User Portal: users@your-app.com
  → Client uses their credentials
  → Reads/writes ONLY their tenant's data
  → AuthJwtGuard (RS256, User key pair)

Admin Portal: admin@your-app.com
  → Your support/operations team
  → Can read any tenant's data (filtered by tenantId passed as arg)
  → PortalAuthJwtGuard (RS256, DIFFERENT key pair)
```

Two separate key pairs enforces that a user JWT cannot elevate to admin actions — even if the user inspects the JWT payload and crafts a similar token, they don't have the Admin private key.

> **Two separate key rings:** The user portal and the admin portal use two physically separate RSA key pairs — like two separate key rings for two separate buildings. A key from Building A (user JWT signed with `JWT_PRIVATE_KEY`) cannot open Building B (admin portal protected by `PortalAuthJwtGuard` verifying against `ADMIN_JWT_PUBLIC_KEY`). Even if a user inspects their JWT payload and crafts a similar token, the RS256 signature verification against the admin public key will fail. The key ring itself is the guarantee.

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
ACPermissionGuard      → validates user.status === ACTIVE + checks permission slugs
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
[✅] Add @UseACGuard('MODULE', ['action-slug']) to write mutations
[✅] Seed permissions for the new module in 2-permissions.seeder.ts
[✅] Add PermissionEntity and RoleEntity to AppModule entities[] if not already there
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
