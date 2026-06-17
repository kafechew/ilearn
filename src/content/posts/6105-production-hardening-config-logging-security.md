---
author: Kai
pubDatetime: 2026-05-05T09:00:00+08:00
title: Production Hardening — Config Validation, Logging & Security Middleware
featured: false
draft: false
slug: 6105-production-hardening-config-logging-security
tags:
  - deeptech
  - meteorjs
  - nestjs
  - security
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/05-production-hardening-config-logging-security.png"
description: Add Joi environment validation, typed config mapper, global LoggingInterceptor, Helmet, rate limiting and a custom ExceptionFilter — the production hardening layer that prevents silent failures in any NestJS app.
---

This is **Part 5 of 24** in the NestJS series. Part 4 set up the database layer with TypeORM and migrations. Before writing any business logic — CQRS, GraphQL resolvers, or auth (Parts 6–8) — this part hardens the environment so that misconfiguration, unhandled errors, and abuse are caught at the earliest possible point. Adding these safeguards now means every feature built from Part 6 onwards inherits them automatically.

## What This Part Covers

- Why "it works locally" is not enough — the production hardening checklist
- Joi validation schema for environment variables (fail fast on startup)
- Typed config mapper (`configuration`) for type-safe `ConfigService` access
- Global `LoggingInterceptor` (from `nestjs-dev-utilities`) — request/response visibility
- `Helmet` — HTTP security headers in one line
- Rate limiting with `@nestjs/throttler` — protect public endpoints from abuse
- Custom global `AllExceptionsFilter` — consistent error shapes and centralised stack traces
- ARM64 docker-compose (create the missing `docker-compose.dev.arm.yml` for Apple Silicon)

---

## Meteor Equivalents

| Meteor                                        | NestJS                                                    | Notes                                                                        |
| --------------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------------------------- |
| No startup env validation                     | `ConfigModule` + `validationSchema` (Joi)                 | Meteor silently starts with undefined vars; NestJS can be made to crash fast |
| `Meteor.settings` loaded from `settings.json` | `ConfigModule.forRoot({ load: [configuration] })`         | NestJS config mapper gives full TypeScript types                             |
| `console.log` + DDP inspector                 | `LoggingInterceptor`                                      | Structured request/response logs in every environment                        |
| No built-in HTTP headers hardening            | `helmet`                                                  | Meteor/Galaxy has no equivalent — you added headers via Nginx config         |
| No built-in rate limiting                     | `@nestjs/throttler`                                       | Meteor needed a community package or Nginx `limit_req`                       |
| Uncaught exceptions crash the process         | `AllExceptionsFilter`                                     | Centralised: log, shape, and gracefully handle all errors                    |
| `linux/amd64` images run under Rosetta on M1  | `docker-compose.dev.arm.yml` with `platform: linux/arm64` | Significant performance difference on Apple Silicon                          |

---

## 1. Why Hardening Matters

NestJS starts successfully with missing environment variables. There is no built-in guard at boot time. A missing `PROJECT_DB_HOST` does not crash the process — it just sets `undefined` on `config.get('PROJECT_DB_HOST')`, which TypeORM silently passes as the host string. The first database query fails with a cryptic TCP connection error minutes after deployment, not at startup.

The same pattern repeats for every piece of missing configuration: missing JWT keys mean the first authenticated request fails, not boot. Missing Redis host means the first Bull job silently hangs. These are the class of failures that make production incidents hard to diagnose.

**Defence in depth** means layering independent safeguards so that no single missing piece causes a silent failure:

1. Joi validation schema: crash at boot with a clear message if any required variable is absent.
2. Typed config mapper: eliminate `string | undefined` throughout the codebase.
3. `LoggingInterceptor`: every request and response is visible in logs by default.
4. Helmet: secure HTTP headers applied at the transport layer, not scattered across controllers.
5. Throttler: rate limit public endpoints so abuse cannot degrade the service.
6. `AllExceptionsFilter`: all unhandled exceptions are logged with stack traces and return consistent error shapes.

None of these is complex individually. Together they close the gap between "works on my machine" and "safe to ship."

---

## 2. Joi Environment Validation

Install Joi:

```bash
yarn add joi
```

### 2.1 Create the validation schema

```typescript
// apps/api/src/config/config.validation.ts
import * as Joi from "joi";

export const validationSchema = Joi.object({
  NODE_ENV: Joi.string()
    .valid("development", "production", "test")
    .default("development"),

  PROJECT_PORT: Joi.number().default(3333),
  PROJECT_GRAPHQL_PLAYGROUND: Joi.boolean().default(true),
  PROJECT_GRAPHQL_SUBSCRIPTIONS: Joi.boolean().default(false),

  PROJECT_DB_CONNECTION: Joi.string().default("postgres"),
  PROJECT_DB_HOST: Joi.string().required(),
  PROJECT_DB_PORT: Joi.number().default(5432),
  PROJECT_DB_USERNAME: Joi.string().required(),
  PROJECT_DB_PASSWORD: Joi.string().required(),
  PROJECT_DB_DATABASE: Joi.string().required(),
  PROJECT_DB_DATABASE_TEST: Joi.string().optional(),
  PROJECT_DB_DEBUG: Joi.boolean().default(false),

  REDIS_BULL_HOST: Joi.string().default("localhost"),
  REDIS_BULL_PORT: Joi.number().default(6379),

  JWT_EXPIRATION_TIME: Joi.string().default("1d"),
  JWT_REFRESH_EXPIRATION_TIME: Joi.string().default("7d"),
  // JWT keys are required in production but optional in development (file-based keys)
  JWT_PRIVATE_KEY: Joi.string().when("NODE_ENV", {
    is: "production",
    then: Joi.required(),
  }),
  JWT_PUBLIC_KEY: Joi.string().when("NODE_ENV", {
    is: "production",
    then: Joi.required(),
  }),
  JWT_REFRESH_PRIVATE_KEY: Joi.string().optional(),
  JWT_REFRESH_PUBLIC_KEY: Joi.string().optional(),
});
```

### 2.2 Wire into AppModule

```typescript
// apps/api/src/app/app.module.ts
import { validationSchema } from "../config/config.validation";

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      envFilePath: ".env",
      validationSchema, // ← add this
    }),
    // ... rest of imports unchanged
  ],
})
export class AppModule {}
```

### 2.3 What startup failure looks like

Remove `PROJECT_DB_HOST` from your `.env` temporarily, then run `yarn api:dev`:

```
[Nest] Error: Config validation error: "PROJECT_DB_HOST" is required
    at ConfigModule.forRoot (/node_modules/@nestjs/config/dist/config.module.js:...)
```

The process exits immediately with a clear message pointing to the exact variable. Restore the value and the API boots normally.

> **The contract:** Every variable in `validationSchema` is now documented and enforced. When a new developer clones the repo or a DevOps engineer provisions a new environment, they get an explicit list of what is missing — not a runtime error three seconds after the first API call.

**Verify:** Temporarily comment out `PROJECT_DB_HOST=` in `.env`, run `yarn api:dev`, confirm the Joi error appears. Restore the line, re-run, confirm normal boot.

---

## 3. Typed Config Mapper

Raw `ConfigService` returns `string | undefined` for every key. The typed config mapper converts the flat `.env` structure into a nested object with full TypeScript types.

### 3.1 Create the mapper

```typescript
// apps/api/src/config/config.mapper.ts

export type AppConfig = {
  env: string;
  port: number;
  db: {
    host: string;
    port: number;
    username: string;
    password: string;
    database: string;
    debug: boolean;
  };
  redis: {
    host: string;
    port: number;
  };
  graphql: {
    playground: boolean;
    subscriptions: boolean;
  };
  jwt: {
    privateKey: string;
    publicKey: string;
    refreshPrivateKey: string;
    refreshPublicKey: string;
    expirationTime: string;
    refreshExpirationTime: string;
  };
};

export const configuration = (): AppConfig => ({
  env: process.env.NODE_ENV || "development",
  port: parseInt(process.env.PROJECT_PORT, 10) || 3333,
  db: {
    host: process.env.PROJECT_DB_HOST,
    port: parseInt(process.env.PROJECT_DB_PORT, 10) || 5432,
    username: process.env.PROJECT_DB_USERNAME,
    password: process.env.PROJECT_DB_PASSWORD,
    database: process.env.PROJECT_DB_DATABASE,
    debug: process.env.PROJECT_DB_DEBUG === "true",
  },
  redis: {
    host: process.env.REDIS_BULL_HOST || "localhost",
    port: parseInt(process.env.REDIS_BULL_PORT, 10) || 6379,
  },
  graphql: {
    playground: process.env.PROJECT_GRAPHQL_PLAYGROUND === "true",
    subscriptions: process.env.PROJECT_GRAPHQL_SUBSCRIPTIONS === "true",
  },
  jwt: {
    privateKey: process.env.JWT_PRIVATE_KEY,
    publicKey: process.env.JWT_PUBLIC_KEY,
    refreshPrivateKey: process.env.JWT_REFRESH_PRIVATE_KEY,
    refreshPublicKey: process.env.JWT_REFRESH_PUBLIC_KEY,
    expirationTime: process.env.JWT_EXPIRATION_TIME || "1d",
    refreshExpirationTime: process.env.JWT_REFRESH_EXPIRATION_TIME || "7d",
  },
});
```

### 3.2 Register in AppModule

```typescript
// apps/api/src/app/app.module.ts
import { configuration } from "../config/config.mapper";
import { validationSchema } from "../config/config.validation";

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      envFilePath: ".env",
      load: [configuration], // ← add this
      validationSchema,
    }),
    // ...
  ],
})
export class AppModule {}
```

### 3.3 Update consumers

Before this change, `main.ts` and `AppModule` accessed raw string keys:

```typescript
// Before — returns string | undefined
config.get("PROJECT_PORT");
config.get("PROJECT_DB_HOST");
```

After the mapper, you access structured typed paths:

```typescript
// After — returns the correct type from AppConfig
config.get<number>("port");
config.get<AppConfig["db"]>("db");
config.get<AppConfig["jwt"]>("jwt");
```

Update `main.ts` to use the typed path:

```typescript
// apps/api/src/main.ts
import { NestFactory } from "@nestjs/core";
import { ValidationPipe } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { AppModule } from "./app/app.module";
import { AppConfig } from "./config/config.mapper";

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
      config.get<string>("env") === "development"
        ? "*"
        : process.env.ALLOWED_ORIGINS,
  });

  const port = config.get<number>("port") ?? 3333;
  await app.listen(port);

  console.log(`API running at http://localhost:${port}`);
  console.log(`GraphQL Playground: http://localhost:${port}/graphql`);
}

bootstrap();
```

Update `AppModule`'s `TypeOrmModule.forRootAsync` to use typed config paths:

```typescript
// apps/api/src/app/app.module.ts  (TypeORM section)
TypeOrmModule.forRootAsync({
  inject: [ConfigService],
  useFactory: (config: ConfigService) => {
    const db = config.get<AppConfig['db']>('db');
    return {
      type: 'postgres',
      host: db.host,
      port: db.port,
      username: db.username,
      password: db.password,
      database: db.database,
      entities: [TodoEntity, UserEntity],
      synchronize: false,
      logging: db.debug,
      namingStrategy: new SnakeNamingStrategy(),
    };
  },
}),
```

And the `GraphQLModule` section:

```typescript
GraphQLModule.forRootAsync<ApolloDriverConfig>({
  driver: ApolloDriver,
  inject: [ConfigService],
  useFactory: (config: ConfigService) => {
    const graphql = config.get<AppConfig['graphql']>('graphql');
    return {
      autoSchemaFile: true,
      playground: graphql.playground,
      context: ({ req }) => ({ req }),
    };
  },
}),
```

> **Why `load: [configuration]` over raw keys?** When you use `load`, ConfigService returns a fully typed nested object. `config.get<AppConfig['jwt']>('jwt')` returns `{ privateKey: string; publicKey: string; ... }` — never `string | undefined`. Services that inject ConfigService get compile-time errors if they access a non-existent key. Raw key access (`config.get('JWT_PRIVATE_KEY')`) always returns `string | undefined`, requiring defensive checks everywhere.

**Verify:** Run `yarn api:dev`. The API should boot normally with all typed paths resolving correctly. TypeScript compilation should pass — run `yarn api:build` to confirm no type errors.

---

## 4. Global LoggingInterceptor

`nestjs-dev-utilities` is already installed (it provides `AbstractEntity` and `AbstractDto`). It also exports `LoggingInterceptor`, which logs method, URL, status code, and response time for every request.

### 4.1 Add to main.ts

```typescript
// apps/api/src/main.ts
import { NestFactory } from "@nestjs/core";
import { ValidationPipe } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { LoggingInterceptor } from "nestjs-dev-utilities";
import { AppModule } from "./app/app.module";
import { AppConfig } from "./config/config.mapper";

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

  // Log every request: method, path, status, duration
  app.useGlobalInterceptors(new LoggingInterceptor());

  app.enableCors({
    origin:
      config.get<string>("env") === "development"
        ? "*"
        : process.env.ALLOWED_ORIGINS,
  });

  const port = config.get<number>("port") ?? 3333;
  await app.listen(port);

  console.log(`API running at http://localhost:${port}`);
  console.log(`GraphQL Playground: http://localhost:${port}/graphql`);
}

bootstrap();
```

### 4.2 What the logs look like

After adding the interceptor, every GraphQL operation produces a log line similar to:

```
[LoggingInterceptor] POST /graphql - 200 - 14ms
[LoggingInterceptor] POST /graphql - 200 - 8ms
[LoggingInterceptor] POST /graphql - 401 - 2ms
```

The short response time on 401s confirms the guard short-circuits before any DB work. Slow queries become immediately visible without adding any per-resolver instrumentation.

> **Why global?** Interceptors registered via `app.useGlobalInterceptors()` run for every route without being declared on any individual controller or resolver. Adding per-module interceptors would require touching every feature module whenever the logging format changes. Global registration means one change, one place.

**Verify:** Run `yarn api:dev`. Open the GraphQL Playground at `http://localhost:3333/graphql` and run any query. Confirm the log line appears in the terminal with method, path, status, and duration. Try an unauthenticated mutation — confirm a `401` log appears with a sub-5ms response time.

---

## 5. Helmet — HTTP Security Headers

Helmet sets secure HTTP response headers that browsers use to mitigate common attacks. Without it, browsers receive no instructions on frame embedding, MIME sniffing, or cross-site scripting behaviour — the defaults are permissive.

Install:

```bash
yarn add helmet
```

### 5.1 Add to main.ts

```typescript
// apps/api/src/main.ts
import helmet from "helmet";
// ... other imports

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  const config = app.get(ConfigService);

  // Helmet: secure HTTP headers
  // In development, disable CSP so the GraphQL Playground (inline scripts) still loads
  app.use(
    helmet({
      crossOriginEmbedderPolicy: false,
      contentSecurityPolicy:
        config.get<string>("env") === "production" ? undefined : false,
    })
  );

  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      forbidNonWhitelisted: true,
      transform: true,
    })
  );

  app.useGlobalInterceptors(new LoggingInterceptor());

  app.enableCors({
    origin:
      config.get<string>("env") === "development"
        ? "*"
        : process.env.ALLOWED_ORIGINS,
  });

  const port = config.get<number>("port") ?? 3333;
  await app.listen(port);

  console.log(`API running at http://localhost:${port}`);
  console.log(`GraphQL Playground: http://localhost:${port}/graphql`);
}

bootstrap();
```

### 5.2 What Helmet adds

| Header                            | What it does                                                           |
| --------------------------------- | ---------------------------------------------------------------------- |
| `X-XSS-Protection: 1; mode=block` | Tells older browsers to block reflected XSS attacks                    |
| `X-Frame-Options: SAMEORIGIN`     | Prevents clickjacking by blocking iframe embedding from other origins  |
| `X-Content-Type-Options: nosniff` | Prevents browsers from MIME-sniffing responses                         |
| `Strict-Transport-Security`       | Forces HTTPS for subsequent requests (production only)                 |
| `X-Download-Options: noopen`      | Prevents IE from executing downloaded files in the context of the site |
| `Content-Security-Policy`         | Restricts sources for scripts, styles, and other resources             |

> **The GraphQL Playground caveat:** Apollo Sandbox / GraphQL Playground loads inline scripts, which a strict CSP blocks. The `contentSecurityPolicy: false` in development disables that check only in `development` mode. In production where `playground: false`, CSP can remain enabled without any issue. Never ship to production with `contentSecurityPolicy: false`.

**Verify:** Run `yarn api:dev`. Open Chrome DevTools, go to the Network tab, make any request to `http://localhost:3333/graphql`, inspect the response headers. You should see `X-Frame-Options`, `X-Content-Type-Options`, and `X-XSS-Protection` present. Confirm the GraphQL Playground still loads (CSP disabled in dev).

---

## 6. Rate Limiting with @nestjs/throttler

Install:

```bash
yarn add @nestjs/throttler
```

### 6.1 Register in AppModule

```typescript
// apps/api/src/app/app.module.ts
import { ThrottlerModule } from "@nestjs/throttler";
import { configuration } from "../config/config.mapper";
import { AppConfig } from "../config/config.mapper";
import { validationSchema } from "../config/config.validation";

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      envFilePath: ".env",
      load: [configuration],
      validationSchema,
    }),

    // Rate limiting: 20 requests per 60 seconds per IP
    ThrottlerModule.forRoot([
      {
        ttl: 60000, // window in milliseconds
        limit: 20, // max requests per window per IP
      },
    ]),

    // ... TypeOrmModule, GraphQLModule, CqrsModule, feature modules
  ],
})
export class AppModule {}
```

### 6.2 Apply the guard to sensitive mutations

The `ThrottlerGuard` can be applied globally, per-resolver class, or per-method. For a GraphQL API, per-method is most useful — you want to throttle auth mutations aggressively while leaving health checks unrestricted.

```typescript
// apps/api/src/modules/auth/auth.resolver.ts  (example)
import { UseGuards } from "@nestjs/common";
import { ThrottlerGuard } from "@nestjs/throttler";
import { Args, Mutation, Resolver } from "@nestjs/graphql";
import { AuthTokensDto } from "./dto/auth.dto";
import { RegisterInput, SignInInput } from "./dto/auth.input";

@Resolver()
export class AuthResolver {
  // ThrottlerGuard here: login brute-force protection
  @UseGuards(ThrottlerGuard)
  @Mutation(() => AuthTokensDto)
  async signIn(@Args("input") input: SignInInput): Promise<AuthTokensDto> {
    // ...
  }

  @UseGuards(ThrottlerGuard)
  @Mutation(() => AuthTokensDto)
  async register(@Args("input") input: RegisterInput): Promise<AuthTokensDto> {
    // ...
  }
}
```

Apply it to destructive todo mutations as well:

```typescript
// apps/api/src/modules/todo/todo.resolver.ts  (deleteTodo)
@UseGuards(AuthJwtGuard, ThrottlerGuard)
@Mutation(() => Boolean)
async deleteTodo(
  @CurrentUser() currentUser: AccessTokenUser,
  @Args('id', { type: () => Int }) id: number,
): Promise<boolean> {
  // ...
}
```

### 6.3 Skipping throttle on internal endpoints

Health checks and read-heavy public queries should not be throttled. Use `@SkipThrottle()`:

```typescript
// apps/api/src/modules/health/health.resolver.ts
import { SkipThrottle } from "@nestjs/throttler";
import { Query, Resolver } from "@nestjs/graphql";

@SkipThrottle()
@Resolver()
export class HealthResolver {
  @Query(() => String)
  health(): string {
    return "ok";
  }
}
```

### 6.4 What a throttled response looks like

After 20 requests within 60 seconds from the same IP, the 21st returns:

```json
{
  "errors": [
    {
      "message": "ThrottlerException: Too Many Requests",
      "extensions": {
        "code": "INTERNAL_SERVER_ERROR"
      }
    }
  ]
}
```

The HTTP status code is `429 Too Many Requests`.

> **Choosing limits:** 20 requests per 60 seconds is a starting point for auth mutations. Adjust based on your expected legitimate traffic. A mobile app that auto-retries token refresh may legitimately send 5-10 requests per minute. A public read API may need a much higher limit. The key is to pick a number that blocks automated attacks while not affecting real users.

**Verify:** Start `yarn api:dev`. Use a shell loop to fire 25 consecutive `signIn` mutations:

```bash
for i in $(seq 1 25); do
  curl -s -X POST http://localhost:3333/graphql \
    -H "Content-Type: application/json" \
    -d '{"query":"mutation { signIn(input: { username: \"test\", password: \"test\" }) { accessToken } }"}' \
    | python3 -m json.tool | grep -E '"message"'
done
```

Requests 1-20 return auth errors (wrong credentials), requests 21-25 return `ThrottlerException: Too Many Requests`. Wait 60 seconds and confirm requests succeed again.

---

## 7. Custom Global ExceptionFilter

NestJS has built-in exception handling, but it logs nothing by default for unhandled exceptions. In production you need centralised error logging with full stack traces. For GraphQL, you also need to re-throw the exception so Apollo can format it into the standard `errors` array — returning an HTTP response directly from a filter bypasses Apollo's error serialisation.

### 7.1 Create the filter

```typescript
// apps/api/src/filters/all-exceptions.filter.ts
import {
  ArgumentsHost,
  Catch,
  ExceptionFilter,
  HttpException,
  HttpStatus,
  Logger,
} from "@nestjs/common";
import { GqlArgumentsHost } from "@nestjs/graphql";

@Catch()
export class AllExceptionsFilter implements ExceptionFilter {
  private readonly logger = new Logger(AllExceptionsFilter.name);

  catch(exception: unknown, host: ArgumentsHost): void {
    const status =
      exception instanceof HttpException
        ? exception.getStatus()
        : HttpStatus.INTERNAL_SERVER_ERROR;

    const message =
      exception instanceof HttpException
        ? exception.message
        : "Internal server error";

    const stack =
      exception instanceof Error ? exception.stack : String(exception);

    this.logger.error(`[${status}] ${message}`, stack);

    // For GraphQL requests: re-throw so Apollo can serialise the error
    // into the standard { errors: [...] } response format.
    // Swallowing it here would return null data with no errors array.
    if (host.getType<string>() === "graphql") {
      throw exception;
    }

    // For REST requests (health endpoint, future REST routes):
    // Return a structured error response instead of crashing.
    const ctx = host.switchToHttp();
    const response = ctx.getResponse<{
      status: (code: number) => { json: (body: unknown) => void };
    }>();
    response.status(status).json({
      statusCode: status,
      message,
      timestamp: new Date().toISOString(),
    });
  }
}
```

### 7.2 Wire into main.ts

```typescript
// apps/api/src/main.ts
import { AllExceptionsFilter } from "./filters/all-exceptions.filter";
// ... other imports

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  const config = app.get(ConfigService);

  app.use(
    helmet({
      crossOriginEmbedderPolicy: false,
      contentSecurityPolicy:
        config.get<string>("env") === "production" ? undefined : false,
    })
  );

  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      forbidNonWhitelisted: true,
      transform: true,
    })
  );

  app.useGlobalFilters(new AllExceptionsFilter()); // ← add this
  app.useGlobalInterceptors(new LoggingInterceptor());

  app.enableCors({
    origin:
      config.get<string>("env") === "development"
        ? "*"
        : process.env.ALLOWED_ORIGINS,
  });

  const port = config.get<number>("port") ?? 3333;
  await app.listen(port);

  console.log(`API running at http://localhost:${port}`);
  console.log(`GraphQL Playground: http://localhost:${port}/graphql`);
}

bootstrap();
```

### 7.3 What the logs look like

When a service throws `NotFoundException`:

```
[AllExceptionsFilter] [404] Todo not found
    at TodoService.findOneTodo (/apps/api/src/modules/todo/todo.service.ts:42:13)
    at TodoFindOneHandler.execute (/apps/api/src/modules/todo/cqrs/handlers/...)
    ...
```

When an unexpected error occurs (database connection lost, etc.):

```
[AllExceptionsFilter] [500] Internal server error
    at Connection.query (/node_modules/typeorm/connection/Connection.js:...)
    ...
```

The GraphQL response the client receives is unchanged — Apollo still formats it as:

```json
{
  "errors": [
    {
      "message": "Todo not found",
      "locations": [...],
      "path": ["todo"],
      "extensions": { "code": "NOT_FOUND" }
    }
  ]
}
```

> **Why re-throw for GraphQL?** Apollo's error formatting middleware runs after the resolver. If the filter consumes the exception and writes an HTTP response directly, Apollo never sees the error — the client receives a `200 OK` with `{ "data": null }` and no `errors` array. The re-throw lets Apollo format the error correctly while still giving you the logging.

**Verify:** Run `yarn api:dev`. Make a GraphQL query that will fail — request a todo with an id that does not exist. Confirm the terminal shows the `[AllExceptionsFilter]` log line. Confirm the client receives a valid `errors` array, not an empty `data` object.

---

## 8. docker-compose.dev.arm.yml (Apple Silicon Fix)

Docker images built for `linux/amd64` run under Rosetta 2 emulation on Apple Silicon (M1/M2/M3). PostgreSQL under emulation is measurably slower for write-heavy workloads — migration runs, seeder resets, and test suites all take noticeably longer. The fix is native `linux/arm64` images.

### 8.1 Create the ARM compose file

```yaml
# docker-compose.dev.arm.yml
version: "3.8"

services:
  postgres:
    image: postgres:15-alpine
    platform: linux/arm64
    container_name: enterprise_todo_postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: enterprise_todo
    ports:
      - "5432:5432"
    volumes:
      - db_volume:/var/lib/postgresql/data
    networks:
      - app-network

  redis:
    image: redis:alpine
    platform: linux/arm64
    container_name: enterprise_todo_redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis_volume:/data
    networks:
      - app-network

  adminer:
    image: adminer
    container_name: enterprise_todo_adminer
    restart: unless-stopped
    ports:
      - "8080:8080"
    networks:
      - app-network

volumes:
  db_volume:
    external: true
  redis_volume:
    external: true

networks:
  app-network:
    driver: bridge
```

### 8.2 Add the script to package.json

```json
{
  "scripts": {
    "docker:dev": "docker compose -f docker-compose.dev.yml up -d",
    "docker:dev:arm": "docker compose -f docker-compose.dev.arm.yml up -d",
    "docker:stop": "docker compose -f docker-compose.dev.yml down"
  }
}
```

### 8.3 Which to use

```bash
# Intel Mac / Linux / CI
yarn docker:dev

# Apple Silicon (M1 / M2 / M3)
yarn docker:dev:arm
```

> **How to tell which you have:** `uname -m` returns `arm64` on Apple Silicon and `x86_64` on Intel. Both files produce identical services — the only difference is the `platform:` field. A CI environment running on GitHub Actions' `ubuntu-latest` runners is `x86_64` and should use the standard file.

**Verify:** On an Apple Silicon machine, run `docker stats` while the ARM compose is up and execute `yarn api:migration:run`. Compare the duration to the same run under the `amd64` image. The ARM image should complete significantly faster on M-series chips.

---

## 9. Smoke Test: All Changes Together

Boot the fully hardened API and verify each layer in sequence.

### Step 1 — Joi fail-fast check

Comment out `PROJECT_DB_HOST=` in `.env`:

```bash
yarn api:dev
# Expected: process exits with:
# Error: Config validation error: "PROJECT_DB_HOST" is required
```

Restore the line. The API boots normally.

### Step 2 — Typed config and LoggingInterceptor

```bash
yarn api:dev
```

Open the GraphQL Playground at `http://localhost:3333/graphql`. Run:

```graphql
query {
  health
}
```

Terminal should show:

```
[LoggingInterceptor] POST /graphql - 200 - 5ms
```

### Step 3 — Helmet headers

In Chrome DevTools (Network tab), inspect the response headers for any request to `http://localhost:3333/graphql`. Confirm:

```
x-frame-options: SAMEORIGIN
x-content-type-options: nosniff
x-xss-protection: 0
```

Confirm the GraphQL Playground itself still loads (CSP is disabled in dev mode).

### Step 4 — Rate limiter

Run 25 quick mutations:

```bash
for i in $(seq 1 25); do
  curl -s -X POST http://localhost:3333/graphql \
    -H "Content-Type: application/json" \
    -d '{"query":"mutation { signIn(input: { username: \"x\", password: \"x\" }) { accessToken } }"}' \
    | grep -o '"message":"[^"]*"'
done
```

First 20: `"message":"Invalid credentials"` (or similar auth error).
Requests 21-25: `"message":"ThrottlerException: Too Many Requests"`.

### Step 5 — ExceptionFilter logging

Make a request that will throw — query a todo that does not exist:

```graphql
query {
  todo(id: 99999) {
    id
    text
  }
}
```

If `NotFoundException` is thrown, confirm:

- Terminal shows `[AllExceptionsFilter] [404] Todo not found` with a stack trace.
- The GraphQL client receives `{ "data": { "todo": null } }` (null return, not an error, because the resolver returns `nullable: true`).

To trigger the filter's error log explicitly, temporarily throw from a resolver:

```typescript
// Temporary test — remove after verification
@Query(() => String)
testError(): string {
  throw new Error('Deliberate test exception');
}
```

Run `query { testError }`. Confirm the terminal logs the stack trace from `AllExceptionsFilter`. Remove the test method.

### Step 6 — Full startup checklist

```bash
yarn api:dev
```

Confirm all of the following in order:

- No Joi validation errors (all required vars present)
- `API running at http://localhost:3333` printed
- `GraphQL Playground: http://localhost:3333/graphql` printed
- GraphQL Playground loads in browser
- A query produces a `LoggingInterceptor` log line
- Response headers include `x-frame-options`

---

## Summary Table

| Concern              | What was missing                 | What we added                                              |
| -------------------- | -------------------------------- | ---------------------------------------------------------- |
| Missing env vars     | Silent `undefined` at runtime    | Joi `validationSchema` — process exits at boot             |
| ConfigService types  | `string \| undefined` everywhere | `configuration()` mapper — typed nested object             |
| Request visibility   | No logging by default            | `LoggingInterceptor` — every request logged                |
| HTTP header security | No secure headers                | `helmet()` — 6+ security headers in one line               |
| Abuse prevention     | No rate limits                   | `ThrottlerModule` + `ThrottlerGuard` — 429 after threshold |
| Error observability  | Silent failures, no stack traces | `AllExceptionsFilter` — centralised logging                |
| Apple Silicon perf   | `amd64` images under Rosetta     | `docker-compose.dev.arm.yml` — native `arm64` images       |

---

## What You Have Now

```
[ ] config/config.validation.ts   — Joi schema; process crashes with clear message on missing vars
[ ] config/config.mapper.ts       — Typed AppConfig; no more string | undefined from ConfigService
[ ] AppModule                     — load: [configuration], validationSchema wired
[ ] main.ts                       — helmet(), AllExceptionsFilter, LoggingInterceptor all registered
[ ] ThrottlerModule               — 20 req / 60s limit registered in AppModule
[ ] AuthResolver                  — @UseGuards(ThrottlerGuard) on login and register mutations
[ ] TodoResolver                  — @UseGuards(ThrottlerGuard) on deleteTodo
[ ] HealthResolver                — @SkipThrottle() applied
[ ] filters/all-exceptions.filter.ts — centralised logging; re-throws for GraphQL
[ ] docker-compose.dev.arm.yml    — native arm64 images for Apple Silicon
```

The API now crashes fast on misconfiguration, logs every request, sends secure HTTP headers, rejects abusive clients, and surfaces all errors with full stack traces. This is the baseline for any production NestJS deployment — a starting point, not a ceiling. Future parts will add Bull queues with Redis-backed rate limiting, structured logging with Pino, and OpenTelemetry tracing for distributed request tracking.

**Next: Part 6 — CQRS & the Enterprise Request Pipeline**
