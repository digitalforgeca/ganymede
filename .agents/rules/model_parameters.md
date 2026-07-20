# Ganymede Model Parameter Invocation

- **NO SDK MAPPING**: When working on Ganymede, we are wrapping the `agy` CLI natively. The CLI handles its own internal SDK model mappings. We are NOT calling the Antigravity Python SDK directly.
- **EXACT STRING**: The exact model string `"Gemini 3.1 Pro (High)"` must be explicitly preserved and passed to `agy` via the `--model` parameter exactly as it is configured in `config.yaml`.
- Never auto-convert `"Gemini 3.1 Pro (High)"` to `"gemini-pro-agent"` under the false assumption that it's an invalid API identifier.
