---
author: Kai
pubDatetime: 2026-03-13T09:00:00+08:00
title: The Agentic Stack - MCP, CLI & Skill
featured: false
draft: false
slug: agentic-stack-mcp-cli-skill
tags:
  - ai
  - agentic
  - mcp
  - cli
  - skill
  - english
description: Explore the efficiency and composability of the CLI against the perceived context bloat and rigidity of the MCP. Also, building skills that execute via precise CLI tools.
---

We’ve entered a feverish phase of AI development where every week introduces a new "protocol" designed to help models talk to the world. The current industry darling is the Model Context Protocol (MCP).

But as I’ve been building out my own autonomous agents and sovereign nodes, I’ve started to ask a skeptical question: Are we over-engineering the bridge between models and tools?

In my experience, the industry is racing to build a glass skyscraper of complex schemas when a well-oiled machine shop—the CLI (Command Line Interface)—has been sitting right there for fifty years.

![The Agentic Stack: MCP, CLI & Skill](https://ik.imagekit.io/moopt/kheai/ai/mcp-vs-cli_qfZzYXYY6.png)



## The MCP Problem: Context Bloat and Rigid Schemas

MCP was designed to give models a standardized way to "see" data. While it’s excellent for corporate API adoption, it carries a hidden "tax" that can cripple a lean, autonomous agent.

 * The "Kitchen Sink" Effect: If you ask an MCP-connected model for the weather, the protocol often dumps a massive JSON blob containing 50+ fields (UV index history, wind gust direction in degrees, humidity gradients). Most of this is "noise" the model doesn't need, yet it still consumes precious tokens and context window space.
 * The Syntax Trap: MCP requires rigid, specific syntax. While it provides a "safe" sandbox, it often feels like we're forcing the model to speak a dialect it wasn't natively designed for, rather than letting it use its natural reasoning.



## The CLI Advantage: Composability as a Superpower

A CLI is a deterministic executable—a piece of software that performs a specific, low-level action when given precise parameters.

Modern LLMs are surprisingly proficient at navigating Unix-like environments. They don’t necessarily need a pre-exported JSON schema to understand a tool; they just need a man page or a --help menu.



## MCP vs. CLI: A Comparison

| Feature     | Model Context Protocol (MCP)          | Command Line Interface (CLI)                  |
| ----------- | ------------------------------------- | --------------------------------------------- |
| Logic       | JSON-RPC / Predefined Schemas         | Unix Philosophy (Pipes & Filters)             |
| Flexibility | Rigid; requires specific server setup | Highly composable; `grep`, `awk`, `sed`       |
| Context     | Often dumps full data objects         | Precise; model can pipe/filter its own output |
| Portability | Requires MCP-compliant hosts          | Runs on any shell/local hardware              |

Models are actually excellent at calling Unix commands. When an agent has access to a CLI, it can pipe, filter, and chain commands autonomously. It reads the `help` menu, identifies the correct flags, and executes. There’s no "middleman" protocol bloat—just the model and the machine.



## Reclaiming the Stack: The "MCP-to-CLI" Pivot

I recently built a tool to convert MCP servers back into scriptable CLIs. The goal was simple: Reclaim leverage through composability.

If a tool is a CLI, I can script it, version-control the logic, and let the agent decide exactly how to slice the data before it ever hits the context window. This shifts the agent's role from a passive consumer of bloated data to an active operator of a precision toolkit. For those of us running agents on local hardware (like a Raspberry Pi), this efficiency isn't just a preference—it's a requirement for hardware resilience.



## Defining "Skills": The Recipe for Autonomy

If the CLI provides the tools, the Skill is the higher-level behavioral package. A Skill is essentially a "recipe card"—a set of instructions (often in Markdown) that tells the AI how to use its tools to achieve a complex goal.

 * The Nature of a Skill: Prompt-based, heuristic, and goal-oriented.
 * Example: A "Market Analysis Skill" isn't a single command. It’s an instruction set:
   * Use the `exchange-cli` to fetch current BTC prices.
   * Use the `news-cli` to fetch the last 10 headlines.
   * Analyze the correlation using internal reasoning.
   * Format a sovereign report for the user.

By building Skills that execute via the CLI, you ensure the logic remains transparent and the execution remains lean.



## The Silver Lining: When Bloat is a Feature

I’m not entirely "anti-MCP." Its greatest contribution has been acting as a catalyst, pressuring companies to finally open up their APIs in a standardized way.

The "Wildcard" Use Case: MCP excels in Enterprise Environments. When you need strict audit logs of exactly which JSON fields were accessed, or when you’re managing complex OAuth2 handshakes that are a nightmare in raw shell scripts, the "over-engineering" of MCP provides a governance layer that IT departments require.



## Final Thought

For quick wins or closed-ecosystem integrations, MCP makes sense. But for a core autonomous stack? I’m sticking to the terminal. In the age of AI, the 50-year-old Unix philosophy of "do one thing and do it well" is proving to be more relevant than ever.
