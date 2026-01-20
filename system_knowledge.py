"""
System Knowledge Base

Provides program knowledge for the conversational agent to answer user questions.
This is injected into the LLM context so it can explain how the system works.
"""

SYSTEM_KNOWLEDGE = """
## Trading System Knowledge Base

### What This Program Does
This program generates buy and sell order sheets for investment accounts.
It reads client holdings from an Excel file and stock prices from a CSV file,
then generates deterministic trade orders based on your specifications.

The key design principle is: "LLM interprets intent, deterministic code calculates numbers."
This means the AI understands what you want, but all actual calculations are done by
predictable, auditable code - ensuring reproducibility.

### How Order Generation Works
1. Sell orders are generated first (if any sell rules exist)
2. Cash from sells becomes available for buys
3. Buy orders calculate exact shares based on available cash
4. The cash floor is maintained (default 2%)
5. Orders are exported to CSV files ready for upload to your trading platform

### Supported Operations

**Buying:**
- Buy to target allocation (e.g., "buy to 2.5% of account value per stock")
- Buy specific dollar amounts (e.g., "buy $5,000 of GOOGL")
- Buy specific share counts (e.g., "buy 100 shares of AAPL")
- Skip stocks already owned above a threshold (e.g., "skip if I own 2% or more")
- Buy only enough to reach target (don't over-buy if partially owned)

**Selling:**
- Sell entire positions ("sell all LUMN")
- Sell partial positions by percentage ("sell 50% of COMM")
- Sell by dollar amount ("raise $50,000 cash")
- Sell by share count ("sell 100 shares")
- Sell cash equivalents to fund buys (automatic when configured)

**Account Filtering:**
- Filter by account value (min/max)
- Filter by specific account numbers
- Filter by holdings (only accounts that hold certain tickers)

**Cash Management:**
- Maintain minimum cash percentage (default 2%)
- Maintain minimum cash dollar amount
- Sell cash equivalents in order (largest first or smallest first)

### Cash Equivalents
Cash equivalents are tickers treated as liquid sources that can be sold to fund buys.
The list of cash equivalents is configured in config.json under the "cash_equivalents" key.
Common examples include money market funds and short-term Treasury ETFs.

### Quantity Types Explained
- **percent_of_account**: 0.025 = 2.5% of total account value (used for target allocations)
- **percent_of_position**: 0.5 = 50% of that specific holding (used for partial sells)
- **shares**: exact number of shares to buy or sell
- **dollars**: specific dollar amount to buy or sell
- **all**: entire position (used for complete liquidation)
- **to_target**: adjust to reach target allocation

### The Cash Floor
The cash floor ensures a minimum percentage of cash remains in each account after trades.
By default, it's set to 2%.

When generating buy orders, the system calculates:
available_cash = current_cash - (account_value × min_cash_percent)

So for a $100,000 account with 2% floor, $2,000 will always remain in cash.
You can change this in config.json or specify it in your trade request.

### How Sells Fund Buys
When you request buys and don't have enough cash:
1. System calculates total cash needed for all buy orders
2. Subtracts available cash (minus the cash floor requirement)
3. If there's a shortfall and you've enabled cash equivalent selling:
   - Sells cash equivalents starting with the largest position
   - Raises just enough cash to cover the shortfall
4. Generates buy orders with the now-available cash

### Default Specification
The default trade specification (no API key required):
- Buy to 2.5% target allocation for each stock on the buy list
- Skip any stocks already owned at 2% or more
- Sell cash equivalents (largest first) if needed to fund buys
- Maintain 2% cash floor

### Output Files
After generating orders, three files are created:
- **orders_*_SELL.csv**: Sell orders (execute these FIRST)
- **orders_*_BUY.csv**: Buy orders (execute AFTER sells settle)
- **orders_*_REPORT.txt**: Human-readable summary for review

Important: Always execute sell orders first and wait for settlement before executing buy orders.

### Required Input Files
**investment_data.xlsx** - Account holdings with required columns:
- Account Number
- Account Name (optional, also accepts 'Client Name')
- Symbol / CUSIP / ID
- Quantity
- Price / NAV
- Market Value

**stock_prices.csv** - Buy list with columns:
- TICKER: Stock symbol
- PRICE: Current price

### Commands You Can Use
- **exit** or **quit**: Exit the program
- **help**: Get help with what you can do
- **holdings** or **show holdings**: Display detailed holdings for all accounts
- **summary**: Show account summary
- **buy list** or **show buy list**: Show the current buy list with prices

### Configuration (config.json)
You can customize:
- **anthropic_api_key**: Your API key for custom specifications
- **default_excel_file**: Path to holdings file
- **default_prices_file**: Path to buy list/prices file
- **cash_equivalents**: List of tickers treated as cash equivalents
- **default_cash_floor_percent**: Minimum cash to maintain (0.02 = 2%)
- **default_target_allocation_percent**: Default buy target (0.025 = 2.5%)
- **default_skip_if_above_percent**: Skip threshold (0.02 = 2%)
"""

CAPABILITIES_SUMMARY = """
I can help you with:

1. **Generate Trade Orders**: Tell me what trades you want to make and I'll create the order sheets
   - "Buy all stocks on my buy list at 2.5% each"
   - "Sell all LUMN and COMM"
   - "Raise $50,000 cash"

2. **Answer Questions**: Ask me how the system works
   - "How does the cash floor work?"
   - "What are cash equivalents?"
   - "How do sells fund buys?"

3. **View Your Data**: See your current positions
   - "Show my holdings"
   - "Show account summary"
   - "Show the buy list"

4. **Settings**: Configure your API key
   - "Check API key" - see if you have an API key configured
   - "Set API key" - add or update your Anthropic API key

5. **Get Help**: I can explain any feature or option

Just tell me what you'd like to do in plain English!
"""

WELCOME_MESSAGE = """
================================================================================
   TRADING SYSTEM v2.0.0 - Conversational Mode
================================================================================

Hello! I'm your trading assistant. I can help you:
- Generate buy/sell order sheets from natural language instructions
- Answer questions about how the system works
- Show you your current holdings and account data

Just tell me what you'd like to do. For example:
- "Buy the stocks on my buy list at 2.5% each"
- "How does the cash floor work?"
- "Show my holdings"

Type 'exit' to quit.
================================================================================
"""
