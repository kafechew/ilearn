---
name: kgt
description: Knowledge Graph Transformer. Ingests raw files (PDFs, images, slides, text docs) into structured atomic Obsidian nodes following the Karpathy LLM Wiki pattern, or runs deep graph link linting diagnostics.
---

# LLM Wiki Pattern Protocol

This protocol enforces the Andrej Karpathy LLM Wiki pattern to ingest unstructured files into the Webby Group's structured Obsidian graph, or audit its structural health.

## 🧭 Routing Logic (Determine Action First)
- **If the input parameter is `--lint`:** Skip all ingestion steps and immediately execute the **Linting Workflow** instructions at the bottom of this protocol.
- **If the input parameter is a file path:** Execute the **Multi-Modal Ingestion Pipeline** steps below using the target file path.

---

## 🏗️ Multi-Modal Ingestion Pipeline

### Step 1: File Processing Branch
Analyze the file extension of the target input asset and choose the appropriate processing route:

- **Route A (Visual and Presentation Layouts):** If the file is an image (`*.png`, `*.jpg`, `*.jpeg`) or presentation deck (`*.pptx`), invoke the multimodal vision script:
  `python kb/schema/ingest_vision.py <input_file_path>`
  *(This script leverages gemini-3.1-flash-lite to handle OCR, graphic translations, and output a raw markdown file).*
  
- **Route B (Standard Documents):** If the file is any other non-markdown asset (e.g., `*.pdf`, `*.docx`, `*.txt`), invoke the baseline MarkItDown CLI engine:
  `markitdown <input_file_path> -o <target_markdown_path>`

- **Output Enforcements:** Always save the parsed markdown outputs into the `kb/raw/` directory. Use an identical filename, but convert it to `lowercase_with_underscores` and swap the extension to `.md` (e.g., `kb/raw/Annual Report.pdf` becomes `kb/raw/annual_report.md`).
- Read the final markdown content into memory before proceeding to Step 2.

### Step 2: Guardrailed Schema Matching
- Open and read the explicit constraints defined in `kb/schema/schema.json`.
- Evaluate the ingested markdown text against the structural categories defined in the schema: Entities, Concepts, and Clusters.

### Step 3: Execution & File Creation (Zero Planning Loops)
- **CRITICAL**: Do not output conversational text blocks asking for confirmation, outlining file paths, or entering planning loops.
- **Deduplication Check:** Search the active vault target directories (`kb/wiki/01_entities/`, `kb/wiki/02_concepts/`, `kb/wiki/03_clusters/`) using file search tools. Identify if a note already exists for an extracted entity to prevent duplicate creations.
- **Naming Rule:** All created file names must be strictly formatted in `lowercase_with_underscores.md`.

#### Format Matrix for Node Creation:
```markdown
---
type: [entity | concept | cluster]
tags: [relevant-tag]
links:
  - "[[existing_node]]"
  - "[[related_node]]"
---
# Name of Item

## Brief Description
[Clear 2-3 sentence overview derived explicitly from the source material]

## Knowledge Network Relations
- This item is connected to [[associated_concept]] because of its design attributes.
- See also [[related_cluster_theme]] for broader operational scale.
```

### Step 4: Logging & Verification
- Verify that every written node is physically placed in its correct category directory.
- Append a timestamped, single-line entry to `kb/wiki/logs.md` tracking the transformation activity:
  `- [YYYY-MM-DD HH:MM] Ingested raw asset <filename>. Generated nodes: [[node_a]], [[node_b]].`

### Step 5: Output Summary
- Output a single, brief sentence summarizing the count of new nodes generated or existing nodes updated.

---

## 🛡️ Linting Workflow (`/kgt --lint`)

Execute a comprehensive network scan across all folders inside `kb/wiki/` to isolate and fix structural anomalies:

1. **Dead Links:** Scan all `.md` files under `kb/wiki` for standard `[[TargetLink]]` markers. If the corresponding `target_link.md` file does not physically exist in any category folder, flag it as a Dead Link.
2. **Lonely Notes (Orphans):** Check all valid node files to see if they have exactly zero incoming link markers pointing to them from other vault notes.
3. **Mismatched Schema:** Parse all node frontmatter blocks against `kb/schema/schema.json`. Flag any document missing mandatory structural keys or violating the lowercase file naming rule.

### Output Action Matrix:
- Output a clean, non-verbose table highlighting all discovered vault discrepancies.
- Provide a strict, programmatic action checklist to fix anomalies. If a dead link can be cleanly resolved by stripping out the stale text citation wrapper, proceed with automatic correction without waiting for a user prompt.
```
