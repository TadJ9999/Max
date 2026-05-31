"""Aegis scan service — orchestrates SAST + SCA scans.

run_scan() is the public entry point: it walks files, runs heuristic rules,
optionally asks the AI to triage each SAST finding, queries OSV.dev for
dependency CVEs, upserts everything into the store, reconciles vanished
findings, and finishes the scan row with the computed posture score.

fix_finding() is an SSE async generator that streams an AI fix for a single
finding using the same chunk format as AegisService.diagnose.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ..config import EngineConfig
from ..providers.factory import build_provider
from ..rag.chunker import gather_files, read_text
from ..router import model_for
from .deps import Package, manifest_for, parse_all
from .osv import query_osv
from .redact import redact
from .scanner import scan_files
from .store import AegisStore

log = logging.getLogger(__name__)

TRIAGE_TIMEOUT_S = 30   # per-finding AI triage timeout


# ---------------------------------------------------------------------------
# Posture score
# ---------------------------------------------------------------------------

def posture_score(counts: dict[str, int]) -> int:
    """Compute posture score 0-100 (higher = better)."""
    raw = (
        100
        - 15 * counts.get("Critical", 0)
        - 7  * counts.get("High", 0)
        - 3  * counts.get("Medium", 0)
        - 1  * counts.get("Low", 0)
    )
    return max(0, min(100, raw))


# ---------------------------------------------------------------------------
# Scan service
# ---------------------------------------------------------------------------

class ScanService:
    def __init__(
        self,
        store: AegisStore,
        config: EngineConfig,
        repo_root: str,
    ) -> None:
        self._store = store
        self._config = config
        self._root = repo_root
        self._running = False
        self._current_scan_id: str | None = None
        self._files_scanned: int = 0
        self._stage: str = ""

    # ---- status ---------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_scan_id(self) -> str | None:
        return self._current_scan_id

    @property
    def files_scanned(self) -> int:
        return self._files_scanned

    @property
    def stage(self) -> str:
        return self._stage

    # ---- run_scan -------------------------------------------------------

    async def run_scan(self, trigger: str = "manual") -> str:
        """Run a full SAST + SCA scan. Returns the scan_id immediately.

        If a scan is already in progress the existing scan_id is returned
        without starting a second one.
        """
        if self._running:
            log.info("Scan already running — skipping %s trigger", trigger)
            return self._current_scan_id or ""

        self._running = True
        scan_id = self._store.start_scan(trigger)
        self._current_scan_id = scan_id
        self._files_scanned = 0
        self._stage = "Initializing"

        try:
            await self._do_scan(scan_id)
        except Exception:
            log.exception("Scan %s failed unexpectedly", scan_id)
            self._store.fail_scan(scan_id)
        finally:
            self._running = False
            self._current_scan_id = None

        return scan_id

    async def _do_scan(self, scan_id: str) -> None:
        cfg = self._config.aegis
        roots = list(cfg.scan_roots) if cfg.scan_roots else [self._root]

        # ---- SAST -------------------------------------------------------
        sast_findings: list[dict[str, Any]] = []
        try:
            self._stage = "Scanning files"
            raw_findings, files_examined = await asyncio.to_thread(scan_files, roots)
            self._files_scanned = files_examined
            self._store.update_scan_files(scan_id, files_examined)

            if raw_findings:
                self._stage = "AI triage"
                sast_findings = await self._triage_all(raw_findings)
            log.info("SAST: %d findings from %d files", len(sast_findings), files_examined)
        except Exception:
            log.exception("SAST scan failed")

        for f in sast_findings:
            self._store.upsert_finding(scan_id, f)

        # ---- SCA --------------------------------------------------------
        sca_findings: list[dict[str, Any]] = []
        if cfg.osv_enabled:
            try:
                self._stage = "Checking dependencies"
                packages = await asyncio.to_thread(parse_all, self._root)
                raw_sca = await query_osv(packages)
                sca_findings = _annotate_sca_files(raw_sca, packages, self._root)
                log.info("SCA: %d findings", len(sca_findings))
            except Exception:
                log.exception("SCA scan failed (offline?)")

        for f in sca_findings:
            self._store.upsert_finding(scan_id, f)

        # ---- Reconcile vanished findings --------------------------------
        self._stage = "Finalizing"
        self._store.reconcile_scan(scan_id)

        # ---- Score + finish -------------------------------------------
        all_findings = sast_findings + sca_findings
        counts: dict[str, int] = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
        for f in all_findings:
            sev = f.get("severity", "Low")
            counts[sev] = counts.get(sev, 0) + 1

        score = posture_score(counts)
        self._store.finish_scan(scan_id, counts, score, self._files_scanned)

    # ---- AI triage ------------------------------------------------------

    async def _triage_all(
        self, findings: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Run AI triage on every SAST finding. Falls back gracefully."""
        provider_name = _pick_provider(self._config)
        try:
            provider = build_provider(provider_name, self._config)
        except Exception:
            return findings  # AI unavailable — return unmodified

        model = model_for(provider_name, "chat", self._config)
        triaged: list[dict[str, Any]] = []

        for finding in findings:
            try:
                result = await asyncio.wait_for(
                    _triage_one(finding, provider, model),
                    timeout=TRIAGE_TIMEOUT_S,
                )
                triaged.append(result)
            except (asyncio.TimeoutError, Exception):
                triaged.append(finding)  # keep unmodified on failure

        return triaged

    # ---- fix_finding (SSE generator) ------------------------------------

    async def fix_finding(self, finding_id: str) -> AsyncIterator[str]:
        finding = self._store.get_finding(finding_id)
        if finding is None:
            yield f"data: {json.dumps({'error': {'message': 'finding not found'}})}\n\n"
            return

        provider_name = _pick_provider(self._config)
        try:
            provider = build_provider(provider_name, self._config)
        except Exception as exc:
            yield f"data: {json.dumps({'error': {'message': str(exc)}})}\n\n"
            return

        model = model_for(provider_name, "chat", self._config)
        messages = _fix_messages(finding, self._config.workspace_allowlist)

        parts: list[str] = []
        try:
            async for chunk in provider.chat(model, messages):
                parts.append(chunk.text)
                delta = {"content": chunk.text} if chunk.text else {}
                payload = {
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [
                        {"index": 0, "delta": delta,
                         "finish_reason": "stop" if chunk.done else None}
                    ],
                }
                yield f"data: {json.dumps(payload)}\n\n"
            yield "data: [DONE]\n\n"

            log_id = self._store.append_log_for_finding(finding_id, {
                "status": "proposed",
                "severity": finding.get("severity"),
                "symptom": f"{finding.get('title', '')}: {finding.get('message', '')[:80]}",
                "root_cause": "".join(parts)[:2000],
                "provider": f"{provider_name}/{model}",
            })
            self._store.stamp_finding_log(finding_id, log_id)

        except Exception as exc:
            err = {"error": {"message": redact(str(exc)), "type": type(exc).__name__}}
            yield f"data: {json.dumps(err)}\n\n"

    # ---- posture --------------------------------------------------------

    def posture(self) -> dict:
        data = self._store.posture()
        data["at_risk"] = data["score"] < self._config.aegis.score_threshold
        return data

    def report_markdown(self) -> str:
        """Generate a Markdown posture report."""
        p = self.posture()
        scans = self._store.list_scans(limit=10)
        findings = self._store.list_findings(status="open", limit=500)

        lines = [
            "# Aegis Security Posture Report",
            "",
            f"**Score:** {p['score']} / 100"
            + (" ⚠ AT RISK" if p.get("at_risk") else ""),
            f"**Critical:** {p['critical']}  **High:** {p['high']}"
            f"  **Medium:** {p['medium']}  **Low:** {p['low']}",
            f"**Last scan:** {p.get('last_scan_ts') or 'never'}",
            "",
            "## Score History",
            "",
        ]
        for s in scans:
            lines.append(f"- {s['ts'][:19]}  →  {s['score']}")
        lines.append("")

        # Group by category then severity
        for cat, cat_label in (("sast", "Code (SAST)"), ("sca", "Dependencies (CVE)")):
            cat_findings = [f for f in findings if f.get("category") == cat]
            if not cat_findings:
                continue
            lines.append(f"## {cat_label} Findings ({len(cat_findings)})")
            lines.append("")
            for f in cat_findings:
                sev = f.get("severity", "?")
                title = f.get("title", "")
                if cat == "sast":
                    loc = f"{f.get('file', '?')}:{f.get('line', '?')}"
                    lines.append(f"- **[{sev}]** {title} — `{loc}`")
                else:
                    pkg = f"{f.get('package', '?')}@{f.get('installed_version', '?')}"
                    cve = f.get("cve_id", "?")
                    fixed = f.get("fixed_version", "unknown")
                    lines.append(f"- **[{sev}]** {cve} in `{pkg}` → fix: {fixed}")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pick_provider(config: EngineConfig) -> str:
    return (
        "claude"
        if config.allow_cloud and os.environ.get("ANTHROPIC_API_KEY")
        else "ollama"
    )


async def _triage_one(
    finding: dict[str, Any],
    provider: Any,
    model: str,
) -> dict[str, Any]:
    """Ask the AI to score confidence and flag false positives for one SAST finding."""
    from ..prompts import SYSTEM_PROMPTS

    file_path = finding.get("file", "")
    file_excerpt = ""
    if file_path:
        text = await asyncio.to_thread(read_text, file_path)
        if text:
            lines = text.splitlines()
            hit = max(0, finding.get("line", 1) - 1)
            start, end = max(0, hit - 10), min(len(lines), hit + 40)
            file_excerpt = "\n".join(lines[start:end])

    user_content = (
        f"SAST FINDING:\n"
        f"Rule: {finding.get('rule_id')} — {finding.get('title')}\n"
        f"File: {file_path}:{finding.get('line', '')}\n"
        f"Snippet: {finding.get('snippet', '')}\n"
        f"Message: {finding.get('message', '')}\n"
    )
    if file_excerpt:
        user_content += f"\nContext:\n```\n{file_excerpt[:2000]}\n```\n"
    user_content += (
        "\nIs this a real vulnerability or a false positive? "
        'Return ONLY valid JSON: {"confidence": 0.0-1.0, '
        '"is_false_positive": true|false, "summary": "one sentence"}'
    )

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPTS.get("aegis_security", SYSTEM_PROMPTS["aegis"]),
        },
        {"role": "user", "content": user_content},
    ]

    acc = ""
    async for chunk in provider.chat(model, messages):
        acc += chunk.text

    import re
    m = re.search(r'\{[^{}]+\}', acc, re.DOTALL)
    if m:
        try:
            result = json.loads(m.group())
            confidence = float(result.get("confidence", 0.5))
            is_fp = bool(result.get("is_false_positive", False))
            summary = str(result.get("summary", "")).strip()

            finding = dict(finding)
            finding["ai_confidence"] = confidence
            finding["ai_summary"] = summary
            # High-confidence false positive → demote to Low
            if is_fp and confidence >= 0.8:
                finding["severity"] = "Low"
        except (json.JSONDecodeError, ValueError, TypeError, KeyError):
            pass

    return finding


def _annotate_sca_files(
    raw_sca: list[dict[str, Any]],
    packages: list[Package],
    repo_root: str,
) -> list[dict[str, Any]]:
    """Add the source manifest file path to each SCA finding."""
    pkg_to_file: dict[str, str] = {
        f"{p.ecosystem}:{p.name}": manifest_for(p, repo_root)
        for p in packages
    }
    result = []
    for f in raw_sca:
        f = dict(f)
        key = f"{f.get('ecosystem', '')}:{f.get('package', '')}"
        f["file"] = pkg_to_file.get(key, "")
        result.append(f)
    return result


def _fix_messages(finding: dict[str, Any], allowlist: list[str]) -> list[dict]:
    from ..prompts import SYSTEM_PROMPTS
    allowlist_str = "\n".join(allowlist) if allowlist else "(none configured)"
    system = SYSTEM_PROMPTS.get("aegis_security", SYSTEM_PROMPTS["aegis"])

    if finding.get("category") == "sca":
        user = (
            f"VULNERABILITY:\n"
            f"CVE/ID: {finding.get('cve_id', 'N/A')}\n"
            f"Package: {finding.get('package')} @ {finding.get('installed_version')}\n"
            f"Fixed in: {finding.get('fixed_version') or 'unknown'}\n"
            f"Manifest: {finding.get('file', 'unknown')}\n"
            f"Severity: {finding.get('severity')}\n"
            f"Description: {finding.get('message', '')}\n\n"
            f"WORKSPACE ALLOWLIST:\n{allowlist_str}\n\n"
            "Produce a unified diff (```diff fenced) that bumps this package to the "
            "fixed version in the manifest file. If the fixed version is unknown, "
            "explain how to determine it. Keep the diff minimal."
        )
    else:
        user = (
            f"SAST FINDING:\n"
            f"Rule: {finding.get('rule_id')} — {finding.get('title')}\n"
            f"File: {finding.get('file')}:{finding.get('line', '')}\n"
            f"Snippet: {finding.get('snippet', '')}\n"
            f"Message: {finding.get('message', '')}\n"
            f"Recommendation: {finding.get('recommendation', '')}\n"
        )
        if finding.get("ai_summary"):
            user += f"AI summary: {finding['ai_summary']}\n"
        user += (
            f"\nWORKSPACE ALLOWLIST:\n{allowlist_str}\n\n"
            "Provide:\n"
            "1. **Root cause** — plain English\n"
            "2. **Fix** — a unified diff (```diff fenced) ready to apply with `git apply`\n"
            "3. **Verification** — the command to confirm the fix\n\n"
            "Only touch files inside the workspace allowlist. Keep the diff minimal."
        )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
