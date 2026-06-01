# Using Max over the LAN (phone & Mac/Linux)

Max runs as a desktop widget on a Windows PC, and that PC does all the work —
the engine, Ollama, Tor, and your cloud API keys never leave it. This doc covers
reaching that engine from **other devices on the same Wi-Fi**:

- an **iPhone/iPad** in Safari (the mobile web UI), and
- a **Mac or Linux** machine running the Max desktop app as a *thin client*.

Both rely on the engine's "Share on LAN" mode (HTTPS on `:8443`).

---

## 1. On the Windows PC: enable Share on LAN

1. Open Max → **Settings → Share on LAN**.
2. Click the cert helper to run **mkcert** (installs a local root CA and issues a
   certificate covering `<pc-name>.local`, the LAN IP, `localhost`, and
   `127.0.0.1`).
3. Toggle **Share on LAN** on. The engine restarts bound to `0.0.0.0:8443` over
   HTTPS, and a subnet-scoped Windows firewall rule is added.
4. Note the URL it shows: `https://<pc-name>.local:8443` (and the QR code).

> HTTPS is **mandatory**, not polish: browsers (and the Tauri WebView) disable
> the microphone, Web Speech, and clipboard on a plain-HTTP LAN origin. The
> mkcert certificate is what makes the secure context — and the voice features —
> work off-box.

---

## 2. Trust the mkcert root CA on the other device

The certificate is locally-trusted, so each client device must install the
**mkcert root CA** once. Reveal it on the PC via the Settings cert helper
("Reveal root CA"), or find it under the directory printed by `mkcert -CAROOT`
(the file is `rootCA.pem`).

**iPhone / iPad**

1. AirDrop or email `rootCA.pem` to the device and open it → install the profile.
2. **Settings → General → VPN & Device Management** → install the Max profile.
3. **Settings → General → About → Certificate Trust Settings** → enable full
   trust for the mkcert root.
4. Open `https://<pc-name>.local:8443` in Safari → you get the mobile UI.

**macOS**

```sh
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain /path/to/rootCA.pem
```

(or double-click `rootCA.pem`, add it to the **System** keychain, and set it to
*Always Trust* in Keychain Access). If you have mkcert installed on the Mac too,
`mkcert -install` does the same thing.

**Linux**

```sh
sudo cp rootCA.pem /usr/local/share/ca-certificates/mkcert-root.crt
sudo update-ca-certificates
```

---

## 3. Mac / Linux: run the desktop app as a thin client

The macOS/Linux build of the Max app is a **thin client**: it shows the UI here
but talks to the remote Windows engine — it never spawns a local engine. Launch
it with [`Max.command`](../Max.command) (double-click in Finder, or
`./Max.command` in a shell).

### Pointing it at your PC

The launcher resolves the engine address in this order (first match wins):

1. the `MAX_ENGINE_URL` environment variable,
2. `client.remote_url` in `engine/.maxconfig.json`,
3. the built-in default (`https://max-pc.local:8443`).

Set it once, either way:

```sh
# one-off
MAX_ENGINE_URL="https://my-pc.local:8443" ./Max.command
```

or persist it in `engine/.maxconfig.json` (the launcher will create/merge this):

```json
{ "client": { "remote_url": "https://my-pc.local:8443" } }
```

`<pc-name>` is the Windows PC's hostname (the same one shown in **Share on LAN**),
reachable as `<pc-name>.local` via mDNS. You can also use the PC's LAN IP.

### What the launcher does

1. Resolves and persists the engine URL (above).
2. Health-checks `GET <url>/health`. If it can't reach the engine it prints a
   checklist (PC awake? Share on LAN on? same network? root CA trusted?) and
   stops, rather than opening a broken window.
3. Builds the app on first run (`npm run tauri build -- --no-bundle`), then
   launches it.

### How it works under the hood

When `client.remote_url` is set, the Tauri app:

- **does not** start a local engine (`spawn_engine` early-returns), and
- points the WebView at the remote engine — `engine_base()` returns the remote
  URL, which `app/src/engine.ts` already uses for every API call.

Two Tauri commands back this: `get_remote_engine` and `set_remote_engine` (so a
Settings field can manage it without hand-editing JSON). The same mechanism also
lets a *Windows* app point at a different machine's engine, if you ever want to.

> CORS: the engine allows all origins, so the WebView's `tauri://` origin is
> accepted; no extra configuration is needed on the client.

---

## Future (out of scope here)

Internet access (Tailscale `*.ts.net` / Cloudflare Tunnel), app-level auth
tokens, and multi-user. The single-origin HTTPS design extends into those
cleanly when needed.
