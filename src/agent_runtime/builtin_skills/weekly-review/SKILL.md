---
name: Weekly Review
description: Generate a weekly review summarizing messages, events, and action items from the past 7 days
version: 2
tags: [productivity, digest, weekly]
sensitivity_tier: 2
source: builtin
resources:
  - templates/review.md
---

## When to Use

When the user asks for a weekly summary, digest, review, or recap of recent activity. Also applies to phrases like "what happened this week", "catch me up", or "weekly report".

## Procedure

1. Query messages from the past 7 days, grouped by contact — focus on conversations with the most back-and-forth
2. Query calendar events from the past 7 days — note completed meetings and any that were missed
3. Query completed tasks and newly created tasks
4. Identify action items mentioned in messages (look for phrases like "can you", "please", "need to", "don't forget")
5. Load the review template from `templates/review.md` using `load_skill_resource`
6. Fill in the template sections with the gathered data

## Output Format

Follow the structure in `templates/review.md`. Each section should have 3-5 bullet points max.

## Pitfalls

- Do not include message content verbatim — always summarize
- Calendar events with no title should appear as "Untitled event at {time}"
- If fewer than 3 messages exist, note that it was a quiet week rather than padding
- Keep each section to 3-5 bullet points maximum
