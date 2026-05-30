"""Parser for the Max command DSL.

A command is::

    [sigil][operator] <body> [operator]

* **sigil** (optional) selects the provider/model. Defaults below; user-configurable.
    - ``@`` -> ollama (local)
    - ``#`` -> qwen   (local)
    - ``!`` -> claude (cloud, opt-in)
    - (none) -> the per-task default provider
* **operator** selects the action and delimits the body:
    - ``.``  ... ``.``   -> generate code
    - ``..`` ... ``..``  -> summarize / docstring / README

Examples::

    . add a function to do X and call Y .
    !. add a function .                       -> generate via Claude (cloud)
    @.. def foo(): pass ..                     -> document via Ollama (local)
    #. refactor this loop .                    -> generate via Qwen (local)
"""

from __future__ import annotations

from dataclasses import dataclass

# Default sigil -> provider map (overridable via config).
DEFAULT_SIGILS: dict[str, str] = {
    "@": "ollama",
    "#": "qwen",
    "!": "claude",
}

# Operator token -> action name. Longest token is matched first.
OPERATORS: dict[str, str] = {
    "..": "summarize",
    ".": "generate",
}


class ParseError(ValueError):
    """Raised when a string is not a well-formed Max command."""


@dataclass(frozen=True)
class Command:
    """A parsed Max command."""

    action: str          # "generate" | "summarize"
    body: str            # the instruction or code, trimmed
    sigil: str | None    # the raw sigil char, or None for default
    provider: str        # resolved provider name (e.g. "ollama", "claude", "default")
    is_cloud: bool       # True when this routes off-machine


def parse_command(text: str, sigils: dict[str, str] | None = None) -> Command:
    """Parse a single Max command string into a :class:`Command`.

    Raises :class:`ParseError` if the text is not a valid command.
    """
    sigil_map = sigils if sigils is not None else DEFAULT_SIGILS
    cloud_providers = {"claude"}  # extend as more cloud adapters are added

    s = text.strip()
    if not s:
        raise ParseError("empty command")

    # 1. Optional leading sigil.
    sigil: str | None = None
    provider = "default"
    if s[0] in sigil_map:
        sigil = s[0]
        provider = sigil_map[sigil]
        s = s[1:]

    # 2. Operator token — match the longest ("..") before the shortest (".").
    action: str | None = None
    open_tok = ""
    for tok in OPERATORS:  # dict preserves insertion order: "..", then "."
        if s.startswith(tok):
            action = OPERATORS[tok]
            open_tok = tok
            break
    if action is None:
        raise ParseError(f"no operator found at start of {text!r}")

    # 3. Body must be closed by the same operator token.
    rest = s[len(open_tok):]
    if not rest.endswith(open_tok):
        raise ParseError(f"command not closed with {open_tok!r}: {text!r}")
    body = rest[: -len(open_tok)].strip()
    if not body:
        raise ParseError("empty command body")

    return Command(
        action=action,
        body=body,
        sigil=sigil,
        provider=provider,
        is_cloud=provider in cloud_providers,
    )
