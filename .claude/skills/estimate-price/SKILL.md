---
name: estimate-price
description: Evaluates proposed solution files, matches them against real-world internal pricing matrices, and outputs client-ready billing architectures.
disable-model-invocation: true
---

# Infrastructure Pricing Estimation Procedure

1. **Scan Scope:** Locate the technical spec in `context_brain/03_clusters/` or `proposals_and_pocs/`.
2. **Access Ground Truth:** Read `context_brain/04_pricing_matrices/aws-pricing-my.md`.
3. **Calculate MRC (Monthly Recurring Costs):** Total cloud expenditures + apply a 15% Webby operations markup. Convert all USD to MYR at the configured matrix rate.
4. **Calculate NRC (Non-Recurring Costs):** Extract engineering hour requirements based on complexity.
5. **Output Generation:** Write a structured markdown table named `infrastructure_tco_estimate.md` directly inside the client's `billing/` subdirectory.