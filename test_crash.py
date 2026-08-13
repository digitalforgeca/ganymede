from ganymede.platforms.discord.formatter import DiscordFormatter
import json

content = """I've just built out the complete REST API for the core modules using Axum and SeaORM!

Here is what was added:
1. **Audiences** (`/api/audiences`): Full CRUD capability mapped to the `audiences` table. Handled schema includes the `criteria` JSON field for tracking heuristic rules.
2. **Ingredients** (`/api/ingredients`): Full CRUD capability mapped to the `ingredients` table. Handled schema includes the `ingredient_type` and arbitrary `payload` JSON.
3. **Examples/Messages** (`/api/messages`): Full CRUD capability mapped to the `messages` table (which serves as the backend repository for the frontend's 'Examples').

These modules are all nested safely under the main API tree and integrate cleanly with the central `AppState` database pooling we set up earlier. 

I've just committed the changes and started the rebuild of the Rust API container (`intelliverts-api`) on `theforge` VPS. Because Rust takes a minute or two to compile in the container, it'll be about 2-3 minutes before the new endpoints are fully live and answering queries!

Once it finishes, would you like me to start wiring the Next.js frontend pages we just built to consume these live API endpoints instead of our local component state?"""

fmt = DiscordFormatter()
try:
    chunks = fmt.split_message(content)
    print("SUCCESS")
except Exception as e:
    print(f"CRASH: {e}")
