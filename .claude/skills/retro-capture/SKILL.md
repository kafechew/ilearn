---
name: retro-capture
description: Reviews sprint retrospective notes and completed PR diffs to automatically update the Obsidian knowledge graph with new ADRs, patterns, and updated velocity data.
disable-model-invocation: true
---

# Post-Sprint Knowledge Capture Protocol

1. **Analyze Artifacts:** Read retrospective notes and git diff from the completed sprint in the target `projects/[project]/` directory.
2. **Identify Learnings:** Detect new patterns introduced, workarounds applied, and decisions made under pressure.
3. **Deconstruct & Distill:**
    * New integration or service dependency = Write a new node in `context_brain/01_entities/`.
    * New reusable pattern or coding standard = Extract into `context_brain/02_concepts/`.
    * Significant architectural decision = Finalize the ADR in `context_brain/03_clusters/`.
4. **Update Velocity Matrix:** Amend `context_brain/04_effort_matrices/team-velocity.md` with actual vs estimated story points from this sprint.
5. **Link Nodes:** Write exact YAML frontmatter to link all new elements, preventing architectural amnesia for future sprints.