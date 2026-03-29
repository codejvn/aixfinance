import os
import json
import anthropic
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timezone

from policy import load_policy, get_sector_rules, format_rules_for_prompt, update_sector

load_dotenv()

# ---------------------------------------------------------------------------
# DATA_FETCHER INTERFACE (data_fetcher.py is built separately)
# run_arena() expects two arguments sourced from data_fetcher.py:
#
#   news_headlines: list[str]
#     → from data_fetcher.fetch_news(theme) — list of recent news headline strings
#       about the given theme (e.g., "AI", "Layer-1s", "Geopolitics")
#
#   price_data: dict
#     → from data_fetcher.fetch_price_data(assets) — OHLCV dict keyed by ticker
#     format: {
#       "BTC": {
#         "dates":  ["2026-03-01", ...],   # list[str], most-recent-last
#         "open":   [float, ...],
#         "high":   [float, ...],
#         "low":    [float, ...],
#         "close":  [float, ...],
#         "volume": [float, ...]
#       },
#       "ETH": { ... },
#       ...
#     }
#     Minimum 30 data points recommended for meaningful stats.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# APP.PY INTERFACE
# The single public entry point is run_arena(). Wire it up as follows:
#
#   from agents import run_arena
#
#   # On button click (e.g., st.button("Run Arena")):
#   #   1. Fetch data from data_fetcher first:
#   #      headlines = data_fetcher.fetch_news(theme)
#   #      price_data = data_fetcher.fetch_price_data(assets)
#   #   2. Call the arena:
#   #      result = run_arena(headlines, price_data, theme, risk_tolerance)
#   #   3. Cache in session state to prevent re-runs on UI interaction:
#   #      st.session_state["arena_result"] = result
#   #   4. Display the result:
#   #      st.json(st.session_state["arena_result"])
#   #
#   # The arena also stores intermediate outputs (actors, critics) in the
#   # returned dict under the key "debug" if you want to expose them in the UI:
#   #   st.session_state["arena_debug"] = result.get("debug", {})
# ---------------------------------------------------------------------------

# ── Client initialization ──────────────────────────────────────────────────

claude_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# GPT via Dedalus Labs proxy
gpt_client = OpenAI(
    api_key=os.getenv("DEDALUS_API_KEY"),
    base_url=os.getenv("DEDALUS_BASE_URL", "").rstrip("/") + "/v1",
)

CLAUDE_MODEL = "claude-sonnet-4-6"
GPT_MODEL    = "gpt-4o"

# ── Mock fallbacks (returned when an API call fails) ──────────────────────

_MOCK_ACTOR = {
    "proposed_trades": [
        {"asset": "BTC",  "direction": "LONG",  "leverage": 2, "entry_rationale": "Mock fallback — actor API error."},
        {"asset": "ETH",  "direction": "LONG",  "leverage": 2, "entry_rationale": "Mock fallback — actor API error."},
    ],
    "thesis": "Mock fallback thesis — actor API error.",
}

_MOCK_CRITIC = {
    "critiques": [
        {"asset": "BTC", "flaw": "Mock fallback — critic API error.", "severity": "LOW"},
    ],
    "overall_verdict": "MODIFY",
    "verdict_rationale": "Mock fallback — critic API error. Treat all positions as unverified.",
}

_MOCK_PORTFOLIO = {
    "portfolio": [
        {"asset": "BTC",  "direction": "LONG", "leverage": 2, "stop_loss_pct": 5.0, "allocation_pct": 60.0, "rationale": "Mock fallback — risk analyst API error."},
        {"asset": "ETH",  "direction": "LONG", "leverage": 2, "stop_loss_pct": 5.0, "allocation_pct": 40.0, "rationale": "Mock fallback — risk analyst API error."},
    ],
    "overall_strategy": "Mock fallback portfolio — risk analyst API error.",
    "risk_level": "LOW",
    "confidence_score": 0.0,
}

# ── Ticker discovery ──────────────────────────────────────────────────────

_TICKER_DISCOVERY_SYSTEM = """You are a quantitative research analyst. Given a trading theme and recent news headlines,
identify the 6-8 most investable publicly traded tickers (stocks, ETFs, or crypto pairs) that offer
the best risk/reward exposure to that theme right now.

Use yfinance-compatible ticker symbols (e.g. NVDA, BTC-USD, ETH-USD, GLD, QQQ).
Crypto pairs must end in -USD (e.g. SOL-USD, not SOL).

You MUST respond with ONLY a valid JSON object. No preamble. No markdown code fences.

Schema:
{
  "tickers": ["TICKER1", "TICKER2", ...],
  "rationale": "<one sentence explaining the selection>"
}"""

def discover_tickers(theme: str, headlines: list = None) -> list:
    """
    Asks Claude to pick the best tickers for a given theme and news context.
    Returns a list of yfinance-compatible ticker strings.
    Falls back to generic market ETFs if the API call fails.
    """
    headlines_text = ""
    if headlines:
        titles = [a.get("title", "") if isinstance(a, dict) else str(a) for a in headlines[:8]]
        headlines_text = "\n".join(f"- {t}" for t in titles if t)

    user_prompt = (
        f"Theme: {theme}\n\n"
        f"Recent headlines:\n{headlines_text}\n\n"
        f"Select the 6-8 best tickers for this theme. Output ONLY the JSON object."
    )

    try:
        print(f"[Ticker Discovery] Asking {CLAUDE_MODEL} for best tickers for theme='{theme}'...")
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=256,
            system=_TICKER_DISCOVERY_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
        result = _parse_json(raw, "Ticker Discovery", {})
        tickers = result.get("tickers", [])
        if tickers:
            print(f"[Ticker Discovery] Selected: {tickers} — {result.get('rationale', '')}")
            return tickers
        raise ValueError("Empty tickers list returned")
    except Exception as e:
        print(f"[Ticker Discovery] Failed ({e}), falling back to generic tickers.")
        return ["SPY", "QQQ", "GLD", "TLT", "BTC-USD", "ETH-USD"]


# ── Prompt templates ───────────────────────────────────────────────────────

_CLAUDE_ACTOR_SYSTEM = """You are an aggressive quantitative trader specializing in perpetuals and crypto derivatives.
You will be given a market context block in JSON format. Your job is to propose a portfolio of
perpetual futures trades that maximizes risk-adjusted return given the provided theme, sentiment,
and price data.

You MUST respond with ONLY a valid JSON object. No preamble. No explanation outside the JSON.
Do not wrap the JSON in markdown code fences.

The JSON must conform exactly to this schema:
{
  "proposed_trades": [
    {
      "asset": "<ticker>",
      "direction": "<LONG|SHORT>",
      "leverage": <integer 1-10>,
      "entry_rationale": "<one sentence>"
    }
  ],
  "thesis": "<2-3 sentence overall market thesis>"
}"""

_GPT_ACTOR_SYSTEM = """You are a systematic macro trader who builds long/short perpetuals books around thematic catalysts.
You will be given a market context block in JSON format. Your job is to propose a portfolio of trades
with strict risk controls and a clear macro rationale. You tend to be more conservative with leverage
than aggressive quant traders but more willing to take contrarian short positions.

You MUST respond with ONLY a valid JSON object. No preamble. No explanation outside the JSON.
Do not wrap the JSON in markdown code fences.

The JSON must conform exactly to this schema:
{
  "proposed_trades": [
    {
      "asset": "<ticker>",
      "direction": "<LONG|SHORT>",
      "leverage": <integer 1-10>,
      "entry_rationale": "<one sentence>"
    }
  ],
  "thesis": "<2-3 sentence overall market thesis>"
}"""

_GPT_CRITIC_SYSTEM = """You are a brutal risk officer at a prop trading firm. Your job is NOT to propose trades.
Your job is to find every possible flaw, hidden risk, and logical gap in a proposed trading portfolio.
Be adversarial. Do not be polite. Challenge leverage assumptions, correlation risks, liquidity constraints,
macro tail risks, and any thesis gaps.

You MUST respond with ONLY a valid JSON object. No preamble. No explanation outside the JSON.
Do not wrap the JSON in markdown code fences.

The JSON must conform exactly to this schema:
{
  "critiques": [
    {
      "asset": "<ticker being critiqued>",
      "flaw": "<specific risk flaw identified>",
      "severity": "<LOW|MEDIUM|HIGH|CRITICAL>"
    }
  ],
  "overall_verdict": "<APPROVE|REJECT|MODIFY>",
  "verdict_rationale": "<2-3 sentences explaining the verdict>"
}"""

_CLAUDE_CRITIC_SYSTEM = """You are a veteran risk manager who has survived multiple crypto market blow-ups including
2018, the 2020 COVID crash, and the 2022 LUNA/FTX collapse. You have zero tolerance for overleveraged
trades or theses that ignore macro tail risk, correlation breaks, or liquidity crises.

Your job is to tear apart a proposed portfolio. Find leverage risks, correlated exposure, flawed
thesis assumptions, missing stop-loss logic, and anything that could cause catastrophic drawdown.

You MUST respond with ONLY a valid JSON object. No preamble. No explanation outside the JSON.
Do not wrap the JSON in markdown code fences.

The JSON must conform exactly to this schema:
{
  "critiques": [
    {
      "asset": "<ticker being critiqued>",
      "flaw": "<specific risk flaw identified>",
      "severity": "<LOW|MEDIUM|HIGH|CRITICAL>"
    }
  ],
  "overall_verdict": "<APPROVE|REJECT|MODIFY>",
  "verdict_rationale": "<2-3 sentences explaining the verdict>"
}"""

_RISK_ANALYST_SYSTEM = """You are the Chief Risk Officer of a quantitative hedge fund specializing in crypto perpetuals.
You have just received two competing trade proposals and two adversarial critiques of those proposals.

Your job is to synthesize the best ideas, discard the flawed ones, set precise stop-losses, and output
a final executable portfolio. You are the last line of defense before trades go live.

Rules you MUST follow:
- Never include a trade that received a CRITICAL severity flaw unless you explicitly document your
  overriding rationale in the trade's "rationale" field.
- Leverage must not exceed 5x on any single position.
- All allocation_pct values MUST sum to exactly 100.0.
- Set tighter stop-losses for higher leverage (guideline: stop_loss_pct ≤ 10 / leverage).
- Include 2-6 positions. Do not concentrate more than 50% in a single asset.

You MUST respond with ONLY a valid JSON object. No preamble. No explanation outside the JSON.
Do not wrap the JSON in markdown code fences.

The JSON must conform exactly to this schema:
{
  "portfolio": [
    {
      "asset": "<ticker>",
      "direction": "<LONG|SHORT>",
      "leverage": <integer 1-5>,
      "stop_loss_pct": <float>,
      "allocation_pct": <float>,
      "rationale": "<one sentence>"
    }
  ],
  "overall_strategy": "<2-3 sentence strategy summary>",
  "risk_level": "<LOW|MEDIUM|HIGH>",
  "confidence_score": <float between 0.0 and 1.0>
}"""


# ── Helper: safe JSON parse ────────────────────────────────────────────────

def _parse_json(raw: str, label: str, fallback: dict) -> dict:
    # Strip markdown code fences Claude sometimes adds despite being told not to
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]          # drop the opening ```json line
        cleaned = cleaned.rsplit("```", 1)[0].strip()  # drop the closing ```
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"[{label}] JSON parse error: {e}")
        print(f"[{label}] Raw output was:\n{raw}")
        return fallback


# ── Step 3: Context synthesis ──────────────────────────────────────────────

def synthesize_context(
    news_headlines: list,
    price_data: dict,
    theme: str,
    risk_tolerance: str = "MEDIUM",
) -> dict:
    """
    Pure Python — no LLM call.
    Converts raw data_fetcher outputs into a compact context block for all agents.

    Args:
        news_headlines: list[str] from data_fetcher.fetch_news(theme)
        price_data: dict from data_fetcher.fetch_price_data(assets)
        theme: user-supplied theme string (e.g. "AI Infrastructure")
        risk_tolerance: "LOW" | "MEDIUM" | "HIGH"

    Returns:
        dict with keys: theme, risk_tolerance, headlines, assets, timestamp
    """
    assets_summary = {}

    for ticker, ohlcv in price_data.items():
        try:
            closes = ohlcv.get("close", [])
            volumes = ohlcv.get("volume", [])

            if len(closes) < 2:
                assets_summary[ticker] = {"error": "insufficient price data"}
                continue

            current_price = closes[-1]

            # % returns (most-recent-last ordering assumed)
            ret_7d  = ((closes[-1] / closes[-7])  - 1) * 100 if len(closes) >= 7  else None
            ret_30d = ((closes[-1] / closes[-30]) - 1) * 100 if len(closes) >= 30 else None

            # Average daily volume (last 7 days)
            avg_vol_7d = sum(volumes[-7:]) / min(7, len(volumes)) if volumes else None

            # Realized volatility: std of daily returns (last 14 days)
            window = closes[-15:] if len(closes) >= 15 else closes
            daily_returns = [(window[i] / window[i - 1]) - 1 for i in range(1, len(window))]
            vol_pct = None
            if daily_returns:
                mean = sum(daily_returns) / len(daily_returns)
                variance = sum((r - mean) ** 2 for r in daily_returns) / len(daily_returns)
                vol_pct = round((variance ** 0.5) * 100, 4)

            assets_summary[ticker] = {
                "current_price":    round(current_price, 6),
                "7d_return_pct":    round(ret_7d, 2)  if ret_7d  is not None else None,
                "30d_return_pct":   round(ret_30d, 2) if ret_30d is not None else None,
                "avg_volume_7d":    round(avg_vol_7d)  if avg_vol_7d is not None else None,
                "realized_vol_pct": vol_pct,
            }
        except Exception as e:
            print(f"[synthesize_context] Error processing {ticker}: {e}")
            assets_summary[ticker] = {"error": str(e)}

    context = {
        "theme":          theme,
        "risk_tolerance": risk_tolerance,
        "headlines":      news_headlines[:10],  # cap at 10 to keep prompt concise
        "assets":         assets_summary,
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }

    print(f"[synthesize_context] Done. Assets: {list(assets_summary.keys())}, Headlines: {len(context['headlines'])}")
    return context


# ── Step 4a: Claude Actor ─────────────────────────────────────────────────

def run_claude_actor(context_block: dict) -> dict:
    """
    Claude proposes a set of perpetuals trades based on the context block.
    Returns: {"proposed_trades": [...], "thesis": "..."}
    """
    policy = load_policy()
    rules  = get_sector_rules(context_block.get("theme", ""), policy)
    policy_block = format_rules_for_prompt(rules)

    user_prompt = (
        f"{policy_block}\n\n"
        f"Here is the current market context:\n\n{json.dumps(context_block, indent=2)}\n\n"
        f"Propose your trades now. Output ONLY the JSON object."
    )

    try:
        print(f"[Claude Actor] Calling {CLAUDE_MODEL}...")
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=_CLAUDE_ACTOR_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
        result = _parse_json(raw, "Claude Actor", _MOCK_ACTOR)
        print(f"[Claude Actor] Proposed {len(result.get('proposed_trades', []))} trades.")
        return result
    except Exception as e:
        print(f"[Claude Actor] API error: {e}")
        return _MOCK_ACTOR


# ── Step 4b: GPT Actor ────────────────────────────────────────────────────

def run_gpt_actor(context_block: dict) -> dict:
    """
    GPT proposes a competing set of perpetuals trades based on the context block.
    Returns: {"proposed_trades": [...], "thesis": "..."}
    """
    policy = load_policy()
    rules  = get_sector_rules(context_block.get("theme", ""), policy)
    policy_block = format_rules_for_prompt(rules)

    user_prompt = (
        f"{policy_block}\n\n"
        f"Here is the current market context:\n\n{json.dumps(context_block, indent=2)}\n\n"
        f"Propose your trades now. Output ONLY the JSON object."
    )

    try:
        print(f"[GPT Actor] Calling {GPT_MODEL}...")
        response = gpt_client.chat.completions.create(
            model=GPT_MODEL,
            response_format={"type": "json_object"},  # hard JSON enforcement
            messages=[
                {"role": "system",  "content": _GPT_ACTOR_SYSTEM},
                {"role": "user",    "content": user_prompt},
            ],
        )
        raw = response.choices[0].message.content
        result = _parse_json(raw, "GPT Actor", _MOCK_ACTOR)
        print(f"[GPT Actor] Proposed {len(result.get('proposed_trades', []))} trades.")
        return result
    except Exception as e:
        print(f"[GPT Actor] API error: {e}")
        return _MOCK_ACTOR


# ── Step 4c: GPT Critic (attacks Claude Actor's proposal) ────────────────

def run_gpt_critic(claude_actor_output: dict, context_block: dict) -> dict:
    """
    GPT Critic brutally attacks Claude Actor's proposed trades.
    Returns: {"critiques": [...], "overall_verdict": "...", "verdict_rationale": "..."}
    """
    user_prompt = (
        f"Here is the market context:\n\n{json.dumps(context_block, indent=2)}\n\n"
        f"Here is the proposed portfolio you must critique:\n\n{json.dumps(claude_actor_output, indent=2)}\n\n"
        f"Find every risk flaw. Be brutal and specific. Output ONLY the JSON object."
    )

    try:
        print(f"[GPT Critic] Calling {GPT_MODEL} to critique Claude Actor...")
        response = gpt_client.chat.completions.create(
            model=GPT_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _GPT_CRITIC_SYSTEM},
                {"role": "user",   "content": user_prompt},
            ],
        )
        raw = response.choices[0].message.content
        result = _parse_json(raw, "GPT Critic", _MOCK_CRITIC)
        print(f"[GPT Critic] Verdict: {result.get('overall_verdict')} — {len(result.get('critiques', []))} critiques.")
        return result
    except Exception as e:
        print(f"[GPT Critic] API error: {e}")
        return _MOCK_CRITIC


# ── Step 4d: Claude Critic (attacks GPT Actor's proposal) ────────────────

def run_claude_critic(gpt_actor_output: dict, context_block: dict) -> dict:
    """
    Claude Critic brutally attacks GPT Actor's proposed trades.
    Returns: {"critiques": [...], "overall_verdict": "...", "verdict_rationale": "..."}
    """
    user_prompt = (
        f"Here is the market context:\n\n{json.dumps(context_block, indent=2)}\n\n"
        f"Here is the proposed portfolio you must critique:\n\n{json.dumps(gpt_actor_output, indent=2)}\n\n"
        f"Find every risk flaw. Be brutal and specific. Output ONLY the JSON object."
    )

    try:
        print(f"[Claude Critic] Calling {CLAUDE_MODEL} to critique GPT Actor...")
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=_CLAUDE_CRITIC_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
        result = _parse_json(raw, "Claude Critic", _MOCK_CRITIC)
        print(f"[Claude Critic] Verdict: {result.get('overall_verdict')} — {len(result.get('critiques', []))} critiques.")
        return result
    except Exception as e:
        print(f"[Claude Critic] API error: {e}")
        return _MOCK_CRITIC


# ── Step 5: Risk Analyst ──────────────────────────────────────────────────

def run_risk_analyst(
    context_block: dict,
    claude_actor_output: dict,
    gpt_actor_output: dict,
    claude_critic_output: dict,
    gpt_critic_output: dict,
) -> dict:
    """
    Final synthesis layer. Reviews all four agent outputs and returns an
    executable portfolio JSON.

    Returns:
        {
          "portfolio": [{"asset", "direction", "leverage", "stop_loss_pct",
                         "allocation_pct", "rationale"}, ...],
          "overall_strategy": str,
          "risk_level": "LOW"|"MEDIUM"|"HIGH",
          "confidence_score": float
        }
    """
    policy = load_policy()
    rules  = get_sector_rules(context_block.get("theme", ""), policy)
    policy_block = format_rules_for_prompt(rules)

    user_prompt = (
        f"{policy_block}\n\n"
        f"MARKET CONTEXT:\n{json.dumps(context_block, indent=2)}\n\n"
        f"ACTOR A PROPOSAL (Claude):\n{json.dumps(claude_actor_output, indent=2)}\n\n"
        f"ACTOR B PROPOSAL (GPT):\n{json.dumps(gpt_actor_output, indent=2)}\n\n"
        f"CRITIQUE OF ACTOR A (by GPT Critic):\n{json.dumps(gpt_critic_output, indent=2)}\n\n"
        f"CRITIQUE OF ACTOR B (by Claude Critic):\n{json.dumps(claude_critic_output, indent=2)}\n\n"
        f"Synthesize these into the final executable portfolio. Output ONLY the JSON object."
    )

    try:
        print(f"[Risk Analyst] Calling {CLAUDE_MODEL} for final synthesis...")
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=_RISK_ANALYST_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
        result = _parse_json(raw, "Risk Analyst", _MOCK_PORTFOLIO)

        # Belt-and-suspenders: normalize allocation_pct to exactly 100.0
        portfolio = result.get("portfolio", [])
        if portfolio:
            total = sum(p.get("allocation_pct", 0) for p in portfolio)
            if total > 0 and abs(total - 100.0) > 0.01:
                print(f"[Risk Analyst] Normalizing allocations (sum was {total:.2f}%)")
                for p in portfolio:
                    p["allocation_pct"] = round((p["allocation_pct"] / total) * 100.0, 2)

        assets = [p["asset"] for p in portfolio]
        print(f"[Risk Analyst] Final portfolio: {assets} | Risk: {result.get('risk_level')} | Confidence: {result.get('confidence_score')}")
        return result

    except Exception as e:
        print(f"[Risk Analyst] API error: {e}")
        return _MOCK_PORTFOLIO


# ── Orchestrator ──────────────────────────────────────────────────────────

def run_arena(context_block: dict) -> dict:
    """
    Public entry point. Runs the full actor-critic arena pipeline.

    Args:
        context_block: dict — the output of data_fetcher.gather_all_data() or
                              data_fetcher.build_context_block(). Already contains
                              synthesized news sentiment + price summaries.

    Returns:
        Final portfolio dict (same schema as run_risk_analyst output).
        Also includes a "debug" key with all intermediate agent outputs:
          result["debug"]["claude_actor"]  — Claude Actor proposal
          result["debug"]["gpt_actor"]     — GPT Actor proposal
          result["debug"]["gpt_critic"]    — GPT Critic verdict (on Claude)
          result["debug"]["claude_critic"] — Claude Critic verdict (on GPT)

    app.py usage:
        result = run_arena(st.session_state["context"])
        st.session_state["arena_result"] = result
    """
    theme = context_block.get("theme", "Unknown")
    risk  = context_block.get("risk_tolerance", "?")
    print(f"\n{'='*60}")
    print(f"[Arena] Starting pipeline | theme='{theme}' | risk={risk}")
    print(f"{'='*60}")

    try:
        # ── Step 4: Actors ────────────────────────────────────────────────
        # TODO: parallelize with concurrent.futures.ThreadPoolExecutor for lower latency
        claude_actor_output = run_claude_actor(context_block)
        gpt_actor_output    = run_gpt_actor(context_block)
        print(gpt_actor_output)

        # ── Step 4: Critics (each attacks the opposing actor) ─────────────
        # TODO: parallelize with concurrent.futures.ThreadPoolExecutor for lower latency
        gpt_critic_output    = run_gpt_critic(claude_actor_output, context_block)
        claude_critic_output = run_claude_critic(gpt_actor_output, context_block)

        # ── Step 5: Risk Analyst final synthesis ──────────────────────────
        final_portfolio = run_risk_analyst(
            context_block,
            claude_actor_output,
            gpt_actor_output,
            claude_critic_output,
            gpt_critic_output,
        )

        # Attach debug payload so app.py can surface intermediate outputs
        final_portfolio["debug"] = {
            "claude_actor":  claude_actor_output,
            "gpt_actor":     gpt_actor_output,
            "gpt_critic":    gpt_critic_output,
            "claude_critic": claude_critic_output,
        }

        print(f"[Arena] Pipeline complete.\n")
        return final_portfolio

    except Exception as e:
        print(f"[Arena] Unhandled error in pipeline: {e}")
        _MOCK_PORTFOLIO["debug"] = {"error": str(e)}
        return _MOCK_PORTFOLIO


# ── Policy update (RLAIF feedback loop) ───────────────────────────────────

_POLICY_UPDATE_SYSTEM = """You are a risk compliance officer. You have just reviewed a completed trading simulation.
Your job is to update the sector policy with tighter or looser limits based on what the data shows.

Adjustment rules — apply ALL that are triggered (they stack):
  max_drawdown < -25%  → reduce max_leverage by 1.5  (floor: 1.0)
  max_drawdown < -15%  → reduce max_leverage by 1.0  (floor: 1.0)
  max_drawdown < -8%   → reduce max_leverage by 0.5  (floor: 1.0)
  sharpe < 0.3 AND total_return < 0%  → reduce max_allocation_pct by 10 (floor: 10.0)
  total_return > 10% AND max_drawdown > -8%  → may increase max_leverage by 0.5 (cap: 5.0)
  total_return > 20% AND sharpe > 1.5        → may increase max_allocation_pct by 5  (cap: 50.0)

You MUST respond with ONLY a valid JSON object. No preamble. No markdown code fences.

Schema:
{
  "max_leverage": <float>,
  "max_allocation_pct": <float>,
  "notes": "<one sentence: what performance data triggered this update>",
  "updated_reason": "<the specific metric that drove the biggest change>"
}"""


def update_policy_from_backtest(
    theme: str,
    portfolio: list,
    metrics: dict,
) -> dict:
    """
    RLAIF feedback loop: after a backtest, Claude grades performance and
    rewrites the sector policy limits in policy.json.

    Args:
        theme:     the theme string (used to look up / create the sector entry)
        portfolio: list of position dicts from run_risk_analyst()
        metrics:   backtest metrics dict from backtester.run_backtest()

    Returns:
        dict with keys: sector_key, old_rules, new_rules  (for display in app.py)
    """
    policy       = load_policy()
    current      = get_sector_rules(theme, policy)
    sector_label = current.get("_sector_key") or theme

    positions_summary = "\n".join(
        f"  {p['asset']} {p['direction']} {p['leverage']}x "
        f"({p['allocation_pct']}% allocation)"
        for p in portfolio
    )

    user_prompt = (
        f"Theme: {theme}\n"
        f"Sector: {sector_label}\n\n"
        f"Current policy limits:\n"
        f"  max_leverage:       {current.get('max_leverage', '?')}x\n"
        f"  max_allocation_pct: {current.get('max_allocation_pct', '?')}%\n\n"
        f"Backtest results ({metrics.get('trading_days', '?')} trading days):\n"
        f"  Total return:  {metrics.get('total_return_pct', 0):+.2f}%\n"
        f"  Max drawdown:  {metrics.get('max_drawdown_pct', 0):.2f}%\n"
        f"  Win rate:      {metrics.get('win_rate_pct', 0):.1f}%\n"
        f"  Sharpe ratio:  {metrics.get('sharpe_ratio', 0):.2f}\n\n"
        f"Positions:\n{positions_summary}\n\n"
        f"Apply the adjustment rules and output the updated policy. Output ONLY the JSON object."
    )

    try:
        print(f"[Policy Update] Calling {CLAUDE_MODEL} to grade performance for '{theme}'...")
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=_POLICY_UPDATE_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw        = response.content[0].text
        new_rules  = _parse_json(raw, "Policy Update", {})

        if not new_rules or "max_leverage" not in new_rules:
            raise ValueError("incomplete policy response")

        # Carry the sector key through to update_sector()
        new_rules["_sector_key"] = current.get("_sector_key")
        change = update_sector(theme, new_rules, policy)
        print(
            f"[Policy Update] Done. "
            f"leverage: {change['old_rules'].get('max_leverage','?')}x → "
            f"{change['new_rules']['max_leverage']}x"
        )
        return change

    except Exception as e:
        print(f"[Policy Update] Error: {e} — policy unchanged.")
        return {"sector_key": sector_label, "old_rules": current, "new_rules": current, "error": str(e)}


# ── Step 7: Performance insight ───────────────────────────────────────────

def generate_performance_insight(portfolio: list, metrics: dict, context_block: dict) -> str:
    """
    Claude writes a 3-4 sentence plain-English insight summarising the backtest.

    Args:
        portfolio:     list of position dicts (from run_risk_analyst)
        metrics:       backtest metrics dict (from backtester.run_backtest)
        context_block: the full context dict (theme, risk_tolerance, news, etc.)

    Returns:
        Plain text string — NOT JSON. Suitable for st.markdown() in app.py.
    """
    positions_summary = ", ".join(
        f"{p['asset']} {p['direction']} {p['leverage']}x ({p['allocation_pct']}%)"
        for p in portfolio
    )

    user_prompt = (
        f"Theme: {context_block.get('theme', 'Unknown')}\n"
        f"Risk Tolerance: {context_block.get('risk_tolerance', 'Unknown')}/10\n"
        f"Market Sentiment: {context_block.get('news', {}).get('overall_sentiment', 'unknown')}\n\n"
        f"Positions: {positions_summary}\n\n"
        f"Backtest Results ({metrics.get('trading_days', '?')} trading days):\n"
        f"  Total Return:  {metrics.get('total_return_pct', 0):+.2f}%\n"
        f"  Max Drawdown:  {metrics.get('max_drawdown_pct', 0):.2f}%\n"
        f"  Win Rate:      {metrics.get('win_rate_pct', 0):.1f}%\n"
        f"  Sharpe Ratio:  {metrics.get('sharpe_ratio', 0):.2f}\n"
        f"  Final Capital: ${metrics.get('final_capital', 10000):,.2f} "
        f"(started ${metrics.get('initial_capital', 10000):,.2f})\n\n"
        f"Write a 3-4 sentence insight for a retail investor covering: "
        f"(1) overall performance verdict, (2) what drove returns or losses, "
        f"(3) key risks to watch going forward. "
        f"Be direct, specific, and avoid filler phrases. Plain text only — no bullet points, no markdown."
    )

    try:
        print(f"[Performance Insight] Calling {CLAUDE_MODEL}...")
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": user_prompt}],
        )
        insight = response.content[0].text.strip()
        print(f"[Performance Insight] Done ({len(insight)} chars).")
        return insight
    except Exception as e:
        print(f"[Performance Insight] API error: {e}")
        return "Performance insight unavailable due to an API error."


# ── Local smoke test ──────────────────────────────────────────────────────

if __name__ == "__main__":
    # Minimal mock context block matching data_fetcher.build_context_block() output.
    # Run `python agents.py` to smoke-test the pipeline without needing data_fetcher.py.
    mock_context = {
        "theme": "Layer-1 Blockchains",
        "risk_tolerance": 5,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "news": {
            "overall_sentiment": "bullish",
            "sentiment_score": 0.6,
            "sentiment_breakdown": {"positive": 4, "negative": 1, "neutral": 0},
            "articles": [
                {"title": "Bitcoin breaks $90k as institutional demand surges", "snippet": "Institutional buyers push BTC above $90k.", "sentiment": "positive"},
                {"title": "Ethereum Layer-2 TVL hits record $50B", "snippet": "L2 ecosystem growth accelerating.", "sentiment": "positive"},
                {"title": "Fed signals no rate cuts before Q3 2026", "snippet": "Macro headwinds remain for risk assets.", "sentiment": "negative"},
                {"title": "Solana DeFi volumes up 40% month-over-month", "snippet": "SOL on-chain activity surging.", "sentiment": "positive"},
                {"title": "BlackRock expands crypto ETF lineup to include SOL", "snippet": "Institutional adoption broadening.", "sentiment": "positive"},
            ],
        },
        "price_data": {
            "BTC-USD": {"ticker": "BTC-USD", "last_price": 91200.0, "return_30d_pct": 12.4, "volatility_30d_pct": 42.1, "avg_volume_30d": 28000000000},
            "ETH-USD": {"ticker": "ETH-USD", "last_price": 3620.0,  "return_30d_pct": 8.1,  "volatility_30d_pct": 51.3, "avg_volume_30d": 14000000000},
            "SOL-USD": {"ticker": "SOL-USD", "last_price": 162.5,   "return_30d_pct": 21.7, "volatility_30d_pct": 68.9, "avg_volume_30d": 3500000000},
        },
    }

    result = run_arena(mock_context)

    print("\n── Final Portfolio ──")
    # Remove debug from print to keep output readable
    display = {k: v for k, v in result.items() if k != "debug"}
    print(json.dumps(display, indent=2))
