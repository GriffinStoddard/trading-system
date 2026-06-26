"""
GUI bridge — the Python API exposed to the desktop frontend via pywebview.

Every public method on Api is callable from JavaScript as
`window.pywebview.api.<method>(...)` and returns a JSON-serializable dict.
The frontend never sees Python objects; everything is serialized here.

Locking: pywebview dispatches JS calls on worker threads. Chat calls (which can
hold a 5-30s LLM round-trip) are serialized by their own lock so the rest of
the UI stays responsive: data views (get_state / get_holdings) are read-only
over structures chat never mutates, and buy-list mutations take a separate
short-lived lock.
"""

import sys
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import (load_config, get_api_key, set_api_key,
                    get_investment_data_path, set_investment_data_path,
                    get_exports_dir)
from models import AccountParser
import paths

VERSION = "3.6.0"


def data_dir() -> Path:
    """Per-user app data directory (config.json, stock_prices.csv)."""
    return paths.user_data_dir()


class Api:
    """JS-facing API. Public methods = the frontend contract."""

    def __init__(self):
        self._chat_lock = threading.Lock()   # serializes agent conversations
        self._data_lock = threading.Lock()   # serializes buy-list / config writes
        self._window = None
        self.agent = None
        self.config = {}
        self.prices_file = "stock_prices.csv"
        self.load_error = None

    def attach_window(self, window):
        self._window = window

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def bootstrap(self) -> dict:
        """Load all data. Called once by the frontend on startup."""
        with self._data_lock:
            paths.migrate_legacy_files()
            try:
                self._load_data()
            except FileNotFoundError as e:
                # Missing/unset holdings file: recoverable via the picker.
                self.load_error = self._friendly_load_error(e)
                return {"ok": False, "error": self.load_error, "needs_file": True}
            except Exception as e:
                self.load_error = self._friendly_load_error(e)
                return {"ok": False, "error": self.load_error}
            return {"ok": True, **self._state()}

    def _load_data(self):
        from conversation_agent import ConversationAgent
        from main import load_stock_prices, export_orders

        self.config = load_config()
        self.prices_file = self.config.get("default_prices_file", "stock_prices.csv")

        excel_path = get_investment_data_path()
        if excel_path is None:
            raise FileNotFoundError(
                "No holdings file selected yet — choose your "
                "investment_data.xlsx to get started.")
        if not excel_path.exists():
            raise FileNotFoundError(
                f"Holdings file not found at {excel_path} — it may have been "
                "moved. Locate it again.")

        accounts = AccountParser(str(excel_path)).parse_accounts()
        if not accounts:
            raise ValueError("No accounts found in the Excel file.")

        stock_prices, buy_list = load_stock_prices(self.prices_file)
        self.agent = ConversationAgent(accounts, stock_prices, buy_list, self.config)
        self.agent.export_orders_callback = export_orders

    @staticmethod
    def _friendly_load_error(error: Exception) -> str:
        from main import friendly_load_error
        return friendly_load_error(error)

    def get_state(self) -> dict:
        """Current sidebar state (accounts, buy list, settings)."""
        if self.agent is None:
            return {"ok": False, "error": self.load_error or "Not loaded"}
        return {"ok": True, **self._state()}

    def _state(self) -> dict:
        accounts = []
        total_all = 0.0
        for num, acct in self.agent.accounts.items():
            total = acct.get_total_value()
            total_all += total
            ce = acct.get_cash_equivalents_value()
            accounts.append({
                "number": num,
                "client_name": acct.client_name or "",
                "total": total,
                "cash": acct.cash,
                "cash_pct": (acct.cash / total * 100) if total else 0,
                "ce_value": ce,
                "ce_pct": (ce / total * 100) if total else 0,
                "n_positions": len(acct.holdings),
            })
        return {
            "version": VERSION,
            "advisor_name": self.config.get("advisor_name", ""),
            "api_key_set": bool(get_api_key()),
            "model": self.agent.model,
            "accounts": accounts,
            "total_value": total_all,
            "buy_list": [
                {"ticker": t, "price": self.agent.stock_prices.get(t, 0)}
                for t in self.agent.buy_list
            ],
            "prices_as_of": self._prices_as_of(),
            "cash_equivalents": self.agent.cash_equivalents,
            "awaiting_confirmation": self.agent.state.awaiting_confirmation,
            "investment_data_path": str(get_investment_data_path() or ""),
            "exports_dir": str(get_exports_dir()),
        }

    def _prices_as_of(self) -> str:
        path = data_dir() / self.prices_file
        if not path.exists():
            return ""
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%b %d, %I:%M %p")

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def chat(self, message: str) -> dict:
        """Send a message to the agent. Returns a serialized AgentReply."""
        with self._chat_lock:
            if self.agent is None:
                return {"error": self.load_error or "Data not loaded"}
            try:
                reply = self.agent.chat(message)
            except Exception as e:
                return {"error": f"Unexpected error: {e}"}
            return self._serialize_reply(reply)

    def confirm_pending(self) -> dict:
        """Confirm and export the staged proposal (GUI Confirm button).

        Deterministic — never routes through the LLM, so confirmation can't be
        lost to the chat flow.
        """
        with self._chat_lock:
            if self.agent is None:
                return {"error": self.load_error or "Data not loaded"}
            try:
                return self._serialize_reply(self.agent.confirm_pending())
            except Exception as e:
                return {"error": f"Unexpected error: {e}"}

    def cancel_pending(self) -> dict:
        """Dismiss the staged proposal without exporting (GUI Dismiss button)."""
        with self._chat_lock:
            if self.agent is None:
                return {"error": self.load_error or "Data not loaded"}
            try:
                return self._serialize_reply(self.agent.cancel_pending())
            except Exception as e:
                return {"error": f"Unexpected error: {e}"}

    def _serialize_reply(self, reply) -> dict:
        out = {
            "text": reply.text,
            "view": reply.view,
            "needs_confirmation": reply.needs_confirmation,
            "alerts": list(reply.alerts or []),
            "diff": reply.diff,
            "preview": None,
            "exported": None,
            "should_exit": self.agent.should_exit,
        }
        if reply.preview:
            plan, analyses, sell_orders, buy_orders = reply.preview
            out["preview"] = {
                "description": plan.description,
                "n_accounts": len(analyses),
                "sell_count": len(sell_orders),
                "sell_total": sum(o.estimated_value for o in sell_orders),
                "buy_count": len(buy_orders),
                "buy_total": sum(o.estimated_value for o in buy_orders),
                "orders": [
                    {
                        "account": o.account_num,
                        "client": o.client_name or "",
                        "action": o.action,
                        "ticker": o.security,
                        "shares": o.shares,
                        "value": o.estimated_value,
                    }
                    for o in list(sell_orders) + list(buy_orders)
                ],
                # Prefix each warning with its account so a flattened list
                # still tells the advisor which account it applies to.
                "warnings": [
                    {
                        "account": a.account_num,
                        "client": a.client_name or "",
                        "message": w,
                    }
                    for a in analyses for w in a.warnings
                ],
            }
        if reply.exported:
            out["exported"] = {
                "folder": reply.exported["folder"],
                "n_sells": reply.exported["n_sells"],
                "n_buys": reply.exported["n_buys"],
            }
        return out

    # ------------------------------------------------------------------
    # Data views
    # ------------------------------------------------------------------

    def get_holdings(self, account_number: str) -> dict:
        """Position-level detail for one account."""
        if self.agent is None:
            return {"ok": False, "error": "Data not loaded"}
        acct = self.agent.accounts.get(str(account_number))
        if acct is None:
            return {"ok": False, "error": f"Unknown account {account_number}"}
        total = acct.get_total_value()

        def row(h, kind):
            value = h.market_value or 0
            return {
                "symbol": h.symbol,
                "kind": kind,
                "shares": h.shares,
                "price": h.price or 0,
                "value": value,
                "alloc": (value / total * 100) if total else 0,
            }

        holdings = [row(h, "stock") for h in acct.holdings]
        holdings += [row(ce, "cash_equiv") for ce in acct.cash_equivalents]
        holdings.append({
            "symbol": "CASH", "kind": "cash", "shares": None, "price": None,
            "value": acct.cash,
            "alloc": (acct.cash / total * 100) if total else 0,
        })
        return {
            "ok": True,
            "number": acct.account_num,
            "client_name": acct.client_name or "",
            "total": total,
            "holdings": holdings,
        }

    # ------------------------------------------------------------------
    # Buy list management
    # ------------------------------------------------------------------

    def refresh_prices(self) -> dict:
        """Pull live prices for the buy list and update the CSV."""
        with self._data_lock:
            if self.agent is None:
                return {"ok": False, "error": "Data not loaded"}
            if not self.agent.buy_list:
                return {"ok": False, "error": "The buy list is empty."}
            try:
                from price_service import fetch_live_prices
                live, failed = fetch_live_prices(self.agent.buy_list)
            except ImportError:
                return {"ok": False, "error": "yfinance is not installed."}
            except ConnectionError as e:
                return {"ok": False, "error": str(e)}

            path = data_dir() / self.prices_file
            df = pd.read_csv(path)
            updates = []
            for ticker, price in live.items():
                old = self.agent.stock_prices.get(ticker, 0)
                df.loc[df["TICKER"] == ticker, "PRICE"] = price
                updates.append({"ticker": ticker, "old": old, "new": price})
            df.to_csv(path, index=False)

            self._reload_prices()
            return {"ok": True, "updated": updates, "failed": failed,
                    "buy_list": self._state()["buy_list"],
                    "prices_as_of": self._prices_as_of()}

    def add_ticker_live(self, ticker: str) -> dict:
        """Add (or update) a ticker by fetching its live price automatically."""
        ticker = (ticker or "").strip().upper()
        if not ticker:
            return {"ok": False, "error": "Ticker is required."}
        if self.agent is None:
            return {"ok": False, "error": "Data not loaded"}
        try:
            from price_service import fetch_live_prices
            live, _failed = fetch_live_prices([ticker])
        except ImportError:
            return {"ok": False, "error": "yfinance is not installed."}
        except ConnectionError as e:
            return {"ok": False, "error": str(e)}
        if ticker not in live:
            return {"ok": False,
                    "error": f"No quote found for {ticker} — check the symbol."}
        action = "update" if ticker in self.agent.stock_prices else "add"
        return self.edit_buy_list(action, ticker, live[ticker])

    def clear_buy_list(self) -> dict:
        """Remove every ticker from the buy list."""
        with self._data_lock:
            if self.agent is None:
                return {"ok": False, "error": "Data not loaded"}
            n = len(self.agent.buy_list)
            if n == 0:
                return {"ok": False, "error": "The buy list is already empty."}
            path = data_dir() / self.prices_file
            pd.DataFrame(columns=["TICKER", "PRICE"]).to_csv(path, index=False)
            self._reload_prices()
            return {"ok": True, "message": f"Cleared {n} tickers from the buy list.",
                    "buy_list": [], "prices_as_of": self._prices_as_of()}

    def edit_buy_list(self, action: str, ticker: str, price=None) -> dict:
        """Add, update, or remove a buy-list ticker."""
        with self._data_lock:
            if self.agent is None:
                return {"ok": False, "error": "Data not loaded"}
            ticker = (ticker or "").strip().upper()
            if not ticker:
                return {"ok": False, "error": "Ticker is required."}

            path = data_dir() / self.prices_file
            df = pd.read_csv(path) if path.exists() else \
                pd.DataFrame(columns=["TICKER", "PRICE"])
            exists = ticker in df["TICKER"].values

            if action == "remove":
                if not exists:
                    return {"ok": False, "error": f"{ticker} is not on the buy list."}
                df = df[df["TICKER"] != ticker]
                message = f"Removed {ticker}."
            else:
                try:
                    price = float(str(price).lstrip("$"))
                except (TypeError, ValueError):
                    return {"ok": False, "error": "A valid price is required."}
                if price <= 0:
                    return {"ok": False, "error": "Price must be positive."}
                if exists:
                    df.loc[df["TICKER"] == ticker, "PRICE"] = price
                    message = f"Updated {ticker} to ${price:,.2f}."
                else:
                    df = pd.concat(
                        [df, pd.DataFrame({"TICKER": [ticker], "PRICE": [price]})],
                        ignore_index=True)
                    message = f"Added {ticker} at ${price:,.2f}."

            df.to_csv(path, index=False)
            self._reload_prices()
            return {"ok": True, "message": message,
                    "buy_list": self._state()["buy_list"],
                    "prices_as_of": self._prices_as_of()}

    def _reload_prices(self):
        from main import load_stock_prices
        stock_prices, buy_list = load_stock_prices(self.prices_file)
        self.agent.stock_prices = stock_prices
        self.agent.buy_list = buy_list

    # ------------------------------------------------------------------
    # Settings & shell
    # ------------------------------------------------------------------

    def save_api_key(self, key: str) -> dict:
        """Save the Anthropic API key and hand it to the live agent."""
        with self._data_lock:
            key = (key or "").strip()
            if len(key) < 20:
                return {"ok": False, "error": "That doesn't look like a valid API key."}
            if not set_api_key(key):
                return {"ok": False, "error": "Could not write config.json."}
            if self.agent is not None:
                self.agent.api_key = key
            return {"ok": True}

    def open_folder(self, folder: str) -> dict:
        """Open an export folder in Finder / Explorer."""
        import subprocess
        path = Path(folder)
        if not path.is_absolute():
            path = get_exports_dir() / folder
        if not path.exists():
            return {"ok": False, "error": f"Folder not found: {path}"}
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            elif sys.platform == "win32":
                subprocess.run(["explorer", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def pick_data_file(self) -> dict:
        """Open a native file dialog to choose the holdings Excel file, then
        (re)load everything from it. Returns a bootstrap-shaped result."""
        if self._window is None:
            return {"ok": False, "error": "Window not ready."}
        try:
            import webview
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=("Excel files (*.xlsx;*.xls)", "All files (*.*)"),
            )
        except Exception as e:
            return {"ok": False, "error": f"Could not open the file dialog: {e}"}
        if not result:
            return {"ok": False, "cancelled": True}
        chosen = result[0] if isinstance(result, (list, tuple)) else result

        with self._data_lock:
            if not set_investment_data_path(chosen):
                return {"ok": False, "error": "Could not save the file path to config."}
            try:
                self._load_data()
            except Exception as e:
                return {"ok": False, "error": self._friendly_load_error(e)}
            self.load_error = None
            return {"ok": True, **self._state()}

    def quit(self) -> dict:
        if self._window is not None:
            self._window.destroy()
        return {"ok": True}
