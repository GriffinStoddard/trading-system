# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Trading System is a Python CLI tool for financial advisors that uses Claude to interpret natural language trading specifications and generate deterministic buy/sell order sheets for client investment accounts.

**Key design principle**: "LLM interprets intent, deterministic code calculates numbers." The LLM converts natural language to a structured ExecutionPlan JSON schema, then order generation is 100% deterministic with no LLM involvement - ensuring reproducibility and auditability.

## Commands

```bash
# Setup
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run
python main.py

# Build Windows executable
pip install pyinstaller
pyinstaller --onefile --console --name TradingSystem main.py
# Output: dist/TradingSystem.exe
```

**Release Process**: Update `VERSION` in main.py, commit, then `git tag v1.0.X && git push origin v1.0.X`. GitHub Actions auto-builds the release.

## Architecture

```
Natural Language → LLM Interpreter → ExecutionPlan (JSON) → Order Generator → CSV + Report
```

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point with interactive menu system |
| `models.py` | Data models: Account, Holding, AccountParser (reads Excel) |
| `execution_plan.py` | ExecutionPlan schema with BuyRule, SellRule, enums |
| `order_generator.py` | Deterministic order execution engine (no LLM) |
| `llm_interpreter.py` | Natural language → ExecutionPlan conversion via Anthropic API |
| `report_generator.py` | Human-readable trade summaries |
| `config.py` | Configuration management (config.json) |

## Data Flow

1. **Input**: `investment_data.xlsx` (Excel file, reads first sheet) + `stock_prices.csv` (buy list)
2. **Processing**: User chooses default plan OR enters custom natural language spec
3. **Output**: Timestamped CSV files (`orders_*_SELL.csv`, `orders_*_BUY.csv`) + `_REPORT.txt`

## Two Execution Modes

- **Default Mode**: No API key needed, uses built-in specification (2.5% target allocation, skip if >= 2% owned, sell cash equivalents if needed, 2% cash floor)
- **Custom Mode**: Requires Anthropic API key, interprets natural language specifications

## Configuration

Cash equivalents are configurable in `config.json` (default: BIL, USFR, PJLXX). These are treated as liquid cash sources that can be sold to fund buy orders.

## Dependencies

- `pandas` + `openpyxl` for Excel/CSV handling
- `anthropic` for Claude API (custom mode only)
