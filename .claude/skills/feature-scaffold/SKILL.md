---
name: feature-scaffold
description: Scaffolds a new NestJS feature module with Webby-standard boilerplate: controller, service, DTOs, repository layer, and Jest test stubs.
disable-model-invocation: true
---

# Feature Scaffold Workflow

For every feature scaffolding request, generate the following file matrix inside `projects/[project]/src/[feature-name]/`:

## Deliverable 1: Module Structure
*   `[feature].module.ts` — NestJS module wiring controller + service + repository.
*   `[feature].controller.ts` — REST endpoints with DTO validation decorators.
*   `[feature].service.ts` — Business logic layer, injected with repository.
*   `[feature].repository.ts` — Aurora PostgreSQL data access via TypeORM.
*   `dto/create-[feature].dto.ts` — Input validation using `class-validator`.
*   `dto/update-[feature].dto.ts` — Partial update DTO extending create DTO.

## Deliverable 2: Test Stubs
*   `[feature].service.spec.ts` — Jest unit tests with mocked repository.
*   `[feature].controller.spec.ts` — Jest integration tests using Supertest.

## Deliverable 3: ADR Stub
*   `projects/[project]/decisions/adr-[feature]-design.md` — Pre-filled ADR template for team to complete before first PR review.