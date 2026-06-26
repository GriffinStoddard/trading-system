"""Tests for the deterministic pre-flight sanity checks."""

import pytest

from models import Account, Holding
from order_generator import Order, AccountTradeAnalysis, TickerAnalysis
from sanity_checks import run_sanity_checks


@pytest.fixture
def account():
    a = Account(account_num="A1", client_name="Pat Doe", cash=10000.0)
    a.add_holding(Holding("AAPL", 100, 150.0, 15000.0))
    a.add_holding(Holding("TSLA", 50, 400.0, 20000.0))
    return {"A1": a}


def make_order(account_num="A1", security="AAPL", action="Sell",
               shares=10, value=1500.0):
    return Order(account_num=account_num, client_name="Pat Doe",
                 security=security, action=action, shares=shares,
                 estimated_value=value)


def make_analysis(skip_ticker=None, skip_reason=""):
    a = AccountTradeAnalysis(
        account_num="A1", client_name="Pat Doe", total_value=45000.0,
        cash_before=10000.0, cash_equivalents_before=0.0, holdings_before=[])
    if skip_ticker:
        a.ticker_analysis.append(TickerAnalysis(
            ticker=skip_ticker, current_shares=0, current_value=0,
            current_allocation=0, target_allocation=0.025, action="SKIP",
            shares_to_trade=0, estimated_value=0, new_allocation=0,
            reason=skip_reason))
    return a


class TestLargeSells:
    def test_flags_sell_over_half_of_account(self, account):
        # Account total is 45k; selling 30k is 67%.
        sells = [make_order(value=30000.0)]
        alerts = run_sanity_checks(account, sells, [], {}, [])
        assert any("Large liquidation" in a and "67%" in a for a in alerts)

    def test_small_sell_not_flagged(self, account):
        sells = [make_order(value=1500.0)]
        alerts = run_sanity_checks(account, sells, [], {}, [])
        assert not any("Large liquidation" in a for a in alerts)


class TestStalePrices:
    def test_flags_diverging_buy_list_price(self, account):
        # Held AAPL at $150, buy list says $250 — 67% divergence.
        buys = [make_order(security="AAPL", action="Buy", value=2500.0)]
        alerts = run_sanity_checks(account, [], buys, {"AAPL": 250.0}, [])
        assert any("stale price" in a.lower() and "AAPL" in a for a in alerts)

    def test_close_price_not_flagged(self, account):
        buys = [make_order(security="AAPL", action="Buy", value=1550.0)]
        alerts = run_sanity_checks(account, [], buys, {"AAPL": 155.0}, [])
        assert not any("stale" in a.lower() for a in alerts)

    def test_ticker_not_held_not_checked(self, account):
        buys = [make_order(security="NVDA", action="Buy", value=900.0)]
        alerts = run_sanity_checks(account, [], buys, {"NVDA": 900.0}, [])
        assert not any("stale" in a.lower() for a in alerts)


class TestUnderfundedBuys:
    def test_flags_insufficient_cash_skips(self, account):
        analyses = [make_analysis("NVDA", "Insufficient cash")]
        alerts = run_sanity_checks(account, [], [], {}, analyses)
        assert any("Underfunded" in a and "NVDA" in a for a in alerts)

    def test_other_skip_reasons_not_flagged(self, account):
        analyses = [make_analysis("NVDA", "Already owns >= 2.0%")]
        alerts = run_sanity_checks(account, [], [], {}, analyses)
        assert not any("Underfunded" in a for a in alerts)


def test_clean_trade_produces_no_alerts(account):
    sells = [make_order(value=1000.0)]
    buys = [make_order(security="MSFT", action="Buy", value=2000.0)]
    alerts = run_sanity_checks(account, sells, buys, {"MSFT": 300.0},
                               [make_analysis()])
    assert alerts == []
