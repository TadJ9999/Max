"""TorService — manages the Tor daemon's lifecycle view from Python.

The actual Tor process is owned by the Tauri/Rust layer (start_tor / stop_tor
Tauri commands). This service observes it: checks ports, reads the control
protocol (stem), exposes status and circuit management, and proxies search
through Ahmia via the Tor SOCKS5 port.
"""

from __future__ import annotations

import asyncio
import socket
import time

from .client import make_tor_client
from .models import FetchResult, SearchResult, TorStatus


class TorService:
    def __init__(self, socks_port: int = 9050, control_port: int = 9051) -> None:
        self._socks_port = socks_port
        self._control_port = control_port
        self._circuit_start: float | None = None

    # ---- public API -------------------------------------------------------

    async def status(self) -> TorStatus:
        running = await asyncio.to_thread(_port_open, self._socks_port)
        if not running:
            return TorStatus(running=False)

        pct, circuit = await asyncio.to_thread(self._bootstrap_info)
        if circuit and self._circuit_start is None:
            self._circuit_start = time.time()

        age = int(time.time() - self._circuit_start) if self._circuit_start else 0

        exit_ip: str | None = None
        if circuit:
            try:
                exit_ip = await self._exit_ip()
            except Exception:
                pass

        return TorStatus(
            running=True,
            bootstrapped=pct,
            circuit_established=circuit,
            exit_ip=exit_ip,
            circuit_age_seconds=age,
            socks_port=self._socks_port,
        )

    async def new_circuit(self) -> None:
        """Request a fresh Tor circuit via SIGNAL NEWNYM."""
        await asyncio.to_thread(self._send_newnym, self._control_port)
        self._circuit_start = time.time()

    def reset_circuit_timer(self) -> None:
        """Call when we know a new circuit has been established externally."""
        self._circuit_start = time.time()

    async def search(self, query: str) -> list[SearchResult]:
        """Search Ahmia for .onion results, routed through Tor."""
        safe_q = query.strip().replace(" ", "+")
        url = f"https://ahmia.fi/search/?q={safe_q}"
        try:
            async with make_tor_client(self._socks_port, timeout=20.0) as client:
                resp = await client.get(url)
            return _parse_ahmia(resp.text)
        except Exception:
            return []

    # ---- private helpers --------------------------------------------------

    def _bootstrap_info(self) -> tuple[int, bool]:
        """Return (bootstrap_pct, circuit_established) via the Tor control port.
        Falls back to assuming 100 % if control port is unreachable but SOCKS is up."""
        try:
            import stem.control  # type: ignore[import]

            with stem.control.Controller.from_port(port=self._control_port) as ctrl:
                ctrl.authenticate()
                phase = ctrl.get_info("status/bootstrap-phase", "")
                pct = 0
                for part in phase.split():
                    if part.startswith("PROGRESS="):
                        try:
                            pct = int(part.split("=", 1)[1])
                        except ValueError:
                            pass
                return pct, pct >= 100
        except Exception:
            # Control port unavailable — SOCKS being open means it bootstrapped
            return 100, True

    @staticmethod
    def _send_newnym(control_port: int) -> None:
        try:
            import stem  # type: ignore[import]
            import stem.control  # type: ignore[import]

            with stem.control.Controller.from_port(port=control_port) as ctrl:
                ctrl.authenticate()
                ctrl.signal(stem.Signal.NEWNYM)
        except Exception as exc:
            raise RuntimeError(f"NEWNYM failed: {exc}") from exc

    async def _exit_ip(self) -> str | None:
        try:
            async with make_tor_client(self._socks_port, timeout=10.0) as client:
                resp = await client.get("https://check.torproject.org/api/ip")
                data = resp.json()
                return data.get("IP")
        except Exception:
            return None


# ---- module-level helpers ------------------------------------------------

def _port_open(port: int) -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=0.5)
        s.close()
        return True
    except OSError:
        return False


def _parse_ahmia(html: str) -> list[SearchResult]:
    """Extract search results from Ahmia's HTML response."""
    try:
        from bs4 import BeautifulSoup  # type: ignore[import]

        soup = BeautifulSoup(html, "html.parser")
        results: list[SearchResult] = []
        for item in soup.select(".result")[:10]:
            a = item.find("a")
            desc_el = item.find("p")
            if not a:
                continue
            href: str = a.get("href", "")
            if "redirect_url=" in href:
                href = href.split("redirect_url=", 1)[-1]
            results.append(
                SearchResult(
                    title=a.get_text(strip=True) or href,
                    url=href,
                    description=desc_el.get_text(strip=True) if desc_el else None,
                    is_onion=".onion" in href,
                )
            )
        return results
    except Exception:
        return []
