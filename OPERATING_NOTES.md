# Ganymede Operating Notes

## IMPORTANT CONTEXT
- **WE ARE NOT USING THE API.** 
- **WE ARE USING AGY CLI AND WE ARE NOT USING THE API.**

## Model Parameter Rules
- The exact string `"Gemini 3.1 Pro (High)"` MUST be correctly passed to `agy` via the `--model` parameter.
- Never auto-convert or map `"Gemini 3.1 Pro (High)"` to another string like `"gemini-pro-agent"` under the assumption that it's an invalid API identifier. The CLI processes it properly.
- All code that invokes `agy` must ensure that `resolved_model` is explicitly injected into the argument list without stripping or modifying the string.
