---
author: Kai
pubDatetime: 2026-05-13T09:00:00+08:00
title: Queues & Real-time
featured: false
draft: false
slug: 6113-queues-real-time
tags:
  - deeptech
  - meteorjs
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/13-queues-real-time.png"
description: By the end of this part, you will learn about async queues, Bull, Redis, GraphQL Subscriptions and when to use.  

---

## What This Part Covers

- Why async queues matter (and what Meteor gave you "free" that was actually fragile)
- Bull + Redis: the enterprise queue pattern
- Creating a queue for email notification after a Todo is created
- Processing jobs with retry logic and error handling
- GraphQL Subscriptions with Redis PubSub
- Real-time Todo updates pushed to the browser
- When to use a queue vs a subscription

---

## Meteor Equivalent

| Concern | Meteor way | Enterprise way |
|---------|-----------|----------------|
| Background work | `Meteor.setInterval`, `Meteor.defer` | Bull queue (Redis-backed, survives crashes) |
| Send email | Inline `Email.send()` blocking the method | Bull job → email worker |
| Real-time updates | DDP publication + reactive query | GraphQL Subscription + Redis PubSub |
| Multi-instance scaling | Broken — each Meteor server has its own reactive graph | Bull: single queue, any worker picks up; PubSub: Redis fan-out to all instances |
| Subscription data isolation | Meteor publish cursors filtered per user | GraphQL Subscription `filter` function — server-side, runs before push |
| Job retry on failure | None — failed `Meteor.defer` is lost | Bull `attempts` + exponential `backoff` + dead-letter queue |
| Inspect queued jobs | None | `bull-board` UI at `/queues` — view, retry, and debug jobs |

The core problem with Meteor's inline DDP and `Meteor.defer`: when the process crashes mid-operation, the work is lost. Bull persists jobs in Redis — if your API pod restarts, the job is still there waiting to be picked up.

---

## 1. Why Bull + Redis for Queues

```
Without a queue (inline processing):
  User request ──→ API handler ──→ send email (300ms) ──→ return response (slow!)
                                                        ^^^ user waited 300ms

  Crash between API handler and send email → email is lost, no retry possible


With a queue:
  User request ──→ API handler ──→ enqueue job (5ms) ──→ return response (fast!)
                                        │
                                        ▼ (background, separate process)
                                   Bull worker ──→ send email ──→ retry on failure
                                                ──→ dead-letter queue on max retries
```

> **The kitchen ticket rail:** Bull is the ticket rail in a restaurant kitchen. The waiter (API handler) takes your order, clips the ticket to the rail, and **immediately returns to serve the next table**. The chef (Bull worker) processes tickets at their own pace in the background. The waiter never stands next to the stove watching your steak cook — that would block the entire front of house. The ticket rail also survives a shift change: if the chef goes on break (worker restarts), the ticket is still on the rail waiting.

A Bull queue guarantees:
- Jobs survive API restarts (stored in Redis)
- Automatic retries with exponential backoff
- Concurrency control (process N jobs at once, not infinite)
- Dead letter queue (inspect failed jobs with `bull-board`)
- Scheduled/delayed jobs (`delay: 60_000` = run in 1 minute)

> **From Meteor?** `Meteor.setTimeout`, `Meteor.defer`, and `synced-cron` were the closest Meteor equivalents — but none persisted jobs to storage. If the Meteor process restarted mid-job, the work was silently lost with no retry. Bull persists every job to Redis before the API handler returns, so a pod restart never loses work.

**Memory hook:** Bull = kitchen ticket rail. API clips the ticket and returns. Worker processes async. Redis-backed means tickets survive a shift change (pod restart).

---

## 2. Install Bull

```bash
yarn add @nestjs/bull bull
yarn add -D @types/bull
```

---

## 3. Register BullModule

```typescript
// apps/api/src/app/app.module.ts (add BullModule to imports)
import { BullModule } from '@nestjs/bull';

@Module({
  imports: [
    // ... existing imports
    BullModule.forRootAsync({
      useFactory: (config: ConfigService) => ({
        redis: {
          host: config.getOrThrow('REDIS_HOST'),
          port: config.getOrThrow<number>('REDIS_PORT'),
        },
      }),
      inject: [ConfigService],
    }),
  ],
})
export class AppModule {}
```

---

## 4. Create the Notification Queue

We'll build a notification system that sends an email when a Todo is created. This demonstrates the complete pattern.

### 4.1 Queue Constants

```typescript
// apps/api/src/modules/notification/notification.constant.ts
export const NOTIFICATION_QUEUE = 'notification';

export enum NotificationJobType {
  TODO_CREATED = 'todo.created',
  TODO_COMPLETED = 'todo.completed',
}

export interface TodoCreatedJobData {
  todoId: number;
  userId: number;
  title: string;
  userEmail: string;
}
```

### 4.2 Notification Module Setup

```typescript
// apps/api/src/modules/notification/notification.module.ts
import { BullModule } from '@nestjs/bull';
import { Module } from '@nestjs/common';
import { NOTIFICATION_QUEUE } from './notification.constant';
import { NotificationProcessor } from './notification.processor';
import { NotificationService } from './notification.service';

@Module({
  imports: [
    BullModule.registerQueue({ name: NOTIFICATION_QUEUE }),
  ],
  providers: [NotificationService, NotificationProcessor],
  exports: [NotificationService],  // export so TodoModule can inject it
})
export class NotificationModule {}
```

> **Hospital wing:** `NotificationModule` is a self-contained hospital wing. It owns `NotificationService` and `NotificationProcessor` as internal staff, borrows the Bull queue configuration from `BullModule`, and lends `NotificationService` to other wings (like `TodoModule`) via `exports`. `TodoModule` cannot reach inside and use `NotificationProcessor` directly — only what is explicitly exported is shared.

> **From Meteor?** In Meteor, email sending was typically `Email.send()` called inline in a method — no module boundary, no ownership, no export contract. Any file could call it. NestJS requires `TodoModule` to formally import `NotificationModule` and use only what `NotificationModule` chooses to expose.

**Memory hook:** Module = hospital wing. `exports: [NotificationService]` lends the service to others; the processor stays internal.

### 4.3 NotificationService — Enqueue Jobs

> **The specialist doctor who writes prescriptions, not the waiter:** `NotificationService` is the service layer for notifications. It knows *what jobs to enqueue and with what parameters* — but it never processes them. It delegates to the Bull queue (the ticket rail) and returns immediately. The actual email sending happens in `NotificationProcessor`, a completely separate class.

> **From Meteor?** In Meteor, `Email.send()` was called directly inside a method body — synchronous, blocking, and if it failed the whole method failed with no retry. `NotificationService.notifyTodoCreated()` enqueues a job in milliseconds and returns. Bull handles retries with exponential backoff independently of the HTTP request.

**Memory hook:** Service = specialist doctor. Enqueues the job and walks away. Never processes it. Retry logic lives in the queue options, not the service.

```typescript
// apps/api/src/modules/notification/notification.service.ts
import { InjectQueue } from '@nestjs/bull';
import { Injectable, Logger } from '@nestjs/common';
import { Queue } from 'bull';
import {
  NOTIFICATION_QUEUE,
  NotificationJobType,
  TodoCreatedJobData,
} from './notification.constant';

@Injectable()
export class NotificationService {
  private readonly logger = new Logger(NotificationService.name);

  constructor(@InjectQueue(NOTIFICATION_QUEUE) private readonly queue: Queue) {}

  async notifyTodoCreated(data: TodoCreatedJobData): Promise<void> {
    await this.queue.add(NotificationJobType.TODO_CREATED, data, {
      attempts: 3,                  // retry up to 3 times
      backoff: { type: 'exponential', delay: 2000 },  // 2s, 4s, 8s
      removeOnComplete: true,       // clean up after success
      removeOnFail: false,          // keep failed jobs for inspection
    });

    this.logger.log(`Enqueued ${NotificationJobType.TODO_CREATED} for todo ${data.todoId}`);
  }

  async notifyTodoCompleted(data: TodoCreatedJobData): Promise<void> {
    await this.queue.add(NotificationJobType.TODO_COMPLETED, data, {
      attempts: 3,
      backoff: { type: 'exponential', delay: 2000 },
      removeOnComplete: true,
    });
  }
}
```

### 4.4 NotificationProcessor — Process Jobs

> **Staff badge wired to the queue:** `NotificationProcessor` carries a staff badge (`@Injectable()`) so the staffing office can deliver it into `NotificationModule`. `@Processor(NOTIFICATION_QUEUE)` is the label that tells Bull which queue this staff member consumes. Each `@Process()` method handles one specific job type — one dedicated task per method.

**Memory hook:** Processor = staff member wired to a queue. `@Processor` names the queue; `@Process` names the job type. `@OnQueueFailed` is the safety net.

```typescript
// apps/api/src/modules/notification/notification.processor.ts
import { OnQueueFailed, Process, Processor } from '@nestjs/bull';
import { Logger } from '@nestjs/common';
import { Job } from 'bull';
import {
  NOTIFICATION_QUEUE,
  NotificationJobType,
  TodoCreatedJobData,
} from './notification.constant';

@Processor(NOTIFICATION_QUEUE)
export class NotificationProcessor {
  private readonly logger = new Logger(NotificationProcessor.name);

  @Process(NotificationJobType.TODO_CREATED)
  async handleTodoCreated(job: Job<TodoCreatedJobData>): Promise<void> {
    const { todoId, title, userEmail } = job.data;
    this.logger.log(`Processing todo.created for todo ${todoId} → ${userEmail}`);

    // Replace with your real email client (SendGrid, SES, etc.)
    await this.sendEmail({
      to: userEmail,
      subject: `New todo created: "${title}"`,
      body: `Your todo "${title}" has been added successfully.`,
    });

    this.logger.log(`Email sent for todo ${todoId}`);
  }

  @Process(NotificationJobType.TODO_COMPLETED)
  async handleTodoCompleted(job: Job<TodoCreatedJobData>): Promise<void> {
    const { todoId, title, userEmail } = job.data;
    this.logger.log(`Processing todo.completed for todo ${todoId}`);

    await this.sendEmail({
      to: userEmail,
      subject: `Todo completed: "${title}"`,
      body: `You completed "${title}". Great work!`,
    });
  }

  @OnQueueFailed()
  onFailed(job: Job, error: Error): void {
    this.logger.error(
      `Job ${job.id} (${job.name}) failed after ${job.attemptsMade} attempt(s): ${error.message}`,
    );
    // In production: alert to Sentry, PagerDuty, etc.
  }

  private async sendEmail(opts: { to: string; subject: string; body: string }): Promise<void> {
    // Stub — replace with real email service
    this.logger.debug(`[EMAIL] To: ${opts.to} | Subject: ${opts.subject}`);
    // await this.emailClient.send(opts);
  }
}
```

### 4.5 Trigger the Queue from TodoService

The service receives `userEmail` as part of the command input — enriched at the resolver layer from the verified JWT, not from the client. Two files need updating first.

**Update the CQRS input type to include `userEmail`:**

```typescript
// apps/api/src/modules/todo/cqrs/todo.cqrs.input.ts
export class CreateOneTodoCommand extends AbstractCqrsCommandInput<
  TodoEntity,
  CreateTodoInput & { userId: number; userEmail: string }  // ← add userEmail
> {}
```

**Update the resolver to enrich the input before dispatching:**

```typescript
@UseGuards(AuthJwtGuard)
@Mutation(() => TodoDto)
async createTodo(
  @CurrentUser() currentUser: AccessTokenUser,
  @Args('input') input: CreateTodoInput,
): Promise<TodoDto> {
  const { data } = await this.commandBus.execute(
    new CreateOneTodoCommand({
      input: {
        ...input,
        userId: currentUser.user.id,
        userEmail: currentUser.user.email,  // ← pass email from JWT to service
      },
    }),
  );
  return data as TodoDto;
}
```

Now the service can read `input.userEmail` without a type error:

```typescript
// apps/api/src/modules/todo/todo.service.ts (add notification call)
@Injectable()
export class TodoService {
  constructor(
    @InjectRepository(TodoEntity) private readonly todoRepo: Repository<TodoEntity>,
    private readonly notificationService: NotificationService,
  ) {}

  async createOne({ input }: CreateOneTodoCqrsInput['args']): Promise<CqrsResult<TodoEntity>> {
    const todo = this.todoRepo.create(input);
    const saved = await this.todoRepo.save(todo);

    // Enqueue — non-blocking, returns immediately
    await this.notificationService.notifyTodoCreated({
      todoId: saved.id,
      userId: saved.userId,
      title: saved.title,
      userEmail: input.userEmail,  // typed: string — passed from resolver via @CurrentUser
    });

    return { success: true, data: saved };
  }
}
```

**Important:** `notifyTodoCreated` is `await`ed to ensure the job is enqueued before we return. This is different from "waiting for the email to be sent" — Bull's `add()` resolves once the job is persisted in Redis (milliseconds). The actual email processing happens in `NotificationProcessor` asynchronously.

---

## 5. GraphQL Subscriptions with Redis PubSub

Subscriptions are a GraphQL transport feature — the browser opens a WebSocket connection and the server pushes events as they happen. This is Meteor's "reactive queries" equivalent, but explicit and controlled.

> **From Meteor?** Meteor's DDP publications (`Meteor.publish`) gave live data automatically — any write to the collection instantly updated every subscriber. GraphQL Subscriptions are the explicit equivalent: you call `pubSub.publish(event, payload)` yourself, and only the clients who called `useSubscription()` for that event receive it. Explicit control means no accidental data leakage and no magic reactive graph that breaks across multiple server instances.

**Memory hook:** GraphQL Subscription = explicit Meteor publication. You publish manually; the `filter` function controls who receives it. Redis PubSub required for multi-pod deployments.

### 5.1 Why Redis PubSub (not in-process)

```
In-process PubSub (bad for production):
  API pod 1 ──→ user connects to pod 1, subscription is registered on pod 1
  API pod 2 ──→ another request triggers an event, publishes on pod 2
  Result: pod 1 never sees the event → subscriber never gets the update

Redis PubSub (correct):
  API pod 1 ──→ user subscribes → subscribes to Redis channel
  API pod 2 ──→ event fires → publishes to Redis channel
  Redis ──→ fans out to ALL pods listening on that channel
  API pod 1 receives it and pushes to the WebSocket client ✓
```

> **Broadcast tower vs walkie-talkie:** In-process PubSub is a **walkie-talkie** — only people within direct radio range (the same server process) receive the message. Redis PubSub is a **broadcast radio tower** — one station transmits, every radio in the country picks up the same signal simultaneously. When your API scales to multiple pods, every pod subscribes to the same Redis channel. One pod publishes an event, Redis fans it out to all pods, and each pod forwards it to its own WebSocket clients.

**Memory hook:** Redis PubSub = broadcast tower. In-process PubSub = walkie-talkie. Always use Redis in production; in-process breaks the moment you have more than one API pod.

### 5.2 Install Redis PubSub

```bash
yarn add graphql-redis-subscriptions ioredis graphql@16
```

### 5.3 PubSub Provider

```typescript
// apps/api/src/shared/redis-pubsub.provider.ts
import { Provider } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { RedisPubSub } from 'graphql-redis-subscriptions';

export const REDIS_PUB_SUB = 'REDIS_PUB_SUB';

export const RedisPubSubProvider: Provider = {
  provide: REDIS_PUB_SUB,
  useFactory: (config: ConfigService) =>
    new RedisPubSub({
      connection: {
        host: config.getOrThrow('REDIS_HOST'),
        port: config.getOrThrow<number>('REDIS_PORT'),
        retryStrategy: (times: number) => Math.min(times * 50, 2000),
      },
    }),
  inject: [ConfigService],
};
```

Register in `AppModule`:

```typescript
// apps/api/src/app/app.module.ts
import { RedisPubSubProvider } from '../shared/redis-pubsub.provider';

@Module({
  providers: [RedisPubSubProvider],
  ...
})
```

Also update `GraphQLModule` to support subscriptions:

```typescript
GraphQLModule.forRoot<ApolloDriverConfig>({
  driver: ApolloDriver,
  autoSchemaFile: true,
  subscriptions: {
    'graphql-ws': true,         // modern WebSocket protocol
    'subscriptions-transport-ws': true,  // legacy Apollo client compat
  },
  context: ({ req, connection }) =>
    connection ? { req: connection.context } : { req },
}),
```

### 5.4 Subscription Events Constants

```typescript
// apps/api/src/modules/todo/todo.constant.ts
export enum TodoEventType {
  CREATED = 'todo.created',
  UPDATED = 'todo.updated',
  DELETED = 'todo.deleted',
}
```

### 5.5 Publish from TodoService

```typescript
// apps/api/src/modules/todo/todo.service.ts
@Injectable()
export class TodoService {
  constructor(
    @InjectRepository(TodoEntity) private readonly todoRepo: Repository<TodoEntity>,
    @Inject(REDIS_PUB_SUB) private readonly pubSub: RedisPubSub,
    private readonly notificationService: NotificationService,
  ) {}

  async createOne({ input }: CreateOneTodoCqrsInput['args']): Promise<CqrsResult<TodoEntity>> {
    const todo = this.todoRepo.create(input);
    const saved = await this.todoRepo.save(todo);

    // Publish real-time event
    await this.pubSub.publish(TodoEventType.CREATED, { todoCreated: saved });

    // Enqueue email notification
    await this.notificationService.notifyTodoCreated({
      todoId: saved.id,
      userId: saved.userId,
      title: saved.title,
      userEmail: input.userEmail,
    });

    return { success: true, data: saved };
  }

  async updateOne({ query, input }: UpdateOneTodoCqrsInput['args']): Promise<CqrsResult<TodoEntity>> {
    // ... update logic
    const updated = await this.todoRepo.save({ ...existing, ...input });

    await this.pubSub.publish(TodoEventType.UPDATED, { todoUpdated: updated });

    return { success: true, data: updated };
  }
}
```

### 5.6 Subscription Resolver

```typescript
// apps/api/src/modules/todo/todo.resolver.ts (add subscription methods)
import { Args, Int, Mutation, Query, Resolver, Subscription, ResolveField, Parent } from '@nestjs/graphql';
import { RedisPubSub } from 'graphql-redis-subscriptions';  // NOT PubSub from graphql-subscriptions — in-process PubSub breaks multi-instance
import { Inject } from '@nestjs/common';
import { REDIS_PUB_SUB } from '../../shared/redis-pubsub.provider';
import { TodoEventType } from './todo.constant';

@Resolver(() => TodoDto)
export class TodoResolver {
  constructor(
    private readonly commandBus: CommandBus,
    private readonly queryBus: QueryBus,
    private readonly todoUserLoader: TodoUserLoader,
    @Inject(REDIS_PUB_SUB) private readonly pubSub: RedisPubSub,
  ) {}

  // ... existing queries and mutations

  @Subscription(() => TodoDto, {
    filter: (payload, variables, context) => {
      // Only push to the user who owns this todo
      const currentUserId = context.req?.user?.id;
      return payload.todoCreated.userId === currentUserId;
    },
  })
  @UseGuards(AuthJwtGuard)
  todoCreated(): AsyncIterator<TodoEntity> {
    return this.pubSub.asyncIterator(TodoEventType.CREATED);
  }

  @Subscription(() => TodoDto, {
    filter: (payload, _variables, context) => {
      const currentUserId = context.req?.user?.id;
      return payload.todoUpdated.userId === currentUserId;
    },
  })
  @UseGuards(AuthJwtGuard)
  todoUpdated(): AsyncIterator<TodoEntity> {
    return this.pubSub.asyncIterator(TodoEventType.UPDATED);
  }
}
```

**The `filter` function is critical.** Without it, every connected user would receive every other user's Todo events — a serious data leakage bug. The filter runs server-side before the event is pushed to the client.

**Memory hook:** Subscription resolver = `pubSub.asyncIterator(event)` + a `filter` function. No filter = every user sees every other user's events. Always filter by `userId` or `tenantId`.

### 5.7 Frontend Subscription (Apollo Client)

```typescript
// apps/web/src/components/TodoList.tsx (add subscription)
import { useSubscription } from '@apollo/client/react';  // v4: React APIs moved to /react
import { gql } from '../generated/gql';

const TODO_CREATED_SUBSCRIPTION = gql(`
  subscription OnTodoCreated {
    todoCreated {
      id title completed priority createdAt
    }
  }
`);

export function TodoList() {
  const { data: queryData, refetch } = useQuery(GET_TODOS, { ... });

  // Subscribe to new todos
  useSubscription(TODO_CREATED_SUBSCRIPTION, {
    onData: ({ data }) => {
      if (data.data?.todoCreated) {
        // Refetch the list to include the new todo
        // Or manually append to the cache with writeFragment
        refetch();
      }
    },
  });

  // ... render
}
```

---

## 6. Bull Board — Job Inspector

In development, mount `bull-board` to view and manage queued jobs:

```bash
yarn add @bull-board/nestjs @bull-board/express @bull-board/api
```

```typescript
// apps/api/src/app/app.module.ts
import { BullBoardModule } from '@bull-board/nestjs';
import { ExpressAdapter } from '@bull-board/express';
import { BullAdapter } from '@bull-board/api/bullAdapter';  // BullAdapter for @nestjs/bull (legacy); use BullMQAdapter only with @nestjs/bullmq

@Module({
  imports: [
    BullBoardModule.forRoot({
      route: '/queues',
      adapter: ExpressAdapter,
    }),
    BullBoardModule.forFeature({ name: NOTIFICATION_QUEUE, adapter: BullAdapter }),
  ],
})
```

Navigate to `http://localhost:3333/queues` in development. You can see pending jobs, failed jobs, and retry them manually.

---

## 7. When to Use Queue vs Subscription

| Scenario | Use | Why |
|----------|-----|-----|
| Send email after signup | Queue | Async, retriable, non-blocking |
| AI evaluation of interview | Queue | Long-running, may fail, must not block HTTP response |
| Push new message to chat | Subscription | Immediate, user is watching, no retry needed |
| Rebuild search index | Queue | Background, can take minutes |
| Show "user is typing" | Subscription | Real-time, ephemeral |
| Export CSV / generate report | Queue | Long-running, email the result when done |
| Collaborative cursor position | Subscription | High frequency, ephemeral |

Rule: **queues for durable work that must not be lost; subscriptions for ephemeral real-time UI updates**.

---

## 8. Environment Variables

Add to `.env`:

```dotenv
REDIS_HOST=localhost
REDIS_PORT=6379
```

The `docker-compose.dev.yml` from Part 02 already has Redis running on port 6379.

---

## Quick Reference

| Concept | Analogy | Meteor equivalent | The one rule |
|---------|---------|-------------------|--------------|
| Bull Queue | Kitchen ticket rail — waiter clips ticket, chef processes async | `Meteor.defer`, `synced-cron` — but in-memory, no retry | API enqueues and returns; worker processes in background; Redis persists jobs across restarts |
| `@Processor` / `@Process` | Appliance plugged into the power grid | No direct equivalent — Meteor had no worker abstraction | `@Processor` names the queue; `@Process` names the job type; must match the queue name string exactly |
| NotificationModule | Hospital wing | `Email.send()` called inline anywhere | `exports: [NotificationService]` lends the service; the processor stays internal |
| NotificationService | Specialist doctor — prescribes the job, never runs it | Inline `Email.send()` in a method | `queue.add()` is non-blocking; actual sending is `NotificationProcessor`'s job |
| GraphQL Subscription | Explicit Meteor publication | `Meteor.publish` + DDP reactive graph | Always filter by `userId` or `tenantId`; without `filter`, all users receive all events |
| Redis PubSub | Broadcast radio tower | In-memory Meteor reactive graph (single-server only) | Required for multi-pod deployments; in-process PubSub silently breaks at scale |
| Subscription `filter` | Gate officer checking which patient the event belongs to | No direct equivalent — Meteor filtered at the publication cursor | Server-side; runs before event is pushed; missing filter = data leakage across users |

---

## Summary

| Concept | Implementation | Key property |
|---------|---------------|-------------|
| Async background jobs | Bull (`@nestjs/bull`) + Redis | Jobs survive restarts, auto-retry |
| Job processor | `@Processor` class with `@Process` methods | Separate from HTTP request path |
| Real-time push | `RedisPubSub` + GraphQL `@Subscription` | Fan-out across all API instances |
| Subscription security | `filter` function + `@UseGuards` | Users only see their own events |
| Development tooling | `bull-board` at `/queues` | Inspect, retry, and debug jobs |
