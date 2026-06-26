"""
Tests for the GUI bridge (gui_api.Api).

No GUI, no network, no API calls: the agent is injected with fixture data and
only the serialization / local-command surface is exercised.
"""

import json

import pytest

from gui_api import Api
from models import Account, Holding
from conversation_agent import ConversationAgent


@pytest.fixture
def api(tmp_path, monkeypatch):
    """Api wired to fixture accounts and a temp prices file."""
    account = Account(account_num="12345", client_name="Test Client")
    account.cash = 10000.0
    account.add_holding(Holding("AAPL", 100, 150.0, 15000.0))
    account.add_cash_equivalent(Holding("BIL", 200, 100.0, 20000.0))
    accounts = {"12345": account}

    prices = {"GOOGL": 100.0, "MSFT": 300.0, "AAPL": 150.0}
    buy_list = ["GOOGL", "MSFT"]
    config = {
        "default_target_allocation_percent": 0.025,
        "default_skip_if_above_percent": 0.02,
        "default_cash_floor_percent": 0.02,
        "default_min_buy_percent": 0.0,
        "cash_equivalents": ["BIL"],
    }

    import paths
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    prices_csv = tmp_path / "stock_prices.csv"
    prices_csv.write_text("TICKER,PRICE\nGOOGL,100.0\nMSFT,300.0\n")

    a = Api()
    a.config = config
    a.agent = ConversationAgent(accounts, prices, buy_list, config)
    a.agent.api_key = ""
    return a


class TestState:
    def test_state_shape(self, api):
        state = api.get_state()
        assert state["ok"] is True
        assert len(state["accounts"]) == 1
        acct = state["accounts"][0]
        assert acct["number"] == "12345"
        assert acct["client_name"] == "Test Client"
        assert acct["total"] == 45000.0
        assert state["total_value"] == 45000.0
        assert {b["ticker"] for b in state["buy_list"]} == {"GOOGL", "MSFT"}
        json.dumps(state)  # must be JSON-serializable

    def test_state_before_load(self):
        api = Api()
        state = api.get_state()
        assert state["ok"] is False


class TestChat:
    def test_local_view_command(self, api):
        reply = api.chat("summary")
        assert reply["view"] == "summary"
        assert reply["preview"] is None
        json.dumps(reply)

    def test_default_trade_serializes_preview(self, api):
        reply = api.chat("default")
        assert reply["needs_confirmation"] is True
        p = reply["preview"]
        assert p is not None
        assert p["n_accounts"] == 1
        assert p["buy_count"] == len([o for o in p["orders"] if o["action"] == "Buy"])
        assert all(set(o) == {"account", "client", "action", "ticker",
                              "shares", "value"} for o in p["orders"])
        json.dumps(reply)

    def test_cancel_flow(self, api):
        api.chat("default")
        reply = api.chat("no")
        assert reply["needs_confirmation"] is False
        assert "Dismissed" in reply["text"]

    def test_confirm_pending_button_exports(self, api, tmp_path):
        folder = tmp_path / "06-09-2026"
        folder.mkdir()
        api.agent.export_orders_callback = lambda s, b: (
            "06-09-2026/sell_order.csv", "06-09-2026/buy_order.csv", folder)
        api.chat("default")
        reply = api.confirm_pending()
        assert reply["exported"] is not None
        json.dumps(reply)

    def test_cancel_pending_button(self, api):
        api.chat("default")
        reply = api.cancel_pending()
        assert reply["exported"] is None
        assert api.agent.state.pending_plan is None
        json.dumps(reply)

    def test_confirm_flow_exports(self, api, tmp_path):
        folder = tmp_path / "06-09-2026"
        folder.mkdir()
        api.agent.export_orders_callback = lambda s, b: (
            "06-09-2026/sell_order.csv", "06-09-2026/buy_order.csv", folder)
        api.chat("default")
        reply = api.chat("yes")
        assert reply["exported"] is not None
        assert reply["exported"]["folder"] == str(folder)
        json.dumps(reply)

    def test_chat_error_path(self, api):
        api.agent = None
        reply = api.chat("anything")
        assert "error" in reply


class TestHoldings:
    def test_holdings_rows(self, api):
        result = api.get_holdings("12345")
        assert result["ok"] is True
        kinds = [h["kind"] for h in result["holdings"]]
        assert kinds == ["stock", "cash_equiv", "cash"]
        cash_row = result["holdings"][-1]
        assert cash_row["value"] == 10000.0
        json.dumps(result)

    def test_unknown_account(self, api):
        assert api.get_holdings("nope")["ok"] is False


class TestBuyList:
    def test_add_then_remove(self, api):
        added = api.edit_buy_list("add", "crdo", 85.5)
        assert added["ok"] is True
        assert any(b["ticker"] == "CRDO" for b in added["buy_list"])

        removed = api.edit_buy_list("remove", "CRDO")
        assert removed["ok"] is True
        assert not any(b["ticker"] == "CRDO" for b in removed["buy_list"])

    def test_update_price(self, api):
        result = api.edit_buy_list("update", "GOOGL", 364.26)
        assert result["ok"] is True
        googl = next(b for b in result["buy_list"] if b["ticker"] == "GOOGL")
        assert googl["price"] == 364.26
        # The in-memory agent state must follow the file.
        assert api.agent.stock_prices["GOOGL"] == 364.26

    def test_bad_price_rejected(self, api):
        assert api.edit_buy_list("add", "XYZ", "not-a-price")["ok"] is False
        assert api.edit_buy_list("add", "XYZ", -5)["ok"] is False

    def test_remove_unknown_rejected(self, api):
        assert api.edit_buy_list("remove", "ZZZZ")["ok"] is False


class TestSettings:
    def test_short_key_rejected(self, api):
        assert api.save_api_key("too-short")["ok"] is False

    def test_open_folder_missing(self, api):
        assert api.open_folder("/definitely/not/a/folder")["ok"] is False


class TestLiveAddAndClear:
    def test_add_ticker_live_fetches_price(self, api, monkeypatch):
        import price_service
        monkeypatch.setattr(price_service, "fetch_live_prices",
                            lambda tickers: ({tickers[0]: 123.45}, []))
        r = api.add_ticker_live("nvda")
        assert r["ok"] is True
        nvda = next(b for b in r["buy_list"] if b["ticker"] == "NVDA")
        assert nvda["price"] == 123.45

    def test_add_ticker_live_existing_updates(self, api, monkeypatch):
        import price_service
        monkeypatch.setattr(price_service, "fetch_live_prices",
                            lambda tickers: ({tickers[0]: 364.26}, []))
        r = api.add_ticker_live("GOOGL")
        assert r["ok"] is True
        assert "Updated" in r["message"]
        assert api.agent.stock_prices["GOOGL"] == 364.26

    def test_add_ticker_live_no_quote(self, api, monkeypatch):
        import price_service
        monkeypatch.setattr(price_service, "fetch_live_prices",
                            lambda tickers: ({}, tickers))
        r = api.add_ticker_live("FAKEX")
        assert r["ok"] is False
        assert "FAKEX" in r["error"]

    def test_add_ticker_live_blank(self, api):
        assert api.add_ticker_live("  ")["ok"] is False

    def test_clear_buy_list(self, api):
        r = api.clear_buy_list()
        assert r["ok"] is True
        assert r["buy_list"] == []
        assert api.agent.buy_list == []
        # Clearing again reports already-empty.
        assert api.clear_buy_list()["ok"] is False
