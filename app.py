import streamlit as st
import pandas as pd

import plotly.graph_objects as go

from data_fetcher import gather_all_data, fetch_news
from agents import (discover_tickers, generate_performance_insight,
                    run_claude_actor, run_gpt_actor,
                    run_gpt_critic, run_claude_critic, run_risk_analyst,
                    update_policy_from_backtest)
from policy import load_policy
from backtester import run_backtest

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="KappaPortfolios",
    page_icon="📈",
    layout="wide",
)

# ─── CSS ─────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  :root {
    --bg:        #0D0D0D;
    --surface:   #1A1A1A;
    --surface-2: #222222;
    --border:    #2C5F2E;
    --brg-mid:   #2C5F2E;
    --brg-light: #3D7A40;
    --text:      #F0F0F0;
    --muted:     #9CA3AF;
    --white:     #FFFFFF;
  }

  /* ── Backgrounds ── */
  [data-testid="stAppViewContainer"],
  [data-testid="stMain"] > div {
    background-color: var(--bg) !important;
  }
  [data-testid="stHeader"] {
    background-color: #000000 !important;
    border-bottom: 1px solid var(--border) !important;
  }
  #MainMenu, footer { visibility: hidden; }

  /* ── Typography ── */
  h1, h2, h3, h4, h5 { color: var(--text) !important; }
  p, label, span      { color: var(--text); }

  /* ── Form card ── */
  [data-testid="stForm"] {
    background-color: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    padding: 2rem !important;
  }

  /* ── Primary / submit buttons ── */
  button[kind="primaryFormSubmit"],
  [data-testid="stFormSubmitButton"] button,
  [data-testid="stButton"] button[kind="primary"] {
    background-color: var(--brg-mid) !important;
    color: var(--white) !important;
    border: none !important;
    border-radius: 6px !important;
    font-size: 1rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.04em !important;
  }
  button[kind="primaryFormSubmit"]:hover,
  [data-testid="stFormSubmitButton"] button:hover,
  [data-testid="stButton"] button[kind="primary"]:hover {
    background-color: var(--brg-light) !important;
  }

  /* ── Secondary buttons ── */
  [data-testid="stButton"] button[kind="secondary"] {
    border: 1.5px solid var(--border) !important;
    color: #A3C9A5 !important;
    background: transparent !important;
    border-radius: 6px !important;
  }

  /* ── Expander ── */
  [data-testid="stExpander"] {
    background-color: var(--surface-2) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
  }
  [data-testid="stExpander"] summary {
    color: var(--text) !important;
  }

  /* ── Dividers ── */
  hr {
    border-color: var(--border) !important;
    opacity: 0.4;
  }

  /* ── Section heading with green left-bar ── */
  .section-heading {
    border-left: 3px solid var(--brg-mid);
    padding-left: 0.75rem;
    margin-bottom: 1rem;
    color: var(--text);
  }

  /* ── Section card wrapper ── */
  .section-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1.75rem 2rem;
    margin-bottom: 2rem;
  }

  /* ── Dataframe ── */
  [data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
  }
</style>
""", unsafe_allow_html=True)

# ─── Mapping dicts ────────────────────────────────────────────────────────────
THEME_LABELS = {
    "Artificial Intelligence": "AI",
    "Crypto — Layer 1s":        "Layer-1s",
    "DeFi Protocols":           "DeFi",
    "Real World Assets (RWAs)": "RWAs",
    "Geopolitics & Defense":    "Geopolitics",
    "Energy":                   "Energy",
    "Biotech":                  "Biotech",
    "Something else...":        None,
}
RISK_MAP = {
    "Very Conservative": 2,
    "Conservative":      4,
    "Balanced":          6,
    "Aggressive":        8,
    "Max Risk":          10,
}
HORIZON_MAP = {"1 Month": 30, "3 Months": 90, "6 Months": 180}

# ─── Page header ─────────────────────────────────────────────────────────────
st.markdown("""
<div style="padding: 1.75rem 0 0.5rem 0;">
  <h1 style="font-size:2rem; font-weight:700; margin-bottom:0.2rem; color:#F0F0F0;
             letter-spacing:-0.01em;">
    KappaPortfolios
  </h1>
  <p style="color:#9CA3AF; font-size:0.95rem; margin:0;">
    Actor-Critic Multi-Agent Trading Portfolio
    &nbsp;·&nbsp; Perpetuals / Crypto / RWAs
  </p>
</div>
<hr style="margin:0.75rem 0 2rem 0;">
""", unsafe_allow_html=True)

# ─── Section 1: Input form ────────────────────────────────────────────────────
st.markdown('<div class="section-heading"><h3 style="margin:0;color:#F0F0F0;">Build your portfolio</h3></div>',
            unsafe_allow_html=True)

# Theme selector lives OUTSIDE the form so the custom text input appears immediately
col_theme, col_gap = st.columns([2, 3], gap="large")
with col_theme:
    theme_choice = st.selectbox(
        "What do you want to invest in?",
        options=list(THEME_LABELS.keys()),
        key="theme_choice",
    )
    if theme_choice == "Something else...":
        custom_theme_input = st.text_input(
            "Describe your investment theme",
            placeholder="e.g. Quantum Computing, Nuclear Energy, Space Tech…",
            key="custom_theme_input",
        )
    else:
        custom_theme_input = ""

st.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)

with st.form("portfolio_form"):
    col_left, col_right = st.columns(2, gap="large")

    with col_left:
        selected_prefs = st.multiselect(
            "Any preferences? *(optional)*",
            options=[
                "Long only — no shorts",
                "Limit leverage to 2x",
                "Include stablecoins as buffer",
                "Prioritise high liquidity assets",
            ],
        )

    with col_right:
        risk_label = st.select_slider(
            "How aggressive should we be?",
            options=list(RISK_MAP.keys()),
            value="Balanced",
        )
        horizon_label = st.radio(
            "Investment horizon",
            options=list(HORIZON_MAP.keys()),
            index=1,
            horizontal=True,
        )

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
    submitted = st.form_submit_button(
        "Run Analysis",
        use_container_width=True,
        type="primary",
    )

# Reset button
col_r, _ = st.columns([1, 5])
with col_r:
    if st.button("Reset", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

# ─── Pipeline trigger ─────────────────────────────────────────────────────────
if submitted:
    _choice = st.session_state.get("theme_choice", list(THEME_LABELS.keys())[0])
    theme = THEME_LABELS.get(_choice) or st.session_state.get("custom_theme_input", "").strip()
    if not theme:
        st.error("Please describe your investment theme before running.")
    else:
        risk_tolerance = RISK_MAP[risk_label]
        lookback_days  = HORIZON_MAP[horizon_label]
        with st.spinner("Gathering market intelligence…"):
            # Pass 1: Claude picks the best tickers for this theme
            tickers = discover_tickers(theme)
            # Pass 2: fetch news for the theme + those specific tickers
            articles = fetch_news(theme, tickers=tickers)
            # Pass 3: fetch price data (using the correct investment horizon) + build context
            context = gather_all_data(theme, risk_tolerance, tickers=tickers,
                                      articles=articles, lookback_days=lookback_days)
            context["user_preferences"] = ", ".join(selected_prefs)
            context["lookback_days"]     = lookback_days
        st.session_state["context"]        = context
        st.session_state["theme"]          = theme
        st.session_state["risk_tolerance"] = risk_tolerance
        st.rerun()

# ─── Sections revealed after analysis ────────────────────────────────────────
if "context" in st.session_state:
    ctx  = st.session_state["context"]
    news = ctx.get("news", {})

    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)
    st.divider()

    # ── Section 2: Market Intelligence ───────────────────────────────────────
    st.markdown('<div class="section-heading"><h3 style="margin:0;color:#F0F0F0;">Market Intelligence</h3></div>',
                unsafe_allow_html=True)

    # Sentiment badge
    sentiment = news.get("overall_sentiment", "neutral")
    badge = {
        "bullish": ("background:#166534; color:#D1FAD1", "BULLISH"),
        "bearish": ("background:#7F1D1D; color:#FEE2E2", "BEARISH"),
        "neutral": ("background:#374151; color:#D1D5DB", "NEUTRAL"),
    }.get(sentiment, ("background:#374151; color:#D1D5DB", sentiment.upper()))

    st.markdown(f"""
    <div style="display:flex; align-items:center; gap:1rem; margin-bottom:1.5rem;">
      <span style="{badge[0]}; font-weight:700; font-size:0.8rem;
                   letter-spacing:0.1em; padding:5px 16px; border-radius:20px;">
        {badge[1]}
      </span>
      <span style="color:#9CA3AF; font-size:0.9rem;">
        Sentiment for <strong style="color:#F0F0F0;">{ctx.get("theme","")}</strong>
        &nbsp;·&nbsp; score: {news.get("sentiment_score", "—")}
      </span>
    </div>
    """, unsafe_allow_html=True)

    # Asset snapshot
    st.markdown("<p style='color:#9CA3AF; font-size:0.8rem; text-transform:uppercase; "
                "letter-spacing:0.08em; margin-bottom:0.5rem;'>Asset Snapshot</p>",
                unsafe_allow_html=True)
    price_rows = []
    for ticker, summary in ctx.get("price_data", {}).items():
        if "error" not in summary:
            price_rows.append({
                "Ticker":           ticker,
                "Last Price":       summary.get("last_price"),
                "30d Return %":     summary.get("return_30d_pct"),
                "30d Volatility %": summary.get("volatility_30d_pct"),
                "Avg Volume (30d)": summary.get("avg_volume_30d"),
            })
        else:
            price_rows.append({"Ticker": ticker, "Error": summary["error"]})
    if price_rows:
        st.dataframe(pd.DataFrame(price_rows), use_container_width=True, hide_index=True)

    # Headlines expander
    with st.expander("Source headlines"):
        for a in news.get("articles", []):
            icon = {"positive": "🟢", "negative": "🔴", "neutral": "🟡"}.get(a.get("sentiment"), "⚪")
            src  = f"`[{a['source']}]`" if a.get("source") else ""
            st.markdown(f"{icon} **{a['title']}** {src}")
            st.caption(a.get("snippet", ""))
            st.divider()

    if st.checkbox("Show raw data (developer)", key="raw_data"):
        st.json(ctx)

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    st.divider()

    # ── Section 3: Agent Arena ────────────────────────────────────────────────
    st.markdown('<div class="section-heading"><h3 style="margin:0;color:#F0F0F0;">Agent Arena</h3></div>',
                unsafe_allow_html=True)

    if st.button("🤖 Run Agent Arena", type="primary", use_container_width=False):
        ctx = st.session_state["context"]
        with st.status("Running Actor-Critic Arena…", expanded=True) as status:
            st.write("🔵 Claude Actor proposing trades…")
            claude_actor = run_claude_actor(ctx)

            st.write("🟢 GPT Actor proposing trades…")
            gpt_actor = run_gpt_actor(ctx)

            st.write("🔴 GPT Critic reviewing Claude's proposal…")
            gpt_critic = run_gpt_critic(claude_actor, ctx)

            st.write("🟡 Claude Critic reviewing GPT's proposal…")
            claude_critic = run_claude_critic(gpt_actor, ctx)

            st.write("⚖️ Risk Analyst synthesising final portfolio…")
            arena_result = run_risk_analyst(ctx, claude_actor, gpt_actor, claude_critic, gpt_critic)
            arena_result["debug"] = {
                "claude_actor":  claude_actor,
                "gpt_actor":     gpt_actor,
                "gpt_critic":    gpt_critic,
                "claude_critic": claude_critic,
            }
            status.update(label="Arena complete!", state="complete", expanded=False)

        st.session_state["arena_result"] = arena_result

    if "arena_result" in st.session_state:
        result = st.session_state["arena_result"]
        debug  = result.get("debug", {})

        # ── Final portfolio ───────────────────────────────────────────────
        st.markdown("<p style='color:#9CA3AF; font-size:0.8rem; text-transform:uppercase; "
                    "letter-spacing:0.08em; margin-bottom:0.5rem;'>Final Portfolio</p>",
                    unsafe_allow_html=True)

        col1, col2, col3 = st.columns(3)
        col1.metric("Risk Level",  result.get("risk_level", "—"))
        col2.metric("Confidence",  f"{result.get('confidence_score', 0):.0%}")
        col3.metric("Positions",   len(result.get("portfolio", [])))

        st.markdown(f"<p style='color:#9CA3AF; font-size:0.9rem;'>{result.get('overall_strategy', '')}</p>",
                    unsafe_allow_html=True)

        portfolio = result.get("portfolio", [])
        if portfolio:
            df = pd.DataFrame(portfolio)
            cols = ["asset", "direction", "leverage", "stop_loss_pct", "allocation_pct", "rationale"]
            df = df[[c for c in cols if c in df.columns]]
            df.columns = [c.replace("_", " ").title() for c in df.columns]
            st.dataframe(df, use_container_width=True, hide_index=True)

        st.divider()

        # ── Actor proposals (collapsed) ───────────────────────────────────
        col_a, col_b = st.columns(2)
        with col_a:
            with st.expander("🔵 Claude Actor", expanded=False):
                ca = debug.get("claude_actor", {})
                st.caption(ca.get("thesis", ""))
                if ca.get("proposed_trades"):
                    st.dataframe(pd.DataFrame(ca["proposed_trades"]), use_container_width=True, hide_index=True)

        with col_b:
            with st.expander("🟢 GPT Actor", expanded=False):
                ga = debug.get("gpt_actor", {})
                st.caption(ga.get("thesis", ""))
                if ga.get("proposed_trades"):
                    st.dataframe(pd.DataFrame(ga["proposed_trades"]), use_container_width=True, hide_index=True)

        # ── Critic verdicts (collapsed) ───────────────────────────────────
        col_c, col_d = st.columns(2)
        with col_c:
            with st.expander("🔴 GPT Critic (vs Claude)", expanded=False):
                gc = debug.get("gpt_critic", {})
                st.caption(gc.get("verdict_rationale", ""))
                if gc.get("critiques"):
                    st.dataframe(pd.DataFrame(gc["critiques"]), use_container_width=True, hide_index=True)

        with col_d:
            with st.expander("🟡 Claude Critic (vs GPT)", expanded=False):
                cc = debug.get("claude_critic", {})
                st.caption(cc.get("verdict_rationale", ""))
                if cc.get("critiques"):
                    st.dataframe(pd.DataFrame(cc["critiques"]), use_container_width=True, hide_index=True)

        with st.expander("Raw arena output (JSON)"):
            st.json({k: v for k, v in result.items() if k != "debug"})

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    st.divider()

    # ── Section 4: Backtest & Results ─────────────────────────────────────────
    st.markdown('<div class="section-heading"><h3 style="margin:0;color:#F0F0F0;">Backtest & Results</h3></div>',
                unsafe_allow_html=True)

    if "arena_result" not in st.session_state:
        st.markdown("""
        <div style="background:#1A1A1A; border:1px solid #2C5F2E; border-radius:8px;
                    padding:2rem; text-align:center; margin-bottom:1rem;">
          <p style="color:#9CA3AF; margin:0; font-size:0.95rem;">
            Run the Agent Arena first to generate a portfolio.
          </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        if st.button("📉 Run Backtest & Generate Insight", type="primary", use_container_width=False):
            portfolio = st.session_state["arena_result"].get("portfolio", [])
            articles  = st.session_state["context"].get("news", {}).get("articles", [])
            lookback  = st.session_state["context"].get("lookback_days", 90)
            with st.spinner("Simulating portfolio performance…"):
                bt = run_backtest(portfolio, articles=articles, lookback_days=lookback)
                st.session_state["backtest"] = bt
            with st.spinner("Generating performance insight…"):
                insight = generate_performance_insight(
                    portfolio,
                    bt["metrics"],
                    st.session_state["context"],
                )
                st.session_state["insight"] = insight
            with st.spinner("Updating policy rulebook…"):
                policy_change = update_policy_from_backtest(
                    st.session_state["context"].get("theme", ""),
                    portfolio,
                    bt["metrics"],
                )
                st.session_state["policy_change"] = policy_change

        if "backtest" in st.session_state:
            bt      = st.session_state["backtest"]
            metrics = bt["metrics"]

            # ── Metrics row ───────────────────────────────────────────────
            c1, c2, c3, c4 = st.columns(4)
            ret = metrics["total_return_pct"]
            c1.metric("Total Return",  f"{ret:+.2f}%",
                      delta=f"{ret:+.2f}%", delta_color="normal")
            c2.metric("Max Drawdown",  f"{metrics['max_drawdown_pct']:.2f}%")
            c3.metric("Win Rate",      f"{metrics['win_rate_pct']:.1f}%")
            c4.metric("Sharpe Ratio",  f"{metrics['sharpe_ratio']:.2f}")

            st.markdown(
                f"<p style='color:#9CA3AF; font-size:0.85rem;'>"
                f"${metrics['initial_capital']:,.0f} → "
                f"<strong style='color:#F0F0F0;'>${metrics['final_capital']:,.2f}</strong>"
                f" over {metrics['trading_days']} trading days</p>",
                unsafe_allow_html=True,
            )

            # ── Equity curve ──────────────────────────────────────────────
            eq   = bt["equity_curve"]
            dates  = [p["date"]  for p in eq]
            values = [p["value"] for p in eq]

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=dates, y=values,
                mode="lines",
                line=dict(color="#3D7A40", width=2),
                fill="tozeroy",
                fillcolor="rgba(61,122,64,0.08)",
            ))
            fig.update_layout(
                paper_bgcolor="#1A1A1A",
                plot_bgcolor="#1A1A1A",
                font=dict(color="#F0F0F0"),
                margin=dict(l=0, r=0, t=20, b=0),
                xaxis=dict(gridcolor="#2A2A2A", color="#9CA3AF", showgrid=True),
                yaxis=dict(gridcolor="#2A2A2A", color="#9CA3AF",
                           tickprefix="$", showgrid=True),
                showlegend=False,
                height=320,
            )
            st.plotly_chart(fig, use_container_width=True)

            # ── Per-position breakdown ────────────────────────────────────
            pos_results = bt.get("position_results", [])
            if pos_results:
                st.markdown("<p style='color:#9CA3AF; font-size:0.8rem; text-transform:uppercase; "
                            "letter-spacing:0.08em; margin-bottom:0.5rem;'>Position Breakdown</p>",
                            unsafe_allow_html=True)
                df_pos = pd.DataFrame(pos_results)
                df_pos.columns = [c.replace("_", " ").title() for c in df_pos.columns]
                st.dataframe(df_pos, use_container_width=True, hide_index=True)

            # ── LLM insight ───────────────────────────────────────────────
            if "insight" in st.session_state:
                st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
                st.markdown(
                    f"<div style='background:#1A1A1A; border:1px solid #2C5F2E; "
                    f"border-radius:8px; padding:1.25rem 1.5rem;'>"
                    f"<p style='color:#9CA3AF; font-size:0.75rem; text-transform:uppercase; "
                    f"letter-spacing:0.08em; margin:0 0 0.5rem 0;'>AI Insight</p>"
                    f"<p style='color:#F0F0F0; font-size:0.95rem; line-height:1.6; margin:0;'>"
                    f"{st.session_state['insight']}</p></div>",
                    unsafe_allow_html=True,
                )

            # ── Policy update display ─────────────────────────────────────
            if "policy_change" in st.session_state:
                pc  = st.session_state["policy_change"]
                old = pc.get("old_rules", {})
                new = pc.get("new_rules", {})

                lev_old   = old.get("max_leverage")
                lev_new   = new.get("max_leverage")
                alloc_old = old.get("max_allocation_pct")
                alloc_new = new.get("max_allocation_pct")

                if lev_old is None or lev_new is None:
                    lev_delta = f"— {lev_new}x" if lev_new is not None else "— unknown"
                else:
                    lev_old, lev_new = float(lev_old), float(lev_new)
                    lev_delta = (f"▼ {lev_old}x → {lev_new}x" if lev_new < lev_old else
                                 f"▲ {lev_old}x → {lev_new}x" if lev_new > lev_old else
                                 f"— unchanged ({lev_new}x)")

                if alloc_old is None or alloc_new is None:
                    alloc_delta = f"— {alloc_new}%" if alloc_new is not None else "— unknown"
                else:
                    alloc_old, alloc_new = float(alloc_old), float(alloc_new)
                    alloc_delta = (f"▼ {alloc_old}% → {alloc_new}%" if alloc_new < alloc_old else
                                   f"▲ {alloc_old}% → {alloc_new}%" if alloc_new > alloc_old else
                                   f"— unchanged ({alloc_new}%)")

                with st.expander(
                    f"📋 Policy rulebook updated — {pc.get('sector_key', 'sector')}",
                    expanded=True,
                ):
                    col_l, col_r = st.columns(2)
                    col_l.metric("Max Leverage",    lev_delta)
                    col_r.metric("Max Allocation",  alloc_delta)
                    if new.get("notes"):
                        st.caption(f"**Reason:** {new['notes']}")

            # ── Current rulebook ──────────────────────────────────────────
            with st.expander("📖 View full policy rulebook (policy.json)", expanded=False):
                st.json(load_policy())
