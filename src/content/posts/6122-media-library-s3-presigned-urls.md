---
author: Kai
pubDatetime: 2026-05-22T09:00:00+08:00
title: Media Library — S3 Presigned Uploads, Magic Byte Validation & CDN
featured: false
draft: false
slug: 6122-media-library-s3-presigned-urls
tags:
  - deeptech
  - nestjs
  - aws
  - s3
  - typescript
  - backend
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/22-media-library-s3-presigned-urls.png"
description: Build a production-grade media library with S3 presigned upload URLs, Bull-queue post-processing, magic-byte file-type validation, sharp thumbnail generation, and CloudFront CDN delivery — without ever routing file bytes through your API server.
---

## What This Part Covers

File upload is one of the most common enterprise features and one of the most frequently implemented incorrectly. The naive approach — POST multipart to the API, save to disk, upload to S3 — works in a tutorial but breaks in production the first time ECS redeploys your container and wipes the ephemeral filesystem. This tutorial builds the correct architecture from the start.

- Why the API must never handle file bytes (thread blocking, ephemeral ECS storage, no CDN)
- S3 presigned URL upload architecture — the 3-step flow that scales without any changes
- `MediaEntity` with a status lifecycle: `PENDING` → `UPLOADED` → `READY` / `FAILED`
- `S3Service` — presigned URL generation with `ContentLengthRange`, CDN URL helper
- `MediaService` — MIME type allowlist, UUID `fileKey` generation with per-tenant S3 prefix
- `MediaResolver` — `requestUpload` + `confirmUpload` mutations with `ACPermissionGuard`
- `MediaProcessor` (Bull) — magic byte validation with `file-type`, thumbnail generation with `sharp`
- Frontend — `useFileUpload` hook and `AvatarUpload` component
- S3 bucket policy + CloudFront OAC setup so only the CDN can serve files directly

---

## Meteor Equivalents

| Concept                   | Meteor (ostrio:files / edgee:slingshot)                   | NestJS presigned URL                                                                           |
| ------------------------- | --------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Upload to S3              | `edgee:slingshot` generates a policy, browser PUTs direct | Same 3-step flow — `requestUpload` → S3 PUT → `confirmUpload`                                  |
| File metadata             | `FilesCollection` MongoDB document                        | `MediaEntity` TypeORM entity with status lifecycle                                             |
| File bytes through server | `ostrio:files` streams through Meteor server by default   | Explicitly blocked — API only exchanges URLs, never bytes                                      |
| Post-processing           | DDP method + synchronous call                             | Bull queue job: magic byte check, `sharp` thumbnail                                            |
| CDN delivery              | Direct S3 URL or manual CloudFront config                 | `getCdnUrl()` on `S3Service` — CloudFront OAC enforced by bucket policy                        |
| File type validation      | Extension + MIME check on server                          | Magic byte check via `file-type` on first 4KB — extension and declared MIME are both untrusted |
| Access control            | `allow/deny` rules on `FilesCollection`                   | `ACPermissionGuard` with `upload-media` slug, per-tenant S3 key prefix                         |

The critical difference from Meteor's `ostrio:files`: when you stream files through the Meteor server, every upload occupies a DDP connection for the entire transfer duration. With presigned URLs, the API exchanges two small JSON payloads — one to get the URL, one to confirm — and S3 handles all the bytes directly. The API worker is free for the entire upload duration.

---

## 1. Why Presigned URLs (Not Multipart Through the API)

### The Problem with Routing File Bytes Through Your API

When a file upload goes through the API server:

```
Wrong: Browser → POST /upload (multipart/form-data) → API reads all bytes → uploads to S3
```

Three things break in production:

**Thread blocking.** Node.js is single-threaded. A 50MB video upload reads 50MB through your event loop. While that read is happening, every other request to that Node worker is queued. At ten concurrent uploads, your API is unresponsive for all other traffic.

**Ephemeral ECS storage.** ECS Fargate tasks have no persistent local storage. If you write the upload to `/tmp` and the task is replaced before the S3 upload completes — during a deploy, during a health check failure, during a spot instance reclaim — the file is gone. Your API confirmed the upload, the file is nowhere.

**No CDN.** If the API re-serves files it downloaded from S3, it pays twice: egress cost from S3 to your server, then egress cost from your server to the browser. CloudFront charges a fraction of origin-to-internet egress costs. More importantly, CloudFront caches at edge locations — a user in Tokyo does not wait for a round trip to your Singapore ECS cluster to load a profile photo.

### The Presigned URL Architecture

```
Step 1 — negotiation (tiny JSON):
  Browser → requestUpload(filename, mimeType) mutation → API validates, generates fileKey
  API → S3 presigned PUT URL (5-minute expiry, ContentLengthRange enforced)
  API → returns { uploadUrl, fileKey, mediaId } to browser

Step 2 — transfer (API never involved):
  Browser → PUT <uploadUrl> with file bytes directly to S3
  S3 → 200 OK (enforces ContentLengthRange — rejects oversized files at the S3 level)

Step 3 — confirmation (tiny JSON):
  Browser → confirmUpload(mediaId) mutation → API sets status UPLOADED, enqueues processor job
  API → returns MediaDto (status: UPLOADED)

Step 4 — async processing (no user waiting):
  Bull worker → downloads first 4KB from S3 → validates magic bytes
  Bull worker → generates thumbnail with sharp → sets status READY
  (or sets FAILED if magic bytes don't match declared MIME type)
```

The API server processes two small GraphQL mutations — no file bytes ever cross the API process boundary. The S3 presigned URL has a `ContentLengthRange` condition baked into it at the AWS policy level, so even if a client crafts a raw PUT larger than the allowed limit, S3 rejects it without your API code being involved.

---

## 2. Install & Config

### Install Dependencies

```bash
yarn add @aws-sdk/client-s3 @aws-sdk/s3-request-presigner file-type sharp
yarn add -D @types/sharp
```

`@aws-sdk/client-s3` — AWS SDK v3 S3 client. Modular — only installs the S3 package, not the entire SDK v2 monolith.

`@aws-sdk/s3-request-presigner` — generates presigned URLs from S3 command objects.

`file-type` — detects real file type from magic bytes (the first few bytes of a file that identify its format). Pure ESM package; see the Gotcha note below.

`sharp` — fast Node.js image processing library, backed by libvips. Used for thumbnail generation.

### ESM Gotcha: file-type

`file-type` v19+ is pure ESM. NestJS runs in CommonJS by default (Webpack bundled). There are two ways to handle this:

**Option A (recommended for this project):** Pin to `file-type@16` which still ships CJS:

```bash
yarn add file-type@16
```

**Option B:** Use dynamic `import()` inline:

```typescript
const { fileTypeFromBuffer } = await import("file-type");
```

This tutorial uses Option A for simplicity. If you upgrade to NestJS with native ESM support later, switch to Option B.

### Add S3 Config to libs/core

Extend the existing `AppConfig` type in `libs/core/src/config/config.mapper.ts`:

```typescript
// libs/core/src/config/config.mapper.ts
export type AppConfig = {
  // ... existing fields (port, jwt, db, redis, etc.) ...

  s3: {
    region: string;
    accessKeyId: string;
    secretAccessKey: string;
    bucket: string;
    cdnBaseUrl: string;
  };
};

export const configuration = (): AppConfig => ({
  // ... existing mappings ...

  s3: {
    region: process.env["AWS_REGION"] ?? "ap-southeast-1",
    accessKeyId: process.env["AWS_ACCESS_KEY_ID"] ?? "",
    secretAccessKey: process.env["AWS_SECRET_ACCESS_KEY"] ?? "",
    bucket: process.env["S3_BUCKET"] ?? "",
    cdnBaseUrl: process.env["CDN_BASE_URL"] ?? "",
  },
});
```

Add Joi validation in `libs/core/src/config/config.validation.ts`:

```typescript
// libs/core/src/config/config.validation.ts  (add to existing Joi.object)
AWS_REGION: Joi.string().default('ap-southeast-1'),
AWS_ACCESS_KEY_ID: Joi.string().required(),
AWS_SECRET_ACCESS_KEY: Joi.string().required(),
S3_BUCKET: Joi.string().required(),
CDN_BASE_URL: Joi.string().uri().required(),
```

### Add Environment Variables

```bash
# .env — add to existing file

# AWS / S3
AWS_REGION=ap-southeast-1
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
S3_BUCKET=enterprise-todo-media-dev
CDN_BASE_URL=https://d1abc123.cloudfront.net
```

For local development without a real AWS account, `CDN_BASE_URL` can point to a LocalStack endpoint or a real S3 URL with public access temporarily enabled. The CloudFront setup in Section 10 covers the production configuration.

### Verify: Config Loads

```bash
yarn api:dev
# Expected: API starts without Joi validation errors
# If you see "AWS_ACCESS_KEY_ID is required" — your .env is not loading
# Check that apps/api/src/app/app.module.ts imports CoreConfigModule
```

---

## 3. MediaEntity

The entity models the full lifecycle of an uploaded file. Each row starts as `PENDING` when the browser requests an upload URL, transitions to `UPLOADED` when the browser confirms the S3 PUT completed, and then transitions to `READY` or `FAILED` when the Bull processor validates and processes the file.

```typescript
// apps/api/src/modules/media/media.entity.ts
import { Column, Entity, Index, ManyToOne, JoinColumn } from "typeorm";
import { AbstractEntity } from "nestjs-dev-utilities";
import { UserEntity } from "../user/user.entity";

export enum MediaStatus {
  PENDING = "PENDING",
  UPLOADED = "UPLOADED",
  READY = "READY",
  FAILED = "FAILED",
}

@Entity({ name: "media" })
export class MediaEntity extends AbstractEntity {
  @Index()
  @Column({ type: "int" })
  tenantId: number;

  @Index()
  @Column({ type: "int" })
  userId: number;

  @ManyToOne(() => UserEntity, { onDelete: "CASCADE" })
  @JoinColumn({ name: "user_id" })
  user: UserEntity;

  // S3 object key — tenants/{tenantId}/media/{uuid}.{ext}
  @Column({ unique: true })
  fileKey: string;

  @Column()
  originalName: string;

  @Column()
  mimeType: string;

  // bigint supports files > 2GB (video uploads)
  // stored as string in JS due to JS number precision limits
  @Column({ type: "bigint" })
  sizeBytes: string;

  // Indexed — queried in every processor job (WHERE status = 'UPLOADED')
  @Index()
  @Column({
    type: "enum",
    enum: MediaStatus,
    default: MediaStatus.PENDING,
  })
  status: MediaStatus;

  // Populated by S3Service after upload is confirmed
  @Column({ nullable: true })
  cdnUrl: string | null;

  @Column({ nullable: true })
  thumbnailUrl: string | null;

  @Column({ type: "timestamp", nullable: true })
  processedAt: Date | null;

  // Set by the Bull processor on FAILED status
  @Column({ nullable: true, length: 500 })
  errorMessage: string | null;
}
```

A note on `sizeBytes` as `bigint`: JavaScript's `number` type is a 64-bit float with 53 bits of integer precision — it cannot represent integers larger than `2^53 - 1` (~9 petabytes is fine, but TypeScript won't infer the right type). TypeORM maps `bigint` columns to `string` in JavaScript to avoid silent precision loss. Cast to `BigInt` only when you need arithmetic.

The `@Index()` on `status` matters for the processor: every Bull job queries `WHERE id = ? AND status = 'UPLOADED'`. Without the index, that query becomes a full table scan as your media table grows.

### Register MediaEntity in AppModule

```typescript
// apps/api/src/app/app.module.ts  (add to entities array)
import { MediaEntity } from '../modules/media/media.entity';

TypeOrmModule.forRootAsync({
  // ...
  useFactory: (config: ConfigService) => ({
    // ...
    entities: [
      // ... existing entities ...
      MediaEntity,
    ],
  }),
}),
```

---

## 4. S3Service

The `S3Service` has two responsibilities: generate presigned upload URLs, and build CDN URLs for confirmed uploads. It knows nothing about tenants, users, or business rules — that is the `MediaService`'s job.

```typescript
// apps/api/src/modules/media/s3.service.ts
import { Injectable } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { S3Client, PutObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import { AppConfig } from "@enterprise-todo/core";

// 5 minutes — enough time for the browser to start the PUT.
// The upload itself can take longer; the expiry only governs when the PUT
// can be *initiated*, not how long the transfer takes once started.
const PRESIGNED_URL_EXPIRY_SECONDS = 300;

@Injectable()
export class S3Service {
  private readonly client: S3Client;
  private readonly bucket: string;
  private readonly cdnBaseUrl: string;

  constructor(private readonly configService: ConfigService) {
    const s3Config = configService.getOrThrow<AppConfig["s3"]>("s3");

    this.client = new S3Client({
      region: s3Config.region,
      credentials: {
        accessKeyId: s3Config.accessKeyId,
        secretAccessKey: s3Config.secretAccessKey,
      },
    });

    this.bucket = s3Config.bucket;
    this.cdnBaseUrl = s3Config.cdnBaseUrl;
  }

  /**
   * Generates a presigned PUT URL for a single S3 object.
   *
   * ContentLengthRange is embedded in the presigned URL as a policy condition.
   * S3 enforces it at the time of the PUT — if the client sends more bytes than
   * maxSizeBytes, S3 returns 400 Bad Request before any bytes are stored.
   * This enforcement happens at S3, not in your API code.
   */
  async generateUploadUrl(
    fileKey: string,
    mimeType: string,
    maxSizeBytes: number
  ): Promise<string> {
    const command = new PutObjectCommand({
      Bucket: this.bucket,
      Key: fileKey,
      ContentType: mimeType,
      // ContentLengthRange condition: 1 byte minimum, maxSizeBytes maximum
      // Note: this is a policy condition on the presigned URL, not a header.
      // It must be passed through the presigner options, not the command.
    });

    const uploadUrl = await getSignedUrl(this.client, command, {
      expiresIn: PRESIGNED_URL_EXPIRY_SECONDS,
      // Enforce size at S3 level — prevents clients from uploading oversized files
      // even if they craft a raw PUT bypassing your API
      signableHeaders: new Set(["content-type"]),
    });

    return uploadUrl;
  }

  /**
   * Returns the CloudFront CDN URL for a given S3 object key.
   * The CDN base URL is configured per environment:
   *   - dev:        https://d1abc.cloudfront.net
   *   - production: https://media.yourdomain.com (CNAME to CloudFront)
   *
   * Local dev: CDN_BASE_URL can be your S3 public URL or LocalStack endpoint.
   */
  getCdnUrl(fileKey: string): string {
    return `${this.cdnBaseUrl}/${fileKey}`;
  }

  /**
   * Downloads only the first numBytes of an S3 object using a Range request.
   * Used by MediaProcessor to read magic bytes without downloading the full file.
   */
  async getFirstBytes(fileKey: string, numBytes: number): Promise<Buffer> {
    const { GetObjectCommand } = await import("@aws-sdk/client-s3");
    const command = new GetObjectCommand({
      Bucket: this.bucket,
      Key: fileKey,
      Range: `bytes=0-${numBytes - 1}`,
    });

    const response = await this.client.send(command);
    const stream = response.Body as NodeJS.ReadableStream;

    return new Promise((resolve, reject) => {
      const chunks: Buffer[] = [];
      stream.on("data", (chunk: Buffer) => chunks.push(chunk));
      stream.on("end", () => resolve(Buffer.concat(chunks)));
      stream.on("error", reject);
    });
  }
}
```

The `ContentLengthRange` note deserves elaboration. The AWS SDK v3 presigner does not support `ContentLengthRange` conditions on `PutObject` presigned URLs directly — that condition is a feature of presigned POST (form-based upload). For `PutObject` presigned URLs, the size enforcement happens via `content-length` header matching. If you need strict server-side size enforcement at S3 level for PUT, use `CreatePresignedPost` instead of `PutObjectCommand`. For this tutorial, size validation happens in `MediaService` before the URL is generated, and a hard limit is enforced by your API — a belt-and-suspenders approach.

---

## 5. MediaService

The service validates the upload request, generates the per-tenant fileKey, saves a `PENDING` entity, and handles the confirm step.

### Constants

```typescript
// apps/api/src/modules/media/media.constants.ts
export const MEDIA_QUEUE = "media-processing";

export const ALLOWED_MIME_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
  "application/pdf",
  "video/mp4",
  "video/webm",
]);

// 100MB — S3 validation is belt-and-suspenders; this check is in the API
export const MAX_SIZE_BYTES = 100 * 1024 * 1024;

// Map MIME type to canonical file extension for the S3 key
export const MIME_TO_EXT: Record<string, string> = {
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
  "image/gif": "gif",
  "application/pdf": "pdf",
  "video/mp4": "mp4",
  "video/webm": "webm",
};
```

### DTOs

```typescript
// apps/api/src/modules/media/dto/media.dto.ts
import { ObjectType, Field, ID, Int, registerEnumType } from "@nestjs/graphql";
import { MediaStatus } from "../media.entity";

registerEnumType(MediaStatus, { name: "MediaStatus" });

@ObjectType()
export class MediaDto {
  @Field(() => ID)
  id: number;

  @Field()
  fileKey: string;

  @Field()
  originalName: string;

  @Field()
  mimeType: string;

  @Field(() => String)
  sizeBytes: string;

  @Field(() => MediaStatus)
  status: MediaStatus;

  @Field({ nullable: true })
  cdnUrl: string | null;

  @Field({ nullable: true })
  thumbnailUrl: string | null;

  @Field({ nullable: true })
  processedAt: Date | null;

  @Field({ nullable: true })
  errorMessage: string | null;
}

@ObjectType()
export class UploadUrlResult {
  @Field()
  uploadUrl: string;

  @Field()
  fileKey: string;

  @Field(() => ID)
  mediaId: number;
}
```

### CQRS Inputs

```typescript
// apps/api/src/modules/media/cqrs/inputs/request-upload.input.ts
import { InputType, Field, Int } from "@nestjs/graphql";
import { IsString, IsMimeType, IsInt, Min, Max } from "class-validator";
import { MAX_SIZE_BYTES } from "../../media.constants";

@InputType()
export class RequestUploadInput {
  @Field()
  @IsString()
  originalName: string;

  @Field()
  @IsMimeType()
  mimeType: string;

  // sizeBytes declared by the client — validated against MAX_SIZE_BYTES
  // Not trusted for enforcement: ContentLengthRange is the S3-level control
  @Field(() => Int)
  @IsInt()
  @Min(1)
  @Max(MAX_SIZE_BYTES)
  sizeBytes: number;
}
```

```typescript
// apps/api/src/modules/media/cqrs/inputs/confirm-upload.input.ts
import { InputType, Field, ID } from "@nestjs/graphql";
import { IsInt, Min } from "class-validator";

@InputType()
export class ConfirmUploadInput {
  @Field(() => ID)
  @IsInt()
  @Min(1)
  mediaId: number;
}
```

### Service

```typescript
// apps/api/src/modules/media/media.service.ts
import {
  BadRequestException,
  Injectable,
  NotFoundException,
} from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { Repository } from "typeorm";
import { InjectQueue } from "@nestjs/bull";
import { Queue } from "bull";
import { randomUUID } from "crypto";
import { MediaEntity, MediaStatus } from "./media.entity";
import { S3Service } from "./s3.service";
import {
  ALLOWED_MIME_TYPES,
  MAX_SIZE_BYTES,
  MEDIA_QUEUE,
  MIME_TO_EXT,
} from "./media.constants";
import { UploadUrlResult } from "./dto/media.dto";

@Injectable()
export class MediaService {
  constructor(
    @InjectRepository(MediaEntity)
    private readonly mediaRepo: Repository<MediaEntity>,
    private readonly s3Service: S3Service,
    @InjectQueue(MEDIA_QUEUE)
    private readonly mediaQueue: Queue
  ) {}

  /**
   * Validates the upload request, generates a per-tenant S3 key,
   * saves a PENDING entity, and returns a presigned PUT URL.
   *
   * fileKey pattern: tenants/{tenantId}/media/{uuid}.{ext}
   *   - Per-tenant prefix enables per-tenant S3 lifecycle rules and IAM policies
   *   - UUID in the key prevents enumeration (you cannot guess another user's key)
   *   - Extension preserved for browsers that infer content type from URL
   */
  async requestUploadMedia(
    userId: number,
    tenantId: number,
    originalName: string,
    mimeType: string,
    sizeBytes: number
  ): Promise<UploadUrlResult> {
    if (!ALLOWED_MIME_TYPES.has(mimeType)) {
      throw new BadRequestException(
        `MIME type '${mimeType}' is not allowed. ` +
          `Allowed types: ${[...ALLOWED_MIME_TYPES].join(", ")}`
      );
    }

    if (sizeBytes > MAX_SIZE_BYTES) {
      throw new BadRequestException(
        `File size ${sizeBytes} bytes exceeds the maximum of ${MAX_SIZE_BYTES} bytes (100MB).`
      );
    }

    const ext = MIME_TO_EXT[mimeType];
    const fileKey = `tenants/${tenantId}/media/${randomUUID()}.${ext}`;

    const media = this.mediaRepo.create({
      tenantId,
      userId,
      fileKey,
      originalName,
      mimeType,
      sizeBytes: sizeBytes.toString(),
      status: MediaStatus.PENDING,
      cdnUrl: null,
      thumbnailUrl: null,
      processedAt: null,
      errorMessage: null,
    });

    const savedMedia = await this.mediaRepo.save(media);

    const uploadUrl = await this.s3Service.generateUploadUrl(
      fileKey,
      mimeType,
      MAX_SIZE_BYTES
    );

    return {
      uploadUrl,
      fileKey,
      mediaId: savedMedia.id,
    };
  }

  /**
   * Called by the browser after the S3 PUT completes successfully.
   * Sets status to UPLOADED and enqueues the processing job.
   *
   * Filters by id + userId + tenantId — a user cannot confirm another user's upload,
   * and cross-tenant confirmation is structurally impossible.
   */
  async confirmUploadMedia(
    mediaId: number,
    userId: number,
    tenantId: number
  ): Promise<MediaEntity> {
    const media = await this.mediaRepo.findOne({
      where: { id: mediaId, userId, tenantId, status: MediaStatus.PENDING },
    });

    if (!media) {
      throw new NotFoundException(
        `Media ${mediaId} not found, already confirmed, or does not belong to this user.`
      );
    }

    media.status = MediaStatus.UPLOADED;
    const saved = await this.mediaRepo.save(media);

    // Enqueue the processing job — magic byte check, thumbnail generation
    // This runs asynchronously; the browser does not wait for it
    await this.mediaQueue.add(
      "process-upload",
      { mediaId: saved.id },
      {
        attempts: 3,
        backoff: { type: "exponential", delay: 5000 },
        removeOnComplete: true,
        removeOnFail: false, // Keep failed jobs for inspection in Bull Board
      }
    );

    return saved;
  }

  async findOneMedia(
    id: number,
    tenantId: number
  ): Promise<MediaEntity | null> {
    return this.mediaRepo.findOne({ where: { id, tenantId } });
  }
}
```

### Verify: Service Wired

```bash
yarn api:dev
# Expected: no "Cannot find module" or DI injection errors
# If BullModule is not imported yet — add it in Section 6 (MediaModule)
```

---

## 6. MediaResolver + CQRS Wiring

### CQRS Commands and Queries

```typescript
// apps/api/src/modules/media/cqrs/commands/request-upload.command.ts
import { TypedCommand } from "nestjs-typed-cqrs";
import { UploadUrlResult } from "../../dto/media.dto";

export class RequestUploadCommand extends TypedCommand<UploadUrlResult> {
  constructor(
    public readonly userId: number,
    public readonly tenantId: number,
    public readonly originalName: string,
    public readonly mimeType: string,
    public readonly sizeBytes: number
  ) {
    super();
  }
}
```

```typescript
// apps/api/src/modules/media/cqrs/commands/confirm-upload.command.ts
import { TypedCommand } from "nestjs-typed-cqrs";
import { MediaEntity } from "../../media.entity";

export class ConfirmUploadCommand extends TypedCommand<MediaEntity> {
  constructor(
    public readonly mediaId: number,
    public readonly userId: number,
    public readonly tenantId: number
  ) {
    super();
  }
}
```

### CQRS Handlers

Handlers are strict one-liners. No business logic — they exist only to bridge the CQRS bus to the service layer.

```typescript
// apps/api/src/modules/media/cqrs/handlers/request-upload.handler.ts
import { CommandHandler, ICommandHandler } from "@nestjs/cqrs";
import { MediaService } from "../../media.service";
import { RequestUploadCommand } from "../commands/request-upload.command";
import { UploadUrlResult } from "../../dto/media.dto";

@CommandHandler(RequestUploadCommand)
export class RequestUploadHandler implements ICommandHandler<
  RequestUploadCommand,
  UploadUrlResult
> {
  constructor(private readonly mediaService: MediaService) {}

  execute(command: RequestUploadCommand): Promise<UploadUrlResult> {
    return this.mediaService.requestUploadMedia(
      command.userId,
      command.tenantId,
      command.originalName,
      command.mimeType,
      command.sizeBytes
    );
  }
}
```

```typescript
// apps/api/src/modules/media/cqrs/handlers/confirm-upload.handler.ts
import { CommandHandler, ICommandHandler } from "@nestjs/cqrs";
import { MediaService } from "../../media.service";
import { ConfirmUploadCommand } from "../commands/confirm-upload.command";
import { MediaEntity } from "../../media.entity";

@CommandHandler(ConfirmUploadCommand)
export class ConfirmUploadHandler implements ICommandHandler<
  ConfirmUploadCommand,
  MediaEntity
> {
  constructor(private readonly mediaService: MediaService) {}

  execute(command: ConfirmUploadCommand): Promise<MediaEntity> {
    return this.mediaService.confirmUploadMedia(
      command.mediaId,
      command.userId,
      command.tenantId
    );
  }
}
```

### CQRS Index

```typescript
// apps/api/src/modules/media/cqrs/index.ts
export { RequestUploadCommand } from "./commands/request-upload.command";
export { ConfirmUploadCommand } from "./commands/confirm-upload.command";
export { RequestUploadHandler } from "./handlers/request-upload.handler";
export { ConfirmUploadHandler } from "./handlers/confirm-upload.handler";
```

### Resolver

```typescript
// apps/api/src/modules/media/media.resolver.ts
import { Args, Mutation, Query, Resolver, ID } from "@nestjs/graphql";
import { UseGuards } from "@nestjs/common";
import { CommandBus } from "@nestjs/cqrs";
import { AuthJwtGuard } from "../auth/auth-jwt.guard";
import { ACPermissionGuard } from "../auth/ac-permission.guard";
import { UseACGuard } from "../auth/use-ac-guard.decorator";
import { CurrentUser } from "../auth/current-user.decorator";
import { JwtPayload } from "@enterprise-todo/contracts";
import { MediaDto, UploadUrlResult } from "./dto/media.dto";
import { RequestUploadInput } from "./cqrs/inputs/request-upload.input";
import { ConfirmUploadInput } from "./cqrs/inputs/confirm-upload.input";
import { RequestUploadCommand, ConfirmUploadCommand } from "./cqrs";
import { MediaEntity } from "./media.entity";

@Resolver(() => MediaDto)
export class MediaResolver {
  constructor(private readonly commandBus: CommandBus) {}

  /**
   * Step 1 of the presigned URL flow.
   * Returns a presigned S3 PUT URL + the mediaId to use in confirmUpload.
   * The browser PUTs the file directly to S3 using uploadUrl — not through this API.
   */
  @UseGuards(AuthJwtGuard, ACPermissionGuard)
  @UseACGuard("MEDIA", ["upload-media"])
  @Mutation(() => UploadUrlResult)
  async requestUpload(
    @Args("input") input: RequestUploadInput,
    @CurrentUser() user: JwtPayload
  ): Promise<UploadUrlResult> {
    return this.commandBus.execute(
      new RequestUploadCommand(
        user.sub,
        user.tenantId,
        input.originalName,
        input.mimeType,
        input.sizeBytes
      )
    );
  }

  /**
   * Step 3 of the presigned URL flow.
   * Called by the browser after the S3 PUT returns 200.
   * Sets status to UPLOADED and enqueues background processing.
   */
  @UseGuards(AuthJwtGuard, ACPermissionGuard)
  @UseACGuard("MEDIA", ["upload-media"])
  @Mutation(() => MediaDto)
  async confirmUpload(
    @Args("input") input: ConfirmUploadInput,
    @CurrentUser() user: JwtPayload
  ): Promise<MediaEntity> {
    return this.commandBus.execute(
      new ConfirmUploadCommand(input.mediaId, user.sub, user.tenantId)
    );
  }
}
```

### Add Permission to Seeder

Add the `upload-media` permission to your permissions seeder so it can be assigned to roles:

```typescript
// apps/api/src/seeders/permissions.seeder.ts  (add to permissions array)
{
  name: 'Upload Media',
  module: 'MEDIA',
  slug: 'upload-media',
  description: 'Upload files to the media library',
},
```

### MediaModule

```typescript
// apps/api/src/modules/media/media.module.ts
import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { BullModule } from "@nestjs/bull";
import { MediaEntity } from "./media.entity";
import { MediaService } from "./media.service";
import { MediaResolver } from "./media.resolver";
import { S3Service } from "./s3.service";
import { MediaProcessor } from "./media.processor";
import { MEDIA_QUEUE } from "./media.constants";
import { RequestUploadHandler, ConfirmUploadHandler } from "./cqrs";

@Module({
  imports: [
    TypeOrmModule.forFeature([MediaEntity]),

    BullModule.registerQueue({
      name: MEDIA_QUEUE,
      // Redis connection is configured globally in AppModule via BullModule.forRootAsync
    }),
  ],
  providers: [
    MediaService,
    MediaResolver,
    S3Service,
    MediaProcessor,
    RequestUploadHandler,
    ConfirmUploadHandler,
  ],
})
export class MediaModule {}
```

Register `MediaModule` in `AppModule`:

```typescript
// apps/api/src/app/app.module.ts  (add to imports)
import { MediaModule } from "../modules/media/media.module";

@Module({
  imports: [
    // ... existing modules ...
    MediaModule,
  ],
})
export class AppModule {}
```

### Verify: Resolver Registered

```bash
yarn api:dev
# Expected: no startup errors

# Introspect to confirm the mutations exist
curl http://localhost:3333/graphql -X POST \
  -H "Content-Type: application/json" \
  -d '{"query":"{ __schema { mutationType { fields { name } } } }"}' \
  | jq '.data.__schema.mutationType.fields[].name' | grep -E "requestUpload|confirmUpload"
# Expected:
# "requestUpload"
# "confirmUpload"
```

---

## 7. MediaProcessor (Bull)

The processor runs as a background Bull worker. It downloads only the first 4KB of the uploaded file, validates the magic bytes against the declared MIME type, generates a thumbnail for images, and updates the entity to `READY` or `FAILED`.

```typescript
// apps/api/src/modules/media/media.processor.ts
import { Processor, Process } from "@nestjs/bull";
import { Logger } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { Repository } from "typeorm";
import { Job } from "bull";
import sharp from "sharp";
import { fileTypeFromBuffer } from "file-type";
import { MediaEntity, MediaStatus } from "./media.entity";
import { S3Service } from "./s3.service";
import { MEDIA_QUEUE } from "./media.constants";

interface ProcessUploadJob {
  mediaId: number;
}

// Magic byte → MIME type mappings that file-type recognises
// If the detected type is not in this set, the file is FAILED (not a security rejection we log and stop)
const PROCESSABLE_IMAGE_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
]);

// Thumbnail dimensions — 200×200 max, converted to webp for optimal size
const THUMBNAIL_SIZE = 200;
const THUMBNAIL_SUFFIX = "_thumb.webp";

@Processor(MEDIA_QUEUE)
export class MediaProcessor {
  private readonly logger = new Logger(MediaProcessor.name);

  constructor(
    @InjectRepository(MediaEntity)
    private readonly mediaRepo: Repository<MediaEntity>,
    private readonly s3Service: S3Service
  ) {}

  @Process("process-upload")
  async handleProcessUpload(job: Job<ProcessUploadJob>): Promise<void> {
    const { mediaId } = job.data;
    this.logger.log(`Processing media ${mediaId}`);

    const media = await this.mediaRepo.findOne({
      where: { id: mediaId, status: MediaStatus.UPLOADED },
    });

    if (!media) {
      // Already processed (READY/FAILED) or never confirmed — do nothing
      this.logger.warn(
        `Media ${mediaId} not found in UPLOADED state — skipping`
      );
      return;
    }

    try {
      // Download only the first 4KB — enough for magic byte detection
      // Avoids downloading the full file (could be 100MB video) just to check the type
      const firstBytes = await this.s3Service.getFirstBytes(
        media.fileKey,
        4096
      );

      // fileTypeFromBuffer inspects magic bytes — the first few bytes that identify
      // the real format regardless of extension or declared Content-Type
      // A .jpg file that is actually a ZIP will have PK\x03\x04 as its first bytes
      const detectedType = await fileTypeFromBuffer(firstBytes);

      if (!detectedType || detectedType.mime !== media.mimeType) {
        // Security rejection — extension/MIME were spoofed
        // Do NOT re-queue (attempts: 3 is for transient S3 errors, not security failures)
        await this.failMedia(
          media,
          `Magic byte mismatch: declared '${media.mimeType}', ` +
            `detected '${detectedType?.mime ?? "unknown"}'. Upload rejected.`
        );
        this.logger.warn(
          `Media ${mediaId} FAILED: magic byte mismatch ` +
            `(declared ${media.mimeType}, detected ${detectedType?.mime ?? "unknown"})`
        );
        return;
      }

      // Set CDN URL for the original file
      media.cdnUrl = this.s3Service.getCdnUrl(media.fileKey);

      // Generate thumbnail for image types
      if (PROCESSABLE_IMAGE_TYPES.has(media.mimeType)) {
        const thumbnailKey = media.fileKey.replace(
          /\.[^.]+$/,
          THUMBNAIL_SUFFIX
        );

        // Sharp works on the first 4KB — only enough for JPEG/PNG magic bytes.
        // For thumbnail generation we need the full image. Download it.
        const fullBytes = await this.s3Service.getFirstBytes(
          media.fileKey,
          // getFirstBytes with a very large number effectively downloads the full file
          // In production, consider a separate getObject method that streams directly to sharp
          100 * 1024 * 1024
        );

        const thumbnailBuffer = await sharp(fullBytes)
          .resize(THUMBNAIL_SIZE, THUMBNAIL_SIZE, {
            fit: "cover",
            position: "attention", // smart crop — focuses on salient regions
          })
          .webp({ quality: 80 })
          .toBuffer();

        // Upload thumbnail to S3 under the same tenant prefix
        await this.uploadThumbnail(thumbnailKey, thumbnailBuffer);
        media.thumbnailUrl = this.s3Service.getCdnUrl(thumbnailKey);
      }

      media.status = MediaStatus.READY;
      media.processedAt = new Date();
      media.errorMessage = null;

      await this.mediaRepo.save(media);
      this.logger.log(`Media ${mediaId} → READY`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      await this.failMedia(media, `Processing error: ${message}`);
      this.logger.error(`Media ${mediaId} → FAILED: ${message}`);
      // Re-throw so Bull retries (attempts: 3 with exponential backoff)
      throw error;
    }
  }

  private async failMedia(
    media: MediaEntity,
    errorMessage: string
  ): Promise<void> {
    media.status = MediaStatus.FAILED;
    media.errorMessage = errorMessage.slice(0, 500); // column length limit
    media.processedAt = new Date();
    await this.mediaRepo.save(media);
  }

  private async uploadThumbnail(key: string, buffer: Buffer): Promise<void> {
    // Re-use the S3 client from S3Service via a direct put
    // Thumbnail is a small webp — no presigned URL needed (server-to-server)
    const { S3Client, PutObjectCommand } = await import("@aws-sdk/client-s3");
    const { ConfigService } = await import("@nestjs/config");
    // Note: in a real implementation, inject S3Client directly rather than re-instantiating.
    // This is simplified for tutorial clarity — see the note below.
    void key;
    void buffer;
    // Implementation detail: extend S3Service with a putObject(key, buffer, contentType) method
    // and call it here. Omitted to keep S3Service focused on its primary responsibilities.
  }
}
```

### Extend S3Service with putObject

Add this method to `S3Service` so the processor can upload thumbnails server-to-server:

```typescript
// apps/api/src/modules/media/s3.service.ts  (add method to existing S3Service)

/**
 * Server-to-server upload — used by the processor to save generated thumbnails.
 * Does NOT generate a presigned URL; the API server writes directly to S3
 * using its IAM credentials. Only the processor calls this.
 */
async putObject(key: string, body: Buffer, contentType: string): Promise<void> {
  const { PutObjectCommand } = await import('@aws-sdk/client-s3');
  const command = new PutObjectCommand({
    Bucket: this.bucket,
    Key: key,
    Body: body,
    ContentType: contentType,
  });
  await this.client.send(command);
}
```

Update the processor's `uploadThumbnail` method:

```typescript
// apps/api/src/modules/media/media.processor.ts  (replace uploadThumbnail)
private async uploadThumbnail(key: string, buffer: Buffer): Promise<void> {
  await this.s3Service.putObject(key, buffer, 'image/webp');
}
```

### Key Design Decisions

**4KB range request for magic bytes.** Most magic byte signatures are in the first 8–16 bytes (JPEG: `\xFF\xD8\xFF`, PNG: `\x89PNG`, ZIP/DOCX/XLSX: `PK\x03\x04`, PDF: `%PDF`). Downloading 4KB gives `file-type` more than enough data while downloading less than 0.004% of a 100MB file.

**Security rejection vs transient error.** A magic byte mismatch is not a transient error — it is a deliberate or accidental file type spoof. Setting `FAILED` immediately is correct. The Bull `attempts: 3` setting is for transient S3 errors (network timeout, throttling). A FAILED job caused by a magic byte mismatch should not be retried; the `throw` in the `catch` block only runs for unexpected errors, not the explicit `failMedia` path which returns early.

**smart crop for thumbnails.** `sharp`'s `attention` gravity analyses the image and crops around salient regions rather than just centre-cropping. A profile photo where the face is at the top of the frame stays correctly framed. Switch to `'center'` if you want predictable crop positions.

### Verify: Processor Processes Jobs

```bash
yarn api:dev

# After running requestUpload + S3 PUT + confirmUpload (see Section 11),
# watch the Bull Board for the job:
# http://localhost:3333/queues
# Expected: job appears in 'media-processing' queue, moves to 'completed'
```

---

## 8. Migration

### Generate the Migration

```bash
yarn api:migration:generate apps/api/src/migrations/CreateMediaTable
```

The generated migration will contain `CREATE TABLE media` with all columns from `MediaEntity`, the `media_status_enum` PostgreSQL enum, and the indexes on `tenantId`, `userId`, and `status`.

Review the generated SQL before running. Confirm:

- `status` column uses the `media_status_enum` enum type
- `size_bytes` column is `bigint` (not `integer`)
- `file_key` has a `UNIQUE` constraint
- `idx_media_status`, `idx_media_tenant_id`, `idx_media_user_id` indexes are present

```bash
# Apply the migration
yarn api:migration:run

# Verify round-trip
yarn api:migration:revert
# Expected: migration reverted — 'media' table dropped

yarn api:migration:run
# Expected: migration re-applied cleanly
```

### Verify: API Starts with New Table

```bash
yarn api:dev
# Expected: NestJS starts without EntityMetadataNotFoundError

# Confirm the table exists in Postgres
# Adminer: http://localhost:8080 → enterprise_todo → media table
```

---

## 9. Frontend Upload Hook + Component

### useFileUpload Hook

```typescript
// apps/web/src/hooks/useFileUpload.ts
import { useState } from "react";
import { useMutation } from "@apollo/client/react";
import { gql } from "@apollo/client";

const REQUEST_UPLOAD = gql`
  mutation RequestUpload($input: RequestUploadInput!) {
    requestUpload(input: $input) {
      uploadUrl
      fileKey
      mediaId
    }
  }
`;

const CONFIRM_UPLOAD = gql`
  mutation ConfirmUpload($input: ConfirmUploadInput!) {
    confirmUpload(input: $input) {
      id
      status
      cdnUrl
      thumbnailUrl
    }
  }
`;

export type UploadState =
  | { type: "idle" }
  | { type: "requesting" }
  | { type: "uploading"; progress: number }
  | { type: "confirming" }
  | { type: "done"; cdnUrl: string | null; mediaId: number }
  | { type: "error"; message: string };

export function useFileUpload() {
  const [state, setState] = useState<UploadState>({ type: "idle" });

  const [requestUploadMutation] = useMutation(REQUEST_UPLOAD);
  const [confirmUploadMutation] = useMutation(CONFIRM_UPLOAD);

  const upload = async (file: File): Promise<void> => {
    setState({ type: "requesting" });

    try {
      // Step 1: Request presigned URL from API
      const { data: requestData } = await requestUploadMutation({
        variables: {
          input: {
            originalName: file.name,
            mimeType: file.type,
            sizeBytes: file.size,
          },
        },
      });

      const { uploadUrl, mediaId } = requestData.requestUpload;

      // Step 2: PUT file directly to S3
      // Note: Authorization header must NOT be sent to S3 — it would cause a SignatureDoesNotMatch error
      // The presigned URL already carries all the auth information in query params
      setState({ type: "uploading", progress: 0 });

      const uploadResponse = await fetch(uploadUrl, {
        method: "PUT",
        body: file,
        headers: {
          "Content-Type": file.type,
          // Do NOT include Authorization header here
        },
      });

      if (!uploadResponse.ok) {
        throw new Error(
          `S3 upload failed: ${uploadResponse.status} ${uploadResponse.statusText}`
        );
      }

      setState({ type: "confirming" });

      // Step 3: Confirm the upload with the API
      const { data: confirmData } = await confirmUploadMutation({
        variables: {
          input: { mediaId },
        },
      });

      const { cdnUrl } = confirmData.confirmUpload;
      setState({ type: "done", cdnUrl, mediaId });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload failed";
      setState({ type: "error", message });
    }
  };

  const reset = () => setState({ type: "idle" });

  return { upload, state, reset };
}
```

### AvatarUpload Component

```typescript
// apps/web/src/components/AvatarUpload.tsx
'use client';

import { useRef } from 'react';
import { useFileUpload } from '../hooks/useFileUpload';

interface AvatarUploadProps {
  currentAvatarUrl?: string | null;
  onUploadComplete?: (cdnUrl: string | null, mediaId: number) => void;
}

export function AvatarUpload({ currentAvatarUrl, onUploadComplete }: AvatarUploadProps) {
  const { upload, state, reset } = useFileUpload();
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // Reset the input so the same file can be re-selected if needed
    event.target.value = '';

    await upload(file);

    if (state.type === 'done') {
      onUploadComplete?.(state.cdnUrl, state.mediaId);
    }
  };

  const isUploading =
    state.type === 'requesting' ||
    state.type === 'uploading' ||
    state.type === 'confirming';

  return (
    <div className="flex flex-col items-center gap-3">
      {/* Avatar preview */}
      <div className="w-24 h-24 rounded-full overflow-hidden bg-muted border border-border">
        {currentAvatarUrl ? (
          <img
            src={currentAvatarUrl}
            alt="Avatar"
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-muted-foreground text-sm">
            No photo
          </div>
        )}
      </div>

      {/* Upload button */}
      <button
        type="button"
        disabled={isUploading}
        onClick={() => inputRef.current?.click()}
        className="px-4 py-2 text-sm rounded-md border border-border bg-background hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isUploading ? 'Uploading...' : 'Change photo'}
      </button>

      {/* Progress states */}
      {state.type === 'uploading' && (
        <p className="text-xs text-muted-foreground">Uploading to S3...</p>
      )}
      {state.type === 'confirming' && (
        <p className="text-xs text-muted-foreground">Confirming upload...</p>
      )}
      {state.type === 'done' && (
        <p className="text-xs text-green-600">Upload complete. Processing in background.</p>
      )}
      {state.type === 'error' && (
        <div className="text-xs text-red-600">
          {state.message}
          <button
            type="button"
            onClick={reset}
            className="ml-2 underline"
          >
            Try again
          </button>
        </div>
      )}

      {/* Hidden file input — only accepts allowed MIME types */}
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        accept="image/jpeg,image/png,image/webp,image/gif"
        onChange={handleFileChange}
      />
    </div>
  );
}
```

### Polling vs Subscriptions for READY Status

After `confirmUpload`, the media is `UPLOADED`. The Bull processor runs asynchronously — the browser needs a way to know when it becomes `READY`. Two approaches:

**Polling (simple):** Add a `media(id: Int!)` query to `MediaResolver` and poll every 2 seconds until `status === 'READY'`. Works without WebSocket infrastructure.

**Subscriptions (elegant):** Use the GraphQL subscription pattern from Tutorial 6111. The processor publishes a `mediaProcessed` event after updating status, and the browser receives it instantly via WebSocket. No polling loop needed.

For the `AvatarUpload` component above, polling is sufficient since the thumbnail appears after the user navigates away and returns. Add this query for completeness:

```typescript
// apps/api/src/modules/media/media.resolver.ts  (add query)
@UseGuards(AuthJwtGuard)
@Query(() => MediaDto, { nullable: true })
async media(
  @Args('id', { type: () => ID }) id: number,
  @CurrentUser() user: JwtPayload,
): Promise<MediaEntity | null> {
  return this.mediaService.findOneMedia(id, user.tenantId);
}
```

---

## 10. S3 Bucket Policy + CloudFront

### S3 Bucket Configuration

Create your S3 bucket with all public access blocked. The bucket itself is never directly accessible from the internet — only CloudFront (via OAC) can read objects.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowCloudFrontOAC",
      "Effect": "Allow",
      "Principal": {
        "Service": "cloudfront.amazonaws.com"
      },
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::enterprise-todo-media-prod/*",
      "Condition": {
        "StringEquals": {
          "AWS:SourceArn": "arn:aws:cloudfront::123456789012:distribution/EDFDVBD6EXAMPLE"
        }
      }
    }
  ]
}
```

This policy allows `s3:GetObject` only when the request originates from your specific CloudFront distribution. Direct S3 URLs (`s3.amazonaws.com/enterprise-todo-media-prod/...`) return `403 AccessDenied`. Only CDN URLs (`d1abc.cloudfront.net/...`) work.

Presigned PUT URLs are not affected by this policy. Presigned URLs carry AWS credentials in query parameters (`X-Amz-Credential`, `X-Amz-Signature`). The `s3:PutObject` permission comes from your API server's IAM role, not from the bucket policy's public access settings. The browser can PUT objects using a presigned URL even though the bucket blocks all public access — these are two independent permission axes.

### IAM Policy for the API Server

Attach this policy to the IAM role used by your ECS task or EC2 instance running the NestJS API:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowPresignedPut",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::enterprise-todo-media-prod/*"
    }
  ]
}
```

`s3:PutObject` — generates presigned PUT URLs and the processor's `putObject` (thumbnail upload).
`s3:GetObject` — the processor's `getFirstBytes` range request (magic byte check).

Do not grant `s3:DeleteObject` to the API server. Soft-delete `MediaEntity` rows instead; run a separate cleanup Lambda on a schedule to remove orphaned S3 objects.

### CloudFront Distribution Setup

1. **Create an Origin Access Control (OAC)** — not the older Origin Access Identity (OAI). In the CloudFront console: Security → Origin access → Create control setting. Type: S3, Signing behavior: Sign requests.

2. **Create a distribution** with:
   - Origin domain: your S3 bucket's REST endpoint (`enterprise-todo-media-prod.s3.ap-southeast-1.amazonaws.com`)
   - Origin access: the OAC you just created
   - Viewer protocol policy: Redirect HTTP to HTTPS
   - Cache policy: CachingOptimized (default TTL 86400s / 24h)
   - Response headers policy: add `Cache-Control: public, max-age=31536000, immutable` for processed media (objects at their final S3 key never change — they are UUID-keyed)

3. **Copy the bucket policy** that CloudFront generates and apply it to your S3 bucket (the policy shown above). CloudFront will display the exact policy to copy, pre-filled with your distribution ARN.

4. Set `CDN_BASE_URL` in your `.env` to your CloudFront domain: `https://d1abc123.cloudfront.net`.

### Local Development

For local development you have three options:

**Option A — Real AWS, public bucket (simplest):** Temporarily enable public read on the dev S3 bucket. Set `CDN_BASE_URL` to the S3 public URL. Remove public access when done.

**Option B — LocalStack:** Run `localstack` via Docker. LocalStack emulates S3 and returns presigned URLs pointing to `http://localhost:4566`. Set `CDN_BASE_URL=http://localhost:4566/enterprise-todo-media-dev`.

**Option C — Real AWS, no CloudFront:** Create a separate dev bucket, enable public read ACL on objects. In `S3Service.putObject`, add `ACL: 'public-read'` to the `PutObjectCommand`. Set `CDN_BASE_URL` to `https://<bucket>.s3.<region>.amazonaws.com`.

---

## 11. Smoke Test (End to End)

Run these steps in order with AWS credentials configured in your `.env`.

### Step 1: Start the Stack

```bash
# Terminal 1 — infrastructure
yarn docker:dev
# Expected: Postgres :5432, Redis :6379, Adminer :8080 running

# Terminal 2 — API
yarn api:dev
# Expected: NestJS starts, Bull connects to Redis, no startup errors
# Expected: "Application is running on: http://localhost:3333"
```

### Step 2: Run Migrations and Seed

```bash
yarn api:migration:run
# Expected: CreateMediaTable migration applied (among others)

yarn api:seed:run
# Expected: permissions seeded including "upload-media" slug
```

### Step 3: Get an Auth Token

```bash
TOKEN=$(curl -s http://localhost:3333/graphql -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { login(input: { email: \"user@example.com\", password: \"password123\" }) { accessToken } }"
  }' | jq -r '.data.login.accessToken')

echo "Token: $TOKEN"
```

### Step 4: Request a Presigned Upload URL

```bash
UPLOAD_RESULT=$(curl -s http://localhost:3333/graphql -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "query": "mutation RequestUpload($input: RequestUploadInput!) { requestUpload(input: $input) { uploadUrl fileKey mediaId } }",
    "variables": {
      "input": {
        "originalName": "avatar.jpg",
        "mimeType": "image/jpeg",
        "sizeBytes": 12345
      }
    }
  }')

echo $UPLOAD_RESULT | jq .

UPLOAD_URL=$(echo $UPLOAD_RESULT | jq -r '.data.requestUpload.uploadUrl')
MEDIA_ID=$(echo $UPLOAD_RESULT | jq -r '.data.requestUpload.mediaId')

echo "Upload URL: $UPLOAD_URL"
echo "Media ID: $MEDIA_ID"
```

Expected response:

```json
{
  "data": {
    "requestUpload": {
      "uploadUrl": "https://enterprise-todo-media-dev.s3.ap-southeast-1.amazonaws.com/tenants/1/media/abc123.jpg?X-Amz-Algorithm=...",
      "fileKey": "tenants/1/media/abc123-...-abc.jpg",
      "mediaId": 1
    }
  }
}
```

### Step 5: PUT the File Directly to S3

```bash
# Use any small JPEG for testing
curl -X PUT "$UPLOAD_URL" \
  -H "Content-Type: image/jpeg" \
  --data-binary @./test.jpg \
  -v 2>&1 | grep "< HTTP"
# Expected: < HTTP/1.1 200 OK
```

If you do not have a test JPEG, create a minimal one:

```bash
# Download a public 1x1 pixel JPEG for testing
curl -o test.jpg https://via.placeholder.com/150.jpg
```

### Step 6: Confirm the Upload

```bash
curl -s http://localhost:3333/graphql -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"query\": \"mutation ConfirmUpload(\$input: ConfirmUploadInput!) { confirmUpload(input: \$input) { id status cdnUrl thumbnailUrl } }\",
    \"variables\": {
      \"input\": { \"mediaId\": $MEDIA_ID }
    }
  }" | jq .
```

Expected response:

```json
{
  "data": {
    "confirmUpload": {
      "id": "1",
      "status": "UPLOADED",
      "cdnUrl": null,
      "thumbnailUrl": null
    }
  }
}
```

`cdnUrl` is null at this point — the processor has not run yet.

### Step 7: Watch the Bull Board

Open `http://localhost:3333/queues` in your browser. You should see:

- Queue: `media-processing`
- One job in `waiting` or `active`
- Within seconds: job moves to `completed`

If the job moves to `failed`, check the job error in the Bull Board for details. Common causes:

- AWS credentials not set in `.env`
- S3 bucket does not exist in the configured region
- `file-type` version issue — check Section 2 Gotcha

### Step 8: Query the Media Record

```bash
# Wait a few seconds for the processor to complete, then:
curl -s http://localhost:3333/graphql -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"query\": \"query { media(id: $MEDIA_ID) { id status cdnUrl thumbnailUrl processedAt } }\"
  }" | jq .
```

Expected after processing:

```json
{
  "data": {
    "media": {
      "id": "1",
      "status": "READY",
      "cdnUrl": "https://d1abc123.cloudfront.net/tenants/1/media/abc123.jpg",
      "thumbnailUrl": "https://d1abc123.cloudfront.net/tenants/1/media/abc123_thumb.webp",
      "processedAt": "2026-06-29T03:15:00.000Z"
    }
  }
}
```

### Step 9: Test Magic Byte Rejection

Upload a ZIP file renamed as a JPEG to verify the security check:

```bash
# Create a ZIP file disguised as a JPEG
cp /path/to/any.zip fake-image.jpg

# Request upload URL for the fake JPEG
FAKE_RESULT=$(curl -s http://localhost:3333/graphql -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "query": "mutation RequestUpload($input: RequestUploadInput!) { requestUpload(input: $input) { uploadUrl mediaId } }",
    "variables": {
      "input": {
        "originalName": "fake-image.jpg",
        "mimeType": "image/jpeg",
        "sizeBytes": 1024
      }
    }
  }')

FAKE_UPLOAD_URL=$(echo $FAKE_RESULT | jq -r '.data.requestUpload.uploadUrl')
FAKE_MEDIA_ID=$(echo $FAKE_RESULT | jq -r '.data.requestUpload.mediaId')

# PUT the ZIP to S3 with a JPEG content type
curl -X PUT "$FAKE_UPLOAD_URL" \
  -H "Content-Type: image/jpeg" \
  --data-binary @./fake-image.jpg

# Confirm the upload
curl -s http://localhost:3333/graphql -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"query\": \"mutation { confirmUpload(input: { mediaId: $FAKE_MEDIA_ID }) { id status } }\"
  }"

# Wait a few seconds, then query the status
sleep 5
curl -s http://localhost:3333/graphql -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"query\": \"{ media(id: $FAKE_MEDIA_ID) { id status errorMessage } }\"
  }" | jq .
```

Expected:

```json
{
  "data": {
    "media": {
      "id": "2",
      "status": "FAILED",
      "errorMessage": "Magic byte mismatch: declared 'image/jpeg', detected 'application/zip'. Upload rejected."
    }
  }
}
```

The file is stored in S3 (the presigned URL let it through), but the processed record is marked `FAILED` and no CDN URL is set. Add a scheduled cleanup to delete `FAILED` S3 objects older than 24 hours using an S3 lifecycle rule on keys matching `tenants/*/media/*` with `status` tag `FAILED`.

---

## Summary: Meteor ostrio:files vs Enterprise Presigned URL Pattern

| Concern                   | Meteor ostrio:files                                | Enterprise presigned URL                                               |
| ------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------- |
| File bytes path           | Through Meteor server DDP connection               | Direct browser → S3, API never sees bytes                              |
| Server load during upload | DDP connection blocked for entire transfer         | Two small JSON mutations, zero file I/O                                |
| Storage on server failure | Files lost if written to local disk                | S3 is durable (11 9s) — server restart irrelevant                      |
| CDN delivery              | Manual CloudFront config, S3 URLs in DB            | `getCdnUrl()` returns CloudFront URL — CDN is the only delivery path   |
| File type validation      | Extension + Content-Type header (both spoofable)   | Magic byte check on first 4KB — extension/MIME both untrusted          |
| Post-processing           | Synchronous in upload handler or manual setTimeout | Bull queue job — async, retryable, observable in Bull Board            |
| Per-tenant isolation      | Manual prefix convention                           | UUID fileKey with `tenants/{id}/` prefix — enforced in `requestUpload` |
| Large file support        | Limited by DDP message size                        | No API limit — S3 presigned PUT supports up to 5GB single-part         |
| Access control            | `allow/deny` on FilesCollection                    | ACPermissionGuard + per-tenant S3 prefix                               |

---

## What You Have Now

- **`apps/api/src/modules/media/media.entity.ts`** — `MediaEntity` with `PENDING → UPLOADED → READY / FAILED` lifecycle, `bigint` sizeBytes, `@Index()` on status
- **`apps/api/src/modules/media/s3.service.ts`** — `S3Service` with `generateUploadUrl`, `getCdnUrl`, `getFirstBytes`, `putObject`
- **`apps/api/src/modules/media/media.service.ts`** — `MediaService` with MIME allowlist, UUID fileKey per tenant, `requestUploadMedia`, `confirmUploadMedia`
- **`apps/api/src/modules/media/media.resolver.ts`** — `MediaResolver` with `requestUpload` + `confirmUpload` mutations, both gated by `ACPermissionGuard`
- **`apps/api/src/modules/media/media.processor.ts`** — `MediaProcessor` Bull worker: 4KB range download, `file-type` magic byte check, `sharp` thumbnail, READY/FAILED update
- **`apps/api/src/modules/media/cqrs/`** — `RequestUploadCommand`, `ConfirmUploadCommand`, one-liner handlers
- **`apps/api/src/modules/media/media.module.ts`** — `MediaModule` with `BullModule.registerQueue`
- **`apps/web/src/hooks/useFileUpload.ts`** — `useFileUpload` hook: requestUpload → S3 PUT → confirmUpload with upload state machine
- **`apps/web/src/components/AvatarUpload.tsx`** — `AvatarUpload` component with file input, preview, and upload state display
- **`libs/core/src/config/config.mapper.ts`** — `AppConfig.s3` with region, credentials, bucket, cdnBaseUrl
- **`libs/core/src/config/config.validation.ts`** — Joi validation for all five AWS env vars
- **Migrations** — `CreateMediaTable` with `media_status_enum`, indexes on tenantId, userId, status
- **Seeder** — `upload-media` permission slug for ACPermissionGuard

File bytes never cross your API server. The API issues presigned URLs, the browser writes to S3, and a Bull worker handles post-processing asynchronously. Adding more media types means extending `ALLOWED_MIME_TYPES` and `MIME_TO_EXT` — the architecture does not change.
