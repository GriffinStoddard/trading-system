"""
Pre-flight sanity checks for proposed trades.

Deterministic, advisory-only checks that run on every simulation before the
confirmation prompt. They never block a trade — they surface things a busy
advisor might miss: outsized sells, stale prices, accounts that couldn't fund
their planned buys.
"""

from models import Account
from order_generator import Order, AccountTradeAnalysis

# Thresholds
LARGE_SELL_FRACTION = 0.50      # selling more than this share of an account
STALE_PRICE_TOLERANCE = 0.20    # buy-list price vs held price divergence
CONCENTRATION_FRACTION = 0.10   # single ticker exceeding this share of new buys


def run_sanity_checks(
    accounts: dict[str, Account],
    sell_orders: list[Order],
    buy_orders: list[Order],
    stock_prices: dict[str, float],
    analyses: list[AccountTradeAnalysis],
) -> list[str]:
    """Return a list of human-readable alert strings (empty = all clear)."""
    alerts: list[str] = []
    alerts += _check_large_sells(accounts, sell_orders)
    alerts += _check_stale_prices(accounts, buy_orders, stock_prices)
    alerts += _check_underfunded_buys(analyses)
    return alerts


def _check_large_sells(accounts: dict[str, Account],
                       sell_orders: list[Order]) -> list[str]:
    """Flag accounts where sells exceed LARGE_SELL_FRACTION of total value."""
    alerts = []
    sold_by_account: dict[str, float] = {}
    for o in sell_orders:
        sold_by_account[o.account_num] = (
            sold_by_account.get(o.account_num, 0) + o.estimated_value)

    for num, sold in sorted(sold_by_account.items()):
        account = accounts.get(num)
        if not account:
            continue
        total = account.get_total_value()
        if total > 0 and sold / total > LARGE_SELL_FRACTION:
            name = f" ({account.client_name})" if account.client_name else ""
            alerts.append(
                f"Large liquidation: account {num}{name} sells "
                f"${sold:,.0f} — {sold / total * 100:.0f}% of its value")
    return alerts


def _check_stale_prices(accounts: dict[str, Account], buy_orders: list[Order],
                        stock_prices: dict[str, float]) -> list[str]:
    """Flag buy-list prices that diverge sharply from the same ticker's price
    in the holdings snapshot — a sign one of the two data sources is stale."""
    alerts = []
    buy_tickers = {o.security for o in buy_orders}
    checked = set()

    for account in accounts.values():
        for h in list(account.holdings) + list(account.cash_equivalents):
            ticker = h.symbol
            if ticker in checked or ticker not in buy_tickers:
                continue
            list_price = stock_prices.get(ticker)
            if not list_price or not h.price or h.price <= 0:
                continue
            checked.add(ticker)
            drift = abs(list_price - h.price) / h.price
            if drift > STALE_PRICE_TOLERANCE:
                alerts.append(
                    f"Possible stale price: {ticker} buy-list price "
                    f"${list_price:,.2f} differs {drift * 100:.0f}% from the "
                    f"held price ${h.price:,.2f} — refresh prices or check the "
                    f"holdings export")
    return alerts


def _check_underfunded_buys(analyses: list[AccountTradeAnalysis]) -> list[str]:
    """Flag accounts that skipped planned buys for lack of cash."""
    alerts = []
    for a in analyses:
        skipped = [
            ta.ticker for ta in a.ticker_analysis
            if ta.action == "SKIP" and "cash" in ta.reason.lower()
        ]
        if skipped:
            name = f" ({a.client_name})" if a.client_name else ""
            alerts.append(
                f"Underfunded: account {a.account_num}{name} couldn't fund "
                f"buys for {', '.join(sorted(set(skipped)))}")
    return alerts
