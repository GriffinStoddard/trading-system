"""
System Knowledge Base

Program knowledge injected into the agent's system prompt so it can answer
questions about how the system works.
"""

SYSTEM_KNOWLEDGE = """
### What This Program Does
This program generates buy and sell order sheets for client investment accounts.
It reads holdings from an Excel file and stock prices from a CSV buy list, then
generates deterministic trade orders from the advisor's instructions.

The key design principle: "LLM interprets intent, deterministic code calculates
numbers." The AI translates what the advisor wants into a structured plan, but
every share count and dollar amount is computed by predictable, auditable code —
the same inputs always produce the same orders.

### How Order Generation Works
1. Sell orders are generated first (cash from sells funds buys)
2. Buy orders compute exact whole-share counts from available cash
3. The cash floor is maintained (default 2% of account value)
4. A preview is shown and the advisor confirms before any files are written
5. Orders are exported as CSVs ready for upload to the trading platform

### Supported Operations

**Buying:**
- Buy to a target allocation ("buy to 2.5% of account value per stock")
- Buy dollar amounts or share counts
- Skip stocks already owned above a threshold ("skip if I own 2% or more")
- Buy only enough to reach the target (top up, don't over-buy)
- Skip buys smaller than a minimum fraction of the account (default 1%)

**Selling:**
- Sell entire positions, partial percentages, dollar amounts, or share counts
- Raise cash across all holdings ("raise $50,000, largest positions first")
- Constraints: minimum shares remaining, max percent of any position
- Sell cash equivalents automatically to fund buys
- Sell cash equivalents directly to move them to cash ("sell all cash
  equivalents", "raise $50k by selling cash equivalents") — a standalone sell,
  not just funding buys

**Conditional sell-then-buy:**
- "Sell all GOOGL, buy AAPL with the proceeds" — the buy only runs in accounts
  that actually sold GOOGL, funded by those proceeds

**Account filtering:**
- By account value (min/max), account numbers, held tickers
- By client name (include or exclude, partial match, case-insensitive)
- Per-rule filters: different sell rules can target different account subsets

**Cash management:**
- Minimum cash percentage and/or dollar floor per account
- Cash equivalents sold largest-first (or smallest-first) when funding buys

### Cash Equivalents
Cash equivalents are tickers treated as liquid cash sources (money market funds,
short-term Treasury ETFs). They can be sold automatically to fund buys. The list
is configured in config.json under "cash_equivalents".

### The Cash Floor
The cash floor keeps a minimum fraction of each account in cash after trades
(default 2%). Available cash for buys = current cash − (account value × floor).
For a $100,000 account with a 2% floor, $2,000 always stays in cash.

### How Sells Fund Buys
If buys need more cash than is available above the floor and cash-equivalent
selling is enabled, the system sells cash equivalents (largest position first),
raising just enough to cover the shortfall, then sizes the buy orders.

### Default Specification
The built-in default (works without an API key):
- Buy to 2.5% target allocation for each buy-list stock
- Skip stocks already owned at 2% or more
- Skip buys under 1% of the account
- Sell cash equivalents (largest first) if needed
- Maintain a 2% cash floor

### Output Files
After the advisor confirms, three files are written to a date-named folder
(e.g. 06-09-2026/):
- **sell_order.csv** — execute these FIRST
- **buy_order.csv** — execute AFTER sells settle
- **trade_report.txt** — full human-readable audit report

### Required Input Files
**investment_data.xlsx** — holdings with columns: Account Number, Account Name
(optional), Symbol / CUSIP / ID, Quantity, Price / NAV, Market Value.
**stock_prices.csv** — buy list with TICKER and PRICE columns.

### Commands
summary, holdings, buy list, add TICKER PRICE, update TICKER PRICE,
remove TICKER, default, api key, help, exit.

### Configuration (config.json)
anthropic_api_key, model, advisor_name, default_excel_file, default_prices_file,
cash_equivalents, default_cash_floor_percent (0.02),
default_target_allocation_percent (0.025), default_skip_if_above_percent (0.02),
default_min_buy_percent (0.01).
"""

CAPABILITIES_SUMMARY = """
I can help you with:

1. **Generate trade orders** — describe the trades in plain English
   - "Buy everything on my buy list at 2.5% each"
   - "Sell all LUMN and COMM, put the proceeds into GOOGL"
   - "Raise $50,000 cash, skip accounts under $25k"

2. **Answer questions** — "How does the cash floor work?"

3. **Show your data** — summary, holdings, buy list

4. **Manage the buy list** — add NVDA 900, update AAPL 250, remove MSFT

Trades always show a preview and require your yes/no confirmation before any
order files are written.
"""

WELCOME_MESSAGE = """
Trading System — Conversational Mode

Describe what you want in plain English and I'll generate the order sheets,
or ask me how anything works. Type 'help' for commands, 'exit' to quit.
"""
