import os
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd
from tavily import TavilyClient
from newsapi import NewsApiClient
from dotenv import load_dotenv

load_dotenv(override=True)

def _get_tavily_client():
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return None
    return TavilyClient(api_key=key)

def _get_newsapi_client():
    key = os.getenv("NEWS_API_KEY")
    if not key:
        return None
    return NewsApiClient(api_key=key)

# ─── Ticker map: theme → list of representative tickers ──────────────────────
THEME_TICKERS = {
    "AI": ["NVDA", "MSFT", "GOOGL", "AMD", "PLTR"],
    "Geopolitics": ["LMT", "RTX", "GLD", "USO", "UUP"],
    "Layer-1s": ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "ADA-USD"],
    "DeFi": ["ETH-USD", "UNI-USD", "AAVE-USD", "MKR-USD", "SNX-USD"],
    "RWAs": ["ONDO-USD", "MPL-USD", "CRED-USD", "CFG-USD", "TRU-USD"],
    "Energy": ["XOM", "CVX", "BP", "SLB", "HAL"],
    "Biotech": ["MRNA", "BNTX", "REGN", "VRTX", "GILD"],
}


def get_tickers_for_theme(theme: str) -> list[str]:
    """Return tickers for a known theme or do a best-effort match."""
    for key in THEME_TICKERS:
        if key.lower() in theme.lower():
            return THEME_TICKERS[key]
    # Fallback: return generic market ETFs
    return ["SPY", "QQQ", "IWM", "GLD", "TLT"]


# ─── Step 2a: News via Tavily ─────────────────────────────────────────────────
def fetch_news_tavily(theme: str, max_results: int = 10) -> list[dict]:
    """Fetch news via Tavily deep-search."""
    print(f"[Tavily] Fetching news for theme: '{theme}'")
    tavily_client = _get_tavily_client()
    if not tavily_client:
        print("[Tavily] No API key set — skipping.")
        return []
    try:
        response = tavily_client.search(
            query=f"{theme} market outlook trading news 2025",
            search_depth="advanced",
            max_results=max_results,
            include_answer=True,
        )
        articles = []
        for r in response.get("results", []):
            articles.append({
                "source": "tavily",
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")[:300],
                "published_date": r.get("published_date", ""),
            })
        print(f"[Tavily] Retrieved {len(articles)} articles.")
        return articles
    except Exception as e:
        print(f"[Tavily] ERROR: {e} — skipping.")
        return []


# ─── Step 2a (alt): News via NewsAPI ─────────────────────────────────────────
def fetch_news_newsapi(theme: str, max_results: int = 10) -> list[dict]:
    """Fetch news via NewsAPI /v2/everything endpoint."""
    print(f"[NewsAPI] Fetching news for theme: '{theme}'")
    newsapi_client = _get_newsapi_client()
    if not newsapi_client:
        print("[NewsAPI] No API key set — skipping.")
        return []
    try:
        from_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        response = newsapi_client.get_everything(
            q=f"{theme} market trading",
            language="en",
            sort_by="relevancy",
            page_size=max_results,
            from_param=from_date,
        )
        articles = []
        for a in response.get("articles", []):
            articles.append({
                "source": "newsapi",
                "title": a.get("title") or "",
                "url": a.get("url") or "",
                "snippet": (a.get("description") or a.get("content") or "")[:300],
                "published_date": a.get("publishedAt") or "",
            })
        print(f"[NewsAPI] Retrieved {len(articles)} articles.")
        return articles
    except Exception as e:
        print(f"[NewsAPI] ERROR: {e} — skipping.")
        return []


def fetch_news(theme: str, max_results: int = 10, tickers: list = None) -> list[dict]:
    """
    Fetch and merge news from Tavily + NewsAPI.
    If tickers are provided, the search query includes the specific ticker names
    so results are relevant to both the theme and the LLM-chosen assets.
    Deduplicates by title. Falls back to mock data if both sources fail.
    """
    # Build an enriched query: theme + up to 4 ticker names (strip -USD suffix for readability)
    query = theme
    if tickers:
        ticker_names = [t.replace("-USD", "") for t in tickers[:4]]
        query = f"{theme} {' '.join(ticker_names)}"

    tavily_articles = fetch_news_tavily(query, max_results)
    newsapi_articles = fetch_news_newsapi(query, max_results)

    # Merge and deduplicate by lowercased title
    seen_titles = set()
    merged = []
    for article in tavily_articles + newsapi_articles:
        key = article["title"].lower().strip()
        if key and key not in seen_titles:
            seen_titles.add(key)
            merged.append(article)

    if not merged:
        print("[News] Both sources failed — returning mock news.")
        return [
            {
                "source": "mock",
                "title": f"Mock headline: {theme} shows strong momentum",
                "url": "",
                "snippet": "Markets are reacting positively to recent developments.",
                "published_date": datetime.utcnow().isoformat(),
            }
        ]

    print(f"[News] Total merged articles: {len(merged)} "
          f"(Tavily={len(tavily_articles)}, NewsAPI={len(newsapi_articles)})")
    return merged


# ─── Step 2b: Price/Volume via yfinance ──────────────────────────────────────
def fetch_price_data(tickers: list[str], lookback_days: int = 90) -> dict:
    """
    Download OHLCV data for a list of tickers.
    Returns dict: { ticker: { "ohlcv": [...], "summary": {...} } }
    """
    end = datetime.utcnow()
    start = end - timedelta(days=lookback_days)
    print(f"[yfinance] Fetching price data for: {tickers}")

    results = {}
    for ticker in tickers:
        try:
            df = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                             end=end.strftime("%Y-%m-%d"), progress=False)
            if df.empty:
                raise ValueError("Empty dataframe")

            # Flatten MultiIndex if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = df.dropna()
            close = df["Close"]
            returns = close.pct_change().dropna()

            summary = {
                "ticker": ticker,
                "last_price": round(float(close.iloc[-1]), 4),
                "price_30d_ago": round(float(close.iloc[-30]) if len(close) >= 30 else float(close.iloc[0]), 4),
                "return_30d_pct": round(float((close.iloc[-1] / close.iloc[-30] - 1) * 100) if len(close) >= 30 else 0, 2),
                "volatility_30d_pct": round(float(returns.tail(30).std() * (252 ** 0.5) * 100), 2),
                "avg_volume_30d": int(df["Volume"].tail(30).mean()) if "Volume" in df.columns else 0,
                "data_points": len(df),
            }

            # Last 30 rows as lightweight OHLCV list
            ohlcv = df.tail(30)[["Open", "High", "Low", "Close", "Volume"]].reset_index()
            ohlcv["Date"] = ohlcv["Date"].astype(str)
            results[ticker] = {
                "summary": summary,
                "ohlcv": ohlcv.to_dict(orient="records"),
            }
            print(f"[yfinance] {ticker}: last={summary['last_price']}, 30d_ret={summary['return_30d_pct']}%")
        except Exception as e:
            print(f"[yfinance] ERROR for {ticker}: {e} — skipping.")
            results[ticker] = {
                "summary": {"ticker": ticker, "error": str(e)},
                "ohlcv": [],
            }
    return results


# ─── Step 3: Sentiment + Synthesis → Context Block ───────────────────────────
def simple_sentiment(text: str) -> str:
    """Rule-based sentiment: positive / negative / neutral."""
    positive_words = ["surge", "rally", "growth", "bullish", "gain", "strong",
                      "record", "rise", "soar", "outperform", "beat", "upside"]
    negative_words = ["crash", "drop", "bearish", "loss", "decline", "risk",
                      "sell-off", "downturn", "miss", "weak", "fall", "slump"]
    text_lower = text.lower()
    pos = sum(w in text_lower for w in positive_words)
    neg = sum(w in text_lower for w in negative_words)
    if pos > neg:
        return "positive"
    elif neg > pos:
        return "negative"
    return "neutral"


def build_context_block(theme: str, risk_tolerance: int,
                        articles: list[dict], price_data: dict) -> dict:
    """
    Synthesize news sentiment and price data into a single JSON context block
    ready to be passed to the actor/critic agents.
    """
    print("[Synthesis] Building context block...")

    # Sentiment on each article
    annotated_news = []
    sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
    for a in articles:
        sentiment = simple_sentiment(a["title"] + " " + a["snippet"])
        sentiment_counts[sentiment] += 1
        annotated_news.append({**a, "sentiment": sentiment})

    total = max(sum(sentiment_counts.values()), 1)
    overall_sentiment_score = round(
        (sentiment_counts["positive"] - sentiment_counts["negative"]) / total, 2
    )
    if overall_sentiment_score > 0.2:
        overall_sentiment = "bullish"
    elif overall_sentiment_score < -0.2:
        overall_sentiment = "bearish"
    else:
        overall_sentiment = "neutral"

    # Compact price summaries (drop raw OHLCV to keep prompt size down)
    price_summaries = {t: v["summary"] for t, v in price_data.items()}

    source_counts = {}
    for a in articles:
        src = a.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1

    context = {
        "theme": theme,
        "risk_tolerance": risk_tolerance,          # 1 (low) → 10 (high)
        "as_of": datetime.utcnow().isoformat(),
        "news": {
            "overall_sentiment": overall_sentiment,
            "sentiment_score": overall_sentiment_score,
            "sentiment_breakdown": sentiment_counts,
            "source_breakdown": source_counts,
            "articles": annotated_news,
        },
        "price_data": price_summaries,
    }

    print(f"[Synthesis] Done. Sentiment={overall_sentiment} ({overall_sentiment_score}), "
          f"sources={source_counts}, tickers={list(price_summaries.keys())}")
    return context


# ─── High-level convenience function ─────────────────────────────────────────
def gather_all_data(theme: str, risk_tolerance: int, tickers: list = None,
                    articles: list = None, lookback_days: int = 90) -> dict:
    """
    Entry point for the pipeline:  theme + risk_tolerance → context block.
    If tickers is provided (e.g. from agents.discover_tickers()), use those;
    otherwise fall back to the hardcoded THEME_TICKERS map.
    If articles is provided (already fetched), skip the news fetch to avoid a duplicate API call.
    lookback_days controls how much price history is fetched for the agent context
    and should match the user's selected investment horizon.
    """
    if not tickers:
        tickers = get_tickers_for_theme(theme)
    if articles is None:
        articles = fetch_news(theme)
    price_data = fetch_price_data(tickers, lookback_days=lookback_days)
    context = build_context_block(theme, risk_tolerance, articles, price_data)
    return context
