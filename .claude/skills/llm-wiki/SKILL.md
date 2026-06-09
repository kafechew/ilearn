---
name: llm-wiki
description: Transforms a legacy document into a structured knowledge graph (Entities, Concepts, Clusters) within the context_brain/ directory for Obsidian visualization.
---

# LLM Wiki Pattern Protocol

This protocol implements the Karpathy LLM Wiki pattern to ingest unstructured legacy documentation into the Webby Group's structured knowledge base.

## Input
- A file path to a legacy document (e.g., `legacy_archive/some-file.md`).

## Execution Steps

1. **Ingestion:** Read the content of the provided file.
2. **Deconstruction (LLM Analysis):**
    Analyze the text to identify:
    - **Entities:** Specific people, organizations, products, systems, or physical assets.
    - **Concepts:** Abstract ideas, technologies, architectural patterns, business processes, or methodologies.
    - **Clusters:** High-level themes or groupings that connect multiple entities and concepts.
3. **Reporting & Execution:**
    **CRITICAL: AVOID PLANNING LOOPS.** Do not repeatedly state your intention to create files or debate the order of creation.
    
    **Process:**
    1. **List Findings:** Output a concise, categorized list of all identified Entities, Concepts, and Clusters.
    2. **Execute Creation:** Immediately follow the list with the necessary `write_to_file` tool calls to create the markdown files.

    **File Requirements:**
    - **Directory:** 
        - `context_brain/01_entities/`
        - `context_brain/02_concepts/`
        - `context_brain/03_clusters/`
    - **YAML Frontmatter:**
        - `type`: (entity | concept | cluster)
        - `links`: A list of `[[WikiLinks]]` to related elements.
    - **Content:**
        - A concise description or summary derived from the source text.
        - Use `[[WikiLinks]]` within the body text to create connections.
4. **Verification:**
    - Ensure no duplicate files are created.
    - Verify that all files are correctly placed in their respective directories.
    - Confirm that the `CoreIndex.md` Dataview query will pick them up.

## Output
- A set of new markdown files in `context_brain/` that form a connected knowledge graph.