# Goal Plan
1. `config.py`: Modify `AppConfig` to have a `bots` dict (keyed by bot id). Deprecate single `bot` and `platform` keys, or migrate them on load.
   - A `BotConfig` should have: `id` (name/key), `provider` (dict with `type` and plugin-specific fields), `model` (default model), `identity` (default system prompt), and `name`.
2. `base.py` / `provider.py`: Add `@classmethod def get_config_schema(cls) -> dict:` to `BasePlatformProvider`. Implement it in Discord and Web providers.
3. `core/routes/config.py`: 
   - Add endpoint `GET /api/providers` to list available providers and their schemas by inspecting the `ganymede.platforms` module (or similar registry).
   - Update `GET /api/config` and `POST /api/config` to support `bots` mapping.
   - Add endpoints for CRUD operations on bots: `GET /api/bots`, `POST /api/bots`, `PUT /api/bots/{id}`, `DELETE /api/bots/{id}`.
4. `cli.py`: Iterate over `config.bots.values()` and spawn providers and routers for each! 
   Wait! If we spawn multiple bots, the gateway (Dashboard) should only be spawned ONCE.
   Currently `DashboardServer` is spawned once and passed `providers`.
5. Frontend UI:
   - Update Settings to remove global Bot settings.
   - Update "Bot configuration" page to use the new `/api/bots` endpoints and dynamically render the config form based on the selected provider type's schema.
