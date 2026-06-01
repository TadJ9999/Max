"""Proxy-browser HTML fetcher: downloads a URL through Tor and rewrites links
so every click stays inside the proxy renderer instead of leaking outside."""

from __future__ import annotations

import time
from urllib.parse import quote as _url_quote, urljoin, urlparse

from .client import make_tor_client
from .models import FetchResult

_DARK_STYLE = (
    "<style>"
    "body{background:#0a0a0f!important;color:#c8d8e8!important;"
    "font-family:monospace,sans-serif!important;margin:0;padding:8px}"
    "a{color:#22d3ee!important;word-break:break-all}"
    "img{max-width:100%;height:auto}"
    "pre,code{background:#111;padding:4px;border-radius:3px;overflow-x:auto}"
    "table{border-collapse:collapse;width:100%}"
    "td,th{border:1px solid #333;padding:4px}"
    "</style>"
)


async def fetch_url(url: str, socks_port: int = 9050, engine_base: str = "http://127.0.0.1:8001") -> FetchResult:
    """Fetch *url* through the Tor SOCKS5 proxy and return sanitised HTML."""
    is_onion = ".onion" in url
    t0 = time.time()

    async with make_tor_client(socks_port, timeout=30.0) as client:
        resp = await client.get(url)

    fetch_ms = int((time.time() - t0) * 1000)
    content_type = resp.headers.get("content-type", "text/html")

    if "html" not in content_type:
        raw = resp.content.decode("utf-8", errors="replace")
        return FetchResult(
            url=url,
            html=f'<pre style="color:#c8d8e8;background:#0a0a0f;padding:8px">{raw}</pre>',
            status_code=resp.status_code,
            is_onion=is_onion,
            fetch_time_ms=fetch_ms,
        )

    from bs4 import BeautifulSoup

    html_str = resp.content.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html_str, "html.parser")

    title: str | None = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Rewrite all anchor hrefs so navigation stays inside the proxy renderer
    for tag in soup.find_all("a", href=True):
        href: str = tag["href"]
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        absolute = urljoin(url, href)
        tag["href"] = f"?url={absolute}"
        tag["target"] = "_self"

    # Proxy images and stylesheets through the engine so the browser can load them
    _res_base = f"{engine_base}/dark/resource?url="
    for tag in soup.find_all("img"):
        src = tag.get("src", "")
        if src and not src.startswith("data:"):
            tag["src"] = _res_base + _url_quote(urljoin(url, src), safe="")
        # Handle srcset too
        if tag.get("srcset"):
            tag["srcset"] = ""
    for tag in soup.find_all("link"):
        rel = tag.get("rel") or []
        if "stylesheet" in rel and tag.get("href"):
            tag["href"] = _res_base + _url_quote(urljoin(url, tag["href"]), safe="")

    # Remove scripts (security) and inline style conflicts
    for script in soup.find_all("script"):
        script.decompose()

    # Disable form submissions (dark web forms may be unsafe)
    for form in soup.find_all("form"):
        form["action"] = "#"
        form["onsubmit"] = "return false"

    # Inject dark theme override after any existing styles
    if soup.head:
        soup.head.append(BeautifulSoup(_DARK_STYLE, "html.parser"))
    else:
        head = soup.new_tag("head")
        head.append(BeautifulSoup(_DARK_STYLE, "html.parser"))
        if soup.html:
            soup.html.insert(0, head)

    return FetchResult(
        url=url,
        title=title,
        html=str(soup),
        status_code=resp.status_code,
        is_onion=is_onion,
        fetch_time_ms=fetch_ms,
    )
