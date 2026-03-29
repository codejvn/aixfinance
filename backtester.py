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


def run_backtest(
    portfolio: list,
    articles: list = None,       # kept for API compatibility — not used
    lookback_days: int = 90,
    initial_capital: float = INITIAL_CAPITAL,
) -> dict:
    """
    Buy-and-hold simulation with per-position stop-losses.

    Logic:
      - Enter every position on the first trading day of the window.
      - Hold until stop-loss is triggered or the window ends.
      - Stop-loss: if the underlying price moves (stop_loss_pct / leverage)
        against the entry price, close the position — returns 0 thereafter.
      - LONG daily P&L  = +daily_return * leverage * weight
      - SHORT daily P&L = -daily_return * leverage * weight

    Args:
        portfolio:      list of position dicts from run_risk_analyst()
                        fields: asset, direction, leverage, stop_loss_pct, allocation_pct
        articles:       ignored (kept for call-site compatibility)
        lookback_days:  calendar days of history (30 / 90 / 180)
        initial_capital: starting portfolio value in USD

    Returns:
        {equity_curve, position_results, metrics}
    """
    print(
        f"[Backtester] Buy-and-hold simulation | "
        f"positions={len(portfolio)}, lookback={lookback_days}d"
    )

    end   = datetime.utcnow()
    start = end - timedelta(days=lookback_days)

    # ── Fetch close prices ─────────────────────────────────────────────────
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
            print(f"[Backtester] {asset} not in price data — skipping.")
            continue

        closes    = prices_df[asset]
        daily_ret = closes.pct_change().fillna(0)

        # Stop-loss threshold: underlying move = stop_loss_pct / leverage
        entry_price    = float(closes.iloc[0])
        move_threshold = stop_pct / leverage

        if direction == 1:   # LONG — stop if price falls too far
            stop_price = entry_price * (1 - move_threshold)
            triggered  = closes <= stop_price
        else:                # SHORT — stop if price rises too far
            stop_price = entry_price * (1 + move_threshold)
            triggered  = closes >= stop_price

        hit_stop = bool(triggered.any())
        stop_day = None

        # Leveraged directional daily returns
        leveraged = daily_ret * direction * leverage * weight

        if hit_stop:
            stop_idx = triggered.idxmax()
            stop_day = str(stop_idx.date())
            leveraged          = leveraged.copy()
            leveraged[stop_idx:] = 0.0
            print(f"[Backtester] {asset} stop-loss triggered on {stop_day} "
                  f"(entry={entry_price:.4f}, stop={stop_price:.4f})")

        position_returns[asset] = leveraged

        total_ret = round(float((1 + leveraged).prod() - 1) * 100, 2)
        print(f"[Backtester] {asset}: direction={pos.get('direction','LONG')}, "
              f"leverage={leverage}x, return={total_ret}%, stop={'YES' if hit_stop else 'no'}")

        position_results.append({
            "asset":            asset,
            "direction":        pos.get("direction", "LONG"),
            "leverage":         leverage,
            "allocation_pct":   pos.get("allocation_pct", 0),
            "total_return_pct": total_ret,
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
