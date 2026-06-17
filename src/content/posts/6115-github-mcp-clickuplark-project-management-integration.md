---
author: Kai
pubDatetime: 2026-05-15T09:00:00+08:00
title: MCP Setup - GitHub, ClickUp & Lark Integration
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
description: Set up GitHub MCP for PR and CI management, ClickUp MCP as your primary project management integration, and Lark MCP as a team comms alternative — all from the terminal without context-switching.
---

## What This Part Covers

- What MCP is and why it eliminates context-switching
- GitHub MCP: setup and daily prompt reference
- ClickUp MCP: setup as your primary ticket and sprint tool
- Lark MCP: when and how to use it instead of (or alongside) ClickUp
- Recommended MCP stack for a new enterprise team

For how these tools fit into your actual daily workflow — morning standup to merged PR — see Part 17.

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

MCP = Model Context Protocol. A standard interface that lets Claude connect to external tools and services. Each MCP server exposes a set of tools (functions) that Claude can call — just like `Read`, `Edit`, or `Bash`.

When you run `claude`, Claude Code reads `.claude/mcp.json` and connects to every server listed. Once connected, those tools are available in the session with no extra configuration.

---

## 2. GitHub MCP

### 2.1 Why Add It

Without GitHub MCP:

```
You: "Create a PR for this branch"
Claude: "Here's the gh command to run: gh pr create --title..."
You: (copy, paste, run, fill template manually)
```

With GitHub MCP:

```
You: "Create a PR for feat/product-module.
     Title: feat(product): add product CRUD module
     Fill the PR template. Link to ticket CU-1234."
Claude: (creates PR directly, fills template, returns PR URL)
```

Other things GitHub MCP enables from inside your Claude session:

- Read and comment on issues
- Check CI status on any PR
- List open PRs assigned to you
- Read review comments without opening the browser
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

**Step 2: Export to your shell profile**

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

Never hardcode the token in `mcp.json`. The `${GITHUB_TOKEN}` syntax reads from your shell environment at runtime — the file itself contains no secret and is safe to commit.

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

**Check CI on a specific PR:**

```
"Check the CI status on PR #42. Which checks are failing?"
```

**Create a PR from the current branch:**

```
"Open a PR for feat/product-module.
Title: feat(product): add product CRUD module
Body: fill the PR template from .github/PULL_REQUEST_TEMPLATE.md
Link to ticket CU-1234."
```

**Read review comments and plan fixes:**

```
"Show me all review comments on PR #42. Summarize what needs fixing."
```

**Merge when approved:**

```
"PR #42 is approved with all checks green. Squash merge and delete the branch."
```

**Create an issue from a code review finding:**

```
"Create a GitHub issue:
Title: Missing @Index on userId in TodoEntity
Body: Found during code review of PR #42. The userId FK column is missing @Index()
which will cause slow queries on getTodos at scale.
Labels: bug, performance"
```

---

## 3. ClickUp MCP — Primary Project Management

ClickUp is the primary tool for sprint planning, ticket tracking, and daily task management. Use it for every ticket lifecycle: unstarted → in progress → in review → done.

### 3.1 Setup

> **ClickUp MCP — built-in, not a local server:** Unlike GitHub MCP (which runs a local server binary), ClickUp integration with Claude is handled through Claude's **built-in OAuth connection panel**. In Claude Desktop or Claude Code web, go to Settings → Connections → ClickUp, authenticate with OAuth. Once connected, Claude can read and create ClickUp tasks without any `mcp.json` entry. There is no `@modelcontextprotocol/server-clickup` npm package — any such config will silently fail.

### 3.2 Daily ClickUp Prompts

**Morning sprint check:**

```
"Show me all ClickUp tasks assigned to me in the current sprint that aren't started."
```

**Start a ticket:**

```
"Mark CU-1234 as in progress."
```

**Create a subtask:**

```
"Create a subtask under CU-1234: 'Write unit tests for ProductService',
assign to me, due this Friday."
```

**Log progress during development:**

```
"Add a comment to CU-1234:
'Migration created and tested locally. PR up for review at #PR-URL.'"
```

**Find what's blocking review:**

```
"Show all ClickUp tasks with status 'in review' in the Backend space."
```

**Close a ticket after merge:**

```
"Mark CU-1234 as complete."
```

**Technical debt tracking:**

```
"Create a ClickUp task in the Backend space:
Title: Add @Index to userId on ProductEntity
Type: chore
Description: Missing index identified during PR #45 review. getTodos will full-scan
when tenants exceed ~10k products.
Priority: medium"
```

---

## 4. Lark MCP — Team Communications

Use Lark MCP in two scenarios:

**Scenario A — Your team uses Lark as the primary communication tool (not Slack/Teams).**
Lark replaces ClickUp here as the team coordination layer. You'd use it for tasks, docs, and messages in one place.

**Scenario B — Your team uses ClickUp for tickets but Lark for chat and announcements.**
Use both MCPs: ClickUp for ticket lifecycle, Lark for team-facing notifications (PR ready for review, deploy complete, incident updates).

### 4.1 Setup

Lark MCP is available as a built-in Claude integration. In a Claude session, click "Add integration" in the MCP panel and complete the OAuth flow in your browser. No manual `mcp.json` entry required.

### 4.2 Daily Lark Prompts

**Notify the team a PR is ready:**

```
"Post a message to the #backend-team channel:
'Product module PR ready for review: <PR URL>. Needs 1 approval.'"
```

**Announce a deploy:**

```
"Post to #deployments:
'v1.4.2 deployed to production at 3:45pm. Product module is live.
Migration completed cleanly. Monitoring for 10 minutes.'"
```

**Create a technical doc:**

```
"Create a Lark doc titled 'Product Module Architecture Decision'
with this content: <paste>"
```

**Find a previous message:**

```
"Find the message in #deployments from today about the staging deploy."
```

**Schedule a meeting:**

```
"Schedule a Lark meeting with @alex for tomorrow at 3pm:
'Sprint review — 30 minutes.'"
```

### 4.3 ClickUp vs Lark — Decision Table

|                   | ClickUp                                         | Lark                                |
| ----------------- | ----------------------------------------------- | ----------------------------------- |
| Best for          | Sprint tracking, ticket lifecycle, time logging | Team messaging, docs, announcements |
| Use when...       | Your PM lives in ClickUp                        | Your team communicates in Lark      |
| Ticket management | Primary — full sprint/task support              | Secondary — basic tasks only        |
| Team comms        | Minimal                                         | Primary                             |
| Common together   | Track work in ClickUp                           | Notify the team in Lark             |

For most teams using this stack: **ClickUp for tickets, Lark for notifications**. They complement rather than compete.

---

## 5. Recommended MCP Stack

| Priority | MCP        | Reason                                                     |
| -------- | ---------- | ---------------------------------------------------------- |
| Day 1    | `gitnexus` | Impact analysis — required before editing any symbol       |
| Day 1    | `github`   | PR creation and CI checks without a browser                |
| Week 1   | `clickup`  | Ticket updates and sprint tracking from the terminal       |
| Week 2   | `lark`     | Team notifications, docs, and comms if your team uses Lark |

**What NOT to add:**

- Database MCPs with direct SQL on production — never
- MCPs with write access to infrastructure (AWS, GCP) without explicit per-action auth
- Any MCP that stores credentials as a literal value in the committed `mcp.json`

---

## Troubleshooting MCP Setup

**GitHub MCP: `Server not found` / `ENOENT`**  
The `npx` command is not in `$PATH` for the subprocess. Provide the absolute path: use `which npx` in your terminal to find it, then replace `"npx"` in mcp.json with the full path (e.g. `/Users/yourname/.nvm/versions/node/v20.x.x/bin/npx`).

**Changes to mcp.json not taking effect**  
Claude Code reads mcp.json at startup only. After any change, quit Claude Code completely and restart — a hot-reload is not triggered.

**GitHub token 403 on PR creation**  
The classic token scope issue. Go to GitHub → Settings → Developer Settings → Personal Access Tokens → find your token → Edit → ensure `repo` scope is checked (not just `public_repo`).

**MCP server crashes silently**  
Check Claude Code's MCP logs: open a terminal, run `claude --debug` and reproduce the action that fails. The debug output includes each MCP server's stderr.

---

## Summary

| Tool        | Setup time         | Daily value                                                       |
| ----------- | ------------------ | ----------------------------------------------------------------- |
| GitHub MCP  | 10 min             | High — PRs, CI checks, issues from the terminal                   |
| ClickUp MCP | 5 min              | High — start ticket, log progress, close ticket without a browser |
| Lark MCP    | 5 min              | Medium — team notifications and docs if your team uses Lark       |
| gitnexus    | Built into project | Critical — impact analysis before every symbol edit               |

The compound effect: code, PR, ticket update, team message — all from one terminal session. Zero browser tabs. Part 17 shows exactly how this plays out across a full day, with a real-world case study of building a module from ticket to production.
