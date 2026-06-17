---
author: Kai
pubDatetime: 2026-05-21T09:00:00+08:00
title: Dual-App Monorepo — Portal API & Platform Interceptor
featured: false
draft: false
slug: 6121-dual-app-portal-api-platform-interceptor
tags:
  - deeptech
  - nestjs
  - nx
  - security
  - typescript
  - backend
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/21-dual-app-portal-api-platform-interceptor.png"
description: Add a second NestJS app (portal-api) for your internal operations team, wire up a RequestPlatformInterceptor that prevents user JWTs from working on the admin portal, and complete the enterprise-todo monorepo as a fullstack replacement scaffold.
---

## What This Part Covers

The previous tutorial extracted `libs/core` specifically to prepare for this moment: adding a second NestJS application to the monorepo without duplicating config. This tutorial makes that concrete by building `apps/portal-api` — a separate backend for your internal operations and support team.

- Why structural separation is safer than guard-only separation
- Generating `apps/portal-api` in the existing Nx 22 monorepo
- Sharing `libs/core` config and `libs/contracts` types across both apps
- Adding a `platform` claim to JWT payloads (`'user'` | `'portal'`)
- `RequestPlatformInterceptor` — enforces the platform claim on every authenticated request
- `PortalAuthModule` + `PortalJwtStrategy` wired in `portal-api` only
- Separate RS256 key pairs per app — cryptographic isolation, not just logical separation
- Smoke test: user token rejected on portal-api, portal token rejected on api

---

## Meteor Equivalents

| Concept              | Meteor                                             | NestJS dual-app                                             |
| -------------------- | -------------------------------------------------- | ----------------------------------------------------------- |
| Admin portal         | Same Meteor app, different publication/method      | Separate NestJS app, separate port, separate RS256 key pair |
| Platform separation  | No native support — relies entirely on role checks | JWT `platform` claim + interceptor — structural enforcement |
| Shared types         | Same codebase — no boundary                        | `libs/contracts` imported by both apps                      |
| Shared config        | Same `settings.json`                               | `libs/core` `CoreConfigModule`, both apps import it         |
| Admin authentication | Same `accounts` package, `isAdmin` role check      | `PortalJwtStrategy` using a completely different key pair   |

Meteor's single-app model meant that a role check was the only thing standing between a regular user and an admin operation. If a developer called the wrong method from the client, or if a method forgot its `check(this.userId, Roles.userIsInRole(...))` call, the operation succeeded. The NestJS dual-app model makes that class of mistake structurally impossible: the wrong key pair is rejected at the cryptographic level before any application code runs.

---

## 1. Why Two Apps, Not One App with Two Guards?

### The Threat Model

The "one app with two guard classes" approach is a common first attempt. It looks like this:

```typescript
// Single app — PortalAuthGuard and AuthGuard both registered
@Mutation()
@UseGuards(PortalAuthGuard)  // only portal admins should call this
async deleteUser(@Args('id') id: number) {
  // ...
}
```

The problem is disciplinary, not technical. Every new admin resolver requires the developer to remember to add `@UseGuards(PortalAuthGuard)`. Forget it once — perhaps during a late-night incident response — and a regular user JWT can reach the admin mutation. The only protection is developer discipline applied consistently across every future change.

The two-app model makes this structurally impossible:

```
apps/api         — registers AuthJwtStrategy (user RS256 key pair)
apps/portal-api  — registers PortalJwtStrategy (admin RS256 key pair)
```

`apps/portal-api` does not have `AuthJwtStrategy` registered. Passport does not know the user key pair exists. A user JWT hits `apps/portal-api`, Passport attempts to verify it with the admin public key, the RS256 signature check fails, and the request is rejected with `401 Unauthorized` — before `@UseGuards` is even evaluated, before any resolver runs, before any application code executes.

There is a second failure mode the two-app model closes: a portal admin who copies their JWT and uses it against the user API. The admin key pair is different from the user key pair, so the signature check fails at `apps/api` too. But what if, in a future refactor, both apps accidentally share the same key pair? That is where the `RequestPlatformInterceptor` provides a second layer: the `platform` claim in the JWT payload is checked even after signature verification succeeds.

### Architecture Diagram

```
Internet
   │
   ├─ :3333  apps/api        (AuthJwtStrategy — user RS256 key pair)
   │                          → @UseGuards(AuthJwtGuard)
   │                          → RequestPlatformInterceptor('user')
   │
   └─ :3334  apps/portal-api  (PortalJwtStrategy — admin RS256 key pair)
                               → @UseGuards(PortalAuthJwtGuard)
                               → RequestPlatformInterceptor('portal')

libs/core       → CoreConfigModule, AppConfig, QUEUE_NAMES, REDIS_KEYS
libs/contracts  → JwtPayload, shared TypeScript types
```

Separate ports means separate DNS records in production (`api.example.com` vs `portal.example.com`). The infrastructure team can apply different firewall rules, rate limits, and WAF policies at the load balancer level — neither can be misconfigured to accept traffic intended for the other.

---

## 2. Generate portal-api

### Run the Nx Generator

```bash
npx nx generate @nx/nest:app portal-api --directory=apps/portal-api
```

Nx will scaffold:

```
apps/portal-api/
  src/
    app/
      app.controller.spec.ts
      app.controller.ts
      app.module.ts
      app.service.spec.ts
      app.service.ts
    main.ts
  project.json
  tsconfig.app.json
  tsconfig.json
  tsconfig.spec.json
  webpack.config.js
```

The generated `AppModule` is a minimal skeleton. You will replace it with `PortalAppModule` in Section 3.

### Add Scripts to package.json

```json
{
  "scripts": {
    "portal:dev": "nx serve portal-api",
    "portal:build": "nx build portal-api",
    "portal:test": "nx test portal-api",
    "portal:e2e": "nx e2e portal-api-e2e"
  }
}
```

### Update main.ts to Use Port 3334

> **Before the import works:** Make sure `libs/core/src/index.ts` exports the interceptor factory:
> ```typescript
> export { createPlatformInterceptor } from './lib/interceptors/request-platform.interceptor';
> ```
> The full interceptor implementation and barrel export are covered in Section 5. If you are following this tutorial top-to-bottom, implement Section 5 first before running `portal-api`.

Replace the generated `apps/portal-api/src/main.ts`:

```typescript
// apps/portal-api/src/main.ts
import { NestFactory } from "@nestjs/core";
import { ValidationPipe } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { createPlatformInterceptor } from "@enterprise-todo/core";
import { PortalAppModule } from "./app/app.module";

async function bootstrap() {
  const app = await NestFactory.create(PortalAppModule);
  const config = app.get(ConfigService);

  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      forbidNonWhitelisted: true,
      transform: true,
    })
  );

  app.enableCors({
    origin:
      config.get("NODE_ENV") === "development"
        ? "*"
        : process.env.PORTAL_ALLOWED_ORIGINS,
  });

  // Rejects any request whose JWT carries platform !== 'portal'
  // Runs after Passport validates the JWT signature
  app.useGlobalInterceptors(new (createPlatformInterceptor("portal"))());

  const port = config.get<number>("PROJECT_PORTAL_PORT") ?? 3334;
  await app.listen(port);

  console.log(`Portal API running at http://localhost:${port}`);
  console.log(`GraphQL Playground: http://localhost:${port}/graphql`);
}

bootstrap();
```

### Add portalPort to libs/core Config

Add the new environment variable to `libs/core/src/config/config.validation.ts`:

```typescript
// libs/core/src/config/config.validation.ts  (add to existing Joi.object)
PROJECT_PORTAL_PORT: Joi.number().default(3334),
```

Add the typed field to `libs/core/src/config/config.mapper.ts`:

```typescript
// libs/core/src/config/config.mapper.ts
export type AppConfig = {
  // ... existing fields ...
  portalPort: number;

  // Admin JWT (separate key pair from user JWT)
  adminJwt: {
    privateKey: string;
    publicKey: string;
    expiresIn: string;
  };
};

export const configuration = (): AppConfig => ({
  // ... existing mappings ...
  portalPort: parseInt(process.env["PROJECT_PORTAL_PORT"] ?? "3334", 10),

  adminJwt: {
    privateKey: process.env["ADMIN_JWT_PRIVATE_KEY"] ?? "",
    publicKey: process.env["ADMIN_JWT_PUBLIC_KEY"] ?? "",
    expiresIn: process.env["ADMIN_JWT_EXPIRATION_TIME"] ?? "8h",
  },
});
```

Add the new env vars to `.env`:

```bash
# Portal API
PROJECT_PORTAL_PORT=3334

# Admin JWT — separate RS256 key pair from user JWT
ADMIN_JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
ADMIN_JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
ADMIN_JWT_EXPIRATION_TIME=8h
```

### Verify: portal-api Starts

```bash
yarn portal:dev
# Expected: "Portal API running at http://localhost:3334"

curl http://localhost:3334/graphql -X POST \
  -H "Content-Type: application/json" \
  -d '{"query":"{ __typename }"}'
# Expected: {"data":{"__typename":"Query"}}
```

Both apps can run simultaneously in separate terminals. `yarn api:dev` on port 3333, `yarn portal:dev` on port 3334.

---

## 3. Shared Libs in portal-api

### PortalAppModule

Replace the generated `apps/portal-api/src/app/app.module.ts`:

```typescript
// apps/portal-api/src/app/app.module.ts
import { Module } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { GraphQLModule } from "@nestjs/graphql";
import { ApolloDriver, ApolloDriverConfig } from "@nestjs/apollo";
import { CqrsModule } from "@nestjs/cqrs";

// Imported from libs/core — identical config, zero duplication
import { CoreConfigModule, AppConfig } from "@enterprise-todo/core";

import { PortalHealthModule } from "../modules/portal-health/portal-health.module";
import { PortalAuthModule } from "../modules/portal-auth/portal-auth.module";

@Module({
  imports: [
    // Same CoreConfigModule as apps/api — reads the same .env, same Joi schema
    CoreConfigModule,

    CqrsModule.forRoot(),

    GraphQLModule.forRootAsync<ApolloDriverConfig>({
      driver: ApolloDriver,
      inject: [ConfigService],
      useFactory: (config: ConfigService) => ({
        autoSchemaFile: true,
        playground:
          config.get<AppConfig["graphql"]>("graphql")?.playground ?? false,
        context: ({ req }: { req: Request }) => ({ req }),
      }),
    }),

    // Portal-specific modules — no AuthModule, no UserModule from apps/api
    PortalAuthModule,
    PortalHealthModule,
  ],
})
export class PortalAppModule {}
```

> **Portal DB config:** `portal-api` shares the same database as `backend` (same PostgreSQL instance, same migrations). Its `TypeOrmModule.forRootAsync` config is identical to `AppModule`'s setup in `apps/backend` — copy it and substitute `PortalConfigService` where applicable. Do NOT run separate migrations for `portal-api`; the single migration source of truth is `apps/backend/src/migrations/`.

The critical point: `PortalAppModule` imports `CoreConfigModule` from `@enterprise-todo/core` (shared), but it does NOT import `AuthModule` from `apps/api`. It has its own `PortalAuthModule`. Because Nx enforces app boundary rules, `apps/portal-api` cannot import directly from `apps/api` — any shared code must go through a library.

### PortalHealthModule

Create a minimal health resolver so the portal has something to hit before auth is wired:

```typescript
// apps/portal-api/src/modules/portal-health/portal-health.resolver.ts
import { Query, Resolver } from "@nestjs/graphql";

@Resolver()
export class PortalHealthResolver {
  @Query(() => String)
  portalHealth(): string {
    return "ok";
  }
}
```

```typescript
// apps/portal-api/src/modules/portal-health/portal-health.module.ts
import { Module } from "@nestjs/common";
import { PortalHealthResolver } from "./portal-health.resolver";

@Module({
  providers: [PortalHealthResolver],
})
export class PortalHealthModule {}
```

### Verify: Shared Config Working

```bash
yarn portal:dev

curl http://localhost:3334/graphql -X POST \
  -H "Content-Type: application/json" \
  -d '{"query":"{ portalHealth }"}'
# Expected: {"data":{"portalHealth":"ok"}}
```

If this fails with `Cannot find module '@enterprise-todo/core'`, verify that `tsconfig.base.json` has both path aliases:

```json
{
  "compilerOptions": {
    "paths": {
      "@enterprise-todo/contracts": ["./libs/contracts/src/index.ts"],
      "@enterprise-todo/core": ["./libs/core/src/index.ts"]
    }
  }
}
```

---

## 4. Platform Claim in JWT

### Update JwtPayload Type

The `platform` claim is the key that ties everything together. Add it to the shared type in `libs/contracts`:

```typescript
// libs/contracts/src/auth/jwt-payload.type.ts
export type Platform = "user" | "portal";

export type JwtPayload = {
  sub: number; // userId or portalUserId
  email: string;
  platform: Platform; // enforced by RequestPlatformInterceptor
  iat?: number;
  exp?: number;
};
```

Export the new `Platform` type from the contracts index:

```typescript
// libs/contracts/src/index.ts  (add to existing exports)
export type { JwtPayload, Platform } from "./auth/jwt-payload.type";
```

### Stamp platform: 'user' in apps/api

The `AccessTokenFactory` (or equivalent service in `apps/api`'s `AuthModule`) must sign every user token with `platform: 'user'`:

```typescript
// apps/api/src/modules/auth/access-token.factory.ts
import { Injectable } from "@nestjs/common";
import { JwtService } from "@nestjs/jwt";
import { JwtPayload } from "@enterprise-todo/contracts";
import { UserEntity } from "../user/user.entity";

@Injectable()
export class AccessTokenFactory {
  constructor(private readonly jwtService: JwtService) {}

  sign(user: UserEntity): string {
    const payload: JwtPayload = {
      sub: user.id,
      email: user.email,
      platform: "user", // ← always 'user' — cannot be overridden by input
    };
    return this.jwtService.sign(payload);
  }
}
```

The `platform` value is hardcoded in the factory — it is never derived from request input. A caller cannot forge a `platform: 'portal'` claim because the claim is set by the server code, not read from the request body.

### Stamp platform: 'portal' in apps/portal-api

The `PortalAccessTokenFactory` in `portal-api` signs every admin token with `platform: 'portal'`:

```typescript
// apps/portal-api/src/modules/portal-auth/portal-access-token.factory.ts
import { Injectable } from "@nestjs/common";
import { JwtService } from "@nestjs/jwt";
import { JwtPayload } from "@enterprise-todo/contracts";
import { PortalUserEntity } from "./portal-user.entity";

@Injectable()
export class PortalAccessTokenFactory {
  constructor(private readonly jwtService: JwtService) {}

  sign(portalUser: PortalUserEntity): string {
    const payload: JwtPayload = {
      sub: portalUser.id,
      email: portalUser.email,
      platform: "portal", // ← always 'portal' — hardcoded in server code
    };
    return this.jwtService.sign(payload);
  }
}
```

### Why the Claim Is Trustworthy

The `platform` claim is part of the JWT payload, which is signed with the RS256 private key. To forge a `platform: 'portal'` claim in a user token, an attacker would need the `ADMIN_JWT_PRIVATE_KEY` — the same private key that the portal server keeps secret and never exposes. Without it, any modification to the payload invalidates the signature, and Passport's `verify()` call rejects the token.

This means the interceptor check is not a second authentication step — it is a semantic check on a claim you already trust because the signature verified.

---

## 5. RequestPlatformInterceptor

### Create the Interceptor in libs/core

```typescript
// libs/core/src/interceptors/request-platform.interceptor.ts
import {
  CallHandler,
  ExecutionContext,
  ForbiddenException,
  Injectable,
  NestInterceptor,
} from "@nestjs/common";
import { GqlExecutionContext } from "@nestjs/graphql";
import { Observable } from "rxjs";
import { Platform } from "@enterprise-todo/contracts";

/**
 * Factory function that returns a NestInterceptor class bound to a specific platform.
 *
 * Usage in main.ts:
 *   app.useGlobalInterceptors(new (createPlatformInterceptor('user'))());
 *
 * The interceptor runs AFTER Passport validates the JWT signature and sets req.user.
 * For unauthenticated requests (no req.user), it passes through — auth guards handle those.
 * For authenticated requests, it checks user.platform === expectedPlatform.
 */
export function createPlatformInterceptor(expectedPlatform: Platform) {
  @Injectable()
  class RequestPlatformInterceptor implements NestInterceptor {
    intercept(
      context: ExecutionContext,
      next: CallHandler
    ): Observable<unknown> {
      const gqlCtx = GqlExecutionContext.create(context);
      const req = gqlCtx.getContext<{ req: { user?: { platform?: string } } }>()
        .req;
      const user = req?.user;

      // No user on the request — unauthenticated path, let auth guards handle it
      if (!user) {
        return next.handle();
      }

      if (user.platform !== expectedPlatform) {
        throw new ForbiddenException(
          `This endpoint requires a '${expectedPlatform}' token. ` +
            `Received '${user.platform ?? "unknown"}' token.`
        );
      }

      return next.handle();
    }
  }

  return RequestPlatformInterceptor;
}
```

### Export from libs/core

```typescript
// libs/core/src/index.ts  (add to existing exports)
export { createPlatformInterceptor } from "./interceptors/request-platform.interceptor";
```

### Wire into apps/api main.ts

```typescript
// apps/api/src/main.ts
import { NestFactory } from "@nestjs/core";
import { ValidationPipe } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { createPlatformInterceptor } from "@enterprise-todo/core";
import { AppModule } from "./app/app.module";

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  const config = app.get(ConfigService);

  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      forbidNonWhitelisted: true,
      transform: true,
    })
  );

  app.enableCors({
    origin:
      config.get("NODE_ENV") === "development"
        ? "*"
        : process.env.ALLOWED_ORIGINS,
  });

  // Rejects any authenticated request whose JWT carries platform !== 'user'
  // A portal admin token (platform: 'portal') gets 403 Forbidden here
  app.useGlobalInterceptors(new (createPlatformInterceptor("user"))());

  const port = config.get<number>("PROJECT_PORT") ?? 3333;
  await app.listen(port);

  console.log(`API running at http://localhost:${port}`);
  console.log(`GraphQL Playground: http://localhost:${port}/graphql`);
}

bootstrap();
```

### Why a Factory Function, Not a Class with a Constructor Parameter

NestJS's `useGlobalInterceptors` and `APP_INTERCEPTOR` both expect a class instance. You cannot pass a parameter to a class instantiated by the DI container without a custom provider. The factory function pattern sidesteps this: `createPlatformInterceptor('user')` returns a new class with `expectedPlatform` closed over in its scope. The returned class is a fully valid `NestInterceptor` with no constructor parameters, so it works with `useGlobalInterceptors` directly.

An alternative is a module-level interceptor with `APP_INTERCEPTOR`, but that requires the `expectedPlatform` to be an injectable token — more wiring for the same result.

### Verify: Interceptor Installed

```bash
# Start user API with the interceptor wired
yarn api:dev

# A request with no auth header (no user on req) should pass through
curl http://localhost:3333/graphql -X POST \
  -H "Content-Type: application/json" \
  -d '{"query":"{ health }"}'
# Expected: {"data":{"health":"ok"}}
# (health resolver has no auth guard — unauthenticated path bypasses the interceptor check)
```

---

## 6. Admin RS256 Key Pair

### Generate the Portal Key Pair

```bash
# Generate a new 4096-bit RSA key pair for the portal (separate from user JWT keys)
openssl genrsa 4096 | openssl pkcs8 -topk8 -nocrypt -out portal_private.pem
openssl rsa -in portal_private.pem -pubout -out portal_public.pem

# View the private key for .env (escape newlines)
cat portal_private.pem
cat portal_public.pem
```

Add both to `.env` as single-line strings with `\n` for newlines (same format as the existing `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY`):

```bash
ADMIN_JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nMIIEvAIBADANBg...\n-----END PRIVATE KEY-----"
ADMIN_JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkq...\n-----END PUBLIC KEY-----"
ADMIN_JWT_EXPIRATION_TIME=8h
```

Add the Joi validation for the new fields in `libs/core/src/config/config.validation.ts`:

```typescript
// libs/core/src/config/config.validation.ts  (add to Joi.object)
ADMIN_JWT_PRIVATE_KEY: Joi.string().required(),
ADMIN_JWT_PUBLIC_KEY: Joi.string().required(),
ADMIN_JWT_EXPIRATION_TIME: Joi.string().default('8h'),
```

The user API does not use these keys. Only `apps/portal-api`'s `PortalAuthModule` references `adminJwt` from the config. But they live in `libs/core`'s Joi schema so that both apps validate all env vars at startup — if an admin key is missing, both apps refuse to start with a clear error, rather than `portal-api` failing at runtime on the first login attempt.

---

## 7. PortalAuthModule in portal-api

### PortalUserEntity

The portal user is a separate entity from the user-facing `UserEntity`. Portal users are your internal operations team — a different table, different password policies, different onboarding flow.

```typescript
// apps/portal-api/src/modules/portal-auth/portal-user.entity.ts
import { Column, Entity, Index } from "typeorm";
import { AbstractEntity } from "nestjs-dev-utilities";

export enum PortalUserRole {
  SUPPORT = "support",
  OPERATIONS = "operations",
  SUPER_ADMIN = "super_admin",
}

@Entity({ name: "portal_user" })
export class PortalUserEntity extends AbstractEntity {
  @Column()
  fullname: string;

  @Index()
  @Column({ unique: true })
  email: string;

  @Column()
  password: string;

  @Column({
    type: "enum",
    enum: PortalUserRole,
    default: PortalUserRole.SUPPORT,
  })
  role: PortalUserRole;

  @Column({ default: true })
  isActive: boolean;
}
```

### PortalJwtStrategy

```typescript
// apps/portal-api/src/modules/portal-auth/portal-jwt.strategy.ts
import { Injectable, UnauthorizedException } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { PassportStrategy } from "@nestjs/passport";
import { InjectRepository } from "@nestjs/typeorm";
import { ExtractJwt, Strategy } from "passport-jwt";
import { Repository } from "typeorm";
import { AppConfig } from "@enterprise-todo/core";
import { JwtPayload } from "@enterprise-todo/contracts";
import { PortalUserEntity } from "./portal-user.entity";

@Injectable()
export class PortalJwtStrategy extends PassportStrategy(
  Strategy,
  "portal-jwt"
) {
  constructor(
    private readonly configService: ConfigService,
    @InjectRepository(PortalUserEntity)
    private readonly portalUserRepo: Repository<PortalUserEntity>
  ) {
    super({
      jwtFromRequest: ExtractJwt.fromAuthHeaderAsBearerToken(),
      ignoreExpiration: false,
      // Uses ADMIN public key — completely separate from the user JWT public key
      secretOrKey:
        configService.getOrThrow<AppConfig["adminJwt"]>("adminJwt").publicKey,
      algorithms: ["RS256"],
    });
  }

  async validate(payload: JwtPayload): Promise<PortalUserEntity> {
    const portalUser = await this.portalUserRepo.findOne({
      where: { id: payload.sub, isActive: true },
    });

    if (!portalUser) {
      throw new UnauthorizedException("Portal user not found or inactive");
    }

    // Attach platform claim to the user object for RequestPlatformInterceptor
    return Object.assign(portalUser, { platform: payload.platform });
  }
}
```

The strategy name `'portal-jwt'` is important — it must match the `defaultStrategy` in `PassportModule.register()`. Using a named strategy instead of `'jwt'` means Passport will not accidentally fall back to the user strategy if something is misconfigured.

### PortalAuthJwtGuard

```typescript
// apps/portal-api/src/modules/portal-auth/portal-auth-jwt.guard.ts
import { ExecutionContext, Injectable } from "@nestjs/common";
import { GqlExecutionContext } from "@nestjs/graphql";
import { AuthGuard } from "@nestjs/passport";

@Injectable()
export class PortalAuthJwtGuard extends AuthGuard("portal-jwt") {
  getRequest(context: ExecutionContext) {
    const ctx = GqlExecutionContext.create(context);
    return ctx.getContext<{ req: Request }>().req;
  }
}
```

### PortalAuthModule

```typescript
// apps/portal-api/src/modules/portal-auth/portal-auth.module.ts
import { Module } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { JwtModule } from "@nestjs/jwt";
import { PassportModule } from "@nestjs/passport";
import { TypeOrmModule } from "@nestjs/typeorm";
import { AppConfig } from "@enterprise-todo/core";
import { PortalUserEntity } from "./portal-user.entity";
import { PortalJwtStrategy } from "./portal-jwt.strategy";
import { PortalAuthJwtGuard } from "./portal-auth-jwt.guard";
import { PortalAccessTokenFactory } from "./portal-access-token.factory";
import { PortalAuthResolver } from "./portal-auth.resolver";
import { PortalAuthService } from "./portal-auth.service";

@Module({
  imports: [
    PassportModule.register({ defaultStrategy: "portal-jwt" }),

    JwtModule.registerAsync({
      inject: [ConfigService],
      useFactory: (config: ConfigService) => {
        const adminJwt = config.getOrThrow<AppConfig["adminJwt"]>("adminJwt");
        return {
          privateKey: adminJwt.privateKey,
          publicKey: adminJwt.publicKey,
          signOptions: {
            algorithm: "RS256",
            expiresIn: adminJwt.expiresIn,
            issuer: "portal",
          },
        };
      },
    }),

    TypeOrmModule.forFeature([PortalUserEntity]),
  ],
  providers: [
    PortalJwtStrategy,
    PortalAuthJwtGuard,
    PortalAccessTokenFactory,
    PortalAuthResolver,
    PortalAuthService,
  ],
  exports: [PortalAuthJwtGuard, PortalAuthService],
})
export class PortalAuthModule {}
```

Note the `issuer: 'portal'` in `signOptions`. When you add `issuer` validation to the strategy, a token issued by `apps/api` (issuer `'enterprise-todo'`) will be rejected even if the key pair were somehow shared. This is defense in depth: key pair separation is the primary control, `platform` claim is the secondary control, and `issuer` validation is a tertiary control.

### PortalAuthService

```typescript
// apps/portal-api/src/modules/portal-auth/portal-auth.service.ts
import { Injectable, UnauthorizedException } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { Repository } from "typeorm";
import * as bcrypt from "bcrypt";
import { PortalUserEntity } from "./portal-user.entity";
import { PortalAccessTokenFactory } from "./portal-access-token.factory";

@Injectable()
export class PortalAuthService {
  constructor(
    @InjectRepository(PortalUserEntity)
    private readonly portalUserRepo: Repository<PortalUserEntity>,
    private readonly tokenFactory: PortalAccessTokenFactory
  ) {}

  async login(
    email: string,
    password: string
  ): Promise<{ accessToken: string }> {
    const portalUser = await this.portalUserRepo.findOne({
      where: { email: email.toLowerCase(), isActive: true },
    });

    if (!portalUser) {
      throw new UnauthorizedException("Invalid credentials");
    }

    const passwordValid = await bcrypt.compare(password, portalUser.password);
    if (!passwordValid) {
      throw new UnauthorizedException("Invalid credentials");
    }

    return { accessToken: this.tokenFactory.sign(portalUser) };
  }
}
```

### PortalAuthResolver

```typescript
// apps/portal-api/src/modules/portal-auth/portal-auth.resolver.ts
import { Args, Mutation, Resolver } from "@nestjs/graphql";
import { ObjectType, Field, InputType } from "@nestjs/graphql";
import { IsEmail, IsString, MinLength } from "class-validator";
import { PortalAuthService } from "./portal-auth.service";

@ObjectType()
export class PortalLoginOutput {
  @Field()
  accessToken: string;
}

@InputType()
export class PortalLoginInput {
  @Field()
  @IsEmail()
  email: string;

  @Field()
  @IsString()
  @MinLength(8)
  password: string;
}

@Resolver()
export class PortalAuthResolver {
  constructor(private readonly portalAuthService: PortalAuthService) {}

  @Mutation(() => PortalLoginOutput)
  async portalLogin(
    @Args("input") input: PortalLoginInput
  ): Promise<PortalLoginOutput> {
    return this.portalAuthService.login(input.email, input.password);
  }
}
```

### Verify: Portal Auth Working

```bash
yarn portal:dev

# Portal login mutation
curl http://localhost:3334/graphql -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { portalLogin(input: { email: \"admin@example.com\", password: \"adminpass\" }) { accessToken } }"
  }'
# Expected: { "data": { "portalLogin": { "accessToken": "eyJ..." } } }
```

If login fails with `UnauthorizedException`, verify that `PortalUserEntity` is in `AppModule`'s TypeORM entities list and that the `portal_user` table exists (you need a migration — see Section 8 below).

---

## 8. Complete Guard + Interceptor Flow

Understanding the exact execution order is important for debugging. Here is the full lifecycle for all four cases:

```
Case 1: apps/api receives a user token (correct app, correct platform)
  1. Passport ExtractJwt reads Bearer token from Authorization header
  2. PassportStrategy('jwt') verifies RS256 signature with JWT_PUBLIC_KEY
     → signature valid, payload decoded
  3. AuthJwtStrategy.validate() finds UserEntity, sets req.user { ..., platform: 'user' }
  4. RequestPlatformInterceptor checks: user.platform === 'user' → PASS
  5. @UseGuards(AuthJwtGuard) on the resolver — req.user exists → PASS
  6. ACPermissionGuard checks user.status + permission slugs → PASS or 403
  7. Resolver executes

Case 2: apps/api receives a portal token (wrong app, right key pair hypothetical)
  1. Passport ExtractJwt reads Bearer token
  2. PassportStrategy('jwt') verifies RS256 signature with JWT_PUBLIC_KEY
     → signature INVALID (portal token was signed with ADMIN_JWT_PRIVATE_KEY)
     → 401 Unauthorized — request rejected at the crypto level
     → never reaches the interceptor

Case 3: apps/portal-api receives a portal token (correct app, correct platform)
  1. Passport ExtractJwt reads Bearer token
  2. PassportStrategy('portal-jwt') verifies RS256 signature with ADMIN_JWT_PUBLIC_KEY
     → signature valid, payload decoded
  3. PortalJwtStrategy.validate() finds PortalUserEntity, sets req.user { ..., platform: 'portal' }
  4. RequestPlatformInterceptor checks: user.platform === 'portal' → PASS
  5. @UseGuards(PortalAuthJwtGuard) on the resolver — req.user exists → PASS
  6. Resolver executes

Case 4: apps/portal-api receives a user token (wrong app, correct key pair)
  1. Passport ExtractJwt reads Bearer token
  2. PassportStrategy('portal-jwt') verifies RS256 signature with ADMIN_JWT_PUBLIC_KEY
     → signature INVALID (user token was signed with JWT_PRIVATE_KEY)
     → 401 Unauthorized — rejected at the crypto level
     → never reaches the interceptor
```

There is a fifth case worth noting: what if the two apps accidentally share a key pair in a future refactoring error?

```
Case 5: apps/api receives a portal token (wrong platform, same hypothetical key pair)
  1. Passport verifies signature → PASS (same key pair)
  2. AuthJwtStrategy.validate() finds... no UserEntity with that id (portal user ids are
     in a different table). Could throw 401. But if ids overlap by coincidence...
  3. RequestPlatformInterceptor checks: user.platform === 'portal' !== 'user' → 403 Forbidden
     "This endpoint requires a 'user' token. Received 'portal' token."
```

This is the defense-in-depth value of the interceptor: even in the worst-case misconfiguration scenario where key pairs are accidentally shared, the `platform` claim provides a second rejection layer.

---

## 9. Migration for portal_user Table

### Generate the Migration

Add `PortalUserEntity` to `apps/portal-api`'s TypeORM config (either in `PortalAppModule`'s `TypeOrmModule.forRootAsync` or a separate datasource file), then generate:

```bash
# Add PortalUserEntity to the TypeORM entities array in PortalAppModule, then:
yarn portal:migration:generate apps/portal-api/src/migrations/CreatePortalUserTable
yarn portal:migration:run
```

The generated migration will create the `portal_user` table with all columns from `PortalUserEntity`, including the `role` enum column and the `is_active` boolean.

Add the portal migration scripts to `package.json`:

```json
{
  "scripts": {
    "portal:migration:generate": "nx run portal-api:migration:generate --args=\"--name=$npm_config_name\"",
    "portal:migration:run": "nx run portal-api:migration:run",
    "portal:migration:revert": "nx run portal-api:migration:revert"
  }
}
```

### Seed a Portal User

Create a one-off seeder to add an initial portal admin. Do not share users between `apps/api` and `apps/portal-api` — portal users are a completely separate identity:

```typescript
// apps/portal-api/src/seeders/1-portal-user.seeder.ts
import { DataSource } from "typeorm";
import * as bcrypt from "bcrypt";
import {
  PortalUserEntity,
  PortalUserRole,
} from "../modules/portal-auth/portal-user.entity";

export async function seedPortalUsers(dataSource: DataSource): Promise<void> {
  const repo = dataSource.getRepository(PortalUserEntity);

  const existing = await repo.findOne({
    where: { email: "admin@portal.example.com" },
  });
  if (existing) return;

  const admin = repo.create({
    fullname: "Portal Admin",
    email: "admin@portal.example.com",
    password: await bcrypt.hash("change-me-in-production", 12),
    role: PortalUserRole.SUPER_ADMIN,
    isActive: true,
  });

  await repo.save(admin);
  console.log("Portal admin seeded: admin@portal.example.com");
}
```

### Verify: Migration and Seed

```bash
yarn portal:migration:run
# Expected: migration "CreatePortalUserTable" applied

yarn portal:migration:revert
# Expected: migration reverted — portal_user table dropped

yarn portal:migration:run
# Expected: re-applied cleanly

# Run portal seeder
yarn portal:seed:run
# Expected: "Portal admin seeded: admin@portal.example.com"
```

---

## 10. Complete Smoke Test

Run these steps in order with both apps running simultaneously.

### Step 1: Start Both Apps

```bash
# Terminal 1
yarn api:dev
# Expected: "API running at http://localhost:3333"

# Terminal 2
yarn portal:dev
# Expected: "Portal API running at http://localhost:3334"
```

### Step 2: Get a User Token from apps/api

```bash
USER_TOKEN=$(curl -s http://localhost:3333/graphql -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { login(input: { email: \"user@example.com\", password: \"password123\" }) { accessToken } }"
  }' | jq -r '.data.login.accessToken')

echo "User token: $USER_TOKEN"
```

### Step 3: Inspect the JWT Payload

```bash
# Decode the payload (middle section of the JWT, base64url encoded)
echo "$USER_TOKEN" | cut -d. -f2 | base64 --decode 2>/dev/null | jq .
# Expected output includes:
# {
#   "sub": 1,
#   "email": "user@example.com",
#   "platform": "user",
#   "iat": ...,
#   "exp": ...
# }
```

Alternatively, paste the token at https://jwt.io and confirm `"platform": "user"` in the payload section.

### Step 4: User Token Rejected on portal-api

```bash
curl -s http://localhost:3334/graphql -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -d '{"query":"{ portalHealth }"}' | jq .
# Expected:
# {
#   "errors": [{
#     "message": "This endpoint requires a '\''portal'\'' token. Received '\''user'\'' token.",
#     "extensions": { "code": "FORBIDDEN" }
#   }]
# }
```

Wait — `portalHealth` has no `@UseGuards`. The interceptor fires for authenticated requests only. If the user token is valid (signature checks out against the portal key pair), the interceptor rejects it. If the signature is invalid (which it will be since the user token was signed with a different key), Passport rejects it with `401 Unauthorized` before the interceptor runs.

This is the expected result for a correctly configured dual-key-pair setup: you see `401 Unauthorized` from Passport, not `403 Forbidden` from the interceptor. The `403` path is the defense-in-depth fallback for misconfigured same-key-pair scenarios.

### Step 5: Get a Portal Token from apps/portal-api

```bash
PORTAL_TOKEN=$(curl -s http://localhost:3334/graphql -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { portalLogin(input: { email: \"admin@portal.example.com\", password: \"change-me-in-production\" }) { accessToken } }"
  }' | jq -r '.data.portalLogin.accessToken')

echo "Portal token: $PORTAL_TOKEN"
```

### Step 6: Inspect the Portal JWT Payload

```bash
echo "$PORTAL_TOKEN" | cut -d. -f2 | base64 --decode 2>/dev/null | jq .
# Expected output includes:
# {
#   "sub": 1,
#   "email": "admin@portal.example.com",
#   "platform": "portal",
#   "iss": "portal",
#   "iat": ...,
#   "exp": ...
# }
```

### Step 7: Portal Token Rejected on apps/api

```bash
curl -s http://localhost:3333/graphql -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $PORTAL_TOKEN" \
  -d '{"query":"{ health }"}' | jq .
# Expected: 401 Unauthorized (Passport rejects the portal token — wrong key pair)
```

### Step 8: Portal Token Accepted on portal-api

```bash
curl -s http://localhost:3334/graphql -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $PORTAL_TOKEN" \
  -d '{"query":"{ portalHealth }"}' | jq .
# Expected: {"data":{"portalHealth":"ok"}}
# (portalHealth has no UseGuards — authenticated but unguarded resolver passes through)
```

### Step 9: User Token Accepted on apps/api

```bash
curl -s http://localhost:3333/graphql -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -d '{"query":"{ health }"}' | jq .
# Expected: {"data":{"health":"ok"}}
```

All four cases pass. The platform boundary is enforced at the cryptographic level (key pair mismatch) and at the semantic level (platform claim check).

---

## Summary: Before vs After

| Concern                      | Before (single app, guard-only)                           | After (dual app + platform interceptor)                      |
| ---------------------------- | --------------------------------------------------------- | ------------------------------------------------------------ |
| Admin endpoint protection    | `@UseGuards(AdminGuard)` on every resolver — disciplinary | Separate app, separate key pair — structural                 |
| User token on admin endpoint | Possible if a guard is forgotten                          | Cryptographically impossible — wrong key pair                |
| Admin token on user endpoint | Possible if strategy is misconfigured                     | Cryptographically impossible + platform interceptor fallback |
| Platform identity            | Implicit — inferred from which module registered the user | Explicit `platform` claim in every JWT — self-describing     |
| Shared config                | Copy-paste `ConfigModule.forRoot(...)` per app            | `import { CoreConfigModule } from '@enterprise-todo/core'`   |
| Shared types                 | Duplicate type definitions or manual sync                 | `import { JwtPayload } from '@enterprise-todo/contracts'`    |
| Separate port                | No — same port, path-based routing at best                | Yes — `:3333` user API, `:3334` portal API                   |
| Infrastructure separation    | Not possible — same app, same process                     | DNS-level separation, separate TLS certs, separate WAF rules |

---

## What You Have Now

- **`apps/portal-api/`** — complete second NestJS app, generated by Nx, running on port 3334
- **`apps/portal-api/src/main.ts`** — `createPlatformInterceptor('portal')` wired as global interceptor
- **`apps/portal-api/src/app/app.module.ts`** — `PortalAppModule` importing `CoreConfigModule` from `libs/core`
- **`apps/portal-api/src/modules/portal-auth/portal-user.entity.ts`** — `PortalUserEntity` with role enum
- **`apps/portal-api/src/modules/portal-auth/portal-jwt.strategy.ts`** — `PortalJwtStrategy` using `ADMIN_JWT_PUBLIC_KEY`
- **`apps/portal-api/src/modules/portal-auth/portal-auth-jwt.guard.ts`** — `PortalAuthJwtGuard`
- **`apps/portal-api/src/modules/portal-auth/portal-access-token.factory.ts`** — stamps `platform: 'portal'` on every token
- **`apps/portal-api/src/modules/portal-auth/portal-auth.module.ts`** — `PortalAuthModule` with separate `JwtModule`
- **`apps/portal-api/src/modules/portal-health/`** — `PortalHealthModule` for smoke testing
- **`apps/api/src/main.ts`** — `createPlatformInterceptor('user')` wired as global interceptor
- **`libs/core/src/interceptors/request-platform.interceptor.ts`** — `createPlatformInterceptor` factory
- **`libs/core/src/index.ts`** — exports `createPlatformInterceptor`
- **`libs/core/src/config/config.mapper.ts`** — `portalPort` and `adminJwt` fields in `AppConfig`
- **`libs/core/src/config/config.validation.ts`** — Joi validation for `PROJECT_PORTAL_PORT`, `ADMIN_JWT_*`
- **`libs/contracts/src/auth/jwt-payload.type.ts`** — `Platform` type and `platform` field on `JwtPayload`
- **Migrations** — `CreatePortalUserTable` for `apps/portal-api`
- **`package.json`** — `portal:dev`, `portal:build`, `portal:test`, `portal:migration:*` scripts

The monorepo now runs two independent NestJS backends sharing config and types through libraries, with cryptographic platform separation enforced at every layer. Every feature module you add to `portal-api` automatically inherits the platform interceptor — there is no per-resolver configuration required. A portal admin token physically cannot authenticate against `apps/api`, and a user token physically cannot authenticate against `apps/portal-api`, without any developer remembering to apply a guard.
