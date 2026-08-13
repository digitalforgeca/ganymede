import sys
sys.path.append("src")
from ganymede.platforms.discord.formatter import DiscordFormatter

text = """**Prioritizing Tool Usage**

I'm now focusing on tool selection, emphasizing specific tools over general ones where possible. The goal is to optimize efficiency by leveraging tools like 'view_file' directly, rather than resorting to broader, less direct methods. I'm aiming for targeted actions.

<details><summary><code>manage_task</code>: Check deploy task status</summary>

```json
{
  "Action": "status",
  "TaskId": "e79c76a2-2d63-461f-ac4f-70f9757f7ea4/task-105",
  "toolAction": "Checking Task Status",
  "toolSummary": "Check deploy task status"
}
```
</details>

I have committed the changes introducing the `Examples` core module and pushed them to the `master` branch. I have also initiated the deployment using the `forge-deploy.sh` script for the `intelliverts` target. 

The deployment is currently running via Hephaestus in the background. I'll let you know as soon as it completes."""

fmt = DiscordFormatter()
formatted = fmt.format_text(text)
print("FORMATTED:", formatted)
chunks = fmt.split_message(formatted)
print("CHUNKS:", chunks)
