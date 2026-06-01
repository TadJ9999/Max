# max — command-line client

A thin terminal client over the same Max engine the desktop app, VS Code
extension, and Neovim plugin use. Local by default; cloud only when you ask
(`!` / `%`). It talks to the engine purely over HTTP, so it works against a
local engine **or a remote one** (e.g. the Windows engine over the LAN).

The client ships *inside* the engine package — there is nothing to build. It
lives at [`engine/max_engine/cli.py`](../../engine/max_engine/cli.py) and is
exposed as the `max` console script.

## Install

From the repo:

```sh
pip install -e engine            # installs the `max` command (and the engine)
```

The only runtime dependency is `httpx`, which the engine already requires.

## Pointing at an engine

By default the CLI talks to `http://127.0.0.1:8001` (the port the desktop app
serves). Override per-invocation or via the environment:

```sh
max --engine https://my-pc.local:8443 health
export MAX_ENGINE_URL=https://my-pc.local:8443   # then just `max …`
```

## Usage

| Command | Does |
|---|---|
| `max "!. write a fizzbuzz ."` | one-shot: runs the DSL command, streams the result |
| `max "what is a monad?"` | one-shot: plain chat (no DSL operators → routed to `/chat`) |
| `max run ". add a docstring ."` | run an explicit DSL command |
| `max chat` *(or just `max`)* | interactive multi-turn REPL with memory |
| `max health` | engine health, active model, and cloud state |
| `max sessions` | list delegate sessions |
| `max sessions cancel <id>` | cancel a queued/running session |
| `max sessions promote <id>` | push a queued session to the cloud |

### DSL sigils & operators

Same grammar as every other client (the engine is the authoritative parser):

| Sigil | Routes to | Locality |
|---|---|---|
| *(none)* | per-task default model | local |
| `@` | Ollama | local |
| `#` | Qwen | local |
| `^` | OpenAI-compatible local server (llama.cpp / vLLM / LM Studio) | local |
| `!` | Claude | ☁ cloud |
| `%` | OpenAI | ☁ cloud |

| Operator | Action |
|---|---|
| `. … .` | generate code |
| `.. … ..` | summarize / docstring |
| `~ … ~` | fix / refactor |

### One-shot routing

A bare `max "<text>"` first tries `/command` (the DSL path). If the engine
rejects the text as not-a-command (HTTP 400), the CLI transparently falls back
to plain chat — so you can type either without thinking about it.

### REPL

In the REPL, plain text is multi-turn chat (memory carried via the
OpenAI-compatible endpoint); a line that begins with a sigil or operator runs
one-shot as a DSL command. Slash commands:

- `/reset` — clear chat memory
- `/health` — engine status
- `/sessions` — list delegate sessions
- `/exit` (or Ctrl-D) — quit

## Notes

- Cloud egress happens only for `!` / `%`. If `allow_cloud` is off (or the
  kill-switch is on) a cloud command exits with a clear message and code 3.
- `NO_COLOR=1` (or piping to a file) disables ANSI styling.
