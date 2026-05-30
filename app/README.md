# Max App (Tauri desktop chat client)

The v1 client: a chat UI plus full configuration (models, sigils, hotkeys,
provider keys, the workspace folder allowlist, and the delegate dashboard).
It talks to the engine's HTTP/WebSocket API — it holds **no** model logic itself.

> Not scaffolded yet — needs the Node + Rust toolchain. Initialize with:

```bash
# from repo root
npm create tauri-app@latest app -- --template react-ts
cd app && npm install && npm run tauri dev
```

## Planned screens (maps to ROADMAP Phase 3 & 4)
- **Chat** — streaming, markdown/code blocks, a clear ☁ indicator when a cloud sigil (`!`) is used.
- **Models** — list / download / switch / params (temp, ctx, quant); live VRAM/RAM meters.
- **Routing** — map sigils → providers/models, set per-task defaults, assign hotkeys.
- **Delegate** — Manual/Smart-Auto toggle; queue dashboard with a manual "send to cloud" override;
  isolated session panes streaming concurrently.
- **Settings** — provider keys, cloud on/off, workspace folder allowlist.
