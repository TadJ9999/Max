"""Aegis SCA — OSV.dev vulnerability lookup.

Queries https://api.osv.dev/v1/querybatch (one HTTP round-trip for all packages)
then returns raw SCA findings. All network errors are silently swallowed so the
scanner degrades gracefully when offline — SAST findings still appear.

The httpx.AsyncClient is injectable for testing (same pattern as osint/events.py).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .deps import Package

log = logging.getLogger(__name__)

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"


# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------

def _cvss_to_severity(score: float) -> str:
    if score >= 9.0:
        return "Critical"
    if score >= 7.0:
        return "High"
    if score >= 4.0:
        return "Medium"
    return "Low"


def _extract_severity(vuln: dict) -> str:
    """Return a severity label from an OSV vuln object."""
    # OSV severity block (CVSS_V3 or CVSS_V2)
    for sev in vuln.get("severity", []):
        sev_type = sev.get("type", "")
        score_str = sev.get("score", "")
        if sev_type in ("CVSS_V3", "CVSS_V2") and score_str:
            # score_str may be a CVSS vector string — check for numeric score
            # in database_specific, or parse the last component
            parts = score_str.split("/")
            # Try to find a simple numeric score at end (some schemas embed it)
            for part in reversed(parts):
                try:
                    return _cvss_to_severity(float(part))
                except ValueError:
                    pass
    # Fallback: database_specific.cvss_score (GitHub Advisory, etc.)
    db = vuln.get("database_specific", {})
    for key in ("cvss_score", "severity_score", "score"):
        val = db.get(key)
        if val is not None:
            try:
                return _cvss_to_severity(float(val))
            except (TypeError, ValueError):
                pass
    # Coarse string mapping from db severity label
    label = str(db.get("severity", "")).upper()
    if label in ("CRITICAL",):
        return "Critical"
    if label in ("HIGH",):
        return "High"
    if label in ("MODERATE", "MEDIUM"):
        return "Medium"
    if label in ("LOW",):
        return "Low"
    return "High"  # conservative default


def _extract_fixed_version(vuln: dict, pkg_name: str) -> str:
    """Return the earliest fixed version across all affected ranges, or ''."""
    for affected in vuln.get("affected", []):
        if affected.get("package", {}).get("name", "").lower() != pkg_name.lower():
            continue
        for rng in affected.get("ranges", []):
            for event in rng.get("events", []):
                fixed = event.get("fixed", "")
                if fixed:
                    return fixed
    return ""


def _vuln_id(vuln: dict) -> str:
    """Return the primary CVE/GHSA/OSV ID, preferring CVE."""
    for alias in vuln.get("aliases", []):
        if alias.startswith("CVE-"):
            return alias
    return vuln.get("id", "")


# ---------------------------------------------------------------------------
# Main query
# ---------------------------------------------------------------------------

async def query_osv(
    packages: list[Package],
    *,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Query OSV.dev for the given packages and return raw SCA findings.

    Swallows all network/HTTP errors (offline-safe). Returns [] on failure.
    """
    if not packages:
        return []

    queries = [
        {"package": {"name": p.name, "ecosystem": p.ecosystem}, "version": p.version}
        for p in packages
    ]

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20.0)

    try:
        resp = await client.post(OSV_BATCH_URL, json={"queries": queries})
        if resp.status_code != 200:
            log.warning("OSV batch returned HTTP %s", resp.status_code)
            return []
        data = resp.json()
    except Exception as exc:
        log.warning("OSV query failed (offline?): %s", exc)
        return []
    finally:
        if own_client:
            await client.aclose()

    findings: list[dict[str, Any]] = []
    results = data.get("results", [])

    for pkg, result in zip(packages, results):
        for vuln in result.get("vulns", []):
            vuln_id = _vuln_id(vuln)
            severity = _extract_severity(vuln)
            fixed_ver = _extract_fixed_version(vuln, pkg.name)
            summary = (vuln.get("summary") or f"Vulnerability in {pkg.name}")[:120]
            details = (vuln.get("details") or summary)[:500]

            findings.append({
                "category": "sca",
                "rule_id": "",
                "cwe": "",
                "cve_id": vuln_id,
                "package": pkg.name,
                "installed_version": pkg.version,
                "fixed_version": fixed_ver,
                "ecosystem": pkg.ecosystem,
                "severity": severity,
                "title": summary,
                "file": "",          # filled by scan_service._annotate_sca_files
                "line": 0,
                "snippet": "",
                "message": details,
                "recommendation": (
                    f"Upgrade {pkg.name} to {fixed_ver}."
                    if fixed_ver
                    else f"Review {vuln_id} — no fixed version reported yet."
                ),
                "ai_confidence": None,
                "ai_summary": None,
            })

    return findings
