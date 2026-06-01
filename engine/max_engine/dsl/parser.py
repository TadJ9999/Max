"""Parser for the Max command DSL.

A command is::

    [sigil][operator] <body> [operator]

* **sigil** (optional) selects the provider/model. Defaults below; user-configurable.
    - ``@`` -> ollama (local)
    - ``#`` -> qwen   (local)
    - ``!`` -> claude (cloud, opt-in)
    - ``%`` -> openai (cloud, opt-in)
    - (none) -> the per-task default provider
* **operator** selects the action and delimits the body:
    - ``.``  ... ``.``   -> generate code
    - ``..`` ... ``..``  -> summarize / docstring / README

Examples::

    . add a function to do X and call Y .
    !. add a function .                       -> generate via Claude (cloud)
    @.. def foo(): pass ..                     -> document via Ollama (local)
    #. refactor this loop .                    -> generate via Qwen (local)
    ~ tidy this messy block ~                  -> fix / refactor (default provider)
    ? explain this ?                           -> custom command (if configured)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import CustomCommand

# Default sigil -> provider map (overridable via config).
DEFAULT_SIGILS: dict[str, str] = {
    "@": "ollama",
    "#": "qwen",
    "!": "claude",
    "%": "openai",
}

# Operator token -> action name. Longest token is matched first, so ".." is
# tried before ".". ("!" is reserved as the cloud sigil, so fix/refactor uses "~".)
OPERATORS: dict[str, str] = {
    "..": "summarize",
    ".": "generate",
    "~": "fix",
}


class ParseError(ValueError):
    """Raised when a string is not a well-formed Max command."""


@dataclass(frozen=True)
class Command:
    """A parsed Max command."""

    action: str  # "generate" | "summarize" | "fix" | "custom:<name>"
    body: str  # the instruction or code, trimmed
    sigil: str | None  # the raw sigil char, or None for default
    provider: str  # resolved provider name (e.g. "ollama", "claude", "default")
    is_cloud: bool  # True when this routes off-machine
    prompt_override: str | None = field(default=None)  # set by custom commands


def parse_command(
    text: str,
    sigils: dict[str, str] | None = None,
    custom_commands: "list[CustomCommand] | None" = None,
) -> Command:
    """Parse a single Max command string into a :class:`Command`.

    Raises :class:`ParseError` if the text is not a valid command. Custom
    command triggers (e.g. ``?``) are tried after built-in operators.
    """
    sigil_map = sigils if sigils is not None else DEFAULT_SIGILS
    cloud_providers = {"claude", "openai"}

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

    # 3. Custom command trigger (single char delimiter, e.g. "? … ?").
    prompt_override: str | None = None
    if action is None and custom_commands:
        for cmd in custom_commands:
            tok = cmd.trigger
            if len(s) > len(tok) * 2 and s.startswith(tok) and s.endswith(tok):
                body_raw = s[len(tok) : -len(tok)].strip()
                if body_raw:
                    action = f"custom:{cmd.name}"
                    open_tok = tok
                    prompt_override = cmd.prompt_template.replace("{body}", body_raw)
                    s = tok + body_raw + tok
                    break

    if action is None:
        raise ParseError(f"no operator found at start of {text!r}")

    # 4. Body — strip operator delimiters.
    rest = s[len(open_tok) :]
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
        prompt_override=prompt_override,
    )
