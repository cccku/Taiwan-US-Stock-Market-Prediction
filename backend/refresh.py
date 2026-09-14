"""Refresh pipeline: prices → fundamentals → news → analysis → prediction history."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .analysis.heuristic import HeuristicAnalyzer
from .analysis.llm import AnalysisFailed, ClaudeAnalyzer, LLMUnavailable, credentials_configured
from .config import AppConfig, Stock, get_config
from .db import INDUSTRY, Database, now_ts
from .providers import NEWS_PROVIDERS
from .providers import prices
from .services import record_predictions

log = logging.getLogger(__name__)

# processed_engine markers
HEURISTIC_RETRY = "heuristic"                 # Claude should retry these when available
HEURISTIC_FINAL = "heuristic:llm-failed"      # Claude refused / couldn't parse — don't retry
UPGRADE_WINDOW_DAYS = 7                       # heuristic results newer than this get re-analyzed by Claude


class RefreshManager:
    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.Lock()
        self._llm: ClaudeAnalyzer | None = None
        self._llm_error: str | None = None
        self.data_version = 0
        self.status = {
            "running": False, "phase": None, "trigger": None,
            "started_at": None, "finished_at": None, "last_status": None,
            "last_error": None, "stats": {}, "warnings": [],
        }
        last = db.last_run()
        if last:
            self.status.update(finished_at=last["finished_at"], last_status=last["status"])

    @property
    def cfg(self) -> AppConfig:
        return get_config()

    # ── public API ───────────────────────────────────────────────────────────
    def trigger(self, reason: str, force: bool = False) -> bool:
        with self._lock:
            if self.status["running"]:
                return False
            started = self.status["started_at"]
            if not force and started and time.time() - started < self.cfg.settings.refresh.min_gap_seconds:
                return False
            self.status.update(running=True, phase="starting", trigger=reason, started_at=now_ts(),
                               last_error=None, warnings=[], stats={})
        threading.Thread(target=self._run, args=(reason,), name="refresh", daemon=True).start()
        return True

    def snapshot(self) -> dict:
        cfg = self.cfg
        since = now_ts() - cfg.settings.news.lookback_days * 86400
        return {
            **self.status,
            "data_version": self.data_version,
            "interval_seconds": cfg.settings.refresh.interval_seconds,
            "pending_articles": self.db.count_pending(since),
            "analysis": self.analysis_status(),
        }

    def analysis_status(self) -> dict:
        a = self.cfg.settings.analysis
        llm = self._get_llm()
        return {
            "mode": a.engine,
            "active_engine": "claude" if llm else "heuristic",
            "model": a.model if llm else None,
            "effort": a.effort,
            "credentials_configured": credentials_configured(),
            "llm_error": self._llm_error,
            "usage": dict(llm.usage) if llm else None,
        }

    # ── pipeline ─────────────────────────────────────────────────────────────
    def _run(self, reason: str) -> None:
        run_id = self.db.start_run(reason)
        stats: dict = {}
        status, error = "ok", None
        try:
            self._phase("prices")
            self._refresh_quotes(stats)
            self._phase("fundamentals")
            self._refresh_fundamentals(stats)
            self._phase("news")
            self._collect_news(stats)
            self._phase("analysis")
            self._analyze(stats)
            self._phase("predictions")
            stats["prediction_updates"] = record_predictions(self.db, self.cfg, now_ts())
            self._bump()
        except Exception as e:  # keep the app alive; surface the error in the UI
            log.exception("Refresh failed")
            status, error = "error", str(e)
        finally:
            self.db.finish_run(run_id, status, stats, error)
            with self._lock:
                self.status.update(running=False, phase=None, finished_at=now_ts(),
                                   last_status=status, last_error=error, stats=stats)
            log.info("Refresh (%s) finished: %s %s", reason, status, stats)

    def _phase(self, name: str) -> None:
        self.status["phase"] = name

    def _bump(self) -> None:
        self.data_version += 1

    def _warn(self, message: str) -> None:
        if message not in self.status["warnings"]:
            self.status["warnings"].append(message)

    def _refresh_quotes(self, stats: dict) -> None:
        ok = failed = 0
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(prices.fetch_quote, s.ticker): s for s in self.cfg.stocks}
            for fut in as_completed(futures):
                stock = futures[fut]
                try:
                    q = fut.result()
                except Exception as e:
                    log.warning("Quote for %s failed: %s", stock.ticker, e)
                    q = None
                if q:
                    self.db.upsert_quote(stock.ticker, q["price"], q["prev_close"], q["currency"], q["market_time"])
                    ok += 1
                else:
                    failed += 1
        stats["quotes"] = {"ok": ok, "failed": failed}
        if failed:
            self._warn(f"Price data unavailable for {failed} stock(s); showing last known prices.")
        self._bump()

    def _refresh_fundamentals(self, stats: dict) -> None:
        ttl = self.cfg.settings.refresh.fundamentals_ttl_hours * 3600
        existing = self.db.fundamentals()
        stale = [s for s in self.cfg.stocks
                 if time.time() - existing.get(s.ticker, {}).get("_updated_at", 0) > ttl]
        updated = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            for stock, data in zip(stale, pool.map(lambda s: prices.fetch_fundamentals(s.ticker), stale)):
                if data:
                    self.db.upsert_fundamentals(stock.ticker, data)
                    updated += 1
        stats["fundamentals_updated"] = updated
        if updated:
            self._bump()

    def _collect_news(self, stats: dict) -> None:
        cfg = self.cfg
        ns = cfg.settings.news
        since = now_ts() - ns.lookback_days * 86400
        providers = [NEWS_PROVIDERS[name](ns) for name in ns.providers if name in NEWS_PROVIDERS]

        tasks = []
        for p in providers:
            tasks += [(p.fetch_for_stock, s, s.ticker) for s in cfg.stocks]
            tasks += [(p.fetch_industry, q, INDUSTRY) for q in cfg.industry.queries]

        new = fetched = 0
        with ThreadPoolExecutor(max_workers=ns.max_workers) as pool:
            futures = {pool.submit(fn, arg, since): target for fn, arg, target in tasks}
            for fut in as_completed(futures):
                target = futures[fut]
                try:
                    articles = fut.result()
                except Exception as e:
                    log.warning("News fetch for %s failed: %s", target, e)
                    continue
                for article in articles:
                    fetched += 1
                    new += self.db.add_article(article.as_row(), target)
        stats["news"] = {"fetched": fetched, "new": new}
        if fetched == 0:
            self._warn("No news could be fetched — check the internet connection.")

    # ── analysis ─────────────────────────────────────────────────────────────
    def _get_llm(self) -> ClaudeAnalyzer | None:
        mode = self.cfg.settings.analysis.engine
        if mode == "heuristic" or self._llm_error or not credentials_configured():
            return None
        if self._llm is None:
            try:
                self._llm = ClaudeAnalyzer(self.cfg)
            except Exception as e:
                self._llm_error = f"Could not initialise Claude client: {e}"
                return None
        return self._llm

    def _analyze(self, stats: dict) -> None:
        cfg = self.cfg
        a_settings, ns = cfg.settings.analysis, cfg.settings.news
        now = now_ts()
        since = now - ns.lookback_days * 86400
        self.db.expire_unprocessed(since)

        llm = self._get_llm()
        if llm is None and a_settings.engine == "llm":
            self._warn("Analysis engine is set to 'llm' but Claude is unavailable; new articles are waiting.")
            stats["analysis"] = {"skipped": True}
            return
        heuristic = HeuristicAnalyzer(cfg)
        upgrade = HEURISTIC_RETRY if llm else None
        upgrade_since = max(since, now - UPGRADE_WINDOW_DAYS * 86400)

        jobs: list[tuple[Stock | None, list[dict]]] = []
        skipped = 0
        size = max(1, a_settings.batch_size)
        targets = [(s, s.ticker, ns.max_new_articles_per_stock) for s in cfg.stocks]
        targets.append((None, INDUSTRY, ns.max_new_industry_articles))
        for stock, target, limit in targets:
            selected = self.db.pending_articles(target, since, limit)
            if upgrade and len(selected) < limit:
                retry = self.db.pending_articles(target, upgrade_since, limit, upgrade_from_engine=upgrade)
                selected += [a for a in retry if a["processed_engine"] == upgrade][: limit - len(selected)]
            # Only the newest articles are analyzed; the older unanalyzed backlog (e.g. the
            # first 30-day fetch) is closed out so refreshes don't keep spending on stale news.
            skipped += self.db.skip_backlog(target, [a["id"] for a in selected])
            jobs += [(stock, selected[i:i + size]) for i in range(0, len(selected), size)]

        counters = {"batches": len(jobs), "articles": sum(len(b) for _, b in jobs), "skipped_backlog": skipped,
                    "claude": 0, "heuristic": 0, "errors": 0}
        with ThreadPoolExecutor(max_workers=max(1, a_settings.max_workers if llm else 1)) as pool:
            for fut in as_completed([pool.submit(self._analyze_batch, s, b, llm, heuristic, now) for s, b in jobs]):
                engine_used, had_error = fut.result()
                counters["claude" if engine_used == "claude" else "heuristic"] += 1
                counters["errors"] += had_error
                self._bump()  # let the UI pick up results as batches land
        stats["analysis"] = counters

    def _analyze_batch(self, stock: Stock | None, batch: list[dict], llm: ClaudeAnalyzer | None,
                       heuristic: HeuristicAnalyzer, now: int) -> tuple[str, bool]:
        target = stock.ticker if stock else INDUSTRY
        marker, had_error = HEURISTIC_RETRY, False
        result = None
        if llm and not self._llm_error:
            try:
                ctx = self._stock_context(stock, batch, now) if stock else {"known_events": self._known_events(None, now)}
                result = (llm.analyze_stock(stock, batch, now=now, **ctx) if stock
                          else llm.analyze_industry(batch, now=now, **ctx))
            except LLMUnavailable as e:
                self._llm_error = str(e)
                self._warn(f"Claude disabled for this session: {e}. Using keyword heuristic.")
                had_error = True
            except AnalysisFailed as e:
                log.warning("Claude analysis failed for %s: %s", target, e)
                self._warn(f"Some articles fell back to the keyword heuristic ({e}).")
                if "declined" in str(e) or "structured output" in str(e) or "Bad request" in str(e):
                    marker = HEURISTIC_FINAL
                had_error = True
            except Exception as e:
                log.exception("Unexpected analysis error for %s", target)
                self._warn(f"Unexpected analysis error: {e}")
                had_error = True

        if result is None:
            if self.cfg.settings.analysis.engine == "llm":
                return "none", had_error  # leave pending for the next refresh
            result = heuristic.analyze_stock(stock, batch) if stock else heuristic.analyze_industry(batch)
            result.engine = marker

        self.db.save_analyses(result.rows, replace_target=(result.processed_ids, target))
        self.db.mark_processed(result.processed_ids, target, result.engine)
        if stock and result.outlook:
            existing = self.db.outlooks().get(stock.ticker)
            if result.engine not in (HEURISTIC_RETRY, HEURISTIC_FINAL) or not existing \
                    or existing["engine"] in (HEURISTIC_RETRY, HEURISTIC_FINAL):
                self.db.set_outlook(stock.ticker, result.outlook, result.engine)
        return ("claude" if result.engine not in (HEURISTIC_RETRY, HEURISTIC_FINAL) else "heuristic"), had_error

    def _known_events(self, ticker: str | None, now: int) -> list[dict]:
        since = now - self.cfg.settings.news.lookback_days * 86400
        rows = self.db.analyses(since, ticker)
        if ticker is None:
            seen, unique = set(), []
            for r in rows:
                if r["target"] == INDUSTRY and r["article_id"] not in seen:
                    seen.add(r["article_id"])
                    unique.append(r)
            return unique
        return rows

    def _stock_context(self, stock: Stock, batch: list[dict], now: int) -> dict:
        quote = self.db.quotes().get(stock.ticker)
        fundamentals = self.db.fundamentals().get(stock.ticker, {})
        price = quote["price"] if quote else None
        returns = {"1d": (price / quote["prev_close"] - 1) if price and quote.get("prev_close") else None, "1m": None}
        moves: dict[str, float | None] = {}
        try:
            month = prices.fetch_history(stock.ticker, "1M")
            if price and month:
                returns["1m"] = price / month[0]["c"] - 1
            for a in batch:
                base = prices.close_on_or_before(stock.ticker, a["published_at"])
                moves[a["id"]] = (price / base - 1) if price and base else None
        except Exception as e:
            log.warning("Price context for %s unavailable: %s", stock.ticker, e)
        return {
            "quote": quote, "fundamentals": fundamentals, "returns": returns,
            "known_events": self._known_events(stock.ticker, now), "price_moves": moves,
        }
