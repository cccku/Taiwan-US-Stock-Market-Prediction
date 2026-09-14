"""SQLite persistence: quotes, fundamentals, articles, analyses, prediction history, prefs."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

INDUSTRY = "INDUSTRY"  # analysis target for industry-wide articles

SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
    ticker TEXT PRIMARY KEY,
    price REAL, prev_close REAL, currency TEXT,
    market_time INTEGER, updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL, summary TEXT, url TEXT, source TEXT,
    published_at INTEGER NOT NULL, fetched_at INTEGER NOT NULL,
    lang TEXT, provider TEXT
);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at);

-- Which analysis target (a ticker, or INDUSTRY) an article was collected for,
-- and whether/by which engine it has been processed.
CREATE TABLE IF NOT EXISTS article_targets (
    article_id TEXT NOT NULL, target TEXT NOT NULL,
    processed_engine TEXT, processed_at INTEGER,
    PRIMARY KEY (article_id, target)
);
CREATE INDEX IF NOT EXISTS idx_targets_target ON article_targets(target, processed_at);

CREATE TABLE IF NOT EXISTS analyses (
    article_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    target TEXT NOT NULL,                 -- ticker (company news) or INDUSTRY
    direction TEXT NOT NULL,              -- positive | negative | neutral
    impact_pct REAL NOT NULL,             -- signed residual impact on fair value, percent
    confidence REAL NOT NULL,             -- 0..1
    duration TEXT NOT NULL,               -- transient | medium | structural
    severity TEXT NOT NULL,               -- low | moderate | major | critical
    priced_in REAL NOT NULL,              -- 0..1
    category TEXT, pillar TEXT, pillar_delta REAL DEFAULT 0,
    company_decision INTEGER DEFAULT 0,
    market_alignment TEXT, alignment_note TEXT,
    reasoning TEXT,
    engine TEXT NOT NULL, analyzed_at INTEGER NOT NULL,
    PRIMARY KEY (article_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_analyses_ticker ON analyses(ticker);

CREATE TABLE IF NOT EXISTS outlooks (
    ticker TEXT PRIMARY KEY, summary TEXT NOT NULL, engine TEXT, updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL, created_at INTEGER NOT NULL,
    base_price REAL, predicted_price REAL,
    expected_return REAL, news_return REAL, valuation_return REAL,
    signature TEXT, note TEXT, trigger_articles TEXT
);
CREATE INDEX IF NOT EXISTS idx_predictions_ticker ON predictions(ticker, created_at);
CREATE TABLE IF NOT EXISTS prefs (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS refresh_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER NOT NULL, finished_at INTEGER,
    trigger TEXT, status TEXT, stats TEXT, error TEXT
);
"""


def now_ts() -> int:
    return int(time.time())


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock, self.connect() as conn:
            yield conn

    # ── quotes & fundamentals ────────────────────────────────────────────────
    def upsert_quote(self, ticker: str, price: float, prev_close: float | None,
                     currency: str | None, market_time: int | None) -> None:
        with self.write() as c:
            c.execute(
                "INSERT OR REPLACE INTO quotes VALUES (?,?,?,?,?,?)",
                (ticker, price, prev_close, currency, market_time, now_ts()),
            )

    def quotes(self) -> dict[str, dict]:
        with self.connect() as c:
            return {r["ticker"]: dict(r) for r in c.execute("SELECT * FROM quotes")}

    def upsert_fundamentals(self, ticker: str, data: dict) -> None:
        with self.write() as c:
            c.execute("INSERT OR REPLACE INTO fundamentals VALUES (?,?,?)",
                      (ticker, json.dumps(data), now_ts()))

    def fundamentals(self) -> dict[str, dict]:
        with self.connect() as c:
            return {
                r["ticker"]: {**json.loads(r["data"]), "_updated_at": r["updated_at"]}
                for r in c.execute("SELECT * FROM fundamentals")
            }

    # ── articles ─────────────────────────────────────────────────────────────
    def add_article(self, article: dict, target: str) -> bool:
        """Insert article + target link. Returns True if the (article, target) pair is new."""
        with self.write() as c:
            c.execute(
                """INSERT OR IGNORE INTO articles
                   (id, title, summary, url, source, published_at, fetched_at, lang, provider)
                   VALUES (:id, :title, :summary, :url, :source, :published_at, :fetched_at, :lang, :provider)""",
                {**article, "fetched_at": now_ts()},
            )
            cur = c.execute(
                "INSERT OR IGNORE INTO article_targets (article_id, target) VALUES (?, ?)",
                (article["id"], target),
            )
            return cur.rowcount > 0

    def pending_articles(self, target: str, since: int, limit: int,
                         upgrade_from_engine: str | None = None) -> list[dict]:
        """Unprocessed articles for a target, newest first. Optionally also articles
        previously processed by `upgrade_from_engine` (e.g. heuristic -> Claude)."""
        clause = "t.processed_at IS NULL"
        params: list[Any] = [target, since]
        if upgrade_from_engine:
            clause = "(t.processed_at IS NULL OR t.processed_engine = ?)"
            params.insert(1, upgrade_from_engine)
        with self.connect() as c:
            rows = c.execute(
                f"""SELECT a.*, t.processed_engine FROM articles a
                    JOIN article_targets t ON t.article_id = a.id
                    WHERE t.target = ? AND {clause} AND a.published_at >= ?
                    ORDER BY a.published_at DESC LIMIT ?""",
                (*params, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_processed(self, article_ids: list[str], target: str, engine: str) -> None:
        if not article_ids:
            return
        with self.write() as c:
            c.executemany(
                "UPDATE article_targets SET processed_engine=?, processed_at=? WHERE article_id=? AND target=?",
                [(engine, now_ts(), aid, target) for aid in article_ids],
            )

    def skip_backlog(self, target: str, keep_ids: list[str]) -> int:
        """Close out unprocessed articles for a target that weren't selected for analysis."""
        placeholders = ",".join("?" * len(keep_ids)) or "''"
        with self.write() as c:
            return c.execute(
                f"""UPDATE article_targets SET processed_engine='skipped', processed_at=?
                    WHERE target=? AND processed_at IS NULL AND article_id NOT IN ({placeholders})""",
                (now_ts(), target, *keep_ids),
            ).rowcount

    def expire_unprocessed(self, since: int) -> None:
        """Articles that fell out of the lookback window without being analyzed are closed out."""
        with self.write() as c:
            c.execute(
                """UPDATE article_targets SET processed_engine='expired', processed_at=?
                   WHERE processed_at IS NULL AND article_id IN
                   (SELECT id FROM articles WHERE published_at < ?)""",
                (now_ts(), since),
            )

    def count_pending(self, since: int) -> int:
        with self.connect() as c:
            return c.execute(
                """SELECT COUNT(*) FROM article_targets t JOIN articles a ON a.id=t.article_id
                   WHERE t.processed_at IS NULL AND a.published_at >= ?""", (since,)
            ).fetchone()[0]

    # ── analyses ─────────────────────────────────────────────────────────────
    def save_analyses(self, rows: list[dict], replace_target: tuple[list[str], str] | None = None) -> None:
        """Company-level analyses replace earlier rows; industry-level rows never
        overwrite a company-level analysis of the same article."""
        with self.write() as c:
            if replace_target:
                ids, target = replace_target
                c.executemany("DELETE FROM analyses WHERE article_id=? AND target=?",
                              [(aid, target) for aid in ids])
            for r in rows:
                verb = "INSERT OR IGNORE" if r["target"] == INDUSTRY else "INSERT OR REPLACE"
                c.execute(
                    f"""{verb} INTO analyses (article_id, ticker, target, direction, impact_pct, confidence,
                        duration, severity, priced_in, category, pillar, pillar_delta, company_decision,
                        market_alignment, alignment_note, reasoning, engine, analyzed_at)
                        VALUES (:article_id, :ticker, :target, :direction, :impact_pct, :confidence,
                        :duration, :severity, :priced_in, :category, :pillar, :pillar_delta, :company_decision,
                        :market_alignment, :alignment_note, :reasoning, :engine, :analyzed_at)""",
                    {**r, "analyzed_at": now_ts()},
                )

    def analyses(self, since: int, ticker: str | None = None) -> list[dict]:
        sql = """SELECT an.*, a.title, a.summary, a.url, a.source, a.published_at, a.lang
                 FROM analyses an JOIN articles a ON a.id = an.article_id
                 WHERE a.published_at >= ?"""
        params: list[Any] = [since]
        if ticker:
            sql += " AND an.ticker = ?"
            params.append(ticker)
        sql += " ORDER BY a.published_at DESC"
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, params)]

    def set_outlook(self, ticker: str, summary: str, engine: str) -> None:
        with self.write() as c:
            c.execute("INSERT OR REPLACE INTO outlooks VALUES (?,?,?,?)", (ticker, summary, engine, now_ts()))

    def outlooks(self) -> dict[str, dict]:
        with self.connect() as c:
            return {r["ticker"]: dict(r) for r in c.execute("SELECT * FROM outlooks")}

    # ── predictions ──────────────────────────────────────────────────────────
    def last_prediction(self, ticker: str) -> dict | None:
        with self.connect() as c:
            r = c.execute("SELECT * FROM predictions WHERE ticker=? ORDER BY id DESC LIMIT 1", (ticker,)).fetchone()
        return dict(r) if r else None

    def add_prediction(self, row: dict) -> None:
        with self.write() as c:
            c.execute(
                """INSERT INTO predictions (ticker, created_at, base_price, predicted_price, expected_return,
                   news_return, valuation_return, signature, note, trigger_articles)
                   VALUES (:ticker, :created_at, :base_price, :predicted_price, :expected_return,
                   :news_return, :valuation_return, :signature, :note, :trigger_articles)""",
                row,
            )

    def prediction_history(self, ticker: str, since: int = 0) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM predictions WHERE ticker=? AND created_at>=? ORDER BY created_at", (ticker, since))]

    # ── prefs ────────────────────────────────────────────────────────────────
    def get_pref(self, key: str, default: Any = None) -> Any:
        with self.connect() as c:
            r = c.execute("SELECT value FROM prefs WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def set_pref(self, key: str, value: Any) -> None:
        with self.write() as c:
            c.execute("INSERT OR REPLACE INTO prefs VALUES (?,?)", (key, json.dumps(value)))

    # ── refresh runs ─────────────────────────────────────────────────────────
    def start_run(self, trigger: str) -> int:
        with self.write() as c:
            return c.execute("INSERT INTO refresh_runs (started_at, trigger, status) VALUES (?,?, 'running')",
                             (now_ts(), trigger)).lastrowid

    def finish_run(self, run_id: int, status: str, stats: dict, error: str | None = None) -> None:
        with self.write() as c:
            c.execute("UPDATE refresh_runs SET finished_at=?, status=?, stats=?, error=? WHERE id=?",
                      (now_ts(), status, json.dumps(stats), error, run_id))

    def last_run(self) -> dict | None:
        with self.connect() as c:
            r = c.execute("SELECT * FROM refresh_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None
