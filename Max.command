#!/usr/bin/env bash
# ============================================================================
#  Max launcher — macOS / Linux THIN CLIENT.
#
#  This machine runs only the UI. All compute — the engine, Ollama, Tor, and
#  your cloud API keys — stays on the Windows PC that runs the Max engine. The
#  desktop app here connects to it over the LAN via HTTPS.
#
#  Double-click in Finder (it's a .command), or run `./Max.command` in a shell.
#
#  Engine address resolution (first match wins):
#    1. MAX_ENGINE_URL environment variable
#    2. client.remote_url in engine/.maxconfig.json
#    3. the default below (edit it, or the config, to your PC's name)
#
#  HTTPS note: the engine serves a locally-trusted mkcert certificate. Install
#  that root CA on this machine (see docs/lan.md) or the app's secure requests
#  to the engine will fail the TLS handshake.
# ============================================================================
cd "$(dirname "$0")" || exit 1

APP_DIR="$PWD/app"
CONFIG="$PWD/engine/.maxconfig.json"
DEFAULT_URL="https://max-pc.local:8443"

PY="$(command -v python3 || command -v python || true)"

read_config_url() {
  [ -f "$CONFIG" ] || return 0
  [ -n "$PY" ] || return 0
  "$PY" - "$CONFIG" <<'PY' 2>/dev/null || true
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(((d.get("client") or {}).get("remote_url") or "").strip())
except Exception:
    print("")
PY
}

write_config_url() {
  [ -n "$PY" ] || return 0
  mkdir -p "$(dirname "$CONFIG")"
  "$PY" - "$CONFIG" "$1" <<'PY' 2>/dev/null || true
import json, os, sys
path, url = sys.argv[1], sys.argv[2].rstrip("/")
try:
    d = json.load(open(path)) if os.path.exists(path) else {}
except Exception:
    d = {}
d.setdefault("client", {})["remote_url"] = url
json.dump(d, open(path, "w"), indent=2)
PY
}

# 1. Resolve the remote engine URL.
ENGINE_URL="${MAX_ENGINE_URL:-}"
[ -z "$ENGINE_URL" ] && ENGINE_URL="$(read_config_url)"
if [ -z "$ENGINE_URL" ]; then
  ENGINE_URL="$DEFAULT_URL"
  echo "[Max] No remote engine configured — defaulting to $ENGINE_URL"
  echo "      Point this at your Windows PC by editing engine/.maxconfig.json:"
  echo '      { "client": { "remote_url": "https://YOUR-PC.local:8443" } }'
  echo "      (or set MAX_ENGINE_URL), then re-run."
fi
ENGINE_URL="${ENGINE_URL%/}"

# Persist it so the app (engine_base) reads the same value the launcher used.
write_config_url "$ENGINE_URL"

# 2. Health-check the remote engine. The mkcert cert is self-signed, so -k.
echo "[Max] Checking engine at $ENGINE_URL ..."
if ! curl -fsk --max-time 4 "$ENGINE_URL/health" >/dev/null 2>&1; then
  cat <<EOF

  [x]  Can't reach the Max engine at:
         $ENGINE_URL

  Check that:
    - The Windows PC is powered on and awake.
    - Max is running there with "Share on LAN" enabled
      (Settings -> Share on LAN).
    - Both machines are on the same Wi-Fi / LAN.
    - You've installed the mkcert root CA on this machine (see docs/lan.md) so
      the engine's HTTPS is trusted — otherwise secure requests fail.

  Fix that, then run this launcher again.

EOF
  exit 1
fi
echo "[Max] Engine is up. Launching the app..."

# 3. Build the app if needed, then launch. The Tauri productName is "Max".
cd "$APP_DIR" || exit 1
APP_BUNDLE_MAC="src-tauri/target/release/bundle/macos/Max.app"
APP_BIN="src-tauri/target/release/Max"

launch() {
  if [ "$(uname)" = "Darwin" ] && [ -d "$APP_BUNDLE_MAC" ]; then
    open "$APP_BUNDLE_MAC"
  elif [ -x "$APP_BIN" ]; then
    "./$APP_BIN" &
  else
    return 1
  fi
}

if ! launch; then
  echo "[Max] No build found — building the desktop app (first run, may take a few minutes)..."
  command -v npm >/dev/null 2>&1 || { echo "[Max] npm not found. Install Node.js, then re-run."; exit 1; }
  npm install
  # --no-bundle matches Max.cmd: produces the raw release binary, no installer.
  npm run tauri build -- --no-bundle
  if ! launch; then
    echo "[Max] Build finished but no app binary was found."
    echo "      Try a dev run instead:  cd app && npm run tauri dev"
    exit 1
  fi
fi
