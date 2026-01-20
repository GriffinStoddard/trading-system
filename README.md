# Trading System

A financial advisor tool that uses natural language to generate buy/sell order sheets for client accounts.

## Quick Start (For End Users)

1. Download the latest release from the [Releases](../../releases) page
2. Extract the zip file to a folder
3. Rename `config.json.example` to `config.json`
4. Edit `config.json` and add your Anthropic API key
5. Place your `investment_data.xlsx` file in the same folder
6. Create or edit `stock_prices.csv` with your buy list
7. Run `TradingSystem.exe`

## Files You Need

| File | Required | Description |
|------|----------|-------------|
| `TradingSystem.exe` | Yes | The program |
| `config.json` | Yes | Your settings and API key |
| `investment_data.xlsx` | Yes | Your client account holdings |
| `stock_prices.csv` | Yes | Stocks available to buy with current prices |

### investment_data.xlsx Format

Excel file (reads the first sheet):

| Account Number | Client Name | Symbol / CUSIP / ID | Quantity | Price / NAV | Market Value |
|----------------|-------------|---------------------|----------|-------------|--------------|
| 12345 | John Smith | AAPL | 100 | 175.50 | 17550.00 |
| 12345 | John Smith | CASH | | | 25000.00 |
| 67890 | Jane Doe | GOOGL | 50 | 140.00 | 7000.00 |

### stock_prices.csv Format

```csv
TICKER,PRICE
PYPL,69.59
MU,208.00
GOOGL,255.08
```

## Usage

### Default Mode (No API Key Required for Basic Use)

The program has a built-in default specification:
- Buy to 2.5% target allocation per stock
- Skip stocks already owned at >= 2%
- Sell cash equivalents if needed
- Maintain 2% cash floor

### Custom Mode (Requires API Key)

Enter natural language specifications like:
- "Sell all AAPL and buy GOOGL with the proceeds"
- "Raise $50,000 cash by selling largest positions first"
- "Rebalance to 5% in each of AAPL, MSFT, GOOGL"

## Output Files

The program generates:
- `orders_YYYYMMDD_HHMMSS_SELL.csv` - Sell orders (execute first)
- `orders_YYYYMMDD_HHMMSS_BUY.csv` - Buy orders (execute after sells settle)
- `orders_YYYYMMDD_HHMMSS_REPORT.txt` - Human-readable summary

---

## For Developers

### Project Structure

```
trading_system/
├── main.py              # CLI entry point
├── config.py            # Configuration management
├── models.py            # Data models (Account, Holding)
├── execution_plan.py    # Structured plan schema
├── order_generator.py   # Deterministic execution engine
├── llm_interpreter.py   # Natural language → plan
├── report_generator.py  # Human-readable reports
├── requirements.txt     # Python dependencies
├── trading_system.spec  # PyInstaller config
├── .gitignore
├── .github/
│   └── workflows/
│       └── build.yml    # Auto-build on release
└── README.md
```

### Local Development Setup

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/trading-system.git
cd trading-system

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Run
python main.py
```

### Building the Executable Locally

```bash
pip install pyinstaller
pyinstaller --onefile --console --name TradingSystem main.py
```

The executable will be in `dist/TradingSystem.exe`

### Creating a Release

1. Update the `VERSION` in `main.py`
2. Commit your changes
3. Create and push a tag:
   ```bash
   git tag v1.0.1
   git push origin v1.0.1
   ```
4. GitHub Actions will automatically build the .exe and create a release

### Architecture

```
Natural Language Spec
        │
        ▼
┌───────────────────┐
│  LLM Interpreter  │  ← Converts to structured plan
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  Execution Plan   │  ← JSON schema (deterministic)
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  Order Generator  │  ← Calculates exact shares
└───────────────────┘
        │
        ▼
   CSV + Report
```

The key design decision: **LLM interprets intent, deterministic code calculates numbers.** This ensures reproducibility and auditability.

## License

Private/Internal Use Only
