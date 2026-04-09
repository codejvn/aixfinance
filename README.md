# Kappa — Actor-Critic Multi-Agent Trading Bot

A consumer-facing web application that generates risk-adjusted thematic trading portfolios for perpetuals, crypto, and RWAs using a **Cross-Model Adversarial Ensemble** — two competing AI models that attack each other's proposals before a final risk layer arbitrates the best trade.

![Python](https://img.shields.io/badge/Python-3.11+-blue) ![Streamlit](https://img.shields.io/badge/UI-Streamlit-red) ![Claude](https://img.shields.io/badge/Claude-Anthropic-orange) ![GPT-4](https://img.shields.io/badge/GPT--4o-OpenAI-green)

---

## What It Does

1. **You pick a theme and risk tolerance** — e.g., "AI infrastructure", "Layer-1s", "Geopolitics", at risk levels from Very Conservative to Max Risk.
2. **Claude dynamically discovers the best tickers** for the theme (no hardcoded lists).
3. **Live news + price data is fetched** via Tavily and yfinance.
4. **Two AI actors compete** — Claude proposes a portfolio, GPT proposes a competing one.
5. **Each AI attacks the other's proposal** — Claude Critic tears apart GPT's trade logic, GPT Critic tears apart Claude's.
6. **A Risk Analyst synthesizes the best ideas** from both proposals + critiques into a final execution JSON (asset, direction, leverage, stop-loss, allocation).
7. **A backtester simulates the strategy** over your selected investment horizon (1M / 3M / 6M) against real historical price data.
8. **A self-improving policy system (RLAIF)** — after each backtest, Claude grades performance and automatically tightens or loosens per-sector leverage limits in `policy.json` for the next run.

---

## Architecture

```
User Input (theme, risk, horizon)
        │
        ▼
┌─────────────────────────┐
│   discover_tickers()    │  ← Claude picks 6-8 yfinance-compatible tickers
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  fetch_news() +         │  ← Tavily / NewsAPI news headlines
│  fetch_price_data()     │  ← yfinance OHLCV (correct horizon window)
└──────────┬──────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────┐
│                  Actor-Critic Arena                          │
│                                                              │
│   Claude Actor  ──proposes──▶  GPT Critic attacks it        │
│   GPT Actor     ──proposes──▶  Claude Critic attacks it     │
│                                                              │
│         ▼ both proposals + both critiques ▼                  │
│                   Risk Analyst (Claude)                      │
│         → final portfolio JSON with stop-losses             │
└──────────┬───────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────┐
│  Backtester             │  ← Simulates buy-and-hold w/ stop-losses
│  Equity curve + metrics │    over real historical price data
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  RLAIF Policy Update    │  ← Claude grades performance, updates
│  (policy.json)          │    per-sector leverage limits for next run
└─────────────────────────┘
```

---

## Key Technical Concepts

### Cross-Model Adversarial Ensemble
Claude and GPT-4o are adversaries. Each model proposes a portfolio, then critiques the other's proposal for risk flaws. This forces both models out of their default "agreeable" behavior — the critiques surface real edge cases before any capital is allocated.

### Hybrid API Architecture
- `anthropic` SDK for all Claude calls (actor, critic, risk analyst, policy update)
- `openai` SDK pointed at a proxy (`DEDALUS_BASE_URL`) for all GPT calls
- Both SDKs run in the same Python process; no microservices needed

### RLAIF Policy System
`policy.json` stores per-sector leverage and allocation ceilings (e.g., DeFi: max 2x leverage, max 30% allocation). After every backtest:
- Drawdown < -25% → reduce max leverage by 1.5x
- Drawdown < -15% → reduce max leverage by 1.0x
- Return > 10% + drawdown > -8% → increase max leverage by 0.5x (cap 5x)
- These limits feed back into the next run's actor prompts as hard constraints

### Event-Driven Backtesting
The backtester uses sentiment signals derived from the news articles' publish dates — no look-ahead bias. For days before any article exists, the earliest available signal is back-filled (representing the agent's current thesis applied to the historical window).

---

## File Structure

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI, session state, pipeline orchestration |
| `agents.py` | All LLM logic — Claude Actor, GPT Actor, critics, Risk Analyst, RLAIF |
| `data_fetcher.py` | Tavily + NewsAPI news fetching, yfinance price data |
| `backtester.py` | Portfolio simulation against historical OHLCV data |
| `policy.py` | Per-sector rulebook — load, query, update `policy.json` |
| `policy.json` | Auto-generated; stores live leverage/allocation limits per sector |
| `.env` | API keys (not committed) |

---

## Setup

### Prerequisites
- Python 3.11+
- API keys for: Anthropic, Dedalus Labs (OpenAI proxy), Tavily, NewsAPI

### Install
```bash
git clone https://github.com/codejvn/kappaportfolios.git
cd kappa
pip install -r requirements.txt
```

### Configure `.env`
```env
ANTHROPIC_API_KEY=sk-ant-...
DEDALUS_API_KEY=...
DEDALUS_BASE_URL=https://api.dedaluslabs.ai
TAVILY_API_KEY=tvly-...
NEWS_API_KEY=...
```

### Run
```bash
streamlit run app.py
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Streamlit |
| LLMs | Claude (Anthropic SDK), GPT-4o (OpenAI SDK via Dedalus proxy) |
| News | Tavily API, NewsAPI |
| Market Data | yfinance |
| Charts | Plotly |
| Data | pandas |

---

## Example Output

The Risk Analyst outputs a structured portfolio like:

```json
[
  { "asset": "SOL", "direction": "LONG",  "leverage": 2.5, "stop_loss_pct": 8.0, "allocation_pct": 30 },
  { "asset": "ARB", "direction": "LONG",  "leverage": 2.0, "stop_loss_pct": 10.0, "allocation_pct": 25 },
  { "asset": "BTC", "direction": "SHORT", "leverage": 1.5, "stop_loss_pct": 6.0,  "allocation_pct": 20 }
]
```

This is then simulated against real price data and the equity curve, win rate, max drawdown, and Sharpe ratio are displayed in a Plotly dashboard.

---

## What Makes This Different

Most AI trading tools are single-model wrappers. Kappa's adversarial architecture means:
- **No single model's bias dominates** — Claude and GPT have meaningfully different risk profiles
- **Critiques are adversarial, not collaborative** — the opposing model is explicitly incentivized to find flaws
- **The system improves across sessions** — policy.json tightens/loosens limits based on real backtest performance, not just hardcoded rules
