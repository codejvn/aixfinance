import streamlit as st
import pandas as pd

from data_fetcher import gather_all_data

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Kappa",
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
    Kappa
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
        with st.spinner("Gathering market intelligence…"):
            context = gather_all_data(theme, risk_tolerance)
            context["user_preferences"] = ", ".join(selected_prefs)
            context["lookback_days"]     = HORIZON_MAP[horizon_label]
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
    st.markdown("""
    <div style="background:#1A1A1A; border:1px solid #2C5F2E; border-radius:8px;
                padding:2rem; text-align:center; margin-bottom:1rem;">
      <p style="color:#9CA3AF; margin:0; font-size:0.95rem;">
        Agent logic coming soon — the actor-critic ensemble will run here.
      </p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    st.divider()

    # ── Section 4: Backtest & Results ─────────────────────────────────────────
    st.markdown('<div class="section-heading"><h3 style="margin:0;color:#F0F0F0;">Backtest & Results</h3></div>',
                unsafe_allow_html=True)
    st.markdown("""
    <div style="background:#1A1A1A; border:1px solid #2C5F2E; border-radius:8px;
                padding:2rem; text-align:center; margin-bottom:1rem;">
      <p style="color:#9CA3AF; margin:0; font-size:0.95rem;">
        Equity curves and performance metrics will appear here once the agents
        have generated a portfolio.
      </p>
    </div>
    """, unsafe_allow_html=True)
