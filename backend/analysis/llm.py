"""Claude-powered news analysis using structured outputs."""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import anthropic

from ..config import AnalysisSettings, AppConfig, Stock
from ..db import INDUSTRY
from .prompts import build_system_prompt, industry_user_prompt, stock_user_prompt
from .schemas import BatchResult, IndustryAnalysis, StockAnalysis, make_row

log = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """Credentials missing or rejected — switch to the heuristic for this session."""


class AnalysisFailed(Exception):
    """A single request failed (refusal, truncation, transient error)."""


def credentials_configured() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_PROFILE"):
        return True
    return (Path.home() / ".config" / "anthropic").is_dir()  # `ant auth login` profile


class ClaudeAnalyzer:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.settings: AnalysisSettings = cfg.settings.analysis
        self.engine = self.settings.model
        self.system_prompt = build_system_prompt(cfg)
        self.client = anthropic.Anthropic(timeout=self.settings.request_timeout_seconds, max_retries=3)
        self._usage_lock = threading.Lock()
        self.usage = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}

    def _parse(self, user_prompt: str, schema: type):
        kwargs = dict(
            model=self.settings.model,
            max_tokens=16000,
            system=[{"type": "text", "text": self.system_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_prompt}],
            thinking={"type": "adaptive"},
            output_config={"effort": self.settings.effort},
            output_format=schema,
        )
        try:
            if self.settings.use_fallbacks:
                # If a safety classifier declines, the API re-runs the request on Anthropic's
                # recommended fallback model instead of returning a refusal.
                response = self.client.beta.messages.parse(
                    **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            else:
                response = self.client.messages.parse(**kwargs)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise LLMUnavailable(f"Claude API rejected credentials: {e.message}") from e
        except anthropic.NotFoundError as e:
            raise LLMUnavailable(f"Model '{self.settings.model}' not available: {e.message}") from e
        except anthropic.BadRequestError as e:
            raise AnalysisFailed(f"Bad request: {e.message}") from e
        except anthropic.RateLimitError as e:
            raise AnalysisFailed("Rate limited by Claude API") from e
        except anthropic.APIStatusError as e:
            raise AnalysisFailed(f"Claude API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise AnalysisFailed("Could not reach Claude API") from e

        u = response.usage
        with self._usage_lock:
            self.usage["requests"] += 1
            self.usage["input_tokens"] += u.input_tokens or 0
            self.usage["output_tokens"] += u.output_tokens or 0
            self.usage["cache_read_input_tokens"] += getattr(u, "cache_read_input_tokens", 0) or 0

        if response.stop_reason == "refusal":
            raise AnalysisFailed("Claude declined to analyze this batch")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise AnalysisFailed(f"No structured output (stop_reason={response.stop_reason})")
        return response.parsed_output

    def analyze_stock(self, stock: Stock, articles: list[dict], *, quote: dict | None, fundamentals: dict,
                      returns: dict, known_events: list[dict], price_moves: dict, now: int) -> BatchResult:
        prompt = stock_user_prompt(stock, self.cfg.segment(stock).label, quote, fundamentals, returns,
                                   known_events, articles, price_moves, now)
        parsed: StockAnalysis = self._parse(prompt, StockAnalysis)
        valid_ids = {a["id"] for a in articles}
        result = BatchResult(processed_ids=list(valid_ids), outlook=parsed.outlook_summary.strip() or None,
                             engine=self.engine)
        for item in parsed.assessments:
            if item.article_id not in valid_ids or not item.relevant or item.duplicate_of_known_event:
                continue
            result.rows.append(make_row(
                article_id=item.article_id, ticker=stock.ticker, target=stock.ticker,
                impact_pct=item.impact_percent, confidence=item.confidence, priced_in=item.already_priced_in,
                duration=item.duration, severity=item.severity, category=item.category, pillar=item.pillar,
                pillar_delta=item.pillar_delta, company_decision=item.company_decision,
                market_alignment=item.market_alignment if item.company_decision else "not_applicable",
                alignment_note=item.alignment_assessment if item.company_decision else "",
                reasoning=item.reasoning, engine=self.engine,
            ))
        return result

    def analyze_industry(self, articles: list[dict], *, known_events: list[dict], now: int) -> BatchResult:
        parsed: IndustryAnalysis = self._parse(industry_user_prompt(known_events, articles, now), IndustryAnalysis)
        valid_ids = {a["id"] for a in articles}
        tickers = {s.ticker for s in self.cfg.stocks}
        result = BatchResult(processed_ids=list(valid_ids), engine=self.engine)
        for item in parsed.assessments:
            if item.article_id not in valid_ids or not item.relevant or item.duplicate_of_known_event:
                continue
            for hit in item.affected:
                if hit.ticker not in tickers:
                    continue
                result.rows.append(make_row(
                    article_id=item.article_id, ticker=hit.ticker, target=INDUSTRY,
                    impact_pct=hit.impact_percent, confidence=hit.confidence, priced_in=hit.already_priced_in,
                    duration=hit.duration, severity=item.severity, category=item.category,
                    pillar="demand_supply", reasoning=hit.reasoning, engine=self.engine,
                ))
        return result
