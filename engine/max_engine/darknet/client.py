from __future__ import annotations

import httpx

# Tor Browser-compatible User-Agent so .onion sites don't flag the request
_UA = "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0"


def make_tor_client(socks_port: int = 9050, timeout: float = 30.0) -> httpx.AsyncClient:
    """Return an httpx AsyncClient that routes all traffic through Tor SOCKS5."""
    return httpx.AsyncClient(
        proxy=f"socks5h://127.0.0.1:{socks_port}",
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        headers={"User-Agent": _UA},
    )
