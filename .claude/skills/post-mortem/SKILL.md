---
name: post-mortem
description: Reviews code changes and customizations at the end of a client project to automatically update the Obsidian knowledge graph.
disable-model-invocation: true
---

# Post-Mortem Knowledge Capture Protocol

1. **Analyze Artifacts:** Run an analytical diff scan over the `src/` path of a completed client in `proposals_and_pocs/`.
2. **Identify Variations:** Detect unique configurations or workarounds (e.g., custom SQS queues, new API integrations).
3. **Deconstruct & Distill:**
    * New API integration = Write a new node in `context_brain/01_entities/`.
    * Custom workaround/pattern = Extract into `context_brain/02_concepts/`.
4. **Update Abstract Layer:** Write exact YAML frontmatter to link the new elements, preventing architectural amnesia for future prompts.