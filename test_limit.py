from ganymede.platforms.discord.formatter import DiscordFormatter
from ganymede.platforms.discord.streamer import DiscordStreamer

class DummyChannel:
    pass
streamer = DiscordStreamer(DummyChannel(), edit_interval=0.0)

content = """<details><summary><code>list_dir</code></summary>

```json
{
  "DirectoryPath": "/Users/mcdoolz/dev",
  "toolAction": "Listing dev directory",
  "toolSummary": "List dev directory"
}
```

</details>
<details><summary><code>list_dir</code></summary>

```json
{
  "DirectoryPath": "/Users/mcdoolz/dev/forge",
  "toolAction": "Listing forge directory",
  "toolSummary": "List forge directory"
}
```

</details>
<details><summary><code>list_dir</code></summary>

```json
{
  "DirectoryPath": "/Users/mcdoolz/dev/forge/crates",
  "toolAction": "Listing forge crates",
  "toolSummary": "List forge crates"
}
```

</details>
<details><summary><code>list_dir</code></summary>

```json
{
  "DirectoryPath": "/Users/mcdoolz/dev/forge/services",
  "toolAction": "Listing forge services",
  "toolSummary": "List forge services"
}
```

</details>
<details><summary><code>grep_search</code></summary>

```json
{
  "Query": "struct Lead",
  "SearchPath": "/Users/mcdoolz/dev/",
  "toolAction": "Searching for struct Lead",
  "toolSummary": "Search for Lead"
}
```

</details>

Thinking out loud: 
I'm going to draft a proposed data model and system architecture for these new lead management features. This includes adding a timeframe-based classification for follow-ups, a dynamic schema for user-customizable statuses, and a decay-based formula for the "freshness" gauge that accounts for expected responses. I'll also outline how this aligns with standard CRM integrations (Hubspot/Salesforce) so we can map these fields correctly during import/export. No tool calls are needed right now while we brainstorm, but let me know when you're ready to start building!

---

That sounds like a solid step toward making leadgen.dforge.ca a much more proactive CRM. Here's a proposed architectural breakdown of how we can model these features in Rust (forge-medea) and Postgres to meet those needs and ensure smooth syncing with external CRMs like Hubspot and Salesforce.

Lead Classification (Heat & Timeframes)
To support a timeframe such as "contact within X [unit]", we should model this as a recurring or static SLA on the lead. 
Data Model: 
follow_up_value (integer)
 
follow_up_unit (enum: Minutes, Hours, Days, Weeks, Months, Years)
next_contact_due_at (timestamp, computed based on the last contact + the heat timeframe)
CRM Integration: When exporting to Salesforce or Hubspot, this can map to standard Task/Activity reminders, or a custom field for "Heat SLA".

Customizable Lead Statuses
Since users will want their own pipelines, hardcoding an enum won't work. We'll need a tenant-level or user-level configuration for statuses.
Data Model: 
A CustomStatus table: id, user_id (or organization_id), name (e.g., "In Negotiation", "Cold"), color_hex (for UI), is_default, sort_order.
The Lead table will hold a status_id referencing this table instead of a hardcoded enum.
CRM Integration: This perfectly mirrors Hubspot's "Lifecycle Stages / Lead Status" and Salesforce's "Lead Status" picklists. We can sync these dynamically or prompt users to map our custom statuses to their existing CRM statuses during their initial integration setup.

In-App Freshness Gauge (Decay Model)
This is an excellent feature that adds a lot of value. We can implement a "Freshness Score" (e.g., 0 to 100) that acts like a health bar for the relationship.
The Math: The score decays over time based on the duration since the last meaningful touchpoint (email sent, meeting held).
The "Expecting Response" Accelerator: If a boolean flag is_expecting_response is set to true (perhaps triggered automatically if the user's last email ended with a question, or set manually), we apply a multiplier (e.g., 2x or 3x) to the decay rate. The lead's "health" drops faster if they leave the user hanging.
UI Representation: A visual temperature gauge, battery indicator, or simple color gradient (Green -> Yellow -> Red) on the lead card.

Next Steps: 
If this structure looks good to you, I can start writing out the exact SQL schema migrations and the Rust structs for forge-medea to implement these models. How does this approach sound?"""

stats = f"\n\n*⚡ 1195 tokens · ⏱ 81.76s*"
content += stats
content = streamer._balance_code_fences(content)
content = streamer.formatter.format_text(content)
chunks = streamer.formatter.split_message(content)

for i, chunk in enumerate(chunks):
    c = streamer._balance_code_fences(chunk)
    print(f"Chunk {i+1} len: {len(c)}")
    if len(c) > 2000:
        print(f"FAILED! Chunk {i+1} is > 2000")

