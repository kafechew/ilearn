---
author: Kai
pubDatetime: 2026-01-27T20:00:00+08:00
title: Nostr NIP-05 Verification Guide
featured: false
draft: false
slug: nostr-nip-05-verification
tags:
  - nostr
  - english
description: A practical walkthrough of NIP-05, showing how domains bridge human identity and cryptographic keys in the Nostr Web3 stack for decentralized communication, without tokens or gatekeepers.
---

## Nostr NIP-05 Verification for kheAI

In decentralized systems, *identity* is everything. If anyone can spin up a keypair in seconds, the question becomes:

> **How do you prove that a given identity is really *you*—without reverting to centralized gatekeepers?**

That’s where **NIP-05** comes in. It’s a simple, elegant bridge between the traditional web (domains, DNS, HTTPS) and the decentralized Nostr network.

This post documents how `kai@kheai.com` was verified using **NIP-05**, why it works, and how this fits into the broader Web3 landscape.

---

## What Is Nostr (in One Breath)

**Nostr** (*Notes and Other Stuff Transmitted by Relays*) is an open protocol for decentralized communication.

* No central servers
* No platform-owned accounts
* No algorithmic gatekeeping

Your identity **is your public key**. Everything else is optional.

---

## The Identity Problem in Decentralized Systems

Public keys are powerful—but also opaque:

```
npub1sjxaa2rmkkw6kv8x2njd3jmlwrac2mkhwrxqh0axh0l57p3sylmq4x07uc
```

That string proves cryptographic ownership, but:

* Is it really *Kai*?
* Is it really associated with **kheAI**?
* Or did someone just copy the name and avatar?

We need **human-readable verification** without centralized authorities.

---

## Enter NIP-05 (Verified Nostr Addresses)

**NIP-05** is a Nostr Improvement Proposal that allows identities like:

```
kai@kheai.com
```

to cryptographically map to a Nostr public key via HTTPS.

It works by hosting a simple JSON file on your own domain.

No tokens. No fees. No third parties.

---

## How NIP-05 Works (Conceptually)

1. A Nostr client sees `kai@kheai.com`
2. It fetches:

   ```
   https://kheai.com/.well-known/nostr.json
   ```
3. The file returns a mapping:

   ```json
   {
     "names": {
       "kai": "npub1sjxaa2rmkkw6kv8x2njd3jmlwrac2mkhwrxqh0axh0l57p3sylmq4x07uc"
     }
   }
   ```
4. The client checks:

   * HTTPS validity
   * Domain control
   * Pubkey match

If everything aligns → **verified**.

---

## kheAI Implementation (Real Example)

### Verified Identity

```
kai@kheai.com
```

### Public Key

```
npub1sjxaa2rmkkw6kv8x2njd3jmlwrac2mkhwrxqh0axh0l57p3sylmq4x07uc
```

### Hosted File

Path:

```
/.well-known/nostr.json
```

Content:

```json
{
  "names": {
    "kai": "npub1sjxaa2rmkkw6kv8x2njd3jmlwrac2mkhwrxqh0axh0l57p3sylmq4x07uc"
  }
}
```

Accessible at:

```
https://kheai.com/.well-known/nostr.json
```

This proves that the **same entity controlling kheai.com also controls the Nostr key**.

---

## Astro + Vercel Setup (Minimal & Clean)

Because kheAI already runs on **Astro + GitHub + Vercel**, the setup is trivial:

```
/public
  /.well-known
    nostr.json
```

Push → auto-deploy → done.

No backend. No server logic. No dependencies.

---

## Why This Is Powerful

NIP-05 quietly solves several Web3 pain points:

### 1. Decentralized Identity Without KYC

* You prove control, not citizenship
* No documents, no approvals

### 2. Anti-Impersonation

* Names are cheap
* Domains are costly to fake

### 3. Composability

* Works across all Nostr clients
* No lock-in

### 4. Longevity

* As long as DNS and HTTPS exist, this works

---

## Is Nostr “Web3”?

**Yes—but with an important nuance.**

### What Nostr Shares with Web3

* **Cryptographic identity** (keys, signatures)
* **Censorship resistance**
* **User-owned accounts**
* **Bitcoin Lightning integrations** (zaps, tips)

### What Nostr Is *Not*

* ❌ Not a blockchain
* ❌ No native token
* ❌ No consensus layer

Instead:

> **Nostr is a protocol layer—the communication pipes.**

Blockchains handle *state and value*.
Nostr handles *speech and presence*.

Together, they form a more complete decentralized stack.

---

## Why This Aligns with kheAI

kheAI focuses on:

* Verifiability over branding
* Proof over promises
* Infrastructure over hype

NIP-05 fits naturally:

* Verifiable identity
* Domain-level trust
* No platform dependence

Just like **Proof of Purity** for medicine, this is **Proof of Identity** for communication.

---

## Final Thoughts

NIP-05 isn’t flashy—and that’s exactly why it matters.

It’s:

* Boring in the best way
* Cheap
* Durable
* Human-readable

If Web3 is going to grow up, it needs more of this:

> **Simple primitives that compose cleanly with the real world.**

---

*If you control a domain, you already have more power than most social platforms want you to realize.*


Reference: [Get Verified](https://nostr.how/en/guides/get-verified)
