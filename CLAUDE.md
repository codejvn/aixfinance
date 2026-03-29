# Project: Actor-Critic Multi-Agent Trading Bot (Perpetuals)

## Mission
We are building a consumer-facing web application that generates risk-adjusted thematic trading portfolios (specifically for perpetuals/crypto/RWAs) using a Cross-Model Adversarial Ensemble.

## Expected File Structure
- `app.py`: The Streamlit frontend and UI state management.
- `data_fetcher.py`: Functions to hit the Tavily and yfinance APIs.
- `agents.py`: All LLM logic (Claude Actor, GPT Actor, Critics, and Risk Analyst).
- `backtester.py`: The simulation logic to generate the equity curve.
- `requirements.txt`: Project dependencies.
- `.env`: API keys (do not commit this).

## Architecture Pipeline
1. **Input (Streamlit UI):** User inputs an asset class/industry (e.g., "AI", "Geopolitics", "Layer-1s") and selects a risk tolerance via a slider.
2. **Data Gathering (`data_fetcher.py`):** - Fetch recent news headlines using Tavily API.
   - Fetch historical price/volume data using `yfinance`.
3. **Sentiment & Synthesis:** Run sentiment analysis on the news and sync it with the numerical financial data into a clean JSON context block.
4. **The Actor-Critic Arena (`agents.py`):** - **Claude Actor:** Proposes a set of trades (Long/Short, Leverage).
   - **GPT Actor:** Proposes a competing set of trades.
   - **Claude Critic:** Brutally attacks GPT's proposal for risk flaws.
   - **GPT Critic:** Brutally attacks Claude's proposal for risk flaws.
5. **The Risk Analyst (Final Layer):** A final LLM call that reviews the proposals and critiques, synthesizes the best logic, and outputs the final execution JSON (Asset, Direction, Leverage, Stop-Loss, Allocation).
6. **Backtesting & Simulation (`backtester.py`):** Run the final JSON portfolio against historical data to simulate paper-trading performance.
7. **Performance Dashboard (`app.py`):** Use Plotly to display equity curves, win rates, max drawdown, and a final written LLM insight summarizing the bot's performance.

## Strict Coding Rules
1. **Never Refactor Without Asking:** Do not rewrite working functions just to make them "cleaner." We are moving fast.
2. **Robust Error Handling:** API calls (Tavily, OpenAI, Anthropic) MUST have try/except blocks so the UI doesn't crash if an endpoint times out. Return mock JSON if an API fails.
3. **Streamlit State:** Use `st.session_state` heavily to prevent the LLMs from re-running every time the user interacts with the UI.
4. **Logging:** Add print statements for every major API call so we can debug terminal output instantly.

## Commands
- Run the app: `streamlit run app.py`