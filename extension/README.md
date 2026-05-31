# Max — VS Code extension

Brings the Max local-first engine into the editor:

- **DSL commands** — write a command on a line (or selection) and Max replaces it
  with the result, streaming inline:
  - `. generate this .` — generate code
  - `.. document this ..` — docstring / summary
  - `~ fix this ~` — fix / refactor
  - Prefix a **sigil** to pick the provider: `@` Ollama · `#` Qwen · `!` Claude (cloud).
    e.g. `!. add a retry decorator .`
- **Trigger** — fires automatically when you type the closing delimiter
  (`max.trigger: auto`, the default), or only on the keybinding
  (`ctrl+enter` / `cmd+enter`) when set to `manual`.
- **Ghost-text completion** — fill-in-the-middle suggestions as you type
  (`max.autocomplete`, toggle with *Max: Toggle ghost-text autocomplete*).
- **Status bar** — engine online/offline, the last model used, and a ☁ indicator
  while a cloud (`!`) command runs.

## Requirements

The Max engine must be running locally (the desktop app starts it on
`http://127.0.0.1:8001`; for dev, `uvicorn max_engine.main:app` on `:8000` —
set `max.engineUrl` accordingly). Ghost-text completion needs a FIM-capable
local model (e.g. `qwen2.5-coder:3b`) pulled in Ollama.

## Develop

```bash
cd extension
npm install
npm run build      # bundle to dist/extension.js
npm run typecheck
```

Then press **F5** in VS Code to launch an Extension Development Host.

## Settings

| Setting | Default | What |
|---------|---------|------|
| `max.engineUrl` | `http://127.0.0.1:8001` | Local engine base URL |
| `max.trigger` | `auto` | `auto` (fire on closing delimiter) or `manual` (keybinding only) |
| `max.autocomplete` | `true` | Ghost-text FIM completion |
| `max.completionDelayMs` | `300` | Idle delay before a completion request |
| `max.maxCompletionTokens` | `96` | Completion length cap |
