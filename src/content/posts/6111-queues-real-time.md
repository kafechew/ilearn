---
author: Kai
pubDatetime: 2026-05-11T09:00:00+08:00
title: Queues & Real-time
featured: false
draft: false
slug: 6111-queues-real-time
tags:
  - deeptech
  - meteorjs
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/11-queues-real-time.png"
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

A Bull queue guarantees:
- Jobs survive API restarts (stored in Redis)
- Automatic retries with exponential backoff
- Concurrency control (process N jobs at once, not infinite)
- Dead letter queue (inspect failed jobs with `bull-board`)
- Scheduled/delayed jobs (`delay: 60_000` = run in 1 minute)

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

### 4.3 NotificationService — Enqueue Jobs

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
    // The user's email comes from the JWT, which the handler passes in via input
    await this.notificationService.notifyTodoCreated({
      todoId: saved.id,
      userId: saved.userId,
      title: saved.title,
      userEmail: input.userEmail,  // passed from resolver via @CurrentUser
    });

    return { success: true, data: saved };
  }
}
```

**Important:** `notifyTodoCreated` is `await`ed to ensure the job is enqueued before we return. This is different from "waiting for the email to be sent" — Bull's `add()` resolves once the job is persisted in Redis (milliseconds). The actual email processing happens in `NotificationProcessor` asynchronously.

---

## 5. GraphQL Subscriptions with Redis PubSub

Subscriptions are a GraphQL transport feature — the browser opens a WebSocket connection and the server pushes events as they happen. This is Meteor's "reactive queries" equivalent, but explicit and controlled.

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

### 5.2 Install Redis PubSub

```bash
yarn add graphql-redis-subscriptions ioredis
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
import { PubSub } from 'graphql-subscriptions';
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

### 5.7 Frontend Subscription (Apollo Client)

```typescript
// apps/web/src/components/TodoList.tsx (add subscription)
import { useSubscription } from '@apollo/client';
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
yarn add @bull-board/nestjs @bull-board/express
```

```typescript
// apps/api/src/app/app.module.ts
import { BullBoardModule } from '@bull-board/nestjs';
import { ExpressAdapter } from '@bull-board/express';
import { BullMQAdapter } from '@bull-board/api/bullMQAdapter';

@Module({
  imports: [
    BullBoardModule.forRoot({
      route: '/queues',
      adapter: ExpressAdapter,
    }),
    BullBoardModule.forFeature({ name: NOTIFICATION_QUEUE, adapter: BullMQAdapter }),
  ],
})
```

Navigate to `http://localhost:3000/queues` in development. You can see pending jobs, failed jobs, and retry them manually.

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

## Summary

| Concept | Implementation | Key property |
|---------|---------------|-------------|
| Async background jobs | Bull (`@nestjs/bull`) + Redis | Jobs survive restarts, auto-retry |
| Job processor | `@Processor` class with `@Process` methods | Separate from HTTP request path |
| Real-time push | `RedisPubSub` + GraphQL `@Subscription` | Fan-out across all API instances |
| Subscription security | `filter` function + `@UseGuards` | Users only see their own events |
| Development tooling | `bull-board` at `/queues` | Inspect, retry, and debug jobs |
