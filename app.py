import streamlit as st
import json

from data_fetcher import gather_all_data, THEME_TICKERS

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AIX Finance — Multi-Agent Trading Bot",
    page_icon="📈",
    layout="wide",
)

st.title("📈 AIX Finance — Actor-Critic Multi-Agent Trading Bot")
st.caption("Cross-Model Adversarial Ensemble · Perpetuals / Crypto / RWAs")

# ─── Sidebar: Step 1 — User Inputs ───────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Strategy Parameters")

    # Asset class / theme
    predefined_themes = list(THEME_TICKERS.keys()) + ["Custom…"]
    theme_choice = st.selectbox("Asset Class / Theme", predefined_themes, index=2)
    if theme_choice == "Custom…":
        theme = st.text_input("Enter custom theme", placeholder="e.g. Quantum Computing")
    else:
        theme = theme_choice

    # Risk tolerance slider
    risk_tolerance = st.slider(
        "Risk Tolerance",
        min_value=1, max_value=10, value=5,
        help="1 = Capital preservation (low leverage, tight stops)  |  10 = Max aggression",
    )

    # Lookback period (used for backtest later)
    lookback_days = st.selectbox("Price Lookback (days)", [30, 60, 90, 180], index=2)

    st.divider()

    run_pipeline = st.button("🚀 Run Pipeline", type="primary", use_container_width=True)

    if st.button("🔄 Reset", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# ─── Main area: pipeline stages ──────────────────────────────────────────────
tab_data, tab_agents, tab_backtest = st.tabs(
    ["📊 Data & Context", "🤖 Agent Arena", "📉 Backtest & Dashboard"]
)

# ── Tab 1: Data & Context (Steps 2 + 3) ──────────────────────────────────────
with tab_data:
    if run_pipeline:
        if not theme:
            st.error("Please enter a theme before running.")
        else:
            with st.spinner(f"Gathering data for **{theme}** (risk={risk_tolerance})…"):
                context = gather_all_data(theme, risk_tolerance)
                st.session_state["context"] = context
                st.session_state["theme"] = theme
                st.session_state["risk_tolerance"] = risk_tolerance

    if "context" in st.session_state:
        ctx = st.session_state["context"]

        # ── News sentiment summary ────────────────────────────────────────────
        st.subheader("📰 News Sentiment")
        news = ctx["news"]
        sentiment_color = {"bullish": "green", "bearish": "red", "neutral": "orange"}
        color = sentiment_color.get(news["overall_sentiment"], "gray")
        st.markdown(
            f"Overall sentiment: **:{color}[{news['overall_sentiment'].upper()}]** "
            f"(score: `{news['sentiment_score']}`)"
        )

        col1, col2, col3 = st.columns(3)
        col1.metric("Positive", news["sentiment_breakdown"]["positive"])
        col2.metric("Neutral", news["sentiment_breakdown"]["neutral"])
        col3.metric("Negative", news["sentiment_breakdown"]["negative"])

        with st.expander("View articles"):
            for a in news["articles"]:
                badge = {"positive": "🟢", "negative": "🔴", "neutral": "🟡"}.get(a["sentiment"], "⚪")
                st.markdown(f"{badge} **{a['title']}**")
                st.caption(a["snippet"])
                st.divider()

        # ── Price data summary ────────────────────────────────────────────────
        st.subheader("💹 Price Data Summary")
        price_rows = []
        for ticker, summary in ctx["price_data"].items():
            if "error" not in summary:
                price_rows.append({
                    "Ticker": ticker,
                    "Last Price": summary.get("last_price"),
                    "30d Return %": summary.get("return_30d_pct"),
                    "30d Vol %": summary.get("volatility_30d_pct"),
                    "Avg Volume (30d)": summary.get("avg_volume_30d"),
                })
            else:
                price_rows.append({"Ticker": ticker, "Error": summary["error"]})

        if price_rows:
            import pandas as pd
            st.dataframe(pd.DataFrame(price_rows), use_container_width=True)

        # ── Full context JSON ─────────────────────────────────────────────────
        with st.expander("🔍 Raw context block (JSON)"):
            st.json(ctx)

    elif not run_pipeline:
        st.info("Configure parameters in the sidebar and click **Run Pipeline** to begin.")

# ── Tab 2: Agent Arena (Steps 4 + 5) ─────────────────────────────────────────
with tab_agents:
    if "context" not in st.session_state:
        st.info("Run the data pipeline first (Tab 1).")
    else:
        st.info("Agent Arena — coming in the next step (agents.py).")

# ── Tab 3: Backtest & Dashboard (Steps 6 + 7) ────────────────────────────────
with tab_backtest:
    if "context" not in st.session_state:
        st.info("Run the full pipeline first.")
    else:
        st.info("Backtest & Dashboard — coming after agents.py is wired up.")
