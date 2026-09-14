# AI Stock Radar

A local Linux app that tracks **10 Taiwan AI-hardware suppliers** and **10 US niche AI-software companies**. It shows today's price next to a **predicted price**, and every change to that prediction traces back to a real news item.

> Predicted prices are model estimates built from public news and market data. They are not investment advice.

## Quick start

```bash
./run.sh
```

The first run creates `.venv` and installs dependencies (it works even without Ubuntu's `python3-venv` package). The script then starts a local server on `http://127.0.0.1:8765` and opens the app in a chromeless Chrome/Chromium window, or your default browser if neither is installed.

**Enable Claude analysis (recommended).** Copy `config/.env.example` to `config/.env` and set `ANTHROPIC_API_KEY`. Without a key, the app falls back to a clearly labeled, low-confidence keyword heuristic. Articles scored that way are re-analyzed by Claude once a key is present.

**App launcher.** `./scripts/install-desktop-entry.sh` adds "AI Stock Radar" to the Ubuntu app grid.

**Tests.** Run `.venv/bin/python -m pytest`. They run offline.

## Pages

| Page | What it shows |
|---|---|
| **Dashboard** | Every stock with its current price (colored by today's move) and predicted price (separate color scheme). Filters at top right: market, industry, price move/outlook, sort. ★ favorites pin to the top, and you can drag them to reorder. A critical-news banner appears when something serious happens. |
| **Stock details** | Current and predicted price, a simple chart (price, past predictions, dashed projection), why the prediction is what it is, the three pillars, demand & supply position, key numbers, and every analyzed news item in a colored frame: **green = raises**, **red = lowers**, **grey = ≈ no change**. Also a log of every news-driven prediction change. |
| **News Hub** | All analyzed news ranked by impact score, with per-company impact chips. |
| **Supply Chain** | Who supplies whom across the watchlist, from EDA and materials through chips, servers and cloud to AI software and end demand. |
| **Method & Settings** | Engine status and token usage, the color legend (includes a "red = up" Taiwan-style toggle), the full methodology, and how to add stocks. |

The app refreshes when opened, then every 5 minutes while open (`config/settings.yaml`).

## How a prediction is made

1. **Collect real news.** Each refresh runs Google News RSS searches in English and Traditional Chinese, pulls Yahoo Finance ticker news, and runs industry-wide queries (AI server demand, hyperscaler capex, CoWoS capacity, export controls and more).
2. **Analyze.** Claude (`claude-opus-5`, adaptive thinking, structured outputs) receives each batch of articles together with:
   - the company's thesis, valuation snapshot and the price move since each article was published
   - a list of already-known events, so the same story isn't counted twice
   - the full supply-chain map

   For every article it estimates:
   - residual impact % on fair value over ~90 days
   - confidence, share already priced in, duration, severity and pillar (leadership / product / price)
   - for company decisions, whether the move goes **with or against the market** and under what conditions it pays off

   The prompt tells Claude to be candid: survival-threatening news gets full weight and a critical flag.
3. **Combine.** Each item adds `impact × confidence × (1 − priced_in) × 0.5^(age / half_life)`. Good news saturates near +40%, while bad news can reach −85%. An optional valuation anchor can pull toward the analyst consensus target (`valuation_weight`). It's off by default (0), so predictions are purely news-driven; analyst targets tend to sit above the price and would otherwise tilt everything bullish.
4. **Predicted price** = current price × (1 + expected move). The prediction log only records a change when the news set or analyst consensus changes, never because the price moved.

**Impact score (News Hub ranking)** = `|impact %| × confidence × (1 − priced in) × recency fade × severity weight`. Severity weights are low 1.0, moderate 1.2, major 1.5 and critical 2.5. An article that affects several companies scores its largest impact plus 25% of the rest.

**Pillars.** Leadership and Product start from a baseline in `watchlist.yaml` and move with relevant news. Price is computed live from upside to the analyst target, forward P/E versus growth, and position in the 52-week range.

## The watchlist

Taiwan — companies that make AI servers possible:

| Ticker | Company | Position in the chain |
|---|---|---|
| 2330.TW | TSMC 台積電 | Leading-edge wafers + CoWoS packaging for AI accelerators |
| 2317.TW | Hon Hai 鴻海 | AI server rack assembly at scale |
| 2382.TW | Quanta 廣達 | AI server/rack ODM for hyperscalers |
| 6669.TW | Wiwynn 緯穎 | Hyperscale rack servers, custom-ASIC platforms |
| 2308.TW | Delta 台達電 | Power shelves, HVDC power & liquid cooling |
| 3017.TW | AVC 奇鋐 | Cold plates, CDUs, thermal modules |
| 2345.TW | Accton 智邦 | 400G/800G data center switches |
| 5274.TWO | ASPEED 信驊 | BMC chips in nearly every server |
| 2383.TW | Elite Material 台光電 | Low-loss CCL for server/GPU/switch boards |
| 3037.TW | Unimicron 欣興 | ABF substrates for GPU/ASIC packages |

US — software solving problems few others solve:

| Ticker | Company | Niche |
|---|---|---|
| PLTR | Palantir | Ontology-based operational AI, including classified government work |
| CDNS | Cadence | EDA + emulation needed to design every AI chip |
| NET | Cloudflare | Edge AI inference and AI-crawler control |
| DDOG | Datadog | Observability incl. LLM monitoring |
| CRWD | CrowdStrike | AI-native single-agent security platform |
| RBRK | Rubrik | Cyber resilience / recovery, incl. AI-agent rollback |
| IOT | Samsara | IoT + AI for physical operations |
| TEM | Tempus AI | Clinical + molecular data with AI diagnostics |
| SDGR | Schrödinger | Physics-based + ML molecular design |
| VEEV | Veeva | Life-sciences industry cloud with AI agents |

## Extending

**Add a stock**
1. Add an entry to `config/watchlist.yaml` with ticker, market, segment, thesis, pillar baselines, keywords and news queries.
2. Add its links in `config/industry.yaml`.
3. Click **Reload config files** in Settings.

Config is validated on load: unknown segments and dangling links are rejected.

**Add a news source.** Subclass `NewsProvider` in `backend/providers/`, register it in `backend/providers/__init__.py`, and list it under `news.providers`.

**Tune.** Horizon, half-lives, caps, valuation weight, Claude model and effort are all in `config/settings.yaml`.

## Project layout

```
config/            watchlist.yaml · industry.yaml · settings.yaml · .env (your key, git-ignored)
backend/
  main.py          FastAPI app (API under /api, serves frontend/)
  refresh.py       pipeline: prices → fundamentals → news → analysis → prediction log
  services.py      builds dashboard / detail / news hub / supply-chain payloads
  providers/       yfinance prices, Google News RSS, Yahoo Finance news
  analysis/        prompts.py · llm.py (Claude) · heuristic.py · predictor.py · scoring.py
frontend/          no-build HTML/CSS/JS (hash router, SVG chart)
tests/             offline unit tests
data/radar.db      SQLite cache (created at runtime)
```

## Limitations

- **Headlines, not full articles.** Analysis reads headlines and short summaries only; Claude is told to lower confidence when text is thin.
- **Delayed prices.** Yahoo Finance data is unofficial and can be delayed or briefly unavailable. The app keeps showing the last known price.
- **Cost of the first run.** With Claude enabled, the first refresh analyzes up to 12 articles per stock plus 20 industry articles. Later refreshes only analyze new articles. Token usage is shown in Settings.
