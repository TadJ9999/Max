"""Naval layer tests — parsing, region weighting, service, endpoint (mocked net)."""

import asyncio

import httpx
from fastapi.testclient import TestClient

import max_engine.main as m
from max_engine.osint.naval import (
    NavalService,
    _twz_date,
    parse_positions,
    strip_html,
)

# Realistic spacing: real USNI posts carry ~300 chars of squadron/air-wing text
# between ships, so the per-ship region windows don't overlap.
_FILLER = (
    " Carrier Air Wing operations continued through the week with squadrons flying "
    "F/A-18E Super Hornets and EA-18G Growlers from their home air stations while "
    "support units performed routine flight-deck cycles, per released Navy photos. "
)

USNI_FEED_XML = f"""<?xml version="1.0"?>
<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item>
  <link>https://news.usni.org/2026/05/26/usni-news-fleet-and-marine-tracker-may-26-2026</link>
  <content:encoded><![CDATA[
    <p>The Abraham Lincoln Carrier Strike Group, USS Abraham Lincoln (CVN-72),
       homeported at Naval Air Station North Island, is operating in the Arabian Sea.</p>
    <p>{_FILLER}</p>
    <p>Aircraft carrier USS George Washington (CVN-73) is underway in the Philippine Sea
       after departing Yokosuka, Japan.</p>
    <p>{_FILLER}</p>
    <p>Carrier USS George H.W. Bush (CVN-77) is in port at Naval Station Norfolk, Va.,
       for maintenance.</p>
    <p>{_FILLER}</p>
    <p>Aircraft carrier USS Nimitz (CVN-68) is underway in the Atlantic Ocean.</p>
  ]]></content:encoded>
</item>
</channel></rss>"""

TWZ_HTML = """<html><body>
  <p>USS Nimitz is operating off the coast of Chile for exercise Southern Seas 2026.</p>
  <p>USS Carl Vinson (CVN-70) is undergoing scheduled maintenance in port.</p>
</body></html>"""


def test_strip_html():
    assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_twz_date():
    assert _twz_date("https://www.twz.com/sea/carrier-tracker-as-of-april-26-2026") == "2026-04-26"
    assert _twz_date("https://www.twz.com/sea/no-date-here") is None


def test_parse_open_water_beats_homeport():
    text = strip_html(USNI_FEED_XML)
    ships = {s.hull: s for s in parse_positions(text, "USNI", "u", "2026-05-26")}
    # Lincoln: "operating in the Arabian Sea" must win over its mentioned homeport.
    assert ships["CVN-72"].region == "Arabian Sea"
    assert ships["CVN-72"].status == "underway"  # homeport mention ≠ in port
    # George Washington: sea beats the departure port.
    assert ships["CVN-73"].region == "Philippine Sea"
    # Bush: genuine in-port + maintenance.
    assert ships["CVN-77"].status == "in port"
    assert "Norfolk" in ships["CVN-77"].region


def test_parse_name_fallback_without_hull():
    # TWZ names Nimitz with no hull token → still located via name alias.
    ships = {s.hull: s for s in parse_positions(strip_html(TWZ_HTML), "TWZ", "t", "2026-04-26")}
    assert "CVN-68" in ships
    assert "Southern Seas" in ships["CVN-68"].region  # AOR/exercise beats bare "Chile"


def _mock_client() -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        if "usni.org" in req.url.host:
            return httpx.Response(200, text=USNI_FEED_XML)
        return httpx.Response(200, text=TWZ_HTML)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_service_merges_and_prefers_usni():
    async def run():
        async with _mock_client() as client:
            svc = NavalService(twz_url="https://twz/x", client=client)
            return await svc.get()

    d = asyncio.run(run())
    hulls = {s["hull"] for s in d["ships"]}
    assert {"CVN-72", "CVN-73", "CVN-77", "CVN-68"} <= hulls
    nimitz = next(s for s in d["ships"] if s["hull"] == "CVN-68")
    assert nimitz["source"] == "USNI Fleet Tracker"  # USNI wins over TWZ for the same hull
    assert nimitz["region"] == "Atlantic Ocean"


def test_naval_endpoint(monkeypatch):
    monkeypatch.setattr(m, "naval", NavalService(twz_url="https://twz/x", client=_mock_client()))
    r = TestClient(m.app).get("/osint/naval")
    assert r.status_code == 200
    body = r.json()
    assert body["ships"] and "updated" in body
    assert all({"name", "hull", "lat", "lon", "region", "status"} <= set(s) for s in body["ships"])
