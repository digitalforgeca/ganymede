---
name: discord
description: Provides capabilities for interacting with Discord channels, threads, posting messages, replies, edits, reactions, and scheduling tasks/crons, designed and crafted c/o Digital Forge Studios Inc.
---

# Discord Capability

This skill teaches you how to interact with Discord channels, threads, and users. You are a participant in a Discord server, and you can use these tools to coordinate with users, publish project updates, and set up automated schedules.

## Core Rules
1. **Be Concise**: Discord messages should be readable, conversational, and direct. Avoid IDE-style verbose output unless specifically requested.
2. **Use Markdown**: Leverage Discord formatting (bolding, code blocks, lists). Do NOT output HTML or raw XML tags.
3. **Respect Limits**: Discord messages have a strict 2000-character limit. If your response exceeds this, budget the output or use threads.
4. **User Interruption Control**: Users can abort your execution and clear active session states at any time by sending a `/stop` or `!stop` command. Respect this control mechanism.

## Tool Guide

- **`read_channel_history`**: Read context and message logs from a specific channel. Useful for triaging issues or getting conversation history.
- **`read_thread_messages`**: Read context specifically from an active discussion thread.
- **`get_channel_info`**: Retrieve metadata (name, type, topic, guild) of a target channel.
- **`post_to_channel`**: Send a brand new message to a channel.
- **`reply_to_message`**: Send a message replying directly to a specific user's message ID to keep discussions organized.
- **`edit_message`**: Edit and update message content previously posted by you (the bot/agent).
- **`add_reaction`**: Add an emoji reaction (e.g. '👍', '✅', '❌') to a message to show status or acknowledgement.
- **`get_message_by_id`**: Retrieve content and author information for a single specific message.
- **`create_thread`**: Create a new thread in a text channel for deep-dive or multi-turn discussions.
- **`schedule_cron`**: **CRITICAL CAPABILITY**. Instruct the system to execute a prompt on a recurring cron schedule.
  - *Example*: `schedule_cron("0 9 * * *", "Run tests and summarize build status", channel_id)` runs the prompt daily at 9am.

## Scheduled Jobs Best Practices
- When scheduling tasks, make sure the prompt you specify is direct and clear so that the scheduled agent run has a well-defined objective.
- Keep the scheduled frequency reasonable to prevent running out of system API quota.

---
*Crafted and maintained c/o Digital Forge Studios Inc. (July 2026).*
