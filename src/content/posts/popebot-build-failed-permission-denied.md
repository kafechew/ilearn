---
author: Kai
pubDatetime: 2026-03-10T13:00:00+08:00
title: PopeBot Build Failed & Permission Denied
featured: false
draft: false
slug: popebot-build-failed-permission-denied
tags:
  - ai
  - agentic
  - rpi
  - popebot
  - fix
  - english
description: Why permission denied when you were trying to build PopeBot and how to fix it.
---

Running into a wall of red text in your terminal is a rite of passage for anyone setting up a project on a Raspberry Pi. If you were trying to build **PopeBot** (or any Next.js project) and got hit with an `EACCES: permission denied` error, don't worry—you haven't broken anything.

This guide will walk you through exactly why this happens and how to fix it so you can get your bot back online.



## The Error: Understanding "EACCES"

When you see `uncaughtException [Error: EACCES: permission denied, open '.../.next/trace']`, your operating system is essentially saying: *"I see you're trying to write to this file, but you aren't the person who created it, and I'm not letting you touch it."*

In the case of a Raspberry Pi, this usually happens because of **The Sudo Trap**. At some point, a command was run using `sudo` (SuperUser Do). This caused the system to create folders—like your `.next` build folder—under the "root" user’s ownership. Now, when you try to run a normal `npm run build` as your regular user (`kafechew`), you don't have the "clearance" to modify those root-owned files.



## How to Fix the Permission Mismatch

Follow these three steps to reclaim your project and finish the build.



## 1. Reclaim Ownership of Your Files

Instead of using `sudo` to force the build (which can cause even more headaches later), the best practice is to tell the system that **you** own these files.

Run this command from inside your `keaibot` directory:

```
sudo chown -R $USER:$USER /home/kafechew/keaibot
```

**What this does:**

- `sudo`: Gives you temporary admin power to change ownership.
- `chown`: Stands for "Change Owner."
- `-R`: Stands for "Recursive." it applies the change to every single file and sub-folder inside the directory.
- `$USER:$USER`: This automatically fills in your current username (e.g., `kafechew`).



## 2. Clear the "Ghost" Build Files

Even after changing permissions, old build artifacts can sometimes cause conflicts. It’s safest to delete the existing build directory and let Next.js start from scratch.

```
rm -rf .next
```

**Note:** Be careful with `rm -rf`. Always double-check that you are in the correct folder before running it!



## 3. Run the Build Again

Now that your user owns the folder and the old, restricted files are gone, you can run the build command normally:

```
npm run build
```



## Pro-Tip

You should know that **using `sudo` with `npm` is generally considered bad practice.** When you use `sudo npm install` or `sudo npm run build`, you risk:

1. **Security Vulnerabilities:** Giving third-party scripts from the internet root access to your entire Raspberry Pi.
2. **Permission Hell:** Constantly having to fix the exact error we just solved.

**The Golden Rule:** If `npm` tells you that you need `sudo` to install something, it’s usually better to fix the permissions of your `node_modules` or use a version manager like **NVM** (Node Version Manager) rather than giving in to the `sudo` prompt.
