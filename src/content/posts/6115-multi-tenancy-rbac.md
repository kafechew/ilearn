---
author: Kai
pubDatetime: 2026-05-15T09:00:00+08:00
title: Multi-tenancy & Role-Based Access Control (RBAC)
featured: false
draft: false
slug: 6115-multi-tenancy-rbac
tags:
  - deeptech
  - meteorjs
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/15-senior-level-multi-tenancy-rbac.png"
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
| Fine-grained permissions | No standard pattern — manual per-method checks | `ACPermissionGuard` + permission slugs seeded in DB |
| Tenant context propagation | Thread `organizationId` as a parameter | REQUEST-scoped `TenantContext` — inject anywhere, no threading |
| Auth token | Server-side DDP session token | Stateless RS256 JWT — `tenantId` + roles travel in the payload |
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

> **From Meteor?** In Meteor, `organizationId` (or equivalent tenant FK) had to be manually added to every `Collection.find()` call in every method and publication — easy to miss one. The NestJS pattern stamps `tenantId` on the entity itself and enforces it at three independent architectural layers, so a developer cannot accidentally forget it on a single query and open a data breach.

**Memory hook:** tenantId = unit number on everything. Every domain entity carries it. From the JWT only. Never from the client.

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

> **RS256 JWT — the king's wax seal:** Only the auth service holds the private key (the signet ring). Any service can inspect the seal to verify it's genuine (public key) — but they cannot produce a forgery. Even if a user decodes their JWT and crafts a payload with a different `tenantId`, the RS256 signature verification fails. The key ring itself is the guarantee.

> **From Meteor?** Meteor's DDP session token was a server-side lookup — the server held session state mapping token to userId. JWT is stateless: the token contains all claims, cryptographically signed. No database lookup needed to verify the token, and the `tenantId` travels with every request automatically.

**Memory hook:** RS256 JWT = king's wax seal. Private key signs, public key verifies. `tenantId` in the payload = comes with every authenticated request for free.

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

> **Guard = gate officer:** `TenantGuard` is a gate officer that doesn't reject anyone — it reads the JWT, extracts the patient wristband (`tenantId`), and records it in `TenantContext` before the request reaches any ward. Every handler downstream sees that wristband without checking the JWT again.

> **TenantContext = automatic wristband holder:** `TenantContext` is REQUEST-scoped — each HTTP request gets its own fresh instance. If it were a singleton, a request from Tenant A could overwrite the `tenantId` that Tenant B's concurrent request is reading. The `Scope.REQUEST` is the lock that keeps the wristbands separate.

> **From Meteor?** In Meteor, tenant identity had to be threaded through every method call manually as a parameter or looked up from a user document inside every method. Here `TenantGuard` runs once globally and `TenantContext` carries the result through the entire request chain automatically — any class that needs it just injects it.

**Memory hook:** TenantGuard = gate officer that reads the patient wristband. TenantContext = REQUEST-scoped holder for that wristband. Never singleton — each request owns its own copy.

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

> **From Meteor?** In Meteor you would write `TasksCollection.find({ organizationId: this.userId /* wrong! */ })` in every method and publication — a copy-paste pattern that broke silently when missed. The NestJS pattern injects `TenantContext` once per handler and the `@Authorize` decorator adds a second safety net at the query builder level.

**Memory hook:** Every handler that touches domain data must inject `TenantContext` and pass `this.tenantContext.tenantId` into every create/query/update/delete operation. Missing it = cross-tenant data leak.

---

## 7. RBAC — Roles & Permissions

### 7.1 Two-tier Authorization Model

Production apps use two guards in combination:

| Guard | Type | Speed | What it checks |
|-------|------|-------|----------------|
| `RolesGuard` | Coarse, enum-based | Fast (in-memory) | Tenant-level role (ADMIN, OWNER…) |
| `ACPermissionGuard` | Fine-grained, DB-backed | Slightly slower (DB join on login) | Specific action slugs (`create-tag`, `delete-user`…) |

`RolesGuard` answers "what level is this user?" — `ACPermissionGuard` answers "can this user perform this action?". Use `RolesGuard` for coarse tenant-level gates; use `ACPermissionGuard` for feature/action-level gates. Both are guards, so they compose with `@UseGuards()` without coupling to business logic.

> **The hospital clearance system:** Think of RBAC like the hospital's security zones. Your clearance level determines which areas you can enter: visitor pass = public areas only, staff badge = clinical wards, department head badge = restricted zones. `RolesGuard` checks your clearance level (OWNER, ADMIN, MEMBER, VIEWER). `ACPermissionGuard` checks specific access slugs (`create-todo`, `delete-user`). A "Tag Manager" role can have the `create-tag` slug without holding full ADMIN clearance.

> **From Meteor?** `alanning:roles` provided `Roles.userIsInRole(userId, 'admin')` — a runtime check you called manually inside each method. Nothing enforced you to call it. Here `RolesGuard` and `ACPermissionGuard` are applied via decorators on the resolver method — they run automatically before the handler, and a missing decorator is visible in code review.

**Memory hook:** Two-tier RBAC: `RolesGuard` checks the clearance level (coarse, fast), `ACPermissionGuard` checks specific access slugs (fine-grained, DB-backed). Both are guards — they compose with `@UseGuards()` and never pollute business logic.

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

**Memory hook:** PermissionEntity = rows in the DB. Each permission has a unique kebab-case slug (`create-todo`, `delete-user`). Roles group permissions. Users hold roles. Guards check slugs.

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

> **SetMetadata/Reflector = labels only supervisors can read:** `UseACGuard` calls `SetMetadata` to attach `{ module, permissions }` metadata to the resolver method. Inside `ACPermissionGuard`, `this.reflector.getAllAndOverride()` reads that label. End users never see the metadata — only the guard can read it, like a label printed in supervisor-only ink.

> **From Meteor?** In Meteor there was no equivalent of `Reflector` — you called `Roles.userIsInRole()` imperatively inside the method body. Here the guard reads declarative metadata from the decorator, so permission requirements are visible at the resolver method signature rather than buried in the method body.

**Memory hook:** `ACPermissionGuard` = Reflector reads the `@UseACGuard` label, flattens all role permission slugs into a Set, checks every required slug is present. Missing one slug = 403.

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

> **From Meteor?** In Meteor you might check `Roles.userIsInRole(this.userId, ['admin', 'owner'])` at the top of a method. That ties the check to role names — change the role structure and you grep-hunt every method. Here the check is against a permission slug (`'create-tag'`), and which roles carry that slug is managed in the database. Roles change without touching resolver code.

**Memory hook:** `@UseACGuard('MODULE', ['slug'])` on the resolver + seed the slug in `PermissionEntity` + assign the permission to a role. Three steps, zero grep-hunting when roles change.

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

> **From Meteor?** There was no standard migration tool for MongoDB in Meteor — schema changes happened at the application layer, silently, with no rollback. Here every schema change (new `role`, `permission`, `role_permission`, `user_role` tables) is a TypeORM migration: versioned, reviewable, and reversible with `migration:revert`.

**Memory hook:** RBAC schema changes = TypeORM migrations. Permission slugs = seeder. Idempotent seeders mean re-running them never creates duplicates.

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

> **From Meteor?** In Meteor, row-level auth was `if (doc.userId !== this.userId) throw new Meteor.Error('not-authorized')` inside each method — manual, per-operation, easy to forget. `@Authorize` is declared once on the DTO and applies to every query that type participates in, automatically, forever.

**Memory hook:** `@Authorize(TodoAuthorizer)` on the `@ObjectType` DTO = one declaration protects every query touching that type. Defense in depth — the second lock after the guard pipeline.

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

> **From Meteor?** Meteor had one user system — "admin" users were just users with a special role flag, using the same auth token as regular users. Here two physically separate RSA key pairs enforce the boundary: a compromised user JWT cannot be used to call admin mutations, because `PortalAuthJwtGuard` verifies against a completely different public key.

**Memory hook:** Dual-auth = two separate key rings. User JWT (RS256 key pair A) cannot open admin portal (verifies against key pair B). Two key pairs = mathematical separation, not just a role flag.

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

> **From Meteor?** In Meteor every method was its own island — you had to remember to add the `organizationId` check, the role check, and the ownership check in every single method. Here the guard pipeline and `@Authorize` compose automatically: a developer building a new module only needs to wire four things (entity FK, handler injection, authorizer on DTO, permission seed) and all the layers run without further thought.

**Memory hook:** Four wiring steps for a new multi-tenant module: (1) `tenantId` FK on entity, (2) `TenantContext` injected in handler, (3) `@Authorize(XxxAuthorizer)` on DTO, (4) permission slug in seeder. Everything else runs automatically.

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

## Quick Reference

| Concept | Analogy | Meteor equivalent | The one rule |
|---------|---------|-------------------|--------------|
| Multi-tenancy | Cloud storage unit facility — every unit shares the building, each tenant can only access their own | Manually add `organizationId` to every query (DIY) | Every operation must check the unit number first. Every time. |
| tenantId | Unit number stamped on every item stored in the system | Manual `organizationId` field on documents | Never from the client — always from `TenantContext` (from JWT) |
| TenantGuard | Gate officer who reads the patient wristband (tenantId) from the JWT | No equivalent — manual per-method | Runs globally after `AuthJwtGuard`; stores `tenantId` in `TenantContext` |
| TenantContext | REQUEST-scoped wristband holder — one per request | Thread `organizationId` as a parameter through every function | Must be `Scope.REQUEST` — singleton would let tenants overwrite each other |
| RS256 JWT | King's wax seal — private key signs, public key verifies | DDP session token (server-side session lookup) | Private key signs (auth service only); public key verifies (any service) |
| RolesGuard | Hospital clearance level check — OWNER, ADMIN, MEMBER, VIEWER | `alanning:roles` + `Roles.userIsInRole()` manual check | Coarse, fast, in-memory; use for tenant-level gates |
| ACPermissionGuard | Specific door slug check — `create-tag`, `delete-user` | Manual per-method role check | Fine-grained, DB-backed; decouples auth from role names |
| SetMetadata / Reflector | Labels only supervisors can read | No equivalent — permissions were imperative checks in method bodies | `SetMetadata` attaches; `Reflector.getAllAndOverride()` reads inside a guard |
| @Authorize | Turnstile inside the database corridor — cannot be bypassed | Manual `if (doc.userId !== this.userId)` per method | Declared once on the `@ObjectType` DTO; protects every query that type touches |
| Dual-auth (user vs admin JWT) | Two separate key rings for two separate buildings | Same user system with a role flag | Two RSA key pairs = mathematical separation; a user JWT cannot open admin routes |

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
| 12 | Unit tests (mock repos) + E2E tests (real DB) |
| 13 | Bull queues for async work, Redis PubSub for real-time |
| 19 | CI/CD pipeline, multi-stage Docker, production migration strategy |
| 15 | Multi-tenancy, RBAC, @Authorize, dual-auth portals |

The codebase patterns you've learned map directly to production-grade enterprise NestJS backends. Every system in this series is a deliberate choice, not a convenience shortcut — and now you know the tradeoff behind each one.
