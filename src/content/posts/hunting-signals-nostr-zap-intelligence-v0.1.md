---
author: Kai
pubDatetime: 2026-03-23T09:00:00+08:00
title: Hunting Signals - Nostr Zap Intelligence v0.1
featured: false
draft: false
slug: hunting-signals-nostr-zap-intelligence-v0.1
tags:
  - ai
  - meteor
  - lightning
  - zap
  - bitcoin
  - nostr
  - deeptech
  - english
description: A simple the Nostr network watcher, hunting for the real commercial signal—bounties, professional tips, and service inquiries in the bitcoin lightning firehose.
---

In the decentralized world of Nostr, value doesn't just move; it speaks. Most users view **Zaps**—instant, micro-payments settled over the Bitcoin Lightning Network—as merely "fancy likes" or social dopamine.

Coming from a background in actuarial statistics and industrial automation, I saw something else: **High-fidelity metadata.** A Zap is a mathematically verified value transfer. In an ecosystem drowning in bot-generated noise and "LFG" memes, the act of attaching capital to a message is the ultimate proof of intent. If you can separate the social noise from the commercial signal, you aren't just watching a feed; you are monitoring a global, real-time marketplace of bounties, service payments, and professional tips.

I built **kheAI** to be the filter. It is an autonomous agent designed to interrogate the Lightning firehose and extract the 1% of transactions that represent real economic opportunity.

![Nostr Agent: Hunting Signal in the Lightning Firehose](https://ik.imagekit.io/moopt/kheai/ai/nostr-ai-zap-hunter_5X-nf9sjn.png)

## The Strategic Pivot: Building the "Zap Hunter"

As I immersed myself in the Nostr protocol from my apartment in Puchong, I realized the immediate bottleneck wasn't a lack of data—it was the **Information Firehose**.

I pivoted the framework to become a **Zap Hunter**. The mission: scan every Kind 9735 (Zap Receipt) event across the network, decode the underlying economic intent, and surface leads that actually matter. It is a "Bloomberg Terminal" for the sovereign individual.



## The Architectural Stack: Why Reactivity Matters

Building an agent that monitors a global network requires a stack that doesn't just "request" data, but "lives" inside it.

- **Meteor 3 & Blaze:** In an era of complex React state management, I chose Meteor for its native **Distributed Data Protocol (DDP)**. It allows my dashboard to be truly reactive. The moment a relay broadcasts a zap in Iceland or New York, the "Signal" card glows on my screen in Malaysia without a single page refresh.
- **NDK (Nostr Dev Kit):** This is the backbone. NDK allows me to maintain persistent, high-performance socket connections across multiple relays (e.g., `damus.io`, `nos.lol`, `primal.net`). It abstracts the messiness of the protocol into a clean, queryable interface.
- **Gemini 3.1 Flash (Lite):** For the "brain," I needed speed over raw size. Gemini 3.1 Flash acts as my AI reasoning layer. It provides near-instant inference with a specific "skeptical" persona, allowing the agent to judge intent in milliseconds.
- **The Bolt11 Source of Truth:** You cannot trust the metadata tags provided by Nostr relays; they are often incomplete or "0-valued." I integrated `light-bolt11-decoder` to reach into the Lightning invoice itself. By decoding the payment request, the agent extracts the **mathematically verified Satoshi count**. No invoice, no signal.

![Nostr Meteor Primal](https://ik.imagekit.io/moopt/kheai/tutorial/nostr-meteor_-1cPt0vOy.png)

## The Triple-Gate Skeptic Framework

Triggering an AI for every social interaction is an actuarial nightmare—it wastes API quotas and, more importantly, human attention. I implemented a **Triple-Gate Skeptic Framework** to ruthlessly protect the system's integrity.

### Gate A: The Actuarial "Deductible" (The Dust Filter)

In insurance, a deductible filters out trivial claims. In kheAI, we automatically discard any Zap under **100 sats**. While micro-zaps are vital for social health, they rarely carry commercial weight. By setting this floor, we instantly prune 70% of the network's social "chatter."

### Gate B: The Content Minimum

Language is the primary carrier of intent. If a Zap note is empty or consists purely of emojis (the ubiquitous "🤙" or "⚡"), the agent kills the process immediately. No text, no context.

### Gate C: The Whale & Intent Logic

This is the final filter before the AI is engaged. The agent only fires its reasoning engine if:

1. **Whale Alert:** The Zap is > **5,000 sats** (a high-value economic event regardless of content).
2. **Keyword Match:** The note contains professional markers such as `fix`, `build`, `bounty`, `hire`, `feature`, or `tool`.



## Training the Skeptic: Real-World Results

Early on, the agent was "too nice." It flagged every polite "Thank you" as a business lead. I had to harden the prompt to force the AI into an **Economic Intelligence** mindset.

**The Internal Directive:** 

```
Analyze this note. Is someone trying to pay for work, or are they just being friendly? If it's social, discard it. BE SKEPTICAL.
```

- **The Win:** A 500-sat zap with the note *"Can you fix this CSS bug on my site?"* was correctly identified as **SIGNAL (92% confidence)**.
- **The Pruning:** A 1,000-sat zap saying *"Great post, man! Bitcoin to the moon!"* was correctly flagged as **NOISE (98% confidence)**.

This separation allows me to operate in a "Signal-only" environment where every entry on my screen is a potential commercial engagement.



## Technical Friction & Lessons from the Edge

Building on the bleeding edge is never clean. I spent hours wrestling with Node.js deprecation warnings (specifically the `util._extend` issue in older dependencies). As a developer, the lesson was clear: **Prioritize function over form during the MVP.** I needed a functional oracle, not a perfect log file.

I also learned that the decentralized nature of Nostr means data is often "lossy." Some relays strip tags; some clients format zap requests incorrectly. This reinforced the need for the **Bolt11 Decoder** as the ultimate arbiter of truth.

The UI design was also a lesson in focus. I realized that for a B2B intelligence tool, "fluff" is a bug. I implemented an `isSignal` flag that effectively "dims" the raw firehose, allowing only the high-confidence green cards to stand out in the dark terminal theme.

![kheai meteor nostr ui ux](https://ik.imagekit.io/moopt/kheai/tutorial/nostr-mobile_GTqor1abz.png)



## kheAI v0.1 Summary

### Phase 1: Foundation & The "Live Infiltration" UI

**Objective:** Establish a low-latency connection to the global lightning firehose and render a high-density "Bloomberg-style" terminal.

- **Protocol Scaffolding:** 
  - Implement **NDK (Nostr Dev Kit)** to manage multi-relay subscriptions (Kinds 9735 for Zap Receipts).
  - Integrate `light-bolt11-decoder` to ensure the SAT amount is mathematically verified from the invoice rather than trusting relay tags.
- **Terminal Aesthetic:** 
  - Adopt a "Terminal Dark" UI: High-contrast, monospaced fonts, and data-dense layouts using **Meteor 3 and Blaze**.
  - **The Market Radar:** A scrolling vertical ticker showing the "unprocessed" firehose (raw Zaps >100 sats). Also labelled as "Signal" that pass the initial skepticism thresholds.
- **Metadata Extraction:** 
  - Identify the **Content Type** (e.g., Kind 1 Short Note vs. Kind 30023 Long-form Article).
  - Capture the **Counterparty Direction** (Sender Pubkey → Recipient Pubkey).



### Phase 2: Agentic Reasoning (The Skeptic Brain)

**Objective:** Deploy a reasoning layer that distinguishes social "appreciation" from commercial "intent."

- **The Three Gates of Skepticism:**
  1. **Gate 1 (The Dust Filter):** Automatically discard any Zap < 100 sats.
  2. **Gate 2 (The Linguistic Gate):** Discard empty notes or single-emoji "social likes."
  3. **Gate 3 (The Whale/Intent Logic):** Trigger AI analysis only for Zaps > 5,000 sats OR those containing specific business keywords (`build`, `fix`, `bounty`, `hire`).
- **LLM Integration:** 
  - Wire the **Gemini 3.1 Flash (Lite)** API as the primary inference engine.
  - **Structured Output:** Force the AI to return JSON containing a "Confidence Score" (0–100), a "Verdict," and standardized "Intent Tags" (e.g., `#HIRING`, `#BOUNTY`, `#SAAS_PAYMENT`).



## What’s Next

Currently, kheAI v0.1 is "volatile"—it lives in the server's RAM. If I restart the Raspberry Pi cluster in my apartment, the leads disappear.

**The Roadmap for v0.2:**

- **Persistent Ledger:** Moving all signals into a local **MongoDB** instance for historical pattern matching.
- **The Identity Vault:** Integrating **NIP-05 verification** to map anonymous hex pubkeys to real-world entities (e.g., mapping `82341f...` to `kai@kheai.com`).
- **Local Inference:** The ultimate goal is to cut the cord to cloud APIs. I am currently testing 4-bit quantized versions of **Qwen 3.5** to run the reasoning layer entirely on local hardware.

kheAI will become a truly **Intelligence Agent**—watching & analyze the signals from the global firehose 24/7 autonomously.



