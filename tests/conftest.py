"""
Shared pytest fixtures for the trading system test suite.
"""

import pytest
import sys
from pathlib import Path

# Add parent directory to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Account, Holding
from execution_plan import (
    ExecutionPlan, BuyRule, SellRule, AccountFilter, CashManagement,
    QuantityType, AllocationMethod, CashSource
)


# =============================================================================
# Account Fixtures
# =============================================================================

@pytest.fixture
def empty_account():
    """Account with no holdings, no cash, no cash equivalents."""
    return Account(account_num="EMPTY001", client_name="Empty Client")


@pytest.fixture
def cash_only_account():
    """Account with only cash, no holdings."""
    account = Account(account_num="CASH001", client_name="Cash Client", cash=50000.0)
    return account


@pytest.fixture
def single_holding_account():
    """Account with one holding."""
    account = Account(
        account_num="SINGLE001",
        client_name="Single Holding Client",
        cash=5000.0
    )
    account.add_holding(Holding("AAPL", shares=100, price=150.0, market_value=15000.0))
    return account


@pytest.fixture
def multi_holding_account():
    """Account with multiple holdings and cash equivalents."""
    account = Account(
        account_num="MULTI001",
        client_name="Multi Holding Client",
        cash=10000.0
    )
    account.add_holding(Holding("AAPL", shares=100, price=150.0, market_value=15000.0))
    account.add_holding(Holding("GOOGL", shares=20, price=2500.0, market_value=50000.0))
    account.add_holding(Holding("MSFT", shares=50, price=300.0, market_value=15000.0))
    account.add_cash_equivalent(Holding("BIL", shares=200, price=91.50, market_value=18300.0))
    account.add_cash_equivalent(Holding("USFR", shares=100, price=50.0, market_value=5000.0))
    return account


@pytest.fixture
def cash_equiv_only_account():
    """Account with only cash equivalents (no regular holdings)."""
    account = Account(
        account_num="CE001",
        client_name="Cash Equiv Client",
        cash=1000.0
    )
    account.add_cash_equivalent(Holding("BIL", shares=500, price=91.50, market_value=45750.0))
    account.add_cash_equivalent(Holding("PJLXX", shares=1000, price=1.0, market_value=1000.0))
    return account


@pytest.fixture
def large_account():
    """Account with substantial holdings for percentage testing."""
    account = Account(
        account_num="LARGE001",
        client_name="Large Account Client",
        cash=100000.0
    )
    # Total value will be ~1M
    account.add_holding(Holding("AAPL", shares=1000, price=150.0, market_value=150000.0))
    account.add_holding(Holding("GOOGL", shares=100, price=2500.0, market_value=250000.0))
    account.add_holding(Holding("MSFT", shares=500, price=300.0, market_value=150000.0))
    account.add_holding(Holding("AMZN", shares=200, price=175.0, market_value=35000.0))
    account.add_cash_equivalent(Holding("BIL", shares=2000, price=91.50, market_value=183000.0))
    account.add_cash_equivalent(Holding("USFR", shares=1000, price=50.0, market_value=50000.0))
    return account


@pytest.fixture
def zero_value_account():
    """Account with holdings but zero market values (edge case)."""
    account = Account(account_num="ZERO001", client_name="Zero Value Client")
    account.add_holding(Holding("AAPL", shares=100, price=None, market_value=None))
    return account


@pytest.fixture
def fractional_shares_account():
    """Account with fractional share holdings."""
    account = Account(
        account_num="FRAC001",
        client_name="Fractional Client",
        cash=500.0
    )
    account.add_holding(Holding("AAPL", shares=10.5, price=150.0, market_value=1575.0))
    account.add_holding(Holding("GOOGL", shares=0.75, price=2500.0, market_value=1875.0))
    account.add_cash_equivalent(Holding("BIL", shares=5.25, price=91.50, market_value=480.375))
    return account


# =============================================================================
# Stock Price Fixtures
# =============================================================================

@pytest.fixture
def basic_stock_prices():
    """Basic stock price dictionary."""
    return {
        "AAPL": 150.0,
        "GOOGL": 2500.0,
        "MSFT": 300.0,
        "AMZN": 175.0,
        "META": 500.0,
        "NVDA": 900.0,
    }


@pytest.fixture
def stock_prices_with_cash_equivs():
    """Stock prices including cash equivalent prices."""
    return {
        "AAPL": 150.0,
        "GOOGL": 2500.0,
        "MSFT": 300.0,
        "AMZN": 175.0,
        "BIL": 91.50,
        "USFR": 50.0,
        "PJLXX": 1.0,
    }


@pytest.fixture
def expensive_stock_prices():
    """Stock prices for testing high-price stocks."""
    return {
        "BRK.A": 500000.0,  # Very expensive
        "AAPL": 150.0,
    }


@pytest.fixture
def penny_stock_prices():
    """Stock prices for testing low-price stocks."""
    return {
        "PENNY": 0.01,
        "CHEAP": 1.0,
        "AAPL": 150.0,
    }


# =============================================================================
# Execution Plan Fixtures
# =============================================================================

@pytest.fixture
def empty_plan():
    """Execution plan with no rules."""
    return ExecutionPlan(description="Empty plan - no operations")


@pytest.fixture
def basic_buy_plan():
    """Simple buy plan with default settings."""
    return ExecutionPlan(
        description="Buy 2.5% allocation in specified tickers",
        buy_rules=[
            BuyRule(
                tickers=["AAPL", "MSFT"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025,
                buy_only_to_target=True,
                skip_if_allocation_above=0.02
            )
        ]
    )


@pytest.fixture
def basic_sell_plan():
    """Simple sell plan."""
    return ExecutionPlan(
        description="Sell all of specified tickers",
        sell_rules=[
            SellRule(
                tickers=["BIL", "USFR"],
                quantity_type=QuantityType.ALL
            )
        ]
    )


@pytest.fixture
def buy_with_cash_equiv_plan():
    """Buy plan that sells cash equivalents if needed."""
    return ExecutionPlan(
        description="Buy with cash equivalent liquidation",
        buy_rules=[
            BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.05,
                sell_cash_equiv_if_needed=True,
                buy_only_to_target=True
            )
        ],
        cash_management=CashManagement(
            min_cash_percent=0.02,
            cash_equiv_sell_order="largest_first"
        )
    )


@pytest.fixture
def complex_plan():
    """Complex plan with multiple rules and filters."""
    return ExecutionPlan(
        description="Complex multi-step rebalancing",
        sell_rules=[
            SellRule(
                tickers=["BIL"],
                quantity_type=QuantityType.ALL
            ),
            SellRule(
                tickers=["GOOGL"],
                quantity_type=QuantityType.PERCENT_OF_POSITION,
                quantity=0.5,
                min_shares_remaining=10
            )
        ],
        buy_rules=[
            BuyRule(
                tickers=["AAPL", "MSFT", "META"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025,
                skip_if_allocation_above=0.02,
                buy_only_to_target=True,
                sell_cash_equiv_if_needed=True
            )
        ],
        account_filter=AccountFilter(
            min_value=10000.0
        ),
        cash_management=CashManagement(
            min_cash_percent=0.02,
            min_cash_dollars=1000.0
        )
    )


@pytest.fixture
def high_cash_floor_plan():
    """Plan with very high cash floor."""
    return ExecutionPlan(
        description="Plan with 100% cash floor",
        buy_rules=[
            BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.05
            )
        ],
        cash_management=CashManagement(
            min_cash_percent=1.0  # 100% - no buying possible
        )
    )


@pytest.fixture
def filtered_plan():
    """Plan with account filter."""
    return ExecutionPlan(
        description="Plan with account filter",
        buy_rules=[
            BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025
            )
        ],
        account_filter=AccountFilter(
            min_value=50000.0,
            account_numbers=["LARGE001", "MULTI001"]
        )
    )


# =============================================================================
# Account Dictionary Fixtures
# =============================================================================

@pytest.fixture
def single_account_dict(multi_holding_account):
    """Dictionary with single account."""
    return {multi_holding_account.account_num: multi_holding_account}


@pytest.fixture
def multiple_accounts_dict(
    empty_account,
    cash_only_account,
    multi_holding_account,
    large_account
):
    """Dictionary with multiple accounts of varying sizes."""
    return {
        empty_account.account_num: empty_account,
        cash_only_account.account_num: cash_only_account,
        multi_holding_account.account_num: multi_holding_account,
        large_account.account_num: large_account,
    }


# =============================================================================
# Helper Fixtures
# =============================================================================

@pytest.fixture
def default_cash_management():
    """Default cash management settings."""
    return CashManagement(
        min_cash_percent=0.02,
        min_cash_dollars=None,
        cash_equiv_sell_order="largest_first"
    )


@pytest.fixture
def strict_cash_management():
    """Strict cash management with both percent and dollar minimums."""
    return CashManagement(
        min_cash_percent=0.05,
        min_cash_dollars=5000.0,
        cash_equiv_sell_order="smallest_first"
    )
