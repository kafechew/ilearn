---
author: Kai
pubDatetime: 2026-05-07T09:00:00+08:00
title: Authentication, Guards & Security Patterns
featured: false
draft: false
slug: 6107-authentication-guards-security-patterns
tags:
  - deeptech
  - meteorjs
  - nestjs
  - security
  - auth
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/07-authentication-guards-security-patterns.png"
description: By the end of this part, you will learn RS256, AuthModule, Passport JWT, AuthJwtGuard, @CurrentUser, ValidationPipe, forbidNonWhitelisted and Dual-auth architecture.  

---

## What This Part Covers

- Why RS256 (RSA asymmetric JWT) instead of HS256 (HMAC)
- Generating and managing RSA key pairs
- Implementing the `AuthModule`: register, sign-in, refresh token
- `Passport` JWT strategy — how it validates incoming requests
- `AuthJwtGuard` — the `@UseGuards` that protects mutations and queries
- `@CurrentUser()` — the custom decorator that injects the authenticated user
- `ValidationPipe` with `forbidNonWhitelisted` — the global protection layer
- The ownership scoping pattern: why `userId` is never a `@Field()`
- `@IsUndefined()` vs `@IsOptional()` for partial updates
- Dual-auth architecture: user auth vs admin portal auth

---

## Meteor Equivalents

| Meteor | NestJS | Difference |
|--------|--------|-----------|
| `accounts-base` + `accounts-password` | `PassportModule` + `JwtModule` + `bcrypt` | Explicit implementation, auditable |
| `Meteor.userId()` | `@CurrentUser() user: AccessTokenUser` | Injected from verified JWT |
| `Meteor.user()` | `currentUser.user` (the UserEntity from DB) | |
| `if (!this.userId) throw new Meteor.Error()` | `@UseGuards(AuthJwtGuard)` | Declarative guard, applied at class/method level |
| DDP session token (in localStorage) | JWT `accessToken` (RS256) | Stateless, cryptographically verifiable |
| Galaxy login | `POST /graphql` with `Authorization: Bearer <token>` | Standard HTTP auth |

---

## 1. HS256 vs RS256: The Key Difference

All JWTs can use symmetric or asymmetric signing.

### HS256 (HMAC-SHA256) — Symmetric

```
One secret key: used to BOTH sign AND verify
```

Problem: every service that needs to verify tokens must have the secret. Any service that can verify can also forge tokens.

### RS256 (RSA-SHA256) — Asymmetric

```
Private key: only the auth service has it — used to SIGN tokens
Public key: every service can have it — used to VERIFY tokens
```

Benefits:
1. **Compartmentalisation.** A compromised downstream service cannot forge JWTs — it only has the public key.
2. **Independent rotation.** Rotate the user access key without affecting the admin portal key.
3. **Multiple key pairs.** This codebase uses three: `JWT` (user access), `JWT_REFRESH` (user refresh), `ADMIN_JWT` (admin portal). A stolen user token cannot be replayed against admin endpoints — different key pair, signature verification fails.

### Generating RSA Key Pairs

Run once locally. Generate fresh keys for each environment (dev, staging, production).

```bash
# User JWT key pair (4096-bit for security)
openssl genrsa -out jwt_private.pem 4096
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem

# Refresh token key pair
openssl genrsa -out jwt_refresh_private.pem 4096
openssl rsa -in jwt_refresh_private.pem -pubout -out jwt_refresh_public.pem
```

Convert to single-line format for `.env`:

```bash
# macOS/Linux: add \n line escaping
awk 'NF {sub(/\r/, ""); printf "%s\\n",$0;}' jwt_private.pem
```

Paste the output into `.env`:

```bash
JWT_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----\n"
JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\nMIIB...\n-----END PUBLIC KEY-----\n"
JWT_REFRESH_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
JWT_REFRESH_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n..."
```

> **Production:** Never store private keys in `.env` files committed to a repository. Use AWS Secrets Manager or Tencent SSM. The ECS task definition loads secrets at runtime from Secrets Manager — the key never touches disk or source control.

---

## 2. User Entity

The `UserEntity` is the foundation of authentication.

```typescript
// apps/api/src/modules/user/user.entity.ts
import { Column, Entity, Index } from 'typeorm';
import { AbstractEntity } from 'nestjs-dev-utilities';
import { UserStatus } from './user.constant';

@Entity({ name: 'user' })
export class UserEntity extends AbstractEntity {
  @Column()
  fullname: string;

  @Index()  // indexed because we look up users by username often
  @Column({ unique: true })
  username: string;

  @Index()  // indexed because we look up users by email often
  @Column({ unique: true })
  email: string;

  // NEVER expose this field in any DTO — it is never sent to clients
  @Column()
  password: string;

  @Column({ type: 'enum', enum: UserStatus, default: UserStatus.ACTIVE })
  status: UserStatus;

  // Optional: for 2FA (Part 11)
  @Column({ nullable: true })
  twoFactorSecret: string | null;
}
```

```typescript
// apps/api/src/modules/user/user.constant.ts
import { registerEnumType } from '@nestjs/graphql';

export enum UserStatus {
  ACTIVE = 'ACTIVE',
  INACTIVE = 'INACTIVE',
  SUSPENDED = 'SUSPENDED',
}
registerEnumType(UserStatus, { name: 'UserStatus' });
```

---

## 3. Auth DTOs

```typescript
// apps/api/src/modules/auth/dto/auth.input.ts
import { Field, InputType } from '@nestjs/graphql';
import { IsEmail, IsNotEmpty, IsString, MinLength, Matches } from 'class-validator';

@InputType()
export class RegisterInput {
  @Field()
  @IsString()
  @IsNotEmpty()
  fullname: string;

  @Field()
  @IsString()
  @IsNotEmpty()
  @Matches(/^[a-zA-Z0-9_]+$/, { message: 'Username can only contain letters, numbers, and underscores' })
  username: string;

  @Field()
  @IsEmail()
  email: string;

  @Field()
  @IsString()
  @MinLength(8, { message: 'Password must be at least 8 characters' })
  @Matches(/(?=.*[A-Z])(?=.*[0-9])/, {
    message: 'Password must contain at least one uppercase letter and one number',
  })
  password: string;
}

@InputType()
export class SignInInput {
  @Field()
  @IsString()
  @IsNotEmpty()
  username: string;  // username or email

  @Field()
  @IsString()
  @IsNotEmpty()
  password: string;
}

@InputType()
export class RefreshTokenInput {
  @Field()
  @IsString()
  @IsNotEmpty()
  refreshToken: string;
}
```

```typescript
// apps/api/src/modules/auth/dto/auth.dto.ts
import { Field, ObjectType } from '@nestjs/graphql';

@ObjectType()
export class AuthTokensDto {
  @Field()
  accessToken: string;

  @Field()
  refreshToken: string;
}
```

---

## 4. Auth Interface

Define the shape of the decoded JWT payload:

```typescript
// apps/api/src/modules/auth/auth.interface.ts
import { UserEntity } from '../user/user.entity';

export interface JwtPayload {
  sub: number;     // user id (standard JWT claim)
  username: string;
  iat: number;     // issued at
  exp: number;     // expires at
}

export interface AccessTokenUser {
  user: UserEntity;
}
```

---

## 5. Auth Service

```typescript
// apps/api/src/modules/auth/auth.service.ts
import { BadRequestException, Injectable, UnauthorizedException } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import { InjectRepository } from '@nestjs/typeorm';
import { ConfigService } from '@nestjs/config';
import { Repository } from 'typeorm';
import * as bcrypt from 'bcrypt';

import { UserEntity } from '../user/user.entity';
import { RegisterInput, SignInInput } from './dto/auth.input';
import { AuthTokensDto } from './dto/auth.dto';
import { JwtPayload } from './auth.interface';

@Injectable()
export class AuthService {
  constructor(
    @InjectRepository(UserEntity)
    private readonly userRepo: Repository<UserEntity>,
    private readonly jwtService: JwtService,
    private readonly config: ConfigService,
  ) {}

  async register(input: RegisterInput): Promise<AuthTokensDto> {
    // Check uniqueness
    const existingByUsername = await this.userRepo.findOne({ where: { username: input.username } });
    if (existingByUsername) throw new BadRequestException('Username already taken');

    const existingByEmail = await this.userRepo.findOne({ where: { email: input.email } });
    if (existingByEmail) throw new BadRequestException('Email already registered');

    // Hash password — never store plain text
    const hashedPassword = await bcrypt.hash(input.password, 12);

    const user = this.userRepo.create({ ...input, password: hashedPassword });
    const savedUser = await this.userRepo.save(user);

    return this.generateTokens(savedUser);
  }

  async signIn(input: SignInInput): Promise<AuthTokensDto> {
    // Find by username or email
    const user = await this.userRepo.findOne({
      where: [{ username: input.username }, { email: input.username }],
    });

    if (!user) throw new UnauthorizedException('Invalid credentials');

    // Compare password against stored hash
    const passwordMatch = await bcrypt.compare(input.password, user.password);
    if (!passwordMatch) throw new UnauthorizedException('Invalid credentials');

    if (user.status !== 'ACTIVE') throw new UnauthorizedException('Account is not active');

    return this.generateTokens(user);
  }

  async refreshToken(token: string): Promise<AuthTokensDto> {
    let payload: JwtPayload;
    try {
      // Verify with the REFRESH public key (different from access token key)
      payload = this.jwtService.verify(token, {
        publicKey: this.config.get('JWT_REFRESH_PUBLIC_KEY')?.replace(/\\n/g, '\n'),
        algorithms: ['RS256'],
      });
    } catch {
      throw new UnauthorizedException('Invalid refresh token');
    }

    const user = await this.userRepo.findOne({ where: { id: payload.sub } });
    if (!user) throw new UnauthorizedException('User not found');

    return this.generateTokens(user);
  }

  private generateTokens(user: UserEntity): AuthTokensDto {
    const payload: Partial<JwtPayload> = { sub: user.id, username: user.username };

    const accessToken = this.jwtService.sign(payload, {
      privateKey: this.config.get('JWT_PRIVATE_KEY')?.replace(/\\n/g, '\n'),
      algorithm: 'RS256',
      expiresIn: this.config.get('JWT_EXPIRATION_TIME') ?? '1d',
    });

    const refreshToken = this.jwtService.sign(payload, {
      privateKey: this.config.get('JWT_REFRESH_PRIVATE_KEY')?.replace(/\\n/g, '\n'),
      algorithm: 'RS256',
      expiresIn: this.config.get('JWT_REFRESH_EXPIRATION_TIME') ?? '7d',
    });

    return { accessToken, refreshToken };
  }
}
```

**Key security decisions:**

1. `bcrypt.hash(password, 12)` — bcrypt with 12 rounds. Higher rounds = harder to brute-force. 12 is the production standard.
2. `UnauthorizedException('Invalid credentials')` — the same error message for both "user not found" and "wrong password". Never reveal which one failed (timing attack mitigation).
3. Refresh token uses a **different private key** than the access token. A stolen access token cannot generate new access tokens.
4. `replace(/\\n/g, '\n')` — PEM keys in `.env` have `\n` as literal backslash-n. This converts them back to real newlines.

---

## 6. JWT Strategy (Passport)

The Passport strategy validates incoming requests. It runs automatically when `AuthJwtGuard` is applied to a resolver.

```typescript
// apps/api/src/modules/auth/strategies/jwt.strategy.ts
import { Injectable, UnauthorizedException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { PassportStrategy } from '@nestjs/passport';
import { InjectRepository } from '@nestjs/typeorm';
import { ExtractJwt, Strategy } from 'passport-jwt';
import { Repository } from 'typeorm';

import { UserEntity } from '../../user/user.entity';
import { JwtPayload, AccessTokenUser } from '../auth.interface';

@Injectable()
export class JwtStrategy extends PassportStrategy(Strategy, 'jwt') {
  constructor(
    private readonly config: ConfigService,
    @InjectRepository(UserEntity)
    private readonly userRepo: Repository<UserEntity>,
  ) {
    super({
      // Extract JWT from Authorization: Bearer <token> header
      jwtFromRequest: ExtractJwt.fromAuthHeaderAsBearerToken(),
      // Use the public key to VERIFY (not the private key)
      secretOrKey: config.get<string>('JWT_PUBLIC_KEY')?.replace(/\\n/g, '\n'),
      algorithms: ['RS256'],
    });
  }

  // Called after the JWT signature is verified
  // Whatever this returns is attached to req.user (and accessible via @CurrentUser())
  async validate(payload: JwtPayload): Promise<AccessTokenUser> {
    const user = await this.userRepo.findOne({
      where: { id: payload.sub },
    });

    if (!user) throw new UnauthorizedException('User not found or token revoked');
    if (user.status !== 'ACTIVE') throw new UnauthorizedException('Account is not active');

    return { user };
  }
}
```

**The validate flow:**
1. Request arrives with `Authorization: Bearer eyJ...`
2. Passport extracts the JWT from the header
3. Passport verifies the signature using `JWT_PUBLIC_KEY` and RS256 algorithm
4. If valid, calls `validate(payload)` with the decoded payload
5. `validate()` looks up the user from the DB, checks they are still active
6. Returns `{ user: UserEntity }` — this becomes `req.user`
7. `@CurrentUser()` extracts `req.user` in the resolver

**Why re-query the database in `validate()`?**

The JWT payload contains the user ID but the payload is cached in the token (immutable until expiry). If you ban a user, their token is still valid until expiry. By querying the database on every request, you check the current user status and can immediately block suspended accounts.

---

## 7. AuthJwtGuard

```typescript
// apps/api/src/modules/auth/guards/auth-jwt.guard.ts
import { AuthGuard } from '@nestjs/passport';

export class AuthJwtGuard extends AuthGuard('jwt') {
  // Inherits all logic from Passport's 'jwt' strategy
  // Override handleRequest() here if you need custom error handling
}
```

Usage in a resolver:

```typescript
@UseGuards(AuthJwtGuard)  // ← everything below this runs ONLY if JWT is valid
@Mutation(() => TodoDto)
async createTodo(
  @CurrentUser() currentUser: AccessTokenUser,
  @Args('input') input: CreateTodoInput,
) {
  // JWT is verified before we reach here
  // currentUser.user is a UserEntity — fully typed
}
```

---

## 8. `@CurrentUser()` Decorator

```typescript
// apps/api/src/modules/auth/decorators/current-user.decorator.ts
import { createParamDecorator, ExecutionContext } from '@nestjs/common';
import { GqlExecutionContext } from '@nestjs/graphql';
import { AccessTokenUser } from '../auth.interface';

export const CurrentUser = createParamDecorator(
  (_data: unknown, context: ExecutionContext): AccessTokenUser => {
    // For GraphQL, we extract from the GraphQL execution context
    const ctx = GqlExecutionContext.create(context);
    return ctx.getContext().req.user;
  },
);
```

**Why a custom decorator?** NestJS's default `@Request()` decorator gives you the raw Express request object. `@CurrentUser()` gives you the typed `AccessTokenUser` from `req.user` — already verified by the guard, fully typed, with the `UserEntity` attached.

---

## 9. Auth Resolver

```typescript
// apps/api/src/modules/auth/auth.resolver.ts
import { Args, Mutation, Query, Resolver } from '@nestjs/graphql';
import { UseGuards } from '@nestjs/common';

import { AuthService } from './auth.service';
import { AuthTokensDto } from './dto/auth.dto';
import { RegisterInput, RefreshTokenInput, SignInInput } from './dto/auth.input';
import { AuthJwtGuard } from './guards/auth-jwt.guard';
import { CurrentUser } from './decorators/current-user.decorator';
import { AccessTokenUser } from './auth.interface';
import { UserDto } from '../user/dto/user.dto';

@Resolver()
export class AuthResolver {
  constructor(private readonly authService: AuthService) {}

  // Public — no guard
  @Mutation(() => AuthTokensDto)
  async register(@Args('input') input: RegisterInput): Promise<AuthTokensDto> {
    return this.authService.register(input);
  }

  // Public — no guard
  @Mutation(() => AuthTokensDto)
  async signIn(@Args('input') input: SignInInput): Promise<AuthTokensDto> {
    return this.authService.signIn(input);
  }

  // Public — refresh token is the credential
  @Mutation(() => AuthTokensDto)
  async refreshToken(@Args('input') input: RefreshTokenInput): Promise<AuthTokensDto> {
    return this.authService.refreshToken(input.refreshToken);
  }

  // Protected — requires valid access token
  @UseGuards(AuthJwtGuard)
  @Query(() => UserDto)
  async me(@CurrentUser() currentUser: AccessTokenUser): Promise<UserDto> {
    return currentUser.user as UserDto;
  }
}
```

---

## 10. Auth Module

```typescript
// apps/api/src/modules/auth/auth.module.ts
import { Module } from '@nestjs/common';
import { JwtModule } from '@nestjs/jwt';
import { PassportModule } from '@nestjs/passport';
import { TypeOrmModule } from '@nestjs/typeorm';

import { UserEntity } from '../user/user.entity';
import { AuthResolver } from './auth.resolver';
import { AuthService } from './auth.service';
import { JwtStrategy } from './strategies/jwt.strategy';

@Module({
  imports: [
    TypeOrmModule.forFeature([UserEntity]),
    PassportModule.register({ defaultStrategy: 'jwt' }),
    JwtModule.register({}),  // configured per-call in service (privateKey varies)
  ],
  providers: [
    AuthResolver,
    AuthService,
    JwtStrategy,    // registers the Passport strategy with NestJS DI
  ],
  exports: [JwtStrategy, PassportModule],  // export so other modules can use the guard
})
export class AuthModule {}
```

Register in `AppModule`:

```typescript
import { AuthModule } from './modules/auth/auth.module';
import { UserEntity } from './modules/user/user.entity';

@Module({
  imports: [
    TypeOrmModule.forRootAsync({
      useFactory: () => ({
        entities: [UserEntity, /* ... */],
      }),
    }),
    AuthModule,
  ],
})
export class AppModule {}
```

---

## 11. ValidationPipe — The Global Guard

`ValidationPipe` runs `class-validator` decorators on every input automatically. It is registered in `main.ts`:

```typescript
app.useGlobalPipes(
  new ValidationPipe({
    whitelist: true,              // strip unknown fields
    forbidNonWhitelisted: true,   // reject requests with unknown fields
    transform: true,              // convert JSON to typed DTO instances
  }),
);
```

### Why `forbidNonWhitelisted: true`?

Without it:

```http
POST /graphql
{ "mutation": "createUser(input: { email: 'x', password: 'y', isAdmin: true })" }
```

`whitelist: true` alone would strip `isAdmin` silently — the request passes. If a developer forgot to add `isAdmin` validation but the field was mapped by TypeORM, it could be set.

With `forbidNonWhitelisted: true`:

```json
{ "statusCode": 400, "message": ["property isAdmin should not exist"] }
```

The request is rejected. The attack surface is explicit.

---

## 12. `@IsUndefined()` vs `@IsOptional()` — The Partial Update Problem

For update input DTOs, you want fields to be optional — but with a subtle difference.

### The problem with `@IsOptional()`

```typescript
@InputType()
export class UpdateTodoInput {
  @Field({ nullable: true })
  @IsOptional()  // ← WRONG for required fields
  @IsString()
  text?: string;
}
```

`@IsOptional()` skips all validation if the value is `null` or `undefined`. This means:
- Client sends `{ "text": null }` → `@IsOptional()` skips `@IsString()` → `null` passes → `text` is set to `null` in DB

But `todo.text` is required (`NOT NULL` in the DB). Setting it to `null` causes a database error (or silently corrupts data if the column is nullable).

### The solution: `@IsUndefined()`

```typescript
@InputType()
export class UpdateTodoInput {
  @Field({ nullable: true })
  @IsUndefined({ each: false })  // ← validates: if present, must not be null
  @IsString()
  text?: string;
}
```

`@IsUndefined()` means: if the field is present in the request, it must be `undefined` (i.e., the field was omitted). If the client explicitly sends `null`, it is NOT `undefined`, so the validation fails with 400.

In practice:
- Field omitted → `undefined` → passes validation → field is not updated
- Field set to `null` → not `undefined` → 400 Bad Request
- Field set to a valid string → `@IsString()` validates normally → field is updated

---

## 13. Dual Auth: User vs Admin Portal

The codebase maintains two separate auth stacks:

| | User Auth | Admin Portal Auth |
|--|-----------|------------------|
| JWT key pair | `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY` | `ADMIN_JWT_PRIVATE_KEY` / `ADMIN_JWT_PUBLIC_KEY` |
| Passport strategy | `JwtStrategy` (`'jwt'`) | `PortalJwtStrategy` (`'portal-jwt'`) |
| Guard | `AuthJwtGuard` | `PortalAuthJwtGuard` |
| Audience | End users (web/mobile app) | Admin operators (admin portal) |

The admin portal has its own `portal-auth` module, its own resolver, its own strategy. The two stacks are completely independent.

**Why this matters:** A stolen user JWT cannot be replayed against admin endpoints. The `PortalAuthJwtGuard` uses `PortalJwtStrategy` which verifies against `ADMIN_JWT_PUBLIC_KEY`. The user JWT was signed with `JWT_PRIVATE_KEY` — the signature verification against `ADMIN_JWT_PUBLIC_KEY` will fail.

The admin strategy also checks roles:

```typescript
// portal-jwt.strategy.ts
async validate(payload: JwtPayload): Promise<PortalTokenUser> {
  const portalUser = await this.portalUserRepo.findOne({
    where: { id: payload.sub },
    relations: ['roles'],
  });
  if (!portalUser) throw new UnauthorizedException();
  if (!portalUser.isActive) throw new UnauthorizedException('Account disabled');
  return { portalUser };
}
```

---

## 14. Complete Authentication Flow

```
REGISTRATION:
Client → POST /graphql { mutation: register(input: {...}) }
  → ValidationPipe validates RegisterInput
  → AuthResolver.register() called
  → AuthService.register():
      1. Check username/email uniqueness
      2. bcrypt.hash(password, 12)
      3. repo.save(user)
      4. generateTokens(user) → RS256 signed accessToken + refreshToken
  → Return { accessToken, refreshToken }
  → Client stores accessToken in memory, refreshToken in httpOnly cookie or localStorage

SUBSEQUENT REQUESTS:
Client → POST /graphql { Authorization: Bearer <accessToken> }
  → AuthJwtGuard triggers JwtStrategy
  → JwtStrategy.validate():
      1. Verify RS256 signature against JWT_PUBLIC_KEY
      2. Decode payload: { sub: 1, username: "alice" }
      3. DB query: userRepo.findOne({ where: { id: 1 } })
      4. Check user.status === ACTIVE
      5. Return { user: UserEntity } → attached to req.user
  → Resolver executes with @CurrentUser() giving full UserEntity

TOKEN REFRESH:
Client → POST /graphql { mutation: refreshToken(input: { refreshToken: "..." }) }
  → AuthService.refreshToken():
      1. Verify refresh token against JWT_REFRESH_PUBLIC_KEY
      2. Decode payload, look up user
      3. generateTokens(user) → new accessToken + refreshToken
  → Client replaces stored tokens
```

---

## 15. Security Checklist

Run through this for every new module:

```
[ ] All mutations have @UseGuards(AuthJwtGuard) — or are explicitly public
[ ] Sensitive queries have @UseGuards(AuthJwtGuard)
[ ] userId is NOT a @Field() on any input DTO (set server-side from JWT)
[ ] Update/delete operations filter by userId: { eq: currentUser.user.id }
[ ] Partial update inputs use @IsUndefined() not @IsOptional() for required fields
[ ] Passwords are hashed with bcrypt (never stored in plain text or encrypted)
[ ] No secrets in code — all from ConfigService / env vars
[ ] New entities soft-delete sensitive data (never hard-delete permissions, audit records)
[ ] New public endpoints are rate-limited with @nestjs/throttler
```

---

## 16. Testing Auth in the GraphQL Playground

With the `AuthModule` registered, test the full auth flow:

**Step 1: Register**

```graphql
mutation {
  register(input: {
    fullname: "Alice Developer"
    username: "alice"
    email: "alice@example.com"
    password: "Secret123!"
  }) {
    accessToken
    refreshToken
  }
}
```

**Step 2: Copy the accessToken, paste into HTTP Headers:**

```json
{ "Authorization": "Bearer eyJhbGci..." }
```

**Step 3: Query the authenticated user:**

```graphql
query {
  me {
    id
    fullname
    email
    status
  }
}
```

**Step 4: Try an authenticated mutation:**

```graphql
mutation {
  createTodo(input: { text: "Buy groceries" }) {
    id
    text
    isChecked
  }
}
```

**Step 5: Try without the Authorization header:**

```graphql
mutation {
  createTodo(input: { text: "This should fail" }) { id }
}
```

Expected response: `{ "errors": [{ "message": "Unauthorized" }] }`

---

## Summary

| Meteor | Enterprise NestJS |
|--------|-------------------|
| `accounts-base` (implicit) | Passport JWT strategy (explicit, auditable) |
| `Meteor.userId()` | `@CurrentUser() user: AccessTokenUser` (from verified JWT) |
| `.allow() / .deny()` | `@UseGuards(AuthJwtGuard)` on every mutation/query |
| Single auth layer | Dual-auth: user JWT + admin portal JWT (separate key pairs) |
| No password policy | `@MinLength(8)` + `@Matches(/(?=.*[A-Z])/)` + bcrypt(12) |
| DDP session token | RS256 JWT (access + refresh) |
| `check(text, String)` | `class-validator` + `ValidationPipe` (globally enforced) |
| No concept | `@IsUndefined()` for safe partial updates |
| No concept | `userId` never a `@Field()` — injected from JWT server-side |

---

## What You Have Now

After Parts 01-07, you have:
- ✅ Full environment (Node, Yarn, Docker, VS Code, Nx workspace)
- ✅ NestJS app with GraphQL, TypeORM, CQRS
- ✅ PostgreSQL + Redis in Docker
- ✅ Entity + migration pattern
- ✅ Full CQRS pipeline: Command → Handler → Service → Repository
- ✅ GraphQL DTOs: @ObjectType, @InputType, cursor pagination
- ✅ Next.js frontend with Apollo Client + Shadcn UI
- ✅ RS256 JWT authentication, Passport strategy, guards, decorators
- ✅ Global ValidationPipe with security hardening

In Part 08, you will apply all of this to build the first complete module from scratch — the `Tag` module — following the 9-step checklist end-to-end with tests.
