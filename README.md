# Trading System

A financial advisor desktop app that turns plain-English instructions into
buy/sell order sheets for client accounts. Claude interprets what you want;
deterministic code calculates every share and dollar — the same request always
produces the same orders.

## Run it

```bash
python app.py    # desktop app (recommended)
python main.py   # terminal version
```

The desktop app is a native window: portfolio sidebar (click any account for
its holdings), buy-list management with live price refresh, and a chat thread
where proposals appear as cards with order tables, pre-flight alerts, and
Confirm/Cancel buttons. Nothing is written to disk until you confirm.

## Quick Start (For End Users — Windows)

1. Download `TradingSystem-vX.Y.Z-windows.zip` from the [Releases](../../releases)
   page (or grab the latest `TradingSystem-windows` build from the
   [Actions](../../actions) tab — every push to `main` produces one).
2. Extract the zip and run **`TradingSystem.exe`** (the desktop app).
   `TradingSystemCLI.exe` is the optional terminal version.
3. **First launch:** Windows SmartScreen may show *"Windows protected your PC"*
   because the app isn't code-signed yet — click **More info → Run anyway**.
4. In the app, open **Settings** to paste your Anthropic API key and pick your
   holdings Excel file. That's it — there is no `config.json` to hand-edit; the
   app creates and manages its settings for you in `%APPDATA%\TradingSystem`.

### What you provide

| Input | Required | Where |
|-------|----------|-------|
| Anthropic API key | Yes (for natural-language mode) | Entered in the app's Settings |
| Client holdings Excel (`.xlsx`) | Yes | Picked via the in-app file chooser |
| Buy list (tickers + prices) | Yes | Managed in-app, or `refresh prices` from Yahoo |

Data views, buy-list edits, and the built-in `default` specification work with no
API key. Nothing is written to disk until you confirm a trade.

### Troubleshooting

- **Blank/empty window on launch** → install Microsoft's
  [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/consumer/).
  It's preinstalled on stock Windows 11, but some managed/enterprise images strip
  it. Install it, then relaunch.

### investment_data.xlsx Format

Excel file (reads the first sheet):

| Account Name | Account Number | Symbol / CUSIP / ID | Quantity | Price / NAV | Market Value |
|--------------|----------------|---------------------|----------|-------------|--------------|
| John Smith | 12345 | AAPL | 100 | 175.50 | 17550.00 |
| John Smith | 12345 | CASH | | | 25000.00 |
| Jane Doe | 67890 | GOOGL | 50 | 140.00 | 7000.00 |

### stock_prices.csv Format

```csv
TICKER,PRICE
PYPL,69.59
MU,208.00
GOOGL,255.08
```

## Usage

Just type what you want at the prompt:

- `Buy everything on the buy list at 2.5%, skip if I already own 2%`
- `Sell all AAPL and buy GOOGL with the proceeds`
- `Raise $50,000 cash, largest positions first, skip accounts under $25k`
- `How does the cash floor work?`

Every proposed trade shows a full preview (orders, totals, pre-flight alerts)
and asks for a yes/no confirmation before any files are written. Instead of
yes/no you can also revise the proposal — "make it 3%", "leave NVDA out" — and
the new preview shows exactly what changed versus the previous one.

Pre-flight checks run on every proposal and flag outsized liquidations (>50%
of an account), buy-list prices that diverge sharply from the holdings export
(stale data), and accounts that couldn't fund their planned buys.

### Instant commands (no API key needed)

| Command | What it does |
|---|---|
| `summary` | Portfolio overview by account |
| `holdings` | Detailed positions for every account |
| `buy list` / `prices` | Show the buy list (with a freshness stamp) |
| `refresh prices` | Pull live prices for the buy list (Yahoo Finance) |
| `add TICKER PRICE` | Add a ticker to the buy list |
| `update TICKER PRICE` | Change a ticker's price |
| `remove TICKER` | Remove a ticker |
| `default` | Run the built-in default specification |
| `help` / `exit` | Help / quit |

The built-in default specification: buy to 2.5% target per stock, skip stocks
already owned at ≥ 2%, skip buys under 1% of the account, sell cash equivalents
if needed, keep a 2% cash floor. All thresholds are configurable in config.json.

## Output Files

After you confirm, a date-named folder (e.g. `06-09-2026/`) is created with:

- `sell_order.csv` — sell orders (execute these **first**)
- `buy_order.csv` — buy orders (execute after sells settle)
- `trade_report.txt` — full human-readable audit report

---

## For Developers

### Project Structure

```
trading-system/
├── app.py                # Desktop app entry point (pywebview window)
├── gui_api.py            # JS↔Python bridge (the frontend's API)
├── gui/                  # Frontend: index.html, style.css, app.js (vanilla JS)
├── main.py               # CLI entry point + REPL
├── ui.py                 # Rich-based terminal UI (tables, panels, previews)
├── conversation_agent.py # Tool-use agent loop (Claude)
├── plan_schema.py        # ExecutionPlan JSON schema + planning guidance
├── config.py             # Configuration management
├── models.py             # Data models (Account, Holding, Excel parser)
├── execution_plan.py     # Structured plan schema (dataclasses)
├── order_generator.py    # Deterministic execution engine (no LLM)
├── report_generator.py   # Human-readable audit reports
├── system_knowledge.py   # Knowledge base for the agent
├── tests/                # pytest suite
├── requirements.txt
└── trading_system.spec   # PyInstaller config
```

### Local Development Setup

```bash
git clone https://github.com/YOUR_USERNAME/trading-system.git
cd trading-system
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
python main.py

# Run tests
pip install -r requirements-dev.txt
pytest tests/
```

### Building the Executables Locally

```bash
pip install pyinstaller
pyinstaller trading_system.spec
```

Produces `dist/TradingSystem` (desktop GUI, bundles the `gui/` frontend) and
`dist/TradingSystemCLI` (terminal version).

### Creating a Release

1. Update the `VERSION` in `main.py`
2. Commit your changes
3. Create and push a tag:
   ```bash
   git tag v3.0.0
   git push origin v3.0.0
   ```
4. GitHub Actions will automatically build the .exe and create a release

### Architecture

```
 "Sell all LUMN, buy GOOGL with the proceeds"
        │
        ▼
┌──────────────────────┐   Claude (claude-opus-4-8) — the model emits the
│  Conversation Agent  │   ExecutionPlan as a schema-guided tool call;
└──────────────────────┘   the handler validates it and feeds back errors
        │
        ▼
┌──────────────────────┐
│   Execution Plan     │   dataclasses — buy/sell rules, filters, cash mgmt
└──────────────────────┘
        │
        ▼
┌──────────────────────┐
│   Order Generator    │   100% deterministic — calculates exact shares
└──────────────────────┘
        │
        ▼
  preview → confirm → CSV + report
```

Key design decisions:

- **LLM interprets intent, deterministic code calculates numbers.** The model
  never does arithmetic; it only fills in a structured plan.
- **Schema-guided tool input.** The plan is produced as a tool call against a
  full JSON schema and validated deterministically; validation errors are fed
  back to the model so it self-corrects — no text parsing or markdown-stripping.
- **Human in the loop.** Plans are simulated and previewed; nothing is written
  without an explicit confirmation.

## License

Private/Internal Use Only
