"""Oracle service — the facade that wires the track-record loop together.

Responsibilities:
  * **capture** a generated report → extract atomic claims → persist (status pending)
  * **grade_due** → for each claim whose checkpoint elapsed, grade it (objective
    for tickers, LLM judge otherwise), embed the resulting lesson, advance status
  * **retrain** the calibrator on the labelled history
  * **stats / list / get / override / hindsight** for the API + UI

Everything off the request path is best-effort: a failed extraction or grade is
swallowed so report generation and the engine never break. Blocking SQLite/embeds
run in a thread via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

from ..market.yahoo import fetch_candles
from .enrichment import (
    build_gap_report,
    build_messages,
    heuristic_suggestions,
    parse_suggestions,
)
from .extract import extract_claims
from .grading import checkpoints
from .hindsight import related
from .judge import judge_claim
from .objective import grade_ticker

# Zero-arg callable returning (provider, model) or None — read live so config
# changes (allow_cloud toggles, model swaps) take effect without a restart.
Route = Callable[[], "tuple[str, str] | None"]
LLM = Callable[..., Awaitable[str]]
EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]


class OracleService:
    def __init__(
        self,
        *,
        store,
        vector=None,
        llm: LLM,
        embed_fn: EmbedFn,
        market=None,
        osint=None,
        calibrator=None,
        extract_route: Route,
        judge_local_route: Route,
        judge_cloud_route: Route | None = None,
        enrich_route: Route | None = None,
        horizons_hours: list[int] | None = None,
        enabled: bool = True,
        escalate: bool = True,
        max_per_run: int = 25,
        enrich_ttl_seconds: int = 1800,
    ) -> None:
        self.store = store
        self.vector = vector
        self.llm = llm
        self.embed_fn = embed_fn
        self.market = market
        self.osint = osint
        self.calibrator = calibrator
        self.extract_route = extract_route
        self.judge_local_route = judge_local_route
        self.judge_cloud_route = judge_cloud_route
        self.enrich_route = enrich_route
        self.horizons_hours = horizons_hours
        self.enabled = enabled
        self.escalate = escalate
        self.max_per_run = max_per_run
        self.enrich_ttl_seconds = enrich_ttl_seconds
        self._enrich_cache: dict | None = None
        self._enrich_at: float | None = None

    # ---- capture --------------------------------------------------------

    async def capture(
        self, *, feature: str, kind: str, title: str, body: str, context: dict | None = None
    ) -> int:
        """Persist a report and its extracted claims. Returns the claim count
        (0 on any failure — never raises into the caller)."""
        if not self.enabled or not (body and body.strip()):
            return 0
        route = self.extract_route()
        if not route:
            return 0
        try:
            report_id = await asyncio.to_thread(
                self.store.add_report, feature=feature, kind=kind, title=title,
                body=body, context=context,
            )
            claims = await extract_claims(
                self.llm, report_text=body, feature=feature,
                provider=route[0], model=route[1],
            )
            if claims:
                await asyncio.to_thread(self.store.add_claims, report_id, feature, claims)
            return len(claims)
        except Exception:
            return 0

    # ---- grading --------------------------------------------------------

    async def grade_due(self, now: int | None = None, max_per_run: int | None = None) -> int:
        """Grade every claim with an elapsed, ungraded checkpoint. Returns the
        number of grades written this run."""
        if not self.enabled:
            return 0
        now = now or int(time.time())
        cps = checkpoints(self.horizons_hours)
        if not cps:
            return 0
        due = await asyncio.to_thread(self.store.claims_due, now, cps)
        if not due:
            return 0
        terminal = cps[-1][0]
        cap = max_per_run or self.max_per_run
        graded = 0
        async with httpx.AsyncClient(timeout=20.0) as client:
            for d in due[:cap]:
                try:
                    grade = await self._grade_one(d, now, client)
                except Exception:
                    grade = None
                if grade is None:
                    continue
                await asyncio.to_thread(
                    self.store.add_grade,
                    claim_id=d["id"], checkpoint=d["checkpoint"],
                    score=grade["score"], outcome=grade["outcome"],
                    confidence=d.get("confidence") or 0.0,
                    failure_tag=grade.get("failure_tag"), reason=grade.get("reason", ""),
                    source=grade.get("source", "llm-local"), evidence=grade.get("evidence"),
                )
                if grade["outcome"] != "too-early":
                    await self._embed_lesson(d, grade, now)
                    if d["checkpoint"] == terminal:
                        await asyncio.to_thread(self.store.set_claim_status, d["id"], "graded")
                graded += 1
        return graded

    async def _grade_one(self, claim: dict, now: int, client: httpx.AsyncClient) -> dict | None:
        # Objective price grading for tickers.
        if claim.get("entityKind") == "ticker" and claim.get("entity"):
            candles = await self._candles(claim["entity"], claim["createdAt"], now, client)
            og = grade_ticker(claim, created_at=claim["createdAt"], candles=candles)
            if og:
                return {**og, "source": "objective"}

        # LLM-as-judge for soft claims.
        local = self.judge_local_route()
        if not local:
            return None
        evidence = await self._evidence(claim, client)
        verdict = await judge_claim(
            self.llm, claim, evidence=evidence, checkpoint=claim["checkpoint"],
            provider=local[0], model=local[1],
        )
        source = "llm-local"
        cloud = self.judge_cloud_route() if (self.escalate and self.judge_cloud_route) else None
        if cloud and verdict["outcome"] != "too-early" and verdict["self_confidence"] < 0.55:
            v2 = await judge_claim(
                self.llm, claim, evidence=evidence, checkpoint=claim["checkpoint"],
                provider=cloud[0], model=cloud[1],
            )
            if v2["outcome"] != "too-early":
                verdict, source = v2, "llm-cloud"
        return {
            "score": verdict["score"],
            "outcome": verdict["outcome"],
            "failure_tag": verdict["failure_tag"],
            "reason": verdict["reason"],
            "evidence": {"text": evidence[:1500], "selfConfidence": verdict["self_confidence"]},
            "source": source,
        }

    async def _candles(self, symbol: str, created_at: int, now: int, client) -> list[dict]:
        span_h = (now - created_at) / 3600
        if span_h <= 48:
            res, days = "60", 7
        else:
            res, days = "D", int(span_h / 24) + 6
        try:
            return await fetch_candles(client, symbol, resolution=res, days=days)
        except Exception:
            return []

    async def _evidence(self, claim: dict, client) -> str:
        parts: list[str] = []
        ek, ent = claim.get("entityKind"), claim.get("entity")
        try:
            if self.osint and ek == "country" and ent:
                arts = await self.osint.get_articles(iso=ent, limit=10)
                parts += [f"- {a.title} ({a.country}, sev{a.severity})" for a in arts[:10]]
            if self.osint and not parts:
                arts = await self.osint.get_articles(limit=10)
                parts += [f"- {a.title}" for a in arts[:8]]
            if self.market and claim.get("feature") == "market":
                news = await self.market.get_news(count=8)
                parts += [f"- {h.get('headline')}" for h in news[:8] if h.get("headline")]
        except Exception:
            pass
        if not parts:
            return "No fresh evidence could be gathered for this claim."
        return "Recent evidence (now):\n" + "\n".join(parts)

    async def _embed_lesson(self, claim: dict, grade: dict, now: int) -> None:
        if self.vector is None:
            return
        body = (
            f"Claim: {claim['claim']}\n"
            f"Outcome: {grade['outcome']} ({grade['score']}/100) at {claim['checkpoint']}. "
            f"{grade.get('reason', '')}"
        )
        try:
            embs = await self.embed_fn([body])
        except Exception:
            embs = []
        if not embs:
            return
        ref = f"oracle:lesson:{claim['id']}:{claim['checkpoint']}"
        meta = {
            "claimId": claim["id"], "claim": claim["claim"], "entity": claim.get("entity"),
            "feature": claim.get("feature"), "outcome": grade["outcome"], "score": grade["score"],
            "checkpoint": claim["checkpoint"], "failureTag": grade.get("failure_tag"),
            "reason": grade.get("reason", ""),
        }
        try:
            await asyncio.to_thread(
                self.vector.upsert,
                [{
                    "kind": "lesson", "ref": ref, "ts": now,
                    "title": claim["claim"][:80], "body": body, "meta": meta,
                    "embedding": embs[0],
                }],
            )
        except Exception:
            pass

    # ---- learning + reads ----------------------------------------------

    def retrain(self) -> dict:
        if not self.calibrator:
            return {"ready": False, "reason": "calibrator disabled"}
        rows = self.store.grades_for_training()
        return self.calibrator.train(rows)

    def stats(self) -> dict:
        s = self.store.stats()
        s["model"] = self.calibrator.metrics() if self.calibrator else {"ready": False}
        s["enabled"] = self.enabled
        s["horizons"] = [lbl for lbl, _ in checkpoints(self.horizons_hours)]
        return s

    # ---- enrichment (what new data would help) -------------------------

    def _source_desc(self) -> dict:
        """Snapshot of the data sources currently feeding predictions/grading."""
        desc: dict = {}
        try:
            if self.osint:
                desc["osint"] = self.osint.sources()
        except Exception:
            pass
        try:
            if self.market:
                desc["market"] = {"watchlist": getattr(self.market, "symbols", None)}
        except Exception:
            pass
        return desc

    async def enrichment(self, *, refresh: bool = False) -> dict:
        """Analyze the track record and suggest data sources that would sharpen
        predictions/grading. Hybrid: a deterministic gap report + Leo's ranked
        suggestions, with a grounded heuristic fallback. Cached on a slow TTL."""
        now = time.monotonic()
        if (
            not refresh
            and self._enrich_cache is not None
            and self._enrich_at is not None
            and (now - self._enrich_at) < self.enrich_ttl_seconds
        ):
            return self._enrich_cache

        stats = self.stats()
        model_metrics = self.calibrator.metrics() if self.calibrator else {"ready": False}
        gap = build_gap_report(stats, model_metrics, self._source_desc())

        suggestions: list[dict] = []
        source = "heuristic"
        route = self.enrich_route() if self.enrich_route else None
        if route:
            try:
                raw = await self.llm(build_messages(gap), provider=route[0], model=route[1])
                suggestions = parse_suggestions(raw)
                if suggestions:
                    source = "llm"
            except Exception:
                suggestions = []
        if not suggestions:
            suggestions = heuristic_suggestions(gap)

        result = {
            "generatedAt": int(time.time()),
            "signals": gap,
            "suggestions": suggestions,
            "modelReady": gap.get("modelReady", False),
            "source": source,
        }
        self._enrich_cache = result
        self._enrich_at = now
        return result

    def list_claims(self, **kw) -> list[dict]:
        return self.store.list_claims(**kw)

    def get_claim(self, claim_id: int) -> dict | None:
        return self.store.get_claim(claim_id)

    def correct(self, claim: dict) -> dict:
        if not self.calibrator:
            return {"ready": False}
        return self.calibrator.correct(claim)

    def override_grade(
        self, claim_id: int, *, score: int, outcome: str,
        failure_tag: str | None = None, reason: str = "",
    ) -> dict | None:
        claim = self.store.get_claim(claim_id)
        if not claim:
            return None
        cps = checkpoints(self.horizons_hours)
        checkpoint = cps[-1][0] if cps else "30d"
        self.store.add_grade(
            claim_id=claim_id, checkpoint=checkpoint, score=score, outcome=outcome,
            confidence=claim.get("confidence") or 0.0, failure_tag=failure_tag,
            reason=reason or "Manual override.", source="user", user_verified=True,
        )
        self.store.set_claim_status(claim_id, "graded")
        return self.store.get_claim(claim_id)

    async def hindsight(
        self, *, feature: str | None = None, entity: str | None = None,
        query: str | None = None, k: int = 6,
    ) -> dict:
        return await related(
            store=self.store, vector=self.vector, embed_fn=self.embed_fn,
            feature=feature, entity=entity, query=query, k=k,
        )
