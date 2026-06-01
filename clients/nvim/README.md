# max.nvim

The Max local-first AI engine, in Neovim. A thin client over the same engine the
desktop app and VS Code extension use — DSL commands with inline-replace streaming,
fill-in-the-middle ghost-text completion, a health/cloud indicator, and
visual-selection operations. Local by default; cloud only when you ask (`!` / `%`).

## Requirements

- **Neovim 0.10+**
- **curl** on `PATH` (ships with Windows 10+, macOS, and most Linux)
- A running **Max engine** (the desktop app starts it on `http://127.0.0.1:8001`;
  dev `uvicorn` uses `:8000`)

## Install

**lazy.nvim** (point it at this subdirectory of the Max repo, or copy `clients/nvim`
into its own repo):

```lua
{
  "your/max",                    -- or a local dir spec
  dir = "/path/to/Max/clients/nvim",
  opts = {
    engine_url = "http://127.0.0.1:8001",
  },
}
```

**packer.nvim**:

```lua
use {
  "/path/to/Max/clients/nvim",
  config = function() require("max").setup({}) end,
}
```

`setup()` is optional — the plugin zero-config bootstraps with defaults on startup
if you never call it. Calling `setup()` (or lazy's `opts`) lets you override config.

## Usage

Type a DSL command on a line and it runs (in `auto` mode, on the closing delimiter):

| You type | Does |
|---|---|
| `. write a function that adds two numbers .` | generate code |
| `.. explain this ..` | summarize / docstring |
| `~ tidy this messy block ~` | fix / refactor |

Optional **sigils** pick the provider (default keybinds in the engine):

| Sigil | Routes to | Locality |
|---|---|---|
| *(none)* | per-task default model | local |
| `@` | Ollama | local |
| `#` | Qwen | local |
| `^` | OpenAI-compatible local server (llama.cpp / vLLM / LM Studio) | local |
| `!` | Claude | ☁ cloud |
| `%` | OpenAI | ☁ cloud |

e.g. `!. explain this regex .` runs on Claude; `^. hello .` on your local server.

- **Run manually:** `:Max`, or `<leader>mm` on the command line.
- **Over a selection:** visually select text that forms a command (e.g. `~ fix this ~`)
  and `:'<,'>Max` (or `<leader>mm` in visual mode) — replaced in place.
- **Ghost text:** pause while typing and a grey inline suggestion appears; press
  `<Tab>` to accept. Toggle with `:MaxToggleAutocomplete` / `<leader>ma`.
- **Health:** `:MaxHealth`, or add the statusline component below.

### Statusline (lualine)

```lua
require("lualine").setup({
  sections = { lualine_x = { require("max.status").statusline } },
})
```

Shows `⚡Max`, `⚡Max ☁` (a cloud command is running), or `⚡Max ⃠` (engine offline).

## Configuration

Defaults (override any via `setup`):

```lua
require("max").setup({
  engine_url = "http://127.0.0.1:8001",
  trigger = "auto",            -- "auto" (fire on closing delimiter) | "manual" (keymap only)
  autocomplete = true,         -- ghost-text FIM completion
  completion_delay_ms = 300,   -- idle delay before requesting a suggestion
  max_completion_tokens = 96,  -- keep small for snappy ghost text
  keymaps = {
    run = "<leader>mm",
    toggle_autocomplete = "<leader>ma",
    accept_completion = "<Tab>",
  },
})
```

Set any keymap to `false` or `""` to skip it (e.g. to bind `<Tab>` yourself).

## Notes

- **Undo:** a streamed result lands as a normal sequence of edits, not a single
  undo step (matching VS Code's single-undo is impractical with async streaming).
  One `u` may not revert the whole block — `undo` repeatedly or use `:earlier`.
- **Auto-trigger in insert mode:** in `auto` mode the command fires as you finish
  typing the closing `.`/`~`; if that feels surprising, set `trigger = "manual"`.
- All backend calls go to the local engine over `curl`; cloud egress happens only
  for `!`/`%` and is marked in the statusline.

## Tests

Pure-function tests (no engine needed), run where Neovim is installed:

```sh
nvim --headless -l clients/nvim/test/run.lua
```
