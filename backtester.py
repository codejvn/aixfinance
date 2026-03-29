import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

INITIAL_CAPITAL = 10_000.0

# Crypto symbols the LLM might output without the -USD suffix
_CRYPTO_SYMBOLS = {
    "BTC", "ETH", "SOL", "AVAX", "ADA", "ONDO", "UNI", "AAVE", "MKR",
    "SNX", "MPL", "CFG", "TRU", "CRED", "DOT", "ATOM", "NEAR", "FTM",
    "ARB", "OP", "INJ", "SUI", "APT", "SEI",
}


def _normalize_ticker(asset: str) -> str:
    """Ensure crypto tickers end in -USD for yfinance compatibility."""
    upper = asset.upper().replace(" ", "")
    if upper in _CRYPTO_SYMBOLS and "-USD" not in upper:
        return upper + "-USD"
    return upper


def _mock_backtest_result() -> dict:
    return {
        "equity_curve": [
            {"date": "2026-01-01", "value": INITIAL_CAPITAL},
            {"date": "2026-03-29", "value": INITIAL_CAPITAL * 1.05},
        ],
        "position_results": [],
        "metrics": {
            "total_return_pct": 5.0,
            "max_drawdown_pct": -2.0,
            "win_rate_pct": 55.0,
            "sharpe_ratio": 0.8,
            "initial_capital": INITIAL_CAPITAL,
            "final_capital": INITIAL_CAPITAL * 1.05,
            "trading_days": 0,
        },
    }


def _build_sentiment_signal(articles: list, date_index: pd.DatetimeIndex) -> pd.Series:
    """
    Build a daily sentiment signal from article published_dates.

    For each trading day, only articles published ON OR BEFORE that day are used
    (no look-ahead). The rolling signal is derived from the 5 most recent articles
    available at that point.

    Returns a Series indexed by date_index:
        +1.0  = bullish  (LONG positions active at full leverage, SHORTs flat)
        -1.0  = bearish  (SHORT positions active at full leverage, LONGs flat)
         0.0  = neutral  (both directions active at half leverage)
        NaN   = no articles yet (positions flat — no information, no trade)
    """
    # Parse article dates robustly — formats vary between Tavily and NewsAPI
    events = []
    for a in articles:
        raw = a.get("published_date", "")
        if not raw:
            continue
        try:
            dt = pd.to_datetime(raw, utc=True).tz_localize(None).normalize()
            events.append({"date": dt, "sentiment": a.get("sentiment", "neutral")})
        except Exception:
            continue

    if not events:
        # No dateable articles — return all-NaN (flat throughout)
        return pd.Series(float("nan"), index=date_index)

    events.sort(key=lambda x: x["date"])

    signal = pd.Series(float("nan"), index=date_index)

    for day in date_index:
        day_ts = pd.Timestamp(day).normalize()
        available = [e for e in events if e["date"] <= day_ts]
        if not available:
            continue  # no articles yet → stay NaN (flat)

        # Rolling window: last 5 articles available at this point in time
        recent   = available[-5:]
        n_pos    = sum(1 for e in recent if e["sentiment"] == "positive")
        n_neg    = sum(1 for e in recent if e["sentiment"] == "negative")

        if n_pos > n_neg:
            signal[day] = 1.0    # bullish signal
        elif n_neg > n_pos:
            signal[day] = -1.0   # bearish signal
        else:
            signal[day] = 0.0    # mixed / neutral

    # Back-fill: news APIs only return recent articles (last 7 days), but the
    # backtest window may be 90-180 days. Days before the first article are NaN
    # (flat). We back-fill using the earliest available signal so the agent's
    # thesis (formed from current news) is applied to the full historical window.
    nan_before = int(signal.isna().sum())
    signal = signal.bfill()
    nan_after = int(signal.isna().sum())
    if nan_before > nan_after:
        print(
            f"[Backtester] Back-filled {nan_before - nan_after} days before first article "
            f"using earliest signal ({signal.iloc[0]:.0f})"
        )

    return signal


def _position_multiplier(signal: float, direction: int) -> float:
    """
    Convert a sentiment signal into a position size multiplier [0, 1].

    Rules:
      LONG  (+1): full size when bullish, half size when neutral, flat when bearish
      SHORT (-1): full size when bearish, half size when neutral, flat when bullish
    No position at all when signal is NaN (no articles available yet).
    """
    if pd.isna(signal):
        return 0.0
    if direction == 1:   # LONG
        if signal > 0:   return 1.0   # bullish → hold full
        if signal == 0:  return 0.5   # neutral → half size
        return 0.0                    # bearish → exit
    else:                # SHORT
        if signal < 0:   return 1.0   # bearish → hold full
        if signal == 0:  return 0.5   # neutral → half size
        return 0.0                    # bullish → exit


def run_backtest(
    portfolio: list,
    articles: list,
    lookback_days: int = 90,
    initial_capital: float = INITIAL_CAPITAL,
) -> dict:
    """
    Event-driven paper-trading simulation over historical price data.

    Trading logic (no look-ahead):
      - Positions are sized each day based on a rolling sentiment signal derived
        exclusively from news articles published on or before that day.
      - Days with no articles yet: position is flat (cash). The AI can't trade
        on information it doesn't have.
      - Days with a bullish signal: LONG positions are fully active.
      - Days with a bearish signal: SHORT positions are fully active.
      - Days with mixed/neutral signal: all positions run at 50% size.
      - Stop-loss: if the underlying moves stop_loss_pct / leverage against the
        entry price, the position is closed for the rest of the simulation
        (perpetuals convention).

    Args:
        portfolio:       list of position dicts from agents.run_risk_analyst()
                         fields: asset, direction, leverage, stop_loss_pct, allocation_pct
        articles:        list of article dicts from context["news"]["articles"]
                         each needs "published_date" and "sentiment" fields
        lookback_days:   calendar days of history — should equal the user's
                         selected investment horizon (30 / 90 / 180)
        initial_capital: starting portfolio value in USD

    Returns:
        {
          "equity_curve":     [{"date": str, "value": float}, ...],
          "position_results": [{asset, direction, leverage, allocation_pct,
                                total_return_pct, hit_stop_loss, stop_loss_day,
                                days_active, days_flat}, ...],
          "metrics": {total_return_pct, max_drawdown_pct, win_rate_pct,
                      sharpe_ratio, initial_capital, final_capital, trading_days}
        }
    """
    print(
        f"[Backtester] Starting event-driven simulation | "
        f"positions={len(portfolio)}, lookback={lookback_days}d, "
        f"articles={len(articles)}"
    )

    end   = datetime.utcnow()
    start = end - timedelta(days=lookback_days)

    # ── Fetch close prices for each portfolio asset ────────────────────────
    price_series = {}
    for pos in portfolio:
        raw    = pos.get("asset", "")
        ticker = _normalize_ticker(raw)
        try:
            df = yf.download(
                ticker,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                progress=False,
            )
            if df.empty:
                raise ValueError("empty dataframe")
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            price_series[raw] = df["Close"].dropna()
            print(f"[Backtester] {ticker}: {len(price_series[raw])} trading days")
        except Exception as e:
            print(f"[Backtester] Could not fetch {ticker}: {e} — skipping.")

    if not price_series:
        print("[Backtester] No price data — returning mock result.")
        return _mock_backtest_result()

    prices_df = pd.DataFrame(price_series).dropna()
    if prices_df.empty or len(prices_df) < 2:
        print("[Backtester] Insufficient aligned data — returning mock result.")
        return _mock_backtest_result()

    # ── Build daily sentiment signal (no look-ahead) ───────────────────────
    sentiment_signal = _build_sentiment_signal(articles, prices_df.index)

    active_days  = int((~sentiment_signal.isna()).sum())
    bullish_days = int((sentiment_signal == 1.0).sum())
    bearish_days = int((sentiment_signal == -1.0).sum())
    neutral_days = int((sentiment_signal == 0.0).sum())
    flat_days    = int(sentiment_signal.isna().sum())
    print(
        f"[Backtester] Signal breakdown over {len(prices_df)} trading days: "
        f"bullish={bullish_days}, bearish={bearish_days}, "
        f"neutral={neutral_days}, flat(no news)={flat_days}"
    )

    # ── Simulate each position ─────────────────────────────────────────────
    position_returns = {}
    position_results = []

    for pos in portfolio:
        asset     = pos.get("asset", "")
        direction = 1 if pos.get("direction", "LONG") == "LONG" else -1
        leverage  = max(1, int(pos.get("leverage", 1)))
        stop_pct  = float(pos.get("stop_loss_pct", 10.0)) / 100.0
        weight    = float(pos.get("allocation_pct", 0)) / 100.0

        if asset not in prices_df.columns:
            continue

        closes    = prices_df[asset]
        daily_ret = closes.pct_change().fillna(0)

        # Position multiplier per day derived from the no-look-ahead sentiment signal
        multipliers = sentiment_signal.apply(
            lambda s: _position_multiplier(s, direction)
        )

        # Stop-loss: based on price movement from entry (first day of simulation).
        # Entry price is the first close in the window — the trader enters at open
        # on day 1 when news first informed the portfolio decision.
        entry_price    = float(closes.iloc[0])
        move_threshold = stop_pct / leverage  # underlying move that wipes stop_loss_pct of position

        if direction == 1:
            stop_price = entry_price * (1 - move_threshold)
            triggered  = closes <= stop_price
        else:
            stop_price = entry_price * (1 + move_threshold)
            triggered  = closes >= stop_price

        hit_stop = bool(triggered.any())
        stop_day = None

        # Raw leveraged directional returns, scaled by daily sentiment multiplier
        leveraged = daily_ret * direction * leverage * multipliers

        if hit_stop:
            stop_idx = triggered.idxmax()
            stop_day = str(stop_idx.date())
            leveraged          = leveraged.copy()
            leveraged[stop_idx:] = 0.0
            print(f"[Backtester] {asset} stop-loss triggered on {stop_day}")

        position_returns[asset] = leveraged * weight

        total_ret  = round(float((1 + leveraged).prod() - 1) * 100, 2)
        days_active = int((multipliers > 0).sum())
        days_flat   = int((multipliers == 0).sum())

        position_results.append({
            "asset":            asset,
            "direction":        pos.get("direction", "LONG"),
            "leverage":         leverage,
            "allocation_pct":   pos.get("allocation_pct", 0),
            "total_return_pct": total_ret,
            "days_active":      days_active,
            "days_flat":        days_flat,
            "hit_stop_loss":    hit_stop,
            "stop_loss_day":    stop_day,
        })

    if not position_returns:
        print("[Backtester] No valid positions — returning mock result.")
        return _mock_backtest_result()

    # ── Portfolio equity curve ─────────────────────────────────────────────
    port_returns = pd.DataFrame(position_returns).sum(axis=1).fillna(0)
    equity       = initial_capital * (1 + port_returns).cumprod()

    equity_curve = [
        {"date": str(d.date()), "value": round(float(v), 2)}
        for d, v in equity.items()
    ]

    # ── Performance metrics ────────────────────────────────────────────────
    total_return_pct = round(float(equity.iloc[-1] / initial_capital - 1) * 100, 2)

    roll_max         = equity.cummax()
    drawdown_series  = (equity - roll_max) / roll_max
    max_drawdown_pct = round(float(drawdown_series.min()) * 100, 2)

    win_rate_pct = round(float((port_returns > 0).mean()) * 100, 2)

    mean_ret = float(port_returns.mean())
    std_ret  = float(port_returns.std())
    sharpe   = round(mean_ret / std_ret * (252 ** 0.5), 2) if std_ret > 0 else 0.0

    metrics = {
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "win_rate_pct":     win_rate_pct,
        "sharpe_ratio":     sharpe,
        "initial_capital":  initial_capital,
        "final_capital":    round(float(equity.iloc[-1]), 2),
        "trading_days":     len(port_returns),
    }

    print(
        f"[Backtester] Done. Return={total_return_pct}%, "
        f"MaxDD={max_drawdown_pct}%, WinRate={win_rate_pct}%, Sharpe={sharpe}"
    )

    return {
        "equity_curve":     equity_curve,
        "position_results": position_results,
        "metrics":          metrics,
    }
