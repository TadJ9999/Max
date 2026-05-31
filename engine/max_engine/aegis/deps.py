"""Aegis SCA — dependency manifest / lockfile parsers.

Parses the project's lockfiles/manifests and returns (ecosystem, name, version)
triples for submission to OSV.dev. All parsing uses stdlib only.

Supported sources:
  Python : engine/pyproject.toml  ([project.dependencies] + optional-deps)
  npm    : app/package-lock.json  and  extension/package-lock.json
  Rust   : app/src-tauri/Cargo.lock
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import NamedTuple


class Package(NamedTuple):
    ecosystem: str   # "PyPI" | "npm" | "crates.io"
    name: str
    version: str


# ---------------------------------------------------------------------------
# Python — pyproject.toml
# ---------------------------------------------------------------------------

def _parse_pep508(dep: str) -> tuple[str, str]:
    """Return (normalised_name, version) from a PEP 508 string, or ("", "") if
    no pinned version is extractable."""
    dep = dep.strip()
    # Match name + version specifier, e.g. "httpx>=0.24,<1", "pydantic==2.0.1"
    m = re.match(
        r'^([A-Za-z0-9][A-Za-z0-9._\-]*)\s*[><=!~^]{1,3}\s*([0-9][^,;\s]*)',
        dep,
    )
    if m:
        name = m.group(1).lower().replace("_", "-")
        version = m.group(2).strip()
        # Strip trailing epoch/local identifiers that OSV doesn't expect
        version = re.sub(r'[!+].*$', '', version)
        return name, version
    # Name only (unpinned) — return name so caller can decide
    m = re.match(r'^([A-Za-z0-9][A-Za-z0-9._\-]*)', dep)
    if m:
        return m.group(1).lower().replace("_", "-"), ""
    return "", ""


def _parse_python(toml_path: Path) -> list[Package]:
    if not toml_path.exists():
        return []
    text = toml_path.read_text(encoding="utf-8")
    deps: list[str] = []

    if sys.version_info >= (3, 11):
        import tomllib  # type: ignore[import]
        try:
            data = tomllib.loads(text)
        except Exception:
            return []
        project = data.get("project", {})
        deps.extend(project.get("dependencies", []))
        for group in project.get("optional-dependencies", {}).values():
            deps.extend(group)
    else:
        # Regex fallback: collect quoted strings under [project.dependencies] blocks
        in_deps = False
        for line in text.splitlines():
            s = line.strip()
            if re.match(r'dependencies\s*=\s*\[', s) or s == "[project.dependencies]":
                in_deps = True
                continue
            if in_deps:
                if s.startswith("[") and "dependencies" not in s:
                    in_deps = False
                    continue
                m = re.search(r'"([^"]+)"', s)
                if m:
                    deps.append(m.group(1))

    pkgs: list[Package] = []
    for dep in deps:
        name, ver = _parse_pep508(dep)
        if name and ver:
            pkgs.append(Package("PyPI", name, ver))
    return _dedup(pkgs)


# ---------------------------------------------------------------------------
# npm — package-lock.json
# ---------------------------------------------------------------------------

def _parse_npm(lock_path: Path) -> list[Package]:
    if not lock_path.exists():
        return []
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    pkgs: list[Package] = []

    # lockfileVersion 2/3: "packages" dict with "node_modules/..." keys
    packages = data.get("packages", {})
    if packages:
        for key, info in packages.items():
            if not key or not key.startswith("node_modules/"):
                continue
            name = key.removeprefix("node_modules/")
            ver = info.get("version", "")
            if name and ver and not info.get("dev", False):
                pkgs.append(Package("npm", name, ver))
    else:
        # lockfileVersion 1: "dependencies" dict
        for name, info in data.get("dependencies", {}).items():
            ver = info.get("version", "")
            if name and ver and not info.get("dev", False):
                pkgs.append(Package("npm", name, ver))

    return _dedup(pkgs)


# ---------------------------------------------------------------------------
# Rust — Cargo.lock
# ---------------------------------------------------------------------------

def _parse_cargo(lock_path: Path) -> list[Package]:
    if not lock_path.exists():
        return []
    text = lock_path.read_text(encoding="utf-8")
    pkgs: list[Package] = []

    for block in re.split(r'\[\[package\]\]', text)[1:]:
        name_m = re.search(r'^name\s*=\s*"([^"]+)"', block, re.MULTILINE)
        ver_m  = re.search(r'^version\s*=\s*"([^"]+)"', block, re.MULTILINE)
        if name_m and ver_m:
            pkgs.append(Package("crates.io", name_m.group(1), ver_m.group(1)))

    return _dedup(pkgs)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_all(repo_root: str) -> list[Package]:
    """Parse all known manifests under repo_root and return deduplicated packages."""
    root = Path(repo_root)
    result: list[Package] = []
    result.extend(_parse_python(root / "engine" / "pyproject.toml"))
    result.extend(_parse_npm(root / "app" / "package-lock.json"))
    result.extend(_parse_npm(root / "extension" / "package-lock.json"))
    result.extend(_parse_cargo(root / "app" / "src-tauri" / "Cargo.lock"))
    return _dedup(result)


def manifest_for(pkg: "Package", repo_root: str) -> str:
    """Return the manifest file path that most likely contains this package."""
    root = Path(repo_root)
    candidates = {
        "PyPI":      root / "engine" / "pyproject.toml",
        "npm":       root / "app" / "package-lock.json",
        "crates.io": root / "app" / "src-tauri" / "Cargo.lock",
    }
    p = candidates.get(pkg.ecosystem)
    return str(p) if p and p.exists() else ""


def _dedup(pkgs: list[Package]) -> list[Package]:
    seen: set[tuple[str, str]] = set()
    out: list[Package] = []
    for p in pkgs:
        key = (p.ecosystem, p.name)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out
