"""OSINT tests — gazetteer, GDELT/RSS parsing, scoring, service, endpoints.

Network is fully mocked via httpx.MockTransport; no real GDELT/RSS calls.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

import max_engine.main as m
from max_engine.osint.gazetteer import find_iso_in_text, iso_for_name
from max_engine.osint.gdelt import fetch_gdelt
from max_engine.osint.models import Article
from max_engine.osint.rss import fetch_rss, parse_feed
from max_engine.osint.score import score_countries
from max_engine.osint.service import OsintService
from max_engine.osint.severity import CRITICAL, HIGH, LOW, MEDIUM, classify

NOW = datetime.now(timezone.utc)

GDELT_JSON = {
    "articles": [
        {
            "url": "https://reuters.com/a",
            "title": "Ukraine front-line update",
            "domain": "reuters.com",
            "sourcecountry": "Ukraine",
            "seendate": "20260530T120000Z",
            "socialimage": "https://img/1.jpg",
        },
        {
            "url": "https://apnews.com/b",
            "title": "US markets rally",
            "domain": "apnews.com",
            "sourcecountry": "United States",
            "seendate": "20260530T110000Z",
        },
        {"url": "", "title": "dropped — no url", "domain": "x.com"},  # skipped
    ]
}

RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Flooding in Pakistan displaces thousands</title>
    <link>https://bbc.co.uk/news/p</link>
    <description>Heavy rains near Islamabad</description>
    <pubDate>Sat, 30 May 2026 10:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Reuters duplicate of Ukraine</title>
    <link>https://reuters.com/a?utm=feed</link>
    <description>Ukraine</description>
    <pubDate>Sat, 30 May 2026 12:00:00 GMT</pubDate>
  </item>
</channel></rss>"""

ATOM_XML = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Germany coalition talks resume</title>
    <link href="https://dw.com/g"/>
    <summary>Berlin negotiations</summary>
    <updated>2026-05-30T09:00:00Z</updated>
  </entry>
</feed>"""


# ---- gazetteer ----------------------------------------------------------


def test_iso_for_name_and_demonym():
    assert iso_for_name("Ukraine") == "UKR"
    assert iso_for_name("United States") == "USA"
    assert iso_for_name("nowhere-land") is None


def test_find_iso_in_text_word_boundary():
    assert find_iso_in_text("Ukrainian forces near Kyiv") == "UKR"
    # longest-alias-first: "south korea" wins over bare "korea"
    assert find_iso_in_text("South Korea summit") == "KOR"
    # the dropped bare "us" alias must not match the pronoun
    assert find_iso_in_text("Let us all go home") is None


# ---- parsing ------------------------------------------------------------


def test_parse_feed_rss_and_atom():
    rss = parse_feed(RSS_XML)
    assert rss[0].iso == "PAK"
    assert rss[0].domain == "bbc.co.uk"
    assert parse_feed(ATOM_XML)[0].iso == "DEU"


def test_parse_feed_bad_xml_is_empty():
    assert parse_feed("<not xml") == []


def test_fetch_gdelt_maps_articles():
    def handler(req: httpx.Request) -> httpx.Response:
        assert "gdeltproject.org" in req.url.host
        return httpx.Response(200, json=GDELT_JSON)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await fetch_gdelt(c)

    arts = asyncio.run(run())
    assert {a.iso for a in arts} == {"UKR", "USA"}  # the url-less row is dropped
    assert arts[0].image == "https://img/1.jpg"


def test_fetch_gdelt_handles_non_json():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="rate limited")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await fetch_gdelt(c)

    assert asyncio.run(run()) == []


def test_fetch_rss_swallows_dead_feeds():
    def handler(req: httpx.Request) -> httpx.Response:
        if "bad" in req.url.host:
            return httpx.Response(500)
        return httpx.Response(200, text=RSS_XML)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await fetch_rss(c, ["https://good/feed", "https://bad/feed"])

    arts = asyncio.run(run())
    assert any(a.iso == "PAK" for a in arts)  # good feed survived


# ---- severity -----------------------------------------------------------


def test_classify_tiers():
    assert classify("Missile strike kills dozens in border town") == CRITICAL
    assert classify("Mass protest and clashes erupt in capital") == HIGH
    assert classify("Parliament holds election amid trade dispute") == MEDIUM
    assert classify("Local museum unveils new art exhibit") == LOW
    assert classify("") == LOW


def test_classify_word_boundaries_no_substring_false_positives():
    # "war" must not fire inside these — the bug that lit up the whole map.
    assert classify("Star Wars editor Marcia Lucas dies aged 80") == LOW
    assert classify("Green leaders warn party to act on inequality") == LOW
    assert classify("Animal welfare violations swarm Miami zoo") == LOW
    # but stems still catch their family
    assert classify("Insurgency spreads across the region") == CRITICAL
    assert classify("Thousands evacuated as floods hit the valley") == HIGH


def test_country_severity_is_weighted_mean_not_peak():
    arts = [
        # SYR: a single critical story dominates its (small) mean
        Article("c", "u3", "d3.com", "gdelt", iso="SYR", published=NOW, severity=CRITICAL),
        # USA: balanced low + medium → medium
        Article("a", "u1", "d1.com", "gdelt", iso="USA", published=NOW, severity=LOW),
        Article("b", "u2", "d2.com", "gdelt", iso="USA", published=NOW, severity=MEDIUM),
        # AUS: one critical headline drowned by routine volume → must NOT be Critical
        *[Article("l", f"a{i}", "d.com", "gdelt", iso="AUS", published=NOW, severity=LOW)
          for i in range(4)],
        Article("k", "ax", "d.com", "gdelt", iso="AUS", published=NOW, severity=CRITICAL),
    ]
    stats = score_countries(arts, NOW)
    by = {s.iso: s.severity for s in stats}
    assert by["SYR"] == CRITICAL
    assert by["USA"] == MEDIUM
    assert by["AUS"] < CRITICAL  # 3/5 = 0.6 mean → Medium, not Critical
    assert stats[0].iso == "SYR"  # most-critical sorts first


def test_service_assigns_severity_from_titles():
    async def run():
        async with _mock_client() as client:
            svc = OsintService(feeds=["https://x/feed"], client=client)
            return await svc.get_articles()

    arts = asyncio.run(run())
    pak = next(a for a in arts if a.iso == "PAK")  # "Flooding in Pakistan..."
    assert pak.severity == HIGH


# ---- scoring ------------------------------------------------------------


def test_score_diversity_and_normalization():
    arts = [
        Article("a", "u1", "reuters.com", "gdelt", iso="UKR", published=NOW),
        Article("b", "u2", "bbc.com", "rss", iso="UKR", published=NOW),
        Article("c", "u3", "ap.com", "gdelt", iso="USA", published=NOW),
    ]
    stats = score_countries(arts, NOW)
    top = stats[0]
    assert top.iso == "UKR" and top.intensity == 1.0  # busiest => normalized to 1
    assert top.sources == 2
    assert stats[1].iso == "USA" and stats[1].intensity < 1.0


def test_score_recency_decay():
    fresh = [Article("a", "u1", "d.com", "gdelt", iso="UKR", published=NOW)]
    old = [Article("a", "u1", "d.com", "gdelt", iso="UKR", published=NOW - timedelta(hours=48))]
    # absolute weights differ even though both normalize to 1.0 alone — assert via
    # a mixed batch: the fresher country outranks the stale one.
    mixed = [
        Article("a", "u1", "d.com", "gdelt", iso="UKR", published=NOW),
        Article("b", "u2", "d.com", "gdelt", iso="USA", published=NOW - timedelta(hours=48)),
    ]
    stats = {s.iso: s.intensity for s in score_countries(mixed, NOW)}
    assert stats["UKR"] > stats["USA"]
    assert score_countries(fresh, NOW)[0].intensity == 1.0
    assert score_countries(old, NOW)[0].intensity == 1.0


# ---- service ------------------------------------------------------------


def _mock_client() -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        if "gdeltproject.org" in req.url.host:
            return httpx.Response(200, json=GDELT_JSON)
        return httpx.Response(200, text=RSS_XML)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_service_dedupes_across_sources():
    async def run():
        async with _mock_client() as client:
            svc = OsintService(feeds=["https://x/feed"], client=client)
            hm = await svc.get_heatmap()
            arts = await svc.get_articles()
            return hm, arts

    hm, arts = asyncio.run(run())
    # GDELT reuters.com/a and RSS reuters.com/a?utm=feed collapse to one.
    reuters = [a for a in arts if a.url.split("?")[0] == "https://reuters.com/a"]
    assert len(reuters) == 1
    assert hm.total_articles == len(arts)
    assert any(c.iso == "UKR" for c in hm.countries)


def test_service_caches_within_ttl():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if "gdeltproject.org" in req.url.host:
            return httpx.Response(200, json=GDELT_JSON)
        return httpx.Response(200, text=RSS_XML)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            svc = OsintService(feeds=["https://x/feed"], client=client, ttl_seconds=600)
            await svc.get_heatmap()
            await svc.get_heatmap()  # second call should hit cache, not the network

    asyncio.run(run())
    assert calls["n"] == 2  # one GDELT + one feed, fetched exactly once


def test_get_articles_filters_by_country():
    async def run():
        async with _mock_client() as client:
            svc = OsintService(feeds=["https://x/feed"], client=client)
            return await svc.get_articles(iso="pak")

    arts = asyncio.run(run())
    assert arts and all(a.iso == "PAK" for a in arts)


def test_get_domains_counts_distinct_sources():
    async def run():
        async with _mock_client() as client:
            svc = OsintService(feeds=["https://x/feed"], client=client)
            return await svc.get_domains()

    domains = asyncio.run(run())
    by = {d["domain"]: d for d in domains}
    # reuters.com appears in both sources but dedupes to one article.
    assert "reuters.com" in by and "bbc.co.uk" in by
    assert all(d["count"] >= 1 for d in domains)
    # sorted by count desc — counts are monotonically non-increasing.
    counts = [d["count"] for d in domains]
    assert counts == sorted(counts, reverse=True)


def test_get_heatmap_and_articles_filter_by_domain():
    async def run():
        async with _mock_client() as client:
            svc = OsintService(feeds=["https://x/feed"], client=client)
            await svc.get_heatmap()  # prime cache
            only_bbc_hm = await svc.get_heatmap(domains={"bbc.co.uk"})
            only_bbc_arts = await svc.get_articles(domains={"bbc.co.uk"})
            return only_bbc_hm, only_bbc_arts

    hm, arts = asyncio.run(run())
    # bbc.co.uk carried the Pakistan flooding story → PAK present, UKR/USA gone.
    assert all(a.domain == "bbc.co.uk" for a in arts)
    isos = {c.iso for c in hm.countries}
    assert "PAK" in isos and "USA" not in isos


def test_get_timeline_frames_are_cumulative():
    async def run():
        async with _mock_client() as client:
            svc = OsintService(feeds=["https://x/feed"], client=client)
            return await svc.get_timeline(frames=6, window_hours=24)

    tl = asyncio.run(run())
    assert len(tl["frames"]) == 6
    totals = [f["totalArticles"] for f in tl["frames"]]
    # cumulative replay: article count never decreases as time advances.
    assert totals == sorted(totals)
    assert all("countries" in f and "at" in f for f in tl["frames"])


def test_get_timeline_clamps_frame_count():
    async def run():
        async with _mock_client() as client:
            svc = OsintService(feeds=["https://x/feed"], client=client)
            return await svc.get_timeline(frames=999), await svc.get_timeline(frames=1)

    big, small = asyncio.run(run())
    assert len(big["frames"]) == 48  # clamped high
    assert len(small["frames"]) == 2  # clamped low


# ---- endpoints ----------------------------------------------------------


def test_osint_endpoints(monkeypatch):
    monkeypatch.setattr(m, "osint", OsintService(feeds=["https://x/feed"], client=_mock_client()))
    c = TestClient(m.app)

    hm = c.get("/osint/heatmap")
    assert hm.status_code == 200
    body = hm.json()
    assert "updated" in body and isinstance(body["countries"], list)

    arts = c.get("/osint/articles", params={"country": "UKR"})
    assert arts.status_code == 200
    assert arts.json()["country"] == "UKR"

    src = c.get("/osint/sources")
    assert src.status_code == 200
    assert "feeds" in src.json()

    dom = c.get("/osint/domains")
    assert dom.status_code == 200
    assert isinstance(dom.json()["domains"], list)

    # domain filter narrows the heatmap
    filt = c.get("/osint/heatmap", params={"domains": "bbc.co.uk"})
    assert filt.status_code == 200
    isos = {cc["iso"] for cc in filt.json()["countries"]}
    assert "USA" not in isos

    tl = c.get("/osint/timeline", params={"frames": 5})
    assert tl.status_code == 200
    assert len(tl.json()["frames"]) == 5
