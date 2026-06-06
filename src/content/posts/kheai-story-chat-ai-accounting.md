---
author: Kai
pubDatetime: 2025-08-08T11:00:00+08:00
title: From Messy Notes to Conversational AI Accounting — The Story Behind kheAI
featured: false
draft: false
slug: kheai-story-chat-ai-accounting
tags:
  - ai
  - accounting
  - bitcoin
  - malaysia
  - telegram
  - fintech
  - announcement
description: How a stack of receipts, late-night messages, and a stubborn idea turned into a Telegram-based AI accountant for Malaysian microbusinesses.
---

It started, as most problems do, with a pile of receipts and a half-empty coffee cup.

A friend — let’s call her Aida — runs a tiny online bakery in Penang. Her cakes are gorgeous, her customers loyal, her weekends fully booked. But when tax season came around, her desk looked like a storm had passed through:  
**sticky notes, crumpled invoices, random screenshots of bank transfers.**

> Accounting software? Too complicated. I just text myself the amounts in WhatsApp 
> 
> Then… I forget.

she told me. 

That night, I stared at my Telegram chats.  
If people already *talk* about their money here, why not make the chat itself the accounting tool?

---

## The First Version: Talking to My Accountant Bot

I hacked together a quick Telegram bot. You could send it a message like:

> Paid rent RM800

It would reply instantly:


> [Recorded] Debit: Rent Expense RM800
> Credit: Cash RM800

Aida tried it. Her first reaction wasn’t “Wow, AI!” — it was:

> Wait… I don’t have to *log in* anywhere?

That’s when I knew:  
The real magic wasn’t AI — it was **zero friction**.

---

## What kheAI Does Now

Today, that scrappy bot has grown into **kheAI** — a chat-first AI accountant that fits in your Telegram.  

Here’s what it can do for you:

- **Turn messages into double-entry records** (English, Malay, Chinese — even “rojak” chat style)
- **Generate financial statements** on demand (`/income_statement`, `/balance_sheet`)
- **Manage your Bitcoin treasury**, with live BTC price in RM and inflation-aware allocation tips
- **Export to CSV** for your accountant — or for tax submissions

Under the hood, Redis 8 powers:
- Fast AI responses (semantic caching)
- Smart categorization (vector search)
- Immutable audit logs (Streams & TimeSeries)

---

## Why Bitcoin Treasury?

I’ve been in Bitcoin since the days when people still argued about whether it was “real money.”  
For small businesses, holding *just a little* BTC — maybe 3% of monthly profit — can be a hedge against inflation.  
kheAI gives you:
- The latest BTC price in RM
- Suggested allocation based on your cash flow
- Safety reminders (because volatility is real)

---

## For Malaysian Microbusinesses

Let’s be honest:  
Most small businesses here don’t need — or want — big, complicated accounting systems. They need:
- **Simple** — no training, no new app to download
- **Mobile-first** — works on the same phone they run their business from
- **Localized** — understands “sewa,” “duit masuk,” and “bayar gaji” instantly

That’s kheAI’s sweet spot.

---

## How You Can Try It

If you can send a message, you can do your books.

1. Open Telegram  
2. Search for [**@kheAIbot**](https://t.me/kheAIbot)  
3. Send: `Sales RM500` or `Bitcoin price now?` 
4. Watch the magic happen.

---

## The Road Ahead

I built kheAI because I believe **tools should adapt to people, not the other way around**.

Next up:
- GST/SST-ready reports
- Auto-recognition of bank transaction CSVs
- Group chat mode (so teams can share one ledger)

---

Aida still bakes in Penang.  
Her Telegram is cleaner now — no random money notes scattered between cat memes and customer messages.  
And every time she checks her monthly profit, she smiles at the tiny line that says:  
> Bitcoin Treasury: RM412 (0.0012 BTC)

It’s not just bookkeeping anymore.  
It’s freedom, one message at a time.


