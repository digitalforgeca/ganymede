# Discord Context Execution Rules

When executing in a Discord conversation context (denoted by a platform identifier "discord" in the context key):

1. **Length Bounds**: Keep messages concise. A message MUST fit within Discord's 2,000-character limit. If your output is longer, break it down or summarize it.
2. **Discord Formatting**: 
   - Use standard Discord markdown syntax (e.g., `**bold**`, `*italics*`, `__underline__`, `~~strikethrough~~`, `` `inline code` ``, and code blocks).
   - Never use HTML or rich layout structures that Discord does not render.
3. **No Code Spoilers**: Do not print entire files unless explicitly requested. Print targeted diffs or snippets.
4. **Actionable Summaries**: Always end long reasoning runs or task completions with a clear, user-friendly summary.
5. **Scheduled Execution**: When invoked via a scheduled cron prompt, direct your output explicitly to the context channel/thread where the job was registered.
