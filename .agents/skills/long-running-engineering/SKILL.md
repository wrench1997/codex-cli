---
name: long-running-engineering
description: Run resumable, evidence-driven software engineering tasks. Use for multi-step features, refactors, migrations, debugging sessions, work that may outlive one context window, or any task requiring checkpoints, verification, Git isolation, and handoff.
---

# Long-Running Engineering

Use the task ledger as the source of truth; conversation is only a working view.

## Workflow

1. Start or resume with `/tasks` and `/resume`. Inspect Git status before changing files.
2. Define a concrete goal and acceptance items with `update_task_contract`.
3. Read narrowly. Use search and paged `read_file`; do not request whole logs or generated files.
4. Record an evidence-backed completion for each acceptance item with `complete_acceptance_item`. A prose claim is not evidence.
5. Run `verify_task`. Treat failures, skips, and timeouts as unfinished work.
6. Save `/checkpoint <phase>` after a coherent phase and before risky refactors. Use `/recall <term>` instead of re-reading historical output.
7. For experimental or parallel work, explicitly create `/worktree <name>` before editing. Do not create branches or worktrees implicitly.

## Handoff format

Before pausing, persist a checkpoint whose next steps state: current behavior, changed files, validation evidence, known risks, and the one next executable action.

## Guardrails

- Never mark acceptance complete without a command result, test result, diff, or user confirmation.
- Keep source of truth in the repository and `.mcodex/`; do not rely on an old summary for exact code or logs.
- When context is compacted, retrieve local observations before repeating expensive commands.
