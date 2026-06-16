---
author: Kai
pubDatetime: 2026-05-23T09:00:00+08:00
title: Affiliate & Referral Tree — Materialized Path Hierarchy on UserEntity
featured: false
draft: false
slug: 6123-affiliate-referral-tree-materialized-path
tags:
  - deeptech
  - nestjs
  - typeorm
  - postgresql
  - typescript
  - backend
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/23-affiliate-referral-tree-materialized-path.png"
description: Add a self-referential affiliate tree to UserEntity using the materialized path pattern — store each user's ancestry as a string path, enabling O(1) depth lookups, efficient descendant queries with a single LIKE clause, and referral commission calculations without recursive CTEs.
---

## What This Part Covers

- Why materialized path beats adjacency list and nested sets for referral trees
- Adding `referralCode`, `referredByCode`, and `path` to `UserEntity`
- Generating unique referral codes on registration
- `ReferralService` — tree queries (descendants, ancestors, depth, count)
- Preventing circular references
- GraphQL queries: referral stats, downline list
- Seeder with a multi-level referral tree
- Migration strategy for adding columns to existing users

---

## Meteor Equivalents

Meteor had no native tree or hierarchy support. Developers typically stored a flat `referredBy: userId` field on the user document and wrote recursive application-level loops when they needed to traverse the tree.

| Concern                  | Meteor approach                                                            | NestJS / materialized path                                                     |
| ------------------------ | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Store referrer           | `referredBy: userId` on user document                                      | `referredByCode: string` (code, not raw ID) on `UserEntity`                    |
| Find descendants         | Recursive `Meteor.users.find()` loop in application code — N+1 round trips | `WHERE path LIKE 'prefix%'` — single indexed query                             |
| Find ancestors           | Walk up manually: fetch user, fetch their referrer, repeat                 | Parse `path` string client-side — zero DB queries                              |
| Depth of a user          | Count recursive hops                                                       | `path.split('.').filter(Boolean).length - 1` — O(1), no query                  |
| Circular reference check | Manual application check before saving                                     | `wouldCreateCircle()` — check if userId appears in the candidate parent's path |
| Commission calculation   | Application-level loop fetching each ancestor                              | Fetch ancestor IDs from `path` string, batch-load users in one query           |
| Referral code            | Custom field — no standard pattern                                         | `referralCode` unique indexed column, generated via `crypto.randomBytes`       |

Meteor's single-document model worked for simple `referredBy` tracking but collapsed under any tree traversal requirement. Every "who referred whom" report became a multi-request waterfall. The materialized path pattern moves the tree topology into the data itself, making subtree queries as cheap as a string prefix match.

---

## 1. Why Materialized Path

There are three classical approaches to storing hierarchical data in a relational database. Understanding why two of them fail for referral trees makes the choice clear.

### Adjacency List (`referredBy: userId`)

The simplest model: each row stores only its direct parent.

```
user_id | referred_by_user_id
--------|--------------------
1       | NULL               ← root
42      | 1
107     | 42
234     | 42
891     | 234
```

Simple to write, hard to query. "Find all descendants of user 42" requires a recursive CTE:

```sql
WITH RECURSIVE descendants AS (
  SELECT id FROM "user" WHERE id = 42
  UNION ALL
  SELECT u.id FROM "user" u
  JOIN descendants d ON u.referred_by_user_id = d.id
)
SELECT * FROM descendants;
```

Recursive CTEs have a hard depth limit (`max_recursion_depth`), cannot use simple btree indexes on the join, and produce query plans that PostgreSQL cannot easily estimate. In application code without CTEs, this becomes N+1: fetch user, fetch their referrals, fetch each referral's referrals — a 5-level tree triggers at least 5 serial queries minimum.

### Nested Sets (left/right integers)

Each row stores a `left` and `right` integer representing a pre-order traversal of the tree.

```
user_id | lft | rgt
--------|-----|----
1       |  1  | 10
42      |  2  |  7
107     |  3  |  4
234     |  5  |  6
891     |  8  |  9
```

Descendants of user 42: `WHERE lft > 2 AND rgt < 7` — blazing fast, single indexed range scan.

The problem is writes. Every insert at any position in the tree requires updating all `lft` and `rgt` values above it in the traversal order. Adding one user to the bottom of a tree with 10,000 nodes rewrites 10,000 rows. Under concurrent signups this becomes a serialization bottleneck. Completely impractical for a growing referral tree where inserts happen continuously.

### Materialized Path

Each row stores its full ancestry as a dot-delimited string of IDs.

```
user_id | path
--------|------------------
1       | 1.
42      | 1.42.
107     | 1.42.107.
234     | 1.42.234.
891     | 1.42.234.891.
```

- **Descendants of user 42:** `WHERE path LIKE '1.42.%'` — single btree index scan (left-anchored prefix, no leading wildcard)
- **Depth of a user:** `path.split('.').filter(Boolean).length - 1` — pure string operation, zero DB queries
- **Ancestor IDs of user 891:** parse `'1.42.234.891.'` → `[1, 42, 234]` — zero DB queries, batch-load users in one `IN` query
- **Insert a new user:** `path = parent.path + newId + '.'` — single UPDATE after INSERT, touches only one row

Reads vastly outnumber writes in a referral tree. Materialized path optimizes exactly for that ratio.

### Visual Example

```
User 1 (root):                       path = '1.'
  User 42 (referred by 1):           path = '1.42.'
    User 107 (referred by 42):       path = '1.42.107.'
    User 234 (referred by 42):       path = '1.42.234.'
      User 891 (referred by 234):    path = '1.42.234.891.'
```

---

## 2. Update UserEntity

`UserEntity` already carries `id`, `email`, `username`, `password`, `status`, `twoFactorSecret`, a `roles` ManyToMany to `RoleEntity`, and `tenantId`. Add three columns.

### The Three New Columns

```typescript
// Column 1: unique referral code — generated once on registration, never changes
// Shared with friends as the signup code ("use code ACME-A1B2C3 to join")
@Index({ unique: true })
@Column({ unique: true, nullable: true })
referralCode: string;

// Column 2: the referral code supplied during signup
// null means organic signup with no referrer
@Column({ nullable: true })
referredByCode: string | null;

// Column 3: the materialized path — populated after INSERT (needs the new row's id)
// '' for un-initialized rows; always ends with '.' once set
@Index()
@Column({ default: '' })
path: string;
```

### Full Updated UserEntity

```typescript
// apps/api/src/modules/user/entities/user.entity.ts
import { Column, Entity, Index, JoinTable, ManyToMany } from "typeorm";
import { AbstractEntity } from "nestjs-dev-utilities";
import { RoleEntity } from "../../role/entities/role.entity";

export enum UserStatus {
  ACTIVE = "ACTIVE",
  INACTIVE = "INACTIVE",
  SUSPENDED = "SUSPENDED",
}

@Entity("user")
export class UserEntity extends AbstractEntity {
  @Index({ unique: true })
  @Column({ unique: true })
  email: string;

  @Column({ nullable: true })
  username: string | null;

  @Column({ select: false })
  password: string;

  @Column({
    type: "enum",
    enum: UserStatus,
    default: UserStatus.INACTIVE,
  })
  status: UserStatus;

  @Column({ nullable: true, select: false })
  twoFactorSecret: string | null;

  @ManyToMany(() => RoleEntity, { eager: true })
  @JoinTable({ name: "user_role" })
  roles: RoleEntity[];

  @Column()
  tenantId: number;

  // --- Referral tree columns ---

  @Index({ unique: true })
  @Column({ unique: true, nullable: true })
  referralCode: string;

  @Column({ nullable: true })
  referredByCode: string | null;

  @Index()
  @Column({ default: "" })
  path: string;
}
```

### Referral Code Generator

Create a small helper — keep it out of the service so it can be unit-tested in isolation.

```typescript
// apps/api/src/helpers/referral-code.ts
import { randomBytes } from "crypto";

/**
 * Generates a referral code like 'REF-A1B2C3'.
 * Uses 3 random bytes (6 hex chars) — 16.7 million combinations.
 * prefix can be customised per tenant if needed.
 */
export function generateReferralCode(prefix = "REF"): string {
  const code = randomBytes(3).toString("hex").toUpperCase();
  return `${prefix}-${code}`;
}
```

### Smoke Test — Section 2

Start the API and confirm TypeORM resolves the new columns without errors:

```bash
yarn api:dev
```

Expected output:

```
[NestApplication] Nest application successfully started
[TypeORM] Synchronizing entity metadata...
```

If you see `column "referral_code" of relation "user" does not exist`, the migration has not run yet — that is expected at this stage. The migration is in Section 7. For now, confirm the app boots and TypeORM recognises the entity shape.

---

## 3. ReferralService

The service handles all tree operations. It is injected into `AuthService` for registration and into the resolver for GraphQL queries.

### Full ReferralService

```typescript
// apps/api/src/modules/referral/referral.service.ts
import { Injectable } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { Repository } from "typeorm";
import { UserEntity } from "../user/entities/user.entity";
import { generateReferralCode } from "../../helpers/referral-code";

@Injectable()
export class ReferralService {
  constructor(
    @InjectRepository(UserEntity)
    private readonly userRepo: Repository<UserEntity>
  ) {}

  /**
   * Called from AuthService.register() after the user row is saved.
   * Sets referralCode and path in a single UPDATE.
   * Safe to call with referredByCode = null for organic signups.
   */
  async initializeReferral(
    userId: number,
    referredByCode: string | null
  ): Promise<void> {
    let path = `${userId}.`;

    if (referredByCode) {
      const referrer = await this.userRepo.findOne({
        where: { referralCode: referredByCode },
      });
      if (referrer) {
        // Append this user's id to the referrer's path
        path = `${referrer.path}${userId}.`;
      }
      // If referredByCode doesn't match any user, treat as organic (root path)
    }

    await this.userRepo.update(userId, {
      referralCode: generateReferralCode(),
      path,
    });
  }

  /**
   * Direct referrals only — users whose path is exactly parent.path + userId + '.'
   * i.e. one level below the target user.
   */
  async getDirectReferrals(userId: number): Promise<UserEntity[]> {
    const user = await this.userRepo.findOneOrFail({ where: { id: userId } });
    // The path a direct child of userId would have
    const childPath = `${user.path}${userId}.`;

    return this.userRepo
      .createQueryBuilder("u")
      .where("u.path = :path", { path: childPath })
      .getMany();
  }

  /**
   * All descendants at any depth — uses a single LIKE prefix query.
   * The trailing dot in the prefix ensures we don't accidentally match
   * a user whose id starts with the same digits (e.g. 1. vs 10.).
   */
  async getAllDescendants(userId: number): Promise<UserEntity[]> {
    const user = await this.userRepo.findOneOrFail({ where: { id: userId } });
    const prefix = `${user.path}${userId}.`;

    return this.userRepo
      .createQueryBuilder("u")
      .where("u.path LIKE :prefix", { prefix: `${prefix}%` })
      .orderBy("u.path", "ASC")
      .getMany();
  }

  /**
   * Count of all descendants — cheaper than getAllDescendants when you only
   * need the number (no entity hydration).
   */
  async countDescendants(userId: number): Promise<number> {
    const user = await this.userRepo.findOneOrFail({ where: { id: userId } });
    const prefix = `${user.path}${userId}.`;

    return this.userRepo
      .createQueryBuilder("u")
      .where("u.path LIKE :prefix", { prefix: `${prefix}%` })
      .getCount();
  }

  /**
   * Depth of a user in the tree. Root users (no referrer) are depth 0.
   * Computed purely from the path string — no DB query.
   *
   * path = '1.'           → segments = ['1'] → depth = 0
   * path = '1.42.'        → segments = ['1', '42'] → depth = 1
   * path = '1.42.107.'    → segments = ['1', '42', '107'] → depth = 2
   */
  getDepth(user: UserEntity): number {
    if (!user.path) return 0;
    // The last segment is the user's own id; exclude it to get depth
    return user.path.split(".").filter(Boolean).length - 1;
  }

  /**
   * Ancestor user IDs parsed from the path string — no DB query.
   * Returns IDs from root down to the immediate parent (excludes self).
   *
   * path = '1.42.107.'  →  [1, 42]   (107 is self, excluded)
   */
  getAncestorIds(user: UserEntity): number[] {
    return user.path
      .split(".")
      .filter(Boolean)
      .slice(0, -1) // drop the last segment (this user's own id)
      .map(Number);
  }

  /**
   * Circular reference guard.
   * Returns true if adding potentialParentCode as the parent of userId
   * would create a cycle — i.e. userId already appears somewhere in
   * the potential parent's ancestry chain.
   *
   * Example: if userId = 42, and the candidate parent has path = '1.42.107.',
   * then '42.' appears in that path → circle detected.
   */
  async wouldCreateCircle(
    userId: number,
    potentialParentCode: string
  ): Promise<boolean> {
    const potentialParent = await this.userRepo.findOne({
      where: { referralCode: potentialParentCode },
    });
    if (!potentialParent) return false;

    // Check if userId appears as a segment in the candidate parent's path
    const userSegment = `${userId}.`;
    return potentialParent.path.includes(userSegment);
  }
}
```

### ReferralModule

```typescript
// apps/api/src/modules/referral/referral.module.ts
import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { UserEntity } from "../user/entities/user.entity";
import { ReferralService } from "./referral.service";

@Module({
  imports: [TypeOrmModule.forFeature([UserEntity])],
  providers: [ReferralService],
  exports: [ReferralService],
})
export class ReferralModule {}
```

Import `ReferralModule` in `AppModule` and in any feature module that needs it.

### Smoke Test — Section 3

```bash
yarn api:dev
```

Confirm the log shows:

```
[NestFactory] Starting Nest application...
[InstanceLoader] ReferralModule dependencies initialized
```

If `ReferralModule dependencies initialized` does not appear, check that `ReferralModule` is listed in `AppModule`'s `imports[]` and that `UserEntity` is in `AppModule`'s `entities[]`.

---

## 4. Wire into Registration

### Update RegisterInput

Add the optional `referredByCode` field to the registration input DTO.

```typescript
// apps/api/src/modules/auth/inputs/register.input.ts
import { Field, InputType } from "@nestjs/graphql";
import { IsEmail, IsOptional, IsString, MinLength } from "class-validator";

@InputType()
export class RegisterInput {
  @Field()
  @IsEmail()
  email: string;

  @Field()
  @MinLength(8)
  password: string;

  @Field({ nullable: true })
  @IsOptional()
  @IsString()
  referredByCode?: string;
}
```

### Update AuthService.register()

Inject `ReferralService` and call `initializeReferral` after the user is saved. The call happens after `save()` because `initializeReferral` needs the new row's `id`.

```typescript
// apps/api/src/modules/auth/auth.service.ts  (relevant excerpt)
import { Injectable } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { Repository } from "typeorm";
import * as bcrypt from "bcrypt";
import { UserEntity, UserStatus } from "../user/entities/user.entity";
import { ReferralService } from "../referral/referral.service";
import { RegisterInput } from "./inputs/register.input";

@Injectable()
export class AuthService {
  constructor(
    @InjectRepository(UserEntity)
    private readonly userRepo: Repository<UserEntity>,
    private readonly referralService: ReferralService
  ) {}

  async register(input: RegisterInput): Promise<UserEntity> {
    const hashed = await bcrypt.hash(input.password, 10);

    const user = this.userRepo.create({
      email: input.email,
      password: hashed,
      status: UserStatus.INACTIVE,
      tenantId: 1, // adjust for multi-tenant setup
    });

    await this.userRepo.save(user);

    // Always initialize — sets referralCode and path regardless of whether
    // the user supplied a referredByCode or signed up organically.
    await this.referralService.initializeReferral(
      user.id,
      input.referredByCode ?? null
    );

    return user;
  }
}
```

### Import ReferralModule in AuthModule

```typescript
// apps/api/src/modules/auth/auth.module.ts  (imports array excerpt)
imports: [
  TypeOrmModule.forFeature([UserEntity]),
  ReferralModule,  // add this
  // ... other imports
],
```

### GraphQL Mutation — Register with Referral Code

```graphql
mutation RegisterWithReferral {
  register(
    input: {
      email: "alice@example.com"
      password: "securepass"
      referredByCode: "REF-A1B2C3"
    }
  ) {
    id
    email
    referralCode
  }
}
```

Expected response after the migration has run:

```json
{
  "data": {
    "register": {
      "id": 42,
      "email": "alice@example.com",
      "referralCode": "REF-D4E5F6"
    }
  }
}
```

---

## 5. GraphQL Queries

### ReferralStats ObjectType

Define a lightweight response type for the stats query.

```typescript
// apps/api/src/modules/referral/dto/referral-stats.dto.ts
import { Field, Int, ObjectType } from "@nestjs/graphql";

@ObjectType()
export class ReferralStats {
  @Field(() => Int)
  directCount: number;

  @Field(() => Int)
  totalCount: number;

  @Field(() => Int)
  depth: number;

  @Field()
  referralCode: string;
}
```

### ReferralResolver

```typescript
// apps/api/src/modules/referral/referral.resolver.ts
import { UseGuards } from "@nestjs/common";
import { Query, Resolver } from "@nestjs/graphql";
import { InjectRepository } from "@nestjs/typeorm";
import { Repository } from "typeorm";
import { plainToInstance } from "class-transformer";
import { AuthJwtGuard } from "../auth/guards/auth-jwt.guard";
import { ACPermissionGuard } from "../auth/guards/ac-permission.guard";
import { UseACGuard } from "../auth/decorators/use-ac-guard.decorator";
import { CurrentUser } from "../auth/decorators/current-user.decorator";
import { AccessTokenInfo } from "../auth/interfaces/access-token-info.interface";
import { UserEntity } from "../user/entities/user.entity";
import { UserDto } from "../user/dto/user.dto";
import { ReferralService } from "./referral.service";
import { ReferralStats } from "./dto/referral-stats.dto";

@Resolver()
export class ReferralResolver {
  constructor(
    @InjectRepository(UserEntity)
    private readonly userRepo: Repository<UserEntity>,
    private readonly referralService: ReferralService
  ) {}

  /**
   * Returns the current user's referral statistics:
   * how many they referred directly, total downline, and their own tree depth.
   */
  @UseGuards(AuthJwtGuard, ACPermissionGuard)
  @UseACGuard("REFERRAL", ["view-referrals"])
  @Query(() => ReferralStats)
  async myReferralStats(
    @CurrentUser() currentUser: AccessTokenInfo
  ): Promise<ReferralStats> {
    const user = await this.userRepo.findOneOrFail({
      where: { id: currentUser.user.id },
    });

    const [directReferrals, totalCount] = await Promise.all([
      this.referralService.getDirectReferrals(user.id),
      this.referralService.countDescendants(user.id),
    ]);

    return {
      directCount: directReferrals.length,
      totalCount,
      depth: this.referralService.getDepth(user),
      referralCode: user.referralCode,
    };
  }

  /**
   * Returns all users in the current user's downline (any depth),
   * ordered by path (top of tree first).
   */
  @UseGuards(AuthJwtGuard, ACPermissionGuard)
  @UseACGuard("REFERRAL", ["view-referrals"])
  @Query(() => [UserDto])
  async myDownline(
    @CurrentUser() currentUser: AccessTokenInfo
  ): Promise<UserDto[]> {
    const descendants = await this.referralService.getAllDescendants(
      currentUser.user.id
    );
    return descendants.map(u => plainToInstance(UserDto, u));
  }
}
```

### GraphQL Playground Queries

Query your own referral stats:

```graphql
query MyReferralStats {
  myReferralStats {
    directCount
    totalCount
    depth
    referralCode
  }
}
```

Expected response for a root user with 3 direct referrals and 9 total descendants:

```json
{
  "data": {
    "myReferralStats": {
      "directCount": 3,
      "totalCount": 9,
      "depth": 0,
      "referralCode": "REF-A1B2C3"
    }
  }
}
```

Query your full downline:

```graphql
query MyDownline {
  myDownline {
    id
    email
  }
}
```

Expected: array of user objects ordered by their `path` column (breadth-first by insertion order).

### Add ReferralModule to Support Resolver

Update `ReferralModule` to include the resolver:

```typescript
// apps/api/src/modules/referral/referral.module.ts
import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { UserEntity } from "../user/entities/user.entity";
import { ReferralService } from "./referral.service";
import { ReferralResolver } from "./referral.resolver";

@Module({
  imports: [TypeOrmModule.forFeature([UserEntity])],
  providers: [ReferralService, ReferralResolver],
  exports: [ReferralService],
})
export class ReferralModule {}
```

### Smoke Test — Section 5

```bash
yarn api:dev
```

Open Apollo Sandbox at `http://localhost:3333/graphql`. Run `myReferralStats` with a valid JWT. Expected: the query resolves without a schema error and returns a `ReferralStats` object. If the permission slug `view-referrals` is not yet seeded, temporarily remove `ACPermissionGuard` for local testing, then re-add it before committing.

---

## 6. Seeder

The seeder builds a verifiable 3-level referral tree: 1 root, 3 level-1 users, 6 level-2 users — 10 users total with fully populated paths.

```typescript
// apps/api/src/seeders/referral-tree.seeder.ts
import { DataSource } from "typeorm";
import { Seeder } from "@jorgebodega/typeorm-seeding";
import * as bcrypt from "bcrypt";
import { UserEntity, UserStatus } from "../modules/user/entities/user.entity";
import { generateReferralCode } from "../helpers/referral-code";

export default class ReferralTreeSeeder implements Seeder {
  async run(dataSource: DataSource): Promise<void> {
    const userRepo = dataSource.getRepository(UserEntity);

    const hashed = await bcrypt.hash("Password1!", 10);

    // ----------------------------------------------------------------
    // Level 0: root user (no referrer)
    // ----------------------------------------------------------------
    const root = await userRepo.save(
      userRepo.create({
        email: "root@referral.test",
        password: hashed,
        status: UserStatus.ACTIVE,
        tenantId: 1,
        referralCode: generateReferralCode("ROOT"),
        referredByCode: null,
        path: "", // will be set below
      })
    );
    root.path = `${root.id}.`;
    await userRepo.save(root);

    // ----------------------------------------------------------------
    // Level 1: 3 users referred directly by root
    // ----------------------------------------------------------------
    const level1: UserEntity[] = [];
    for (let i = 1; i <= 3; i++) {
      const u = await userRepo.save(
        userRepo.create({
          email: `level1-${i}@referral.test`,
          password: hashed,
          status: UserStatus.ACTIVE,
          tenantId: 1,
          referralCode: generateReferralCode("L1"),
          referredByCode: root.referralCode,
          path: "",
        })
      );
      u.path = `${root.path}${u.id}.`;
      await userRepo.save(u);
      level1.push(u);
    }

    // ----------------------------------------------------------------
    // Level 2: 2 users per level-1 user (6 total)
    // ----------------------------------------------------------------
    for (const parent of level1) {
      for (let i = 1; i <= 2; i++) {
        const u = await userRepo.save(
          userRepo.create({
            email: `level2-${parent.id}-${i}@referral.test`,
            password: hashed,
            status: UserStatus.ACTIVE,
            tenantId: 1,
            referralCode: generateReferralCode("L2"),
            referredByCode: parent.referralCode,
            path: "",
          })
        );
        u.path = `${parent.path}${u.id}.`;
        await userRepo.save(u);
      }
    }

    // ----------------------------------------------------------------
    // Verify — assert path structure is correct
    // ----------------------------------------------------------------
    const rootUser = await userRepo.findOneOrFail({
      where: { email: "root@referral.test" },
    });
    console.log("[ReferralTreeSeeder] root path:", rootUser.path);
    // Expected: '1.'  (or whatever the root's actual id is)

    const l1Users = await userRepo
      .createQueryBuilder("u")
      .where("u.path LIKE :p", { p: `${rootUser.path}%.` })
      .andWhere(`LENGTH(u.path) - LENGTH(REPLACE(u.path, '.', '')) = 2`)
      .getMany();
    console.log("[ReferralTreeSeeder] level-1 count:", l1Users.length);
    // Expected: 3

    const allDescendants = await userRepo
      .createQueryBuilder("u")
      .where("u.path LIKE :p", { p: `${rootUser.path}%` })
      .getMany();
    console.log(
      "[ReferralTreeSeeder] total descendants:",
      allDescendants.length
    );
    // Expected: 9
  }
}
```

### Expected Path Values

After the seeder runs, the `path` column values will look like this (exact IDs depend on your sequence, but the structure is fixed):

```
root (id=1):          path = '1.'
  L1 user (id=2):     path = '1.2.'
    L2 user (id=5):   path = '1.2.5.'
    L2 user (id=6):   path = '1.2.6.'
  L1 user (id=3):     path = '1.3.'
    L2 user (id=7):   path = '1.3.7.'
    L2 user (id=8):   path = '1.3.8.'
  L1 user (id=4):     path = '1.4.'
    L2 user (id=9):   path = '1.4.9.'
    L2 user (id=10):  path = '1.4.10.'
```

### Run the Seeder

```bash
yarn api:seed:run
```

After seeding, query `myReferralStats` as the root user:

```json
{
  "data": {
    "myReferralStats": {
      "directCount": 3,
      "totalCount": 9,
      "depth": 0,
      "referralCode": "ROOT-..."
    }
  }
}
```

---

## 7. Migration

### Generate and Run

```bash
yarn api:migration:generate apps/api/src/migrations/AddReferralColumns
yarn api:migration:run
```

TypeORM diffs the entity against the current schema and generates a migration that adds the three columns. The generated file will look like this:

```typescript
// apps/api/src/migrations/1751234567890-AddReferralColumns.ts
import { MigrationInterface, QueryRunner } from "typeorm";

export class AddReferralColumns1751234567890 implements MigrationInterface {
  name = "AddReferralColumns1751234567890";

  public async up(queryRunner: QueryRunner): Promise<void> {
    // Add referral_code column (unique, nullable during migration)
    await queryRunner.query(`
      ALTER TABLE "user"
      ADD "referral_code" character varying
    `);
    await queryRunner.query(`
      ALTER TABLE "user"
      ADD CONSTRAINT "UQ_user_referral_code" UNIQUE ("referral_code")
    `);

    // Add referred_by_code column (nullable)
    await queryRunner.query(`
      ALTER TABLE "user"
      ADD "referred_by_code" character varying
    `);

    // Add path column (not null, default empty string)
    await queryRunner.query(`
      ALTER TABLE "user"
      ADD "path" character varying NOT NULL DEFAULT ''
    `);

    // Index on path for LIKE prefix queries
    await queryRunner.query(`
      CREATE INDEX "IDX_user_path" ON "user" ("path")
    `);

    // ----------------------------------------------------------------
    // Data migration for existing users
    // ----------------------------------------------------------------

    // 1. Assign referral codes to all existing users that don't have one
    await queryRunner.query(`
      UPDATE "user"
      SET referral_code = CONCAT('REF-', UPPER(SUBSTR(MD5(id::text), 1, 6)))
      WHERE referral_code IS NULL
    `);

    // 2. Set path for all existing users — treat them all as roots
    //    (no historical referral data to reconstruct)
    await queryRunner.query(`
      UPDATE "user"
      SET path = CONCAT(id::text, '.')
      WHERE path = '' OR path IS NULL
    `);
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`DROP INDEX "IDX_user_path"`);
    await queryRunner.query(`
      ALTER TABLE "user" DROP CONSTRAINT "UQ_user_referral_code"
    `);
    await queryRunner.query(`ALTER TABLE "user" DROP COLUMN "path"`);
    await queryRunner.query(
      `ALTER TABLE "user" DROP COLUMN "referred_by_code"`
    );
    await queryRunner.query(`ALTER TABLE "user" DROP COLUMN "referral_code"`);
  }
}
```

### Data Migration Notes

The data migration in `up()` does two things for existing rows:

**Step 1 — assign referral codes.** Uses `MD5(id::text)` seeded by the user's own ID to produce a deterministic 6-char hex code. This is not cryptographically meaningful — it just gets every existing user a code without requiring application code in the migration. After migration you can optionally regenerate codes via a one-off script if you want fully random codes for all existing users.

**Step 2 — set paths.** All existing users are treated as roots (`path = id + '.'`). There is no referral history to reconstruct from a flat `referredBy` column. New signups after this migration will have proper tree paths. If you had a flat `referredBy: userId` column before, write a separate migration to reconstruct the tree by walking parent pointers in topological order before running this one.

### Verify Migration

```bash
yarn api:migration:run
```

Check the result in psql or Adminer (`http://localhost:8080`):

```sql
SELECT id, email, referral_code, referred_by_code, path
FROM "user"
LIMIT 10;
```

Every row should have a non-null `referral_code` and a `path` ending with `.<id>.`.

### Always Test Revert

```bash
yarn api:migration:revert
```

Confirm the columns are dropped cleanly, then re-run:

```bash
yarn api:migration:run
```

---

## 8. Performance Notes

### Index Strategy

The `@Index()` on `path` is critical. PostgreSQL's btree index supports `LIKE 'prefix%'` queries when the pattern is left-anchored (no leading wildcard). The query `WHERE path LIKE '1.42.%'` uses the index. The query `WHERE path LIKE '%1.42%'` does not — never write a trailing-wildcard-only query against the path column.

The `@Index({ unique: true })` on `referralCode` makes code lookups O(1). Every registration and every `wouldCreateCircle` check hits this index.

### Depth-Segment Counting

The depth formula `path.split('.').filter(Boolean).length - 1` runs in application memory with zero DB round trips. For commission calculations that need the depth of every node in a 1,000-user downline, loading all rows via `getAllDescendants()` and computing depth client-side is cheaper than running a depth-counting SQL expression on every row.

### ltree Extension (for very large networks)

For referral trees exceeding 100k nodes or 10+ levels of depth, consider PostgreSQL's `ltree` extension. `ltree` is a dedicated hierarchical label type with GiST/GIN indexes that outperform btree on very large prefix scans. The trade-off is a harder migration path and tighter PostgreSQL coupling. For most affiliate programs (sub-100k users, sub-10 levels), a btree-indexed `VARCHAR` path column is sufficient and operationally simpler.

### Caching referralStats

`myReferralStats` is a read-heavy query that users check frequently. Cache the result in Redis with a short TTL (60–300 seconds):

```typescript
// Sketch — wire into ReferralResolver using CacheInterceptor or manually:
const cacheKey = `referral:stats:${userId}`;
const cached = await this.redis.get(cacheKey);
if (cached) return JSON.parse(cached);

const stats = await this.computeStats(userId);
await this.redis.set(cacheKey, JSON.stringify(stats), "EX", 300);
return stats;
```

Invalidate the cache key for a user's ancestors whenever a new user registers under them — their `totalCount` changes.

### Writes Are Cheap

Each registration triggers one `SELECT` (look up referrer by code) and one `UPDATE` (set path and referralCode). No parent rows are touched. This scales linearly with registration volume regardless of tree depth.

---

## Summary: Flat referredBy vs Materialized Path

| Concern                        | Flat adjacency list (`referredBy: userId`) | Materialized path (`path: string`)                       |
| ------------------------------ | ------------------------------------------ | -------------------------------------------------------- |
| Query complexity — descendants | O(depth) queries or recursive CTE          | O(1) — single `LIKE prefix%` query                       |
| Query complexity — ancestors   | O(depth) queries                           | O(1) — parse `path` string in application                |
| Write complexity               | O(1) — set one FK                          | O(1) — single UPDATE after INSERT                        |
| Depth lookup                   | O(depth) recursive hops                    | O(1) — count segments in `path` string                   |
| Descendant query               | Recursive CTE or N+1 loop                  | `WHERE path LIKE 'prefix%'`                              |
| Index type                     | btree on `referred_by_user_id`             | btree on `path` (left-anchored LIKE)                     |
| Circular reference check       | Walk ancestors in a loop                   | Check if `userId.` appears in candidate's `path`         |
| Commission calc (multi-level)  | Recursive loop, N queries                  | Parse `path`, batch `WHERE id IN (...)`                  |
| Schema complexity              | One FK column                              | Three columns (`referralCode`, `referredByCode`, `path`) |
| Max practical depth            | ~10 levels (CTE limit / performance)       | Hundreds of levels (string length is the only limit)     |

---

## What You Have Now

- **`apps/api/src/helpers/referral-code.ts`** — `generateReferralCode()` helper using `crypto.randomBytes`
- **`apps/api/src/modules/user/entities/user.entity.ts`** — `referralCode`, `referredByCode`, `path` columns added with proper indexes
- **`apps/api/src/modules/referral/referral.service.ts`** — `ReferralService` with `initializeReferral`, `getDirectReferrals`, `getAllDescendants`, `countDescendants`, `getDepth`, `getAncestorIds`, `wouldCreateCircle`
- **`apps/api/src/modules/referral/referral.module.ts`** — `ReferralModule` exporting `ReferralService`
- **`apps/api/src/modules/referral/dto/referral-stats.dto.ts`** — `ReferralStats` GraphQL ObjectType
- **`apps/api/src/modules/referral/referral.resolver.ts`** — `myReferralStats` and `myDownline` queries, guarded by `AuthJwtGuard` + `ACPermissionGuard`
- **`apps/api/src/modules/auth/inputs/register.input.ts`** — `referredByCode?: string` optional field
- **`apps/api/src/modules/auth/auth.service.ts`** — `register()` calls `referralService.initializeReferral()` after user save
- **`apps/api/src/seeders/referral-tree.seeder.ts`** — 10-user, 3-level referral tree with path assertions
- **Migration `AddReferralColumns`** — adds three columns, unique constraint on `referralCode`, btree index on `path`, data migration for existing users

Every user registered after this migration automatically receives a unique referral code and a path that correctly encodes their position in the tree. Subtree queries that previously required recursive CTEs or application-level loops now execute as a single indexed `LIKE` scan. Depth and ancestor lookups require no database round trips at all — the answer is encoded in the `path` string already loaded with the user record.
