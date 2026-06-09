---
name: scaffold-pre-sales
description: Executes the Harness Engineering loop to ingest raw discovery files and produce pre-sales deliverables (Architecture, Costing, and Pitch).
disable-model-invocation: true
---

# Pre-Sales Core Deliverables Generation Workflow

For every discovery document processed, output this file matrix in `proposals_and_pocs/[client-dir]/`:

## Deliverable 1: Architecture-as-Code
*   `infra/docker-compose.yml` (Local isolated replication)
*   `infra/main.tf` (AWS Malaysia `ap-southeast-5` Terraform script)

## Deliverable 2: Cost Optimization Matrix
*   `billing/infrastructure_tco_estimate.md` (Read `context_brain/04_pricing_matrices/aws-pricing-my.md`. Calculate USD/MYR with Webby 15% operations premium).

## Deliverable 3: Pre-sales Pitch
*   `docs/pre_sales_pitch.md` (Business proposal focused on ROI, addressing Risk Mitigation, following Webby's 7-Stage Sales Cycle).
