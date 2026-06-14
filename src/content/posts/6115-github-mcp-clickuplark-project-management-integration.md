---
author: Kai
pubDatetime: 2026-05-15T09:00:00+08:00
title: GitHub MCP, ClickUp/Lark & Project Management Integration
featured: false
draft: false
slug: 6115-github-mcp-clickuplark-project-management-integration
tags:
  - deeptech
  - mcp
  - project-management
  - nestjs
  - typescript
  - backend
  - code
  - enterprise
  - english
ogImage: "https://ik.imagekit.io/kheai/tutorial/15-github-mcp-clickuplark-project-management-integration.png"
description: By the end of this part, you will learn MCP, GitHub MCP, ClickUp MCP, Lark MCP and the integrated workflow.  

---

## What This Part Covers

- What MCP (Model Context Protocol) is and why it matters
- GitHub MCP: setup, what it enables, daily usage
- ClickUp MCP vs Lark MCP: which to choose and when
- The integrated workflow: ticket → branch → build → PR → close ticket
- Practical prompts for each tool

---

## The Problem Without MCP

Your development environment is fragmented:

```
Terminal (code) ←──── context switch ────→ Browser (GitHub PRs)
                                          ↕ context switch
                                     Browser (ClickUp tickets)
                                          ↕ context switch
                                     Browser (Lark messages)
```

Every context switch costs focus. With MCP servers connected to Claude Code:

```
Terminal (claude session)
  ├── reads your code
  ├── checks GitHub PRs and CI status
  ├── updates ClickUp ticket status
  └── posts a Lark message to the team
```

One context. Everything from the terminal.

---

## 1. What MCP Is

MCP = Model Context Protocol. It's a standard interface that lets Claude connect to external tools and services. Each MCP server exposes a set of tools (functions) that Claude can call, just like `Read`, `Edit`, or `Bash`.

When you run `claude`, Claude Code automatically reads `.claude/mcp.json` and tries to connect to every server listed. Once connected, those tools are available in the session without any extra configuration.

---

## 2. GitHub MCP

### 2.1 Why Add It

Without GitHub MCP:
```
You: "Create a PR for this branch"
Claude: "Here's the gh command to run: gh pr create --title..."
You: (copy, paste, run, fill in template manually)
```

With GitHub MCP:
```
You: "Create a PR for this branch. Title feat(product): add product module. Link ticket CU-1234."
Claude: (creates PR directly with template filled, links ticket, returns PR URL)
```

Other things GitHub MCP enables:
- Read and comment on issues
- Check CI status on a PR
- List open PRs assigned to you
- View PR review comments without leaving the terminal
- Get the diff of any PR

### 2.2 Setup

**Step 1: Create a GitHub Personal Access Token**

```
github.com → Settings → Developer settings
→ Personal access tokens → Fine-grained tokens → Generate new token

Permissions needed:
- Contents: Read and Write
- Pull requests: Read and Write
- Issues: Read and Write
- Actions: Read (for CI status)
```

**Step 2: Add to your shell profile**

```bash
# ~/.zshrc
export GITHUB_TOKEN=ghp_your_token_here
```

```bash
source ~/.zshrc
```

**Step 3: Add to `.claude/mcp.json`**

```json
{
  "mcpServers": {
    "gitnexus": {
      "command": "node",
      "args": [".gitnexus/run.cjs", "mcp"]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
      }
    }
  }
}
```

> **Never hardcode the token in mcp.json.** It would be committed to git. The `${GITHUB_TOKEN}` syntax reads from your shell environment at runtime.

**Step 4: Verify**

```bash
claude
/mcp
# → github: connected ✓
```

### 2.3 Daily GitHub Prompts

**Check your PR queue:**
```
"Show me all open PRs in this repo that need my review."
```

**Check CI on a PR:**
```
"Check the CI status on PR #42. Which checks are failing?"
```

**Create a PR:**
```
"Open a PR for the current branch feat/product-module.
Title: feat(product): add product CRUD module
Body: follows the PR template in .github/pull_request_template.md
Link to ticket: CU-1234"
```

**Respond to review comments:**
```
"Show me the review comments on PR #42. Summarize what needs fixing."
```

**Merge when approved:**
```
"PR #42 is approved with all checks green. Squash merge and delete the branch."
```

**Create an issue for a bug found in review:**
```
"Create a GitHub issue: title 'Missing @Index on userId in TodoEntity',
body 'Found during code review of PR #42. The userId FK column is missing @Index()
which will cause slow queries on the getTodos endpoint at scale.',
labels: bug, performance"
```

### 2.4 Branch Protection Rules (Set These Up Once)

In the GitHub repo settings:

```
Settings → Branches → Add rule for main:

[✅] Require a pull request before merging
  [✅] Require approvals: 1
  [✅] Dismiss stale pull request approvals when new commits are pushed

[✅] Require status checks to pass before merging
  [✅] Require branches to be up to date before merging
  Status checks: lint, unit-test, e2e-test (from your CI workflow)

[✅] Require conversation resolution before merging
[✅] Delete head branches automatically
```

This enforces the workflow: no direct pushes to main, CI must pass, one approval required.

---

## 3. ClickUp MCP vs Lark MCP

### 3.1 The Decision

| | ClickUp | Lark |
|---|---|---|
| Best for | Teams that track work in sprints with detailed task breakdown | Teams where docs + chat + tasks are all in one place |
| MCP value | Read tasks, update status, create subtasks, log time | Read messages, create docs, manage tasks, post updates |
| Claude integration | "Mark task CU-1234 as in-progress" | "Post a Lark message to #backend-team about the deploy" |
| Choose if... | You live in ClickUp for sprint planning | Your team primarily coordinates in Lark |

**For most teams: use GitHub MCP for code workflow, and whichever tool your PM uses for tickets.**

### 3.2 ClickUp MCP Setup

ClickUp MCP is available through Claude's built-in integrations:

```bash
# In a Claude session:
# Click "Add integration" in the MCP panel, or authenticate via the browser
```

Or add to `mcp.json` with your API key:

```json
"clickup": {
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-clickup"],
  "env": {
    "CLICKUP_API_TOKEN": "${CLICKUP_TOKEN}"
  }
}
```

Add to `~/.zshrc`:
```bash
export CLICKUP_TOKEN=pk_your_token_here
```

**Useful ClickUp prompts:**
```
"Show me all tasks assigned to me in the current sprint."

"Mark task CU-1234 as in progress."

"Create a subtask under CU-1234: 'Write unit tests for ProductService', assign to me, due Friday."

"Add a comment to CU-1234: 'Migration created and tested locally. PR up for review at #PR-link.'"

"Show me all tasks with status 'in review' in the Backend space."
```

### 3.3 Lark MCP Setup

```bash
# In a Claude session, authenticate:
# The Lark MCP is available as a built-in integration
# Click "Connect" in the MCP panel and complete the OAuth flow in your browser
```

**Useful Lark prompts:**
```
"Post a message to the #backend-team channel:
'Product module PR is up for review: <link>. Needs 1 approval to merge.'"

"Create a Lark doc titled 'Product Module Architecture Decision'
and paste in the content I'm about to provide."

"Find the message in #deployment channel from today about the staging deploy."

"Schedule a Lark meeting with @kai and @alex for tomorrow at 3pm:
'Sprint review — 30 minutes'."
```

---

## 4. The Complete Integrated Workflow

This is how the full ticket → code → PR → merge → close cycle looks with all tools connected.

### Morning: Pull the Day's Work

```bash
cd enterprise-todo
claude
```

```
"Check my ClickUp tasks for today's sprint. What's assigned to me and not started?"
```

Claude returns:
```
CU-1234: Add Product module (unstarted, estimated 3h)
CU-1240: Fix N+1 on TagResolver (unstarted, estimated 1h)
```

```
"Mark CU-1234 as in progress and create the feature branch."
```

Claude:
- Marks CU-1234 as "In Progress" in ClickUp
- Tells you to run: `git checkout -b feat/product-module`

### During Development

```
"I'm about to build the Product module. Query the graph for the closest reference pattern."
```

```
"I want to modify FilterQueryBuilder. Run impact analysis first."
```

```
"Use the backend-specialist agent to scaffold Product. Columns: name, price, status, userId."
```

```
"Use the migration-specialist to review this migration: <paste>"
```

```
"Use the test-writer to write unit tests for ProductService."
```

### Pre-PR: Verify and Review

```bash
yarn api:test      # must pass
yarn lint          # must pass
yarn migration:run # run and verify
```

```
"Run detect_changes against main. Verify I only touched Product module files."
```

```
"/code-review"
```

Fix any issues flagged. Then commit:

```bash
git add apps/api/src/modules/product/
git add apps/api/src/migrations/*product*
git add apps/api/src/app/app.module.ts
yarn cz
# feat(product): add product CRUD module with CQRS pattern
```

### Open the PR

```
"Open a PR for feat/product-module.
Title: feat(product): add product CRUD module
Fill the PR template from .github/pull_request_template.md.
Link it to ticket CU-1234."
```

Claude creates the PR and returns the URL.

```
"Post a message to #backend-team in Lark: 'Product module PR ready for review: <URL>'"
```

### After Approval and Merge

```
"PR #45 was approved and merged. Mark CU-1234 as complete in ClickUp."
```

```bash
git checkout main && git pull
graphify update .
node .gitnexus/run.cjs analyze
```

---

## 5. Setting Up Your Team's MCP Stack

**Recommended stack for a new enterprise NestJS team:**

| Priority | MCP | Reason |
|----------|-----|--------|
| Day 1 | `gitnexus` | Impact analysis — critical before any edit |
| Day 1 | `github` | PR creation, CI checks without browser switching |
| Week 1 | `sequential-thinking` | Complex architectural decisions |
| Week 2 | `clickup` or `lark` | Task management integration |

**What NOT to add:**
- Database MCPs that allow direct SQL on production — never
- MCPs with write access to infrastructure (AWS, GCP) — requires explicit auth per action
- Any MCP that stores credentials in the `mcp.json` committed file

---

## Summary

| Tool | Setup time | Daily value |
|------|-----------|-------------|
| GitHub MCP | 10 min | High — PR creation, CI checks, issue management from terminal |
| ClickUp MCP | 5 min | Medium — task updates without context switch |
| Lark MCP | 5 min | Medium — team comms without context switch |
| gitnexus | Built into project | Critical — impact analysis before every edit |

The compound effect: you stop context-switching. Code, PR, ticket update, team message — all from one terminal session. At the end of the day, your PR is open, your ticket is updated, and your team is notified, with zero browser tabs opened.
