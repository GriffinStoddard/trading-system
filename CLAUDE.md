# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Trading System is a Python CLI tool for financial advisors. The advisor describes trades in natural language; Claude converts the request into a structured ExecutionPlan (emitted as a schema-guided tool call, validated deterministically with error feedback to the model), and order generation is 100% deterministic with no LLM involvement — ensuring reproducibility and auditability.

**Key design principle**: "LLM interprets intent, deterministic code calculates numbers."

## Commands

```bash
# Setup
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run
python app.py    # desktop GUI (pywebview window)
python main.py   # terminal version

# Test
pip install -r requirements-dev.txt
pytest tests/

# Build both executables (GUI + CLI) — uses the platform-aware spec
pip install "pyinstaller>=6.0" "pyinstaller-hooks-contrib>=2024.0"
pyinstaller trading_system.spec
# Windows output: dist/TradingSystem.exe (windowed GUI) + dist/TradingSystemCLI.exe (console)
# macOS output:   dist/TradingSystem.app + dist/TradingSystemCLI
```

**CI / Release** (`.github/workflows/build.yml`, runs on `windows-latest`):
- **Every push to `main`** (or a manual *Run workflow*) builds both `.exe`s and uploads them as the downloadable `TradingSystem-windows` artifact on the Actions run — no tag required.
- **Pushing a `v*` tag** additionally zips the exes and attaches them to a GitHub Release.

**Release Process**: Update `VERSION` in main.py, commit, then `git tag v3.6.X && git push origin v3.6.X`. GitHub Actions auto-builds the release. The tag must start with `v` to trigger the workflow.

## Architecture

```
Natural Language → Conversation Agent (Claude tool-use loop)
                   → ExecutionPlan (strict JSON schema tool input)
                   → Order Generator (deterministic)
                   → preview → user confirms → CSV + report
```

| File | Purpose |
|------|---------|
| `app.py` | Desktop app entry point — pywebview window |
| `gui_api.py` | JS↔Python bridge: serializes AgentReply/state to JSON; chat has its own lock so views stay responsive during LLM calls |
| `gui/` | Frontend (index.html, style.css, app.js — vanilla JS, no CDN; talks to `window.pywebview.api.*`) |
| `main.py` | CLI entry point, REPL, order export, buy-list editing |
| `ui.py` | Rich-based terminal UI — all rendering lives here |
| `conversation_agent.py` | Tool-use agent loop; local commands; confirmation flow |
| `plan_schema.py` | JSON schema for ExecutionPlan (strict tool input) + planning guidance |
| `price_service.py` | Live buy-list prices via yfinance (`refresh prices` command) |
| `sanity_checks.py` | Deterministic pre-flight alerts (large sells, stale prices, underfunded buys) |
| `models.py` | Data models: Account, Holding, AccountParser (reads Excel) |
| `execution_plan.py` | ExecutionPlan dataclasses with BuyRule, SellRule, enums |
| `order_generator.py` | Deterministic order execution engine (no LLM) |
| `report_generator.py` | Human-readable trade reports |
| `system_knowledge.py` | Knowledge base injected into the agent's system prompt |
| `config.py` | Configuration management (config.json) |

## How the agent works

- One Claude conversation (model from config, default `claude-opus-4-8`) with two tools:
  - `propose_execution_plan` — input schema = `EXECUTION_PLAN_SCHEMA` (NOT `strict: true`: the compiled grammar exceeds the API's size limit and 400s). The handler validates tickers and `from_dict()`, simulates via OrderGenerator, stages the result for confirmation, and returns a summary to the model.
  - `get_account_details` — position-level drill-down for one account.
- Local commands (summary, holdings, buy list, add/update/remove, default, help, exit) are handled without any API call — see `ConversationAgent.handle_command` and the buy-list editing in `main.py`.
- Confirmation (yes/no) is a deterministic local state machine; the model never executes trades. A non-yes/no answer is treated as a revision: the previous simulation is kept in `state.last_simulation`, and the next proposed plan's preview includes a diff against it.
- Every simulation runs `sanity_checks.run_sanity_checks()` — advisory alerts shown in the preview panel and passed to the model in the tool result.
- The system prompt carries the knowledge base + full portfolio context and uses prompt caching (`cache_control: ephemeral`).

## Data Flow

1. **Input**: `investment_data.xlsx` (Excel, first sheet) + `stock_prices.csv` (buy list)
2. **Processing**: natural language → plan → simulation → preview → confirmation
3. **Output**: date-named folder (e.g. `06-09-2026/`) with `sell_order.csv`, `buy_order.csv`, `trade_report.txt`

## Configuration

`config.json`: `anthropic_api_key`, `model`, `advisor_name`, cash equivalents (default: BIL, USFR, PJLXX, JAAA — treated as liquid cash sources), and the default-spec thresholds (target allocation, skip threshold, cash floor, min buy).

Without an API key the app still works for data views, buy-list edits, and the `default` specification.

## Dependencies

- `pandas` + `openpyxl` for Excel/CSV handling
- `anthropic` for the Claude API (natural language mode only)
- `rich` for the terminal UI

## Testing notes

- `tests/` covers the deterministic engine extensively and the agent's local logic (commands, confirmation flow, tool handlers). No test makes a network call — agent tests set `agent.api_key = ""` and call tool handlers directly.
