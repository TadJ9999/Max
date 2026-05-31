"""Aegis SAST scanner — static code vulnerability detection.

Walks the workspace with the same gather_files / CODE_EXTS / DEFAULT_IGNORE_DIRS
logic as the RAG chunker, applies heuristic rules line-by-line, and returns raw
findings. Snippets are redacted before leaving this module.

AI triage is handled by scan_service (caller), not here, so the scanner stays
pure and testable without a provider.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Any

from ..rag.chunker import CODE_EXTS, DEFAULT_IGNORE_DIRS, MAX_FILE_BYTES, gather_files, read_text
from .redact import redact


# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    severity: str             # Critical | High | Medium | Low
    langs: frozenset[str]     # empty = all extensions
    pattern: re.Pattern
    message: str
    recommendation: str
    cwe: str = ""


RULES: list[Rule] = [
    # R001 — Hardcoded secret / API key
    Rule(
        id="R001",
        title="Hardcoded secret / API key",
        severity="Critical",
        langs=frozenset(),
        pattern=re.compile(
            r'(?:api[_\-]?key|secret[_\-]?key|access[_\-]?token|auth[_\-]?token'
            r'|password|passwd|apikey|private[_\-]?key)\s*[=:]\s*["\']'
            r'(?!(?:[^"\']*(?:env|environ|getenv|os\.|config|placeholder|example'
            r'|your[_\- ]|YOUR|<[^>]+>|\{[^}]+\})))'
            r'[A-Za-z0-9+/\-_.]{16,}["\']',
            re.IGNORECASE,
        ),
        message="A secret value appears to be hardcoded in source.",
        recommendation=(
            "Move this value to an environment variable or a secret store. "
            "Never commit credentials to version control."
        ),
        cwe="CWE-798",
    ),
    # R002 — eval()/exec() with dynamic input
    Rule(
        id="R002",
        title="Dynamic eval / exec",
        severity="High",
        langs=frozenset({".py", ".js", ".ts", ".jsx", ".tsx", ".mjs"}),
        pattern=re.compile(r'\b(?:eval|exec)\s*\((?!\s*["\'])', re.IGNORECASE),
        message="eval()/exec() called with a non-literal argument — possible code injection.",
        recommendation="Remove eval/exec. If unavoidable, validate and whitelist the argument.",
        cwe="CWE-95",
    ),
    # R003 — os.system / subprocess shell=True
    Rule(
        id="R003",
        title="Shell-injection risk (shell=True / os.system)",
        severity="High",
        langs=frozenset({".py"}),
        pattern=re.compile(
            r'\b(?:os\.system\s*\(|subprocess\.\w+\s*\([^)]*shell\s*=\s*True)',
            re.IGNORECASE,
        ),
        message=(
            "Command executed through the shell — shell-injection possible "
            "if any argument is user-controlled."
        ),
        recommendation="Use subprocess with a list argument and shell=False.",
        cwe="CWE-78",
    ),
    # R004 — SQL built by string concatenation / f-string
    Rule(
        id="R004",
        title="SQL injection via string concatenation",
        severity="High",
        langs=frozenset({".py", ".js", ".ts", ".jsx", ".tsx", ".php", ".rb", ".java"}),
        pattern=re.compile(
            r'(?:SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\b.{0,120}'
            r'(?:'
            r'\+\s*(?:str\()?(?:request|req|params|input|user|query|name|val|data)'
            r'|f["\'].*\{(?:request|req|params|input|user|query|name|id|val|data)'
            r'|%\s*(?:\(|str|unicode)?(?:request|req|user|query|name|id|val|data)'
            r')',
            re.IGNORECASE,
        ),
        message=(
            "SQL query built using string concatenation or f-string with "
            "what looks like user-controlled input."
        ),
        recommendation="Use parameterised queries / prepared statements.",
        cwe="CWE-89",
    ),
    # R005 — pickle.load / unsafe yaml.load
    Rule(
        id="R005",
        title="Unsafe deserialization (pickle / yaml.load)",
        severity="High",
        langs=frozenset({".py"}),
        pattern=re.compile(
            r'\b(?:pickle\.loads?\s*\(|yaml\.load\s*\((?!.*Loader\s*=\s*yaml\.(?:Safe|Base)Loader))',
            re.IGNORECASE,
        ),
        message=(
            "pickle.load or yaml.load (without SafeLoader) can execute arbitrary code "
            "when deserialising untrusted data."
        ),
        recommendation=(
            "Use yaml.safe_load() instead of yaml.load(). "
            "Avoid pickle entirely on data from external sources."
        ),
        cwe="CWE-502",
    ),
    # R006 — XSS sinks (JS/TS/HTML)
    Rule(
        id="R006",
        title="XSS sink (dangerouslySetInnerHTML / innerHTML / document.write)",
        severity="High",
        langs=frozenset({".js", ".ts", ".jsx", ".tsx", ".html", ".mjs"}),
        pattern=re.compile(
            r'(?:dangerouslySetInnerHTML\s*=|\.innerHTML\s*=|document\.write\s*\()',
            re.IGNORECASE,
        ),
        message=(
            "Direct HTML injection sink — if any part of the value is user-controlled "
            "this is an XSS vector."
        ),
        recommendation=(
            "Use safe DOM APIs (textContent, createElement). "
            "Sanitise HTML with a library like DOMPurify before injection."
        ),
        cwe="CWE-79",
    ),
    # R007 — TLS verification disabled
    Rule(
        id="R007",
        title="TLS verification disabled",
        severity="High",
        langs=frozenset(),
        pattern=re.compile(
            r'(?:'
            r'verify\s*=\s*False'
            r'|rejectUnauthorized\s*[=:]\s*false'
            r'|ssl\.CERT_NONE'
            r'|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*["\']0["\']'
            r')',
            re.IGNORECASE,
        ),
        message="TLS certificate verification is disabled — MITM attacks are possible.",
        recommendation=(
            "Enable certificate verification. "
            "Use a proper CA bundle or install the certificate rather than disabling verification."
        ),
        cwe="CWE-295",
    ),
    # R008 — Weak hashing algorithm
    Rule(
        id="R008",
        title="Weak hashing algorithm (MD5 / SHA-1)",
        severity="Medium",
        langs=frozenset(),
        pattern=re.compile(
            r'\b(?:'
            r'hashlib\.(?:md5|sha1)\s*\('
            r"|crypto\.createHash\s*\(\s*['\"](?:md5|sha1)['\"]"
            r'|new\s+MD5\s*\('
            r')\b',
            re.IGNORECASE,
        ),
        message=(
            "MD5 and SHA-1 are cryptographically broken. "
            "Do not use for authentication, integrity checking, or digital signatures."
        ),
        recommendation=(
            "Use SHA-256 or stronger: hashlib.sha256() / crypto.createHash('sha256')."
        ),
        cwe="CWE-327",
    ),
    # R009 — debug=True in source
    Rule(
        id="R009",
        title="Debug mode enabled in source",
        severity="Medium",
        langs=frozenset(),
        pattern=re.compile(r'\bdebug\s*=\s*True\b', re.IGNORECASE),
        message=(
            "Debug mode is enabled — may expose stack traces, "
            "secret variables, or admin endpoints in production."
        ),
        recommendation=(
            "Set debug=False in production. "
            "Drive debug mode via an environment variable, not source code."
        ),
        cwe="CWE-215",
    ),
    # R010 — Permissive CORS (allow_origins=["*"])
    Rule(
        id="R010",
        title="Permissive CORS (allow_origins / Access-Control-Allow-Origin: *)",
        severity="Medium",
        langs=frozenset(),
        pattern=re.compile(
            r'(?:'
            r'allow_origins\s*=\s*\[?\s*["\']?\*["\']?\s*\]?'
            r'|Access-Control-Allow-Origin\s*:\s*\*'
            r')',
            re.IGNORECASE,
        ),
        message=(
            "CORS is configured to allow all origins — "
            "any domain can make credentialed cross-origin requests."
        ),
        recommendation=(
            "Restrict allow_origins to a specific list of trusted domains. "
            "Use '*' only for fully public, unauthenticated APIs."
        ),
        cwe="CWE-942",
    ),
]


# ---------------------------------------------------------------------------
# Finding builder + fingerprint
# ---------------------------------------------------------------------------

def _fingerprint(rule_id: str, file: str, snippet: str) -> str:
    raw = f"{rule_id}:{file}:{snippet[:120]}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _make_finding(*, rule: Rule, file: str, line: int, snippet: str) -> dict[str, Any]:
    redacted = redact(snippet.strip()[:400])
    return {
        "category": "sast",
        "rule_id": rule.id,
        "cwe": rule.cwe,
        "severity": rule.severity,
        "title": rule.title,
        "file": file,
        "line": line,
        "snippet": redacted,
        "message": rule.message,
        "recommendation": rule.recommendation,
        # AI fields filled later by triage
        "ai_confidence": None,
        "ai_summary": None,
    }


# ---------------------------------------------------------------------------
# Scanner entry point
# ---------------------------------------------------------------------------

def scan_files(roots: list[str]) -> tuple[list[dict[str, Any]], int]:
    """Walk the workspace and return (raw_sast_findings, files_examined_count).

    Uses gather_files / DEFAULT_IGNORE_DIRS / CODE_EXTS so the scope is
    identical to the RAG chunker. All snippets are redacted before returning.
    Returns findings de-duped by fingerprint within this scan run.
    """
    findings: list[dict[str, Any]] = []
    seen_fps: set[str] = set()
    files_examined = 0

    for path in gather_files(roots):
        files_examined += 1
        ext = os.path.splitext(path)[1].lower()
        text = read_text(path)
        if text is None:
            continue

        lines = text.splitlines()
        for rule in RULES:
            if rule.langs and ext not in rule.langs:
                continue
            for i, line_text in enumerate(lines, start=1):
                if rule.pattern.search(line_text):
                    fp = _fingerprint(rule.id, path, line_text)
                    if fp in seen_fps:
                        continue
                    seen_fps.add(fp)
                    findings.append(_make_finding(
                        rule=rule, file=path, line=i, snippet=line_text,
                    ))

    return findings, files_examined
