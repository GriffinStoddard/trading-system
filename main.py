#!/usr/bin/env python3
"""
Trading System — Main CLI Application

A financial advisor tool: describe trades in plain English, Claude turns the
request into a structured execution plan, and deterministic code generates the
buy/sell order sheets.

Usage:
    python main.py
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from models import AccountParser
from config import load_config, get_api_key, get_investment_data_path, get_exports_dir
import paths
import ui

VERSION = "3.6.0"


def get_base_path() -> Path:
    """Base path for bundled assets (design/, gui/) — NOT for data files.

    Data lives in paths.user_data_dir(); exports in config.get_exports_dir().
    """
    return paths.app_assets_dir()


def play_startup_sound():
    """Play the startup sound in the background (macOS only, best-effort)."""
    try:
        import subprocess
        import threading

        sound_path = get_base_path() / "design" / "trade_start_sound.mp3"
        if sound_path.exists() and sys.platform == "darwin":
            threading.Thread(
                target=lambda: subprocess.run(
                    ["afplay", str(sound_path)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
                daemon=True,
            ).start()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_stock_prices(prices_file: str) -> tuple[dict[str, float], list[str]]:
    """Load the buy list (ticker -> price) from CSV in the user data dir."""
    full_path = paths.user_data_dir() / prices_file
    if not full_path.exists():
        return {}, []

    df = pd.read_csv(full_path)
    prices, buy_list = {}, []
    for _, row in df.iterrows():
        ticker = str(row["TICKER"]).strip().upper()
        try:
            price = float(row["PRICE"])
        except (ValueError, TypeError):
            continue
        if price > 0:
            prices[ticker] = price
            buy_list.append(ticker)
    return prices, buy_list


def friendly_load_error(error: Exception) -> str:
    """Convert a data-loading exception into an actionable message."""
    s = str(error).lower()
    if isinstance(error, FileNotFoundError) or "no such file" in s:
        return "File not found — check the path in config.json."
    if isinstance(error, PermissionError) or "permission denied" in s:
        return "Permission denied — the file may be open in Excel. Close it and retry."
    for col in ("account number", "symbol", "quantity", "price", "market value"):
        if col in s:
            return f"The Excel file is missing the required '{col.title()}' column."
    if "worksheet" in s or "sheet" in s:
        return "Could not read the worksheet — make sure it's a valid .xlsx file."
    if isinstance(error, pd.errors.EmptyDataError):
        return "The file is empty."
    return str(error)


# ---------------------------------------------------------------------------
# Order export
# ---------------------------------------------------------------------------

ORDER_COLUMNS = ["Account Number", "Security", "Action", "Share Quantity", "Dollar Amount"]


def export_orders(sell_orders: list, buy_orders: list) -> tuple[str, str, Path]:
    """Write orders to CSV files in a date-named subfolder.

    Returns (sell_file, buy_file, absolute_folder) — the relative names are used
    in the report text, the absolute folder is where the report gets written.

    A second export on the same day must never clobber the first: if the date
    folder already holds order files, a timestamped sibling folder is used.
    """
    exports_root = get_exports_dir()
    exports_root.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%m-%d-%Y")
    folder = exports_root / date_str
    existing = ("sell_order.csv", "buy_order.csv", "trade_report.txt")
    if folder.exists() and any((folder / f).exists() for f in existing):
        folder = exports_root / f"{date_str}_{datetime.now().strftime('%H-%M-%S')}"
    folder.mkdir(exist_ok=True)

    def to_frame(orders):
        if not orders:
            return pd.DataFrame(columns=ORDER_COLUMNS)
        return pd.DataFrame([{
            "Account Number": o.account_num,
            "Security": o.security,
            "Action": o.action,
            "Share Quantity": o.shares,
            "Dollar Amount": "",
        } for o in orders])

    to_frame(sell_orders).to_csv(folder / "sell_order.csv", index=False)
    to_frame(buy_orders).to_csv(folder / "buy_order.csv", index=False)
    return f"{folder.name}/sell_order.csv", f"{folder.name}/buy_order.csv", folder


# ---------------------------------------------------------------------------
# Buy list editing (local commands: add / update / remove)
# ---------------------------------------------------------------------------

def edit_buy_list(command: str, args: list[str], prices_file: str) -> bool:
    """Apply an add/update/remove command to the prices CSV. Returns True if changed."""
    path = paths.user_data_dir() / prices_file
    df = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=["TICKER", "PRICE"])

    if command == "remove":
        if len(args) != 1:
            ui.warn("Usage: remove TICKER")
            return False
        ticker = args[0].upper()
        if ticker not in df["TICKER"].values:
            ui.warn(f"{ticker} is not on the buy list.")
            return False
        df = df[df["TICKER"] != ticker]
        df.to_csv(path, index=False)
        ui.success(f"Removed {ticker} from the buy list.")
        return True

    # add / update
    if len(args) != 2:
        ui.warn(f"Usage: {command} TICKER PRICE")
        return False
    ticker = args[0].upper()
    try:
        price = float(args[1].lstrip("$"))
    except ValueError:
        ui.warn(f"'{args[1]}' is not a valid price.")
        return False
    if price <= 0:
        ui.warn("Price must be positive.")
        return False

    exists = ticker in df["TICKER"].values
    if command == "add" and exists:
        ui.warn(f"{ticker} already exists — use `update {ticker} {price}` instead.")
        return False
    if exists:
        df.loc[df["TICKER"] == ticker, "PRICE"] = price
        ui.success(f"Updated {ticker} to ${price:,.2f}.")
    else:
        df = pd.concat([df, pd.DataFrame({"TICKER": [ticker], "PRICE": [price]})],
                       ignore_index=True)
        ui.success(f"Added {ticker} at ${price:,.2f}.")
    df.to_csv(path, index=False)
    return True


# ---------------------------------------------------------------------------
# Live price refresh
# ---------------------------------------------------------------------------

def prices_as_of(prices_file: str) -> str:
    """Freshness stamp for the buy list, from the price file's mtime."""
    path = paths.user_data_dir() / prices_file
    if not path.exists():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%m/%d %H:%M")


def refresh_prices(buy_list: list[str], old_prices: dict, prices_file: str) -> bool:
    """Fetch live prices for the buy list and update the CSV. Returns True if updated."""
    if not buy_list:
        ui.warn("The buy list is empty — nothing to refresh.")
        return False

    try:
        with ui.working("Fetching live prices..."):
            from price_service import fetch_live_prices
            live, failed = fetch_live_prices(buy_list)
    except ImportError:
        ui.error("yfinance is not installed — run: pip install yfinance")
        return False
    except ConnectionError as e:
        ui.error(str(e))
        return False

    path = paths.user_data_dir() / prices_file
    df = pd.read_csv(path)
    for ticker, price in live.items():
        df.loc[df["TICKER"] == ticker, "PRICE"] = price
    df.to_csv(path, index=False)

    for ticker in buy_list:
        if ticker in live:
            old = old_prices.get(ticker, 0)
            change = ((live[ticker] - old) / old * 100) if old else 0
            ui.success(f"{ticker}: ${old:,.2f} → ${live[ticker]:,.2f} ({change:+.1f}%)")
    for ticker in failed:
        ui.warn(f"{ticker}: no quote found — kept previous price")
    return True


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_reply(reply, agent, prices_file: str):
    """Render an AgentReply via the UI layer."""
    if reply.view == "help":
        ui.console.print(ui.help_panel())
    elif reply.view == "summary":
        ui.console.print(ui.summary_table(agent.accounts))
    elif reply.view == "holdings":
        ui.console.print(ui.holdings_view(agent.accounts))
    elif reply.view == "buy_list":
        ui.console.print(ui.buy_list_table(agent.buy_list, agent.stock_prices,
                                           as_of=prices_as_of(prices_file)))

    if reply.preview:
        plan, analyses, sell_orders, buy_orders = reply.preview
        ui.console.print(ui.orders_preview(plan.description, analyses,
                                           sell_orders, buy_orders,
                                           alerts=reply.alerts, diff=reply.diff))

    if reply.text:
        ui.assistant(reply.text)

    if reply.exported:
        ui.console.print(ui.export_result(
            reply.exported["folder"], reply.exported["n_sells"],
            reply.exported["n_buys"]))

    if reply.needs_confirmation:
        ui.console.print("[bold yellow]Export these orders?[/] [dim](yes/no)[/]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    play_startup_sound()
    ui.banner(VERSION)

    for note in paths.migrate_legacy_files():
        ui.info(note)

    config = load_config()
    prices_file = config.get("default_prices_file", "stock_prices.csv")
    excel_path = get_investment_data_path()

    if excel_path is None or not excel_path.exists():
        where = excel_path or "(not configured)"
        ui.error(f"Holdings file not found: {where}")
        ui.info("Set \"investment_data_path\" in "
                f"{paths.user_data_dir() / 'config.json'} to the absolute path "
                "of your investment_data.xlsx — or use the desktop app "
                "(python app.py), which has a file picker.")
        ui.info("Required columns: Account Number, Account Name (optional), "
                "Symbol / CUSIP / ID, Quantity, Price / NAV, Market Value")
        input("\nPress Enter to exit...")
        return

    try:
        with ui.working(f"Loading {excel_path.name}..."):
            accounts = AccountParser(str(excel_path)).parse_accounts()
            stock_prices, buy_list = load_stock_prices(prices_file)
    except Exception as e:
        ui.error(f"Error loading data: {friendly_load_error(e)}")
        input("\nPress Enter to exit...")
        return

    if not accounts:
        ui.error("No accounts found in the Excel file.")
        input("\nPress Enter to exit...")
        return

    total = sum(a.get_total_value() for a in accounts.values())
    ui.success(f"Loaded {len(accounts)} accounts (${total:,.0f}) and "
               f"{len(buy_list)} buy-list tickers.")

    if not get_api_key():
        ui.warn("No API key configured — natural language requests are disabled. "
                "`default`, `summary`, `holdings` and price edits still work. "
                "Say `api key` for setup instructions.")

    from conversation_agent import ConversationAgent
    agent = ConversationAgent(accounts, stock_prices, buy_list, config)
    agent.export_orders_callback = export_orders

    name = config.get("advisor_name", "").strip()
    greeting = f"Hello, {name}." if name else "Hello."
    ui.console.print(f"\n[bold {ui.ACCENT}]{greeting} Let's trade.[/] "
                     f"[dim]Type 'help' for commands.[/]\n")

    while True:
        try:
            user_input = ui.console.input("[bold]You ›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            ui.console.print("\nGoodbye!")
            break
        if not user_input:
            continue

        # Buy-list edits and price refresh are handled here so the price file
        # and the in-memory state stay in sync.
        parts = user_input.split()
        cmd = parts[0].lower()
        if cmd in ("add", "update", "remove") or \
                user_input.lower().strip() in ("refresh", "refresh prices"):
            if cmd == "refresh":
                changed = refresh_prices(buy_list, stock_prices, prices_file)
            else:
                changed = edit_buy_list(cmd, parts[1:], prices_file)
            if changed:
                stock_prices, buy_list = load_stock_prices(prices_file)
                agent.stock_prices = stock_prices
                agent.buy_list = buy_list
            continue

        # Local commands return instantly; the spinner only becomes visible
        # when a request actually goes to the API.
        with ui.working():
            reply = agent.chat(user_input)

        render_reply(reply, agent, prices_file)

        if agent.should_exit:
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting...")
        sys.exit(0)
