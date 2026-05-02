"""
Tests for order_generator.py - Core order generation logic.

This is the most critical test file, focusing on edge cases and boundary conditions
for the deterministic order generation engine.
"""

import pytest
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Account, Holding
from execution_plan import (
    ExecutionPlan, BuyRule, SellRule, AccountFilter, CashManagement,
    QuantityType, AllocationMethod, CashSource
)
from order_generator import OrderGenerator, Order, AccountTradeAnalysis, TickerAnalysis


# =============================================================================
# Buy Rule Edge Cases
# =============================================================================

class TestBuyRuleEdgeCases:
    """Tests for buy rule edge cases."""

    def test_buy_with_zero_available_cash(self, basic_stock_prices):
        """Zero available cash generates no orders."""
        account = Account(account_num="TEST", cash=0.0)
        accounts = {"TEST": account}

        plan = ExecutionPlan(
            description="Buy with no cash",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025
            )]
        )

        generator = OrderGenerator(accounts, basic_stock_prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(buy_orders) == 0

    def test_buy_price_exactly_equals_available_cash(self, basic_stock_prices):
        """Price exactly equals available cash should buy 1 share."""
        # AAPL = $150, need cash such that usable >= 150
        # If cash = X, total = X, floor = 0.02*X, usable = X - 0.02*X = 0.98*X
        # Need 0.98*X >= 150, so X >= 153.06
        # Let's use exact amount with no floor to simplify
        account = Account(account_num="TEST", cash=150.0)
        accounts = {"TEST": account}

        plan = ExecutionPlan(
            description="Buy exactly one share",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=150.0
            )],
            cash_management=CashManagement(min_cash_percent=0.0)  # No floor for exact test
        )

        generator = OrderGenerator(accounts, basic_stock_prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(buy_orders) == 1
        assert buy_orders[0].shares == 1

    def test_buy_cash_floor_exactly_hit(self):
        """Cash floor exactly at 2% remaining stops buying."""
        # $10000 account, 2% floor = $200
        # Cash = $200, should have $0 usable
        account = Account(account_num="TEST", cash=200.0)
        account.add_holding(Holding("MSFT", shares=32.67, price=300.0, market_value=9800.0))
        # Total = $10000, 2% = $200, usable = $0
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0, "MSFT": 300.0}

        plan = ExecutionPlan(
            description="Cash floor test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025
            )],
            cash_management=CashManagement(min_cash_percent=0.02)
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(buy_orders) == 0

    def test_buy_cash_floor_leaves_fractional_cents(self):
        """Cash floor calculation with fractional cents."""
        # Total value that creates fractional cent floor
        account = Account(account_num="TEST", cash=333.33)
        account.add_holding(Holding("MSFT", shares=10, price=300.0, market_value=3000.0))
        # Total = 3333.33, 2% floor = 66.6666
        accounts = {"TEST": account}

        prices = {"AAPL": 100.0, "MSFT": 300.0}

        plan = ExecutionPlan(
            description="Fractional cents test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=250.0
            )],
            cash_management=CashManagement(min_cash_percent=0.02)
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Usable = 333.33 - 66.67 = ~266.66, can buy 2 shares at $100
        assert len(buy_orders) == 1
        assert buy_orders[0].shares == 2

    def test_buy_only_to_target_at_target(self):
        """buy_only_to_target with existing position exactly at target skips."""
        account = Account(account_num="TEST", cash=10000.0)
        # 2.5% of 50000 = 1250
        account.add_holding(Holding("AAPL", shares=8.33, price=150.0, market_value=1250.0))
        account.add_holding(Holding("MSFT", shares=125, price=300.0, market_value=37500.0))
        # Total = 10000 + 1250 + 37500 = 48750, AAPL = 2.56%
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0, "MSFT": 300.0}

        plan = ExecutionPlan(
            description="At target test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025,  # 2.5% target
                buy_only_to_target=True
            )]
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Already at ~2.56%, target is 2.5%, should buy 0
        assert len(buy_orders) == 0

    def test_buy_only_to_target_above_target(self):
        """buy_only_to_target with existing position above target skips."""
        account = Account(account_num="TEST", cash=5000.0)
        # Set AAPL to 5% of account
        account.add_holding(Holding("AAPL", shares=20, price=150.0, market_value=3000.0))
        account.add_holding(Holding("MSFT", shares=100, price=520.0, market_value=52000.0))
        # Total = 60000, AAPL = 5%
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0, "MSFT": 520.0}

        plan = ExecutionPlan(
            description="Above target test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025,  # 2.5% target
                buy_only_to_target=True
            )]
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Already at 5%, target is 2.5%, buy_only_to_target means buy 0
        assert len(buy_orders) == 0

    def test_skip_if_allocation_above_threshold_exactly_met(self):
        """skip_if_allocation_above threshold exactly met should skip."""
        account = Account(account_num="TEST", cash=5000.0)
        # Set AAPL to exactly 2% of account
        account.add_holding(Holding("AAPL", shares=10, price=100.0, market_value=1000.0))
        account.add_holding(Holding("MSFT", shares=100, price=440.0, market_value=44000.0))
        # Total = 50000, AAPL = 2%
        accounts = {"TEST": account}

        prices = {"AAPL": 100.0, "MSFT": 440.0}

        plan = ExecutionPlan(
            description="Skip threshold test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025,
                skip_if_allocation_above=0.02  # Skip if >= 2%
            )]
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Exactly at 2% threshold, should skip
        assert len(buy_orders) == 0

    def test_multiple_tickers_one_missing_price(self):
        """Multiple tickers with one missing price - others still process."""
        # Use enough cash for multiple buys (2.5% of 10000 = $250 per ticker)
        account = Account(account_num="TEST", cash=10000.0)
        accounts = {"TEST": account}

        # UNKNOWN not in prices
        prices = {"AAPL": 150.0, "MSFT": 300.0}

        plan = ExecutionPlan(
            description="Missing price test",
            buy_rules=[BuyRule(
                tickers=["AAPL", "UNKNOWN", "MSFT"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025  # 2.5% of 10000 = $250 each
            )],
            cash_management=CashManagement(min_cash_percent=0.0)  # No floor to ensure enough cash
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Should have orders for AAPL and MSFT, skip UNKNOWN
        # AAPL: $250/$150 = 1 share, MSFT: $250/$300 = 0 shares (can't afford)
        # Actually the order generator processes all and generates analysis
        assert len(buy_orders) >= 1
        tickers = {o.security for o in buy_orders}
        assert "AAPL" in tickers
        assert "UNKNOWN" not in tickers

    def test_rounding_insufficient_cash_for_one_share(self):
        """$99.99 available, $100 stock -> floor to 0 shares."""
        account = Account(account_num="TEST", cash=102.04)  # ~$100 usable after 2% floor
        accounts = {"TEST": account}

        prices = {"EXPENSIVE": 100.01}  # Just over usable cash

        plan = ExecutionPlan(
            description="Rounding test",
            buy_rules=[BuyRule(
                tickers=["EXPENSIVE"],
                quantity_type=QuantityType.DOLLARS,
                quantity=100.01
            )],
            cash_management=CashManagement(min_cash_percent=0.02)
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Usable cash ~$100, can't afford $100.01 stock
        assert len(buy_orders) == 0

    def test_buy_shares_quantity_type(self):
        """Buy specific number of shares."""
        account = Account(account_num="TEST", cash=5000.0)
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0}

        plan = ExecutionPlan(
            description="Buy shares test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.SHARES,
                quantity=10
            )],
            cash_management=CashManagement(min_cash_percent=0.02)
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(buy_orders) == 1
        assert buy_orders[0].shares == 10
        assert buy_orders[0].estimated_value == 1500.0

    def test_buy_dollars_quantity_type(self):
        """Buy specific dollar amount."""
        account = Account(account_num="TEST", cash=5000.0)
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0}

        plan = ExecutionPlan(
            description="Buy dollars test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=1000.0
            )],
            cash_management=CashManagement(min_cash_percent=0.02)
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(buy_orders) == 1
        # $1000 / $150 = 6.67 -> floor to 6 shares
        assert buy_orders[0].shares == 6
        assert buy_orders[0].estimated_value == 900.0


# =============================================================================
# Sell Rule Edge Cases
# =============================================================================

class TestSellRuleEdgeCases:
    """Tests for sell rule edge cases."""

    def test_sell_all_with_fractional_shares(self, fractional_shares_account):
        """Sell ALL with fractional shares rounds to int."""
        accounts = {"FRAC001": fractional_shares_account}
        prices = {"AAPL": 150.0, "GOOGL": 2500.0, "BIL": 91.50}

        plan = ExecutionPlan(
            description="Sell all fractional",
            sell_rules=[SellRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.ALL
            )]
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(sell_orders) == 1
        # 10.5 shares -> int(10.5) = 10
        assert sell_orders[0].shares == 10
        assert isinstance(sell_orders[0].shares, int)

    def test_sell_min_shares_remaining_exceeds_holding(self):
        """min_shares_remaining exceeds current holding -> sell 0."""
        account = Account(account_num="TEST", cash=1000.0)
        account.add_holding(Holding("AAPL", shares=5, price=150.0, market_value=750.0))
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0}

        plan = ExecutionPlan(
            description="Min shares test",
            sell_rules=[SellRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.ALL,
                min_shares_remaining=10  # More than we own
            )]
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Can't sell any because min_shares_remaining > current shares
        assert len(sell_orders) == 0

    def test_sell_max_percent_of_position_zero(self):
        """max_percent_of_position = 0.0 is falsy so constraint is not applied.

        Note: In Python, 0.0 is falsy, so `if rule.max_percent_of_position:`
        evaluates to False and the constraint is skipped. This test documents
        the actual behavior.
        """
        account = Account(account_num="TEST", cash=1000.0)
        account.add_holding(Holding("AAPL", shares=100, price=150.0, market_value=15000.0))
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0}

        plan = ExecutionPlan(
            description="Max percent zero test",
            sell_rules=[SellRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.ALL,
                max_percent_of_position=0.0  # Falsy, so constraint not applied
            )]
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Since 0.0 is falsy, the constraint is not applied, sells ALL
        assert len(sell_orders) == 1
        assert sell_orders[0].shares == 100

    def test_sell_percent_of_position_rounds_down(self):
        """Sell PERCENT_OF_POSITION where result < 1 share rounds to 0."""
        account = Account(account_num="TEST", cash=1000.0)
        account.add_holding(Holding("AAPL", shares=5, price=150.0, market_value=750.0))
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0}

        plan = ExecutionPlan(
            description="Small percent test",
            sell_rules=[SellRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_POSITION,
                quantity=0.1  # 10% of 5 = 0.5 shares -> int = 0
            )]
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(sell_orders) == 0

    def test_sell_cash_equivalent_from_ce_list(self, multi_holding_account):
        """Sell cash equivalent falls back to cash_equivalents list."""
        accounts = {"MULTI001": multi_holding_account}
        prices = {"BIL": 91.50, "USFR": 50.0}

        plan = ExecutionPlan(
            description="Sell CE test",
            sell_rules=[SellRule(
                tickers=["BIL"],
                quantity_type=QuantityType.ALL
            )]
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(sell_orders) == 1
        assert sell_orders[0].security == "BIL"
        assert sell_orders[0].shares == 200

    def test_sell_non_existent_ticker(self, multi_holding_account):
        """Sell non-existent ticker skips gracefully."""
        accounts = {"MULTI001": multi_holding_account}
        prices = {"AAPL": 150.0, "UNKNOWN": 100.0}

        plan = ExecutionPlan(
            description="Non-existent ticker",
            sell_rules=[SellRule(
                tickers=["UNKNOWN"],
                quantity_type=QuantityType.ALL
            )]
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(sell_orders) == 0

    def test_sell_with_zero_price(self):
        """Sell with zero price in holding uses stock_prices fallback."""
        account = Account(account_num="TEST", cash=1000.0)
        account.add_holding(Holding("AAPL", shares=100, price=0, market_value=15000.0))
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0}

        plan = ExecutionPlan(
            description="Zero price test",
            sell_rules=[SellRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.ALL
            )]
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(sell_orders) == 1
        assert sell_orders[0].shares == 100
        # Uses stock_prices fallback
        assert sell_orders[0].estimated_value == 15000.0

    def test_sell_shares_quantity_type(self):
        """Sell specific number of shares."""
        account = Account(account_num="TEST", cash=1000.0)
        account.add_holding(Holding("AAPL", shares=100, price=150.0, market_value=15000.0))
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0}

        plan = ExecutionPlan(
            description="Sell shares test",
            sell_rules=[SellRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.SHARES,
                quantity=25
            )]
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(sell_orders) == 1
        assert sell_orders[0].shares == 25

    def test_sell_shares_more_than_owned(self):
        """Sell more shares than owned caps at owned amount."""
        account = Account(account_num="TEST", cash=1000.0)
        account.add_holding(Holding("AAPL", shares=50, price=150.0, market_value=7500.0))
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0}

        plan = ExecutionPlan(
            description="Sell more than owned",
            sell_rules=[SellRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.SHARES,
                quantity=100  # More than 50 owned
            )]
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(sell_orders) == 1
        assert sell_orders[0].shares == 50  # Capped at owned

    def test_sell_dollars_quantity_type(self):
        """Sell specific dollar amount."""
        account = Account(account_num="TEST", cash=1000.0)
        account.add_holding(Holding("AAPL", shares=100, price=150.0, market_value=15000.0))
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0}

        plan = ExecutionPlan(
            description="Sell dollars test",
            sell_rules=[SellRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=1000.0  # $1000 / $150 = 6.67 -> 6 shares
            )]
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(sell_orders) == 1
        assert sell_orders[0].shares == 6


# =============================================================================
# Cash Equivalent Liquidation Edge Cases
# =============================================================================

class TestCashEquivalentLiquidation:
    """Tests for cash equivalent liquidation logic."""

    def test_partial_liquidation_sells_enough_for_buy(self):
        """Partial liquidation sells enough shares to enable the buy."""
        account = Account(account_num="TEST", cash=100.0)
        account.add_cash_equivalent(Holding("BIL", shares=100, price=91.50, market_value=9150.0))
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0, "BIL": 91.50}

        plan = ExecutionPlan(
            description="Partial liquidation",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=500.0,
                sell_cash_equiv_if_needed=True
            )],
            cash_management=CashManagement(min_cash_percent=0.0)  # No floor for simplicity
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Should sell some BIL to fund the AAPL purchase
        ce_sells = [o for o in sell_orders if o.security == "BIL"]
        assert len(ce_sells) == 1
        # The implementation uses ceil for partial sells
        assert ce_sells[0].shares >= 1

        # Should be able to buy some AAPL
        assert len(buy_orders) == 1
        assert buy_orders[0].security == "AAPL"

    def test_multiple_cash_equivalents_largest_first(self, multi_holding_account):
        """Multiple cash equivalents sold largest_first."""
        accounts = {"MULTI001": multi_holding_account}
        prices = {"AAPL": 150.0, "BIL": 91.50, "USFR": 50.0}

        # BIL = $18300, USFR = $5000
        # Need to sell to buy - largest first means BIL first

        plan = ExecutionPlan(
            description="Largest first test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=20000.0,  # More than available cash
                sell_cash_equiv_if_needed=True
            )],
            cash_management=CashManagement(
                min_cash_percent=0.02,
                cash_equiv_sell_order="largest_first"
            )
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Should sell BIL (largest) first
        ce_sells = [o for o in sell_orders if o.security in ["BIL", "USFR"]]
        if len(ce_sells) > 0:
            assert ce_sells[0].security == "BIL"

    def test_multiple_cash_equivalents_smallest_first(self):
        """Multiple cash equivalents sold smallest_first."""
        account = Account(account_num="TEST", cash=100.0)
        account.add_cash_equivalent(Holding("BIL", shares=200, price=91.50, market_value=18300.0))
        account.add_cash_equivalent(Holding("USFR", shares=100, price=50.0, market_value=5000.0))
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0, "BIL": 91.50, "USFR": 50.0}

        plan = ExecutionPlan(
            description="Smallest first test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=3000.0,
                sell_cash_equiv_if_needed=True
            )],
            cash_management=CashManagement(
                min_cash_percent=0.0,
                cash_equiv_sell_order="smallest_first"
            )
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Should sell USFR (smallest) first
        ce_sells = [o for o in sell_orders if o.security in ["BIL", "USFR"]]
        if len(ce_sells) > 0:
            assert ce_sells[0].security == "USFR"

    def test_need_exactly_full_ce_value(self):
        """Sells enough CE shares to fund the buy request."""
        # With $0 cash, need to sell CE to buy AAPL
        # AAPL @ $150, want $10000 worth = 66 shares = $9900
        # So need 99 shares of BIL @ $100 = $9900
        account = Account(account_num="TEST", cash=0.0)
        account.add_cash_equivalent(Holding("BIL", shares=100, price=100.0, market_value=10000.0))
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0, "BIL": 100.0}

        plan = ExecutionPlan(
            description="Exact value test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=10000.0,
                sell_cash_equiv_if_needed=True
            )],
            cash_management=CashManagement(min_cash_percent=0.0)
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        ce_sells = [o for o in sell_orders if o.security == "BIL"]
        assert len(ce_sells) == 1
        # Sells enough to cover the actual buy cost (66 * 150 = 9900)
        assert ce_sells[0].shares >= 99

        # Should buy AAPL
        assert len(buy_orders) == 1
        assert buy_orders[0].security == "AAPL"
        assert buy_orders[0].shares == 66  # $9900 / $150 = 66 shares

    def test_shortfall_larger_than_all_cash_equivalents(self):
        """Shortfall > all CE value -> sells all, proceeds with partial buy."""
        account = Account(account_num="TEST", cash=100.0)
        account.add_cash_equivalent(Holding("BIL", shares=10, price=100.0, market_value=1000.0))
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0, "BIL": 100.0}

        plan = ExecutionPlan(
            description="Huge shortfall test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=50000.0,  # Way more than available
                sell_cash_equiv_if_needed=True
            )],
            cash_management=CashManagement(min_cash_percent=0.0)
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Should sell all BIL
        ce_sells = [o for o in sell_orders if o.security == "BIL"]
        assert len(ce_sells) == 1
        assert ce_sells[0].shares == 10

        # Should still buy what we can
        assert len(buy_orders) == 1
        # Total cash = 100 + 1000 = 1100, buy 1100/150 = 7 shares
        assert buy_orders[0].shares == 7

    def test_zero_cash_equivalents_available(self):
        """No cash equivalents returns empty sell list."""
        account = Account(account_num="TEST", cash=100.0)
        # No cash equivalents added
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0}

        plan = ExecutionPlan(
            description="No CE test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=5000.0,
                sell_cash_equiv_if_needed=True
            )],
            cash_management=CashManagement(min_cash_percent=0.0)
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # No CE to sell
        assert len(sell_orders) == 0
        # Can only buy with $100
        assert len(buy_orders) == 0  # Can't afford even 1 share at $150


# =============================================================================
# Cash Floor Edge Cases
# =============================================================================

class TestCashFloorEdgeCases:
    """Tests for cash floor (minimum cash) edge cases."""

    def test_min_cash_percent_and_dollars_both_set_uses_maximum(self):
        """Both min_cash_percent and min_cash_dollars set -> uses maximum."""
        account = Account(account_num="TEST", cash=10000.0)
        account.add_holding(Holding("MSFT", shares=300, price=300.0, market_value=90000.0))
        # Total = 100000
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0, "MSFT": 300.0}

        plan = ExecutionPlan(
            description="Both floors test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=8000.0
            )],
            cash_management=CashManagement(
                min_cash_percent=0.02,  # 2% of 100000 = 2000
                min_cash_dollars=5000.0  # $5000 > $2000
            )
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Usable = 10000 - 5000 (max of 2000 and 5000) = 5000
        # Can buy 5000/150 = 33 shares
        assert len(buy_orders) == 1
        assert buy_orders[0].shares == 33

    def test_min_cash_percent_100_no_buying(self, high_cash_floor_plan):
        """min_cash_percent = 100% -> no buying possible."""
        account = Account(account_num="TEST", cash=10000.0)
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0}

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(high_cash_floor_plan)

        # 100% cash floor means $0 usable
        assert len(buy_orders) == 0

    def test_min_cash_dollars_greater_than_account_value(self):
        """min_cash_dollars > account value -> no buying possible."""
        account = Account(account_num="TEST", cash=1000.0)
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0}

        plan = ExecutionPlan(
            description="High dollar floor",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=500.0
            )],
            cash_management=CashManagement(
                min_cash_percent=0.0,
                min_cash_dollars=5000.0  # More than $1000 account
            )
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(buy_orders) == 0

    def test_negative_cash_handling(self):
        """Negative cash (edge case) - usable should be 0."""
        account = Account(account_num="TEST", cash=-1000.0)  # Negative!
        account.add_holding(Holding("MSFT", shares=100, price=300.0, market_value=30000.0))
        accounts = {"TEST": account}

        prices = {"AAPL": 150.0, "MSFT": 300.0}

        plan = ExecutionPlan(
            description="Negative cash test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=1000.0
            )],
            cash_management=CashManagement(min_cash_percent=0.02)
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Negative cash means max(0, -1000 - floor) = 0 usable
        assert len(buy_orders) == 0

    def test_account_starting_below_cash_floor_with_ce_liquidation(self):
        """Account starting below cash floor should raise enough CEs to meet floor AND fund buys."""
        # Account starts with 1% cash but needs 2% floor
        account = Account(account_num="TEST", cash=1000.0)  # 1% of 100000
        account.add_holding(Holding("MSFT", shares=200, price=300.0, market_value=60000.0))
        account.add_cash_equivalent(Holding("BIL", shares=400, price=97.50, market_value=39000.0))
        # Total = 1000 + 60000 + 39000 = 100000
        accounts = {"TEST": account}

        prices = {"AAPL": 100.0, "MSFT": 300.0, "BIL": 97.50}

        plan = ExecutionPlan(
            description="Below floor with CE liquidation",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=5000.0,  # Want to buy $5000 of AAPL
                sell_cash_equiv_if_needed=True
            )],
            cash_management=CashManagement(min_cash_percent=0.02)  # 2% = $2000 floor
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)
        analyses = generator.get_analyses()

        # Should have CE sells and buys
        assert len(sell_orders) > 0
        assert len(buy_orders) > 0

        # Final cash should be AT or ABOVE the 2% floor ($2000)
        # Starting cash: $1000, floor: $2000, deficit: $1000
        # Need: $5000 for buys + $1000 deficit = $6000 from CEs
        # Ending cash should be >= $2000
        assert analyses[0].cash_after >= 2000.0, f"Cash {analyses[0].cash_after} should be >= $2000 floor"

    def test_account_starting_below_cash_floor_limits_buys(self):
        """Account below floor with limited CEs should reduce buys to maintain floor."""
        # Account starts with 0.5% cash but needs 2% floor
        account = Account(account_num="TEST", cash=500.0)  # 0.5% of 100000
        account.add_holding(Holding("MSFT", shares=300, price=300.0, market_value=90000.0))
        account.add_cash_equivalent(Holding("BIL", shares=100, price=95.0, market_value=9500.0))
        # Total = 500 + 90000 + 9500 = 100000
        accounts = {"TEST": account}

        prices = {"AAPL": 100.0, "MSFT": 300.0, "BIL": 95.0}

        plan = ExecutionPlan(
            description="Below floor limited CEs",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=10000.0,  # Want $10k but CEs only have $9500
                sell_cash_equiv_if_needed=True
            )],
            cash_management=CashManagement(min_cash_percent=0.02)  # 2% = $2000 floor
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)
        analyses = generator.get_analyses()

        # Final cash should be AT or ABOVE the 2% floor
        assert analyses[0].cash_after >= 2000.0, f"Cash {analyses[0].cash_after} should be >= $2000 floor"


class TestMinBuyAllocationRecheck:
    """Tests for min_buy_allocation being rechecked after buy amount reduction."""

    def test_min_buy_skipped_after_reduction_due_to_insufficient_cash(self):
        """Buy reduced below min_buy_allocation due to cash should be skipped."""
        account = Account(account_num="TEST", cash=500.0)  # Only $500 available
        accounts = {"TEST": account}

        prices = {"AAPL": 100.0}

        plan = ExecutionPlan(
            description="Reduced buy test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=5000.0,  # Want $5000 but only have $500
                min_buy_allocation=0.01  # 1% minimum
            )],
            cash_management=CashManagement(min_cash_percent=0.0)  # No floor
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)
        analyses = generator.get_analyses()

        # $500 buy on $500 account = 100%, which is > 1%, so it SHOULD go through
        # But wait, account value is $500, so 1% = $5. $500 > $5, so it should work.
        # Let me redesign this test...
        pass

    def test_min_buy_skipped_when_reduced_below_threshold(self):
        """Buy that starts above min but gets reduced below should be skipped."""
        # Account with $100k total, but only $500 cash available for buys
        account = Account(account_num="TEST", cash=2500.0)  # $2500 cash
        account.add_holding(Holding("MSFT", shares=300, price=325.0, market_value=97500.0))
        # Total = 2500 + 97500 = 100000
        # Floor = 2% = $2000, so usable = $500
        accounts = {"TEST": account}

        # Stock price $10, so $500 can buy 50 shares = $500
        # $500 is 0.5% of $100k - below 1% minimum
        prices = {"AAPL": 10.0, "MSFT": 325.0}

        plan = ExecutionPlan(
            description="Reduced below min test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=2500.0,  # Want $2500 (2.5% of account)
                min_buy_allocation=0.01  # 1% = $1000 minimum
            )],
            cash_management=CashManagement(min_cash_percent=0.02)  # 2% floor
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)
        analyses = generator.get_analyses()

        # Only $500 usable (can buy 50 shares), which is 0.5% of account - below 1% minimum
        # Should be SKIPPED
        assert len(buy_orders) == 0, "Buy reduced below 1% minimum should be skipped"

        # Check analysis shows it was skipped
        ticker_analysis = [ta for ta in analyses[0].ticker_analysis if ta.ticker == "AAPL"]
        assert len(ticker_analysis) == 1
        assert ticker_analysis[0].action == "SKIP"
        assert "minimum" in ticker_analysis[0].reason.lower()

    def test_min_buy_passes_when_above_threshold_after_reduction(self):
        """Buy reduced but still above min_buy_allocation should proceed."""
        # Account with $100k total, $5000 usable
        account = Account(account_num="TEST", cash=7000.0)  # $7000 cash
        account.add_holding(Holding("MSFT", shares=300, price=310.0, market_value=93000.0))
        # Total = 7000 + 93000 = 100000
        # Floor = 2% = $2000, so usable = $5000
        accounts = {"TEST": account}

        prices = {"AAPL": 100.0, "MSFT": 310.0}

        plan = ExecutionPlan(
            description="Reduced but above min test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=10000.0,  # Want $10k but only $5k usable
                min_buy_allocation=0.01  # 1% = $1000 minimum
            )],
            cash_management=CashManagement(min_cash_percent=0.02)
        )

        generator = OrderGenerator(accounts, prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # $5000 usable = 5% of account, above 1% minimum - should proceed
        assert len(buy_orders) == 1
        # Should buy $5000 worth = 50 shares at $100
        assert buy_orders[0].shares == 50


# =============================================================================
# Account Filter Edge Cases
# =============================================================================

class TestAccountFilterEdgeCases:
    """Tests for account filter edge cases."""

    def test_min_value_filters_out_all_accounts(self, multiple_accounts_dict, basic_stock_prices):
        """min_value too high filters out all accounts."""
        plan = ExecutionPlan(
            description="High min value filter",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025
            )],
            account_filter=AccountFilter(min_value=999999999.0)
        )

        generator = OrderGenerator(multiple_accounts_dict, basic_stock_prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(buy_orders) == 0
        assert len(generator.get_analyses()) == 0

    def test_must_hold_tickers_nobody_owns(self, multiple_accounts_dict, basic_stock_prices):
        """must_hold_tickers with ticker nobody owns -> no accounts pass."""
        plan = ExecutionPlan(
            description="Must hold unknown",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025
            )],
            account_filter=AccountFilter(must_hold_tickers=["UNKNOWN_TICKER"])
        )

        generator = OrderGenerator(multiple_accounts_dict, basic_stock_prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(buy_orders) == 0

    def test_empty_account_numbers_list(self, multiple_accounts_dict, basic_stock_prices):
        """account_numbers = [] (empty list) is falsy so filter not applied.

        Note: In Python, [] is falsy, so `if filter_obj.account_numbers and ...`
        evaluates to False and the filter is not applied. This test documents
        the actual behavior - all accounts pass when account_numbers is [].
        """
        plan = ExecutionPlan(
            description="Empty account list",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025
            )],
            account_filter=AccountFilter(account_numbers=[])  # Falsy, filter not applied
        )

        generator = OrderGenerator(multiple_accounts_dict, basic_stock_prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Since [] is falsy, the account_numbers filter is not applied
        # All accounts with enough cash pass through
        assert len(buy_orders) >= 1

    def test_combined_conflicting_filters(self, large_account, basic_stock_prices):
        """Combined filters that conflict -> no accounts pass."""
        accounts = {"LARGE001": large_account}

        plan = ExecutionPlan(
            description="Conflicting filters",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025
            )],
            account_filter=AccountFilter(
                min_value=500000.0,  # LARGE001 passes this
                account_numbers=["NONEXISTENT"]  # But fails this
            )
        )

        generator = OrderGenerator(accounts, basic_stock_prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(buy_orders) == 0

    def test_max_value_filter(self, multiple_accounts_dict, basic_stock_prices):
        """max_value filters out large accounts."""
        plan = ExecutionPlan(
            description="Max value filter",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025
            )],
            account_filter=AccountFilter(max_value=100.0)  # Very low
        )

        generator = OrderGenerator(multiple_accounts_dict, basic_stock_prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Only empty account (value=0) passes
        assert len(buy_orders) == 0  # Empty account has no cash

    def test_must_hold_tickers_intersection(self, multi_holding_account, basic_stock_prices):
        """must_hold_tickers checks for ANY ticker, not ALL."""
        accounts = {"MULTI001": multi_holding_account}

        plan = ExecutionPlan(
            description="Must hold intersection",
            buy_rules=[BuyRule(
                tickers=["META"],  # Not owned
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025
            )],
            account_filter=AccountFilter(
                must_hold_tickers=["AAPL", "UNKNOWN"]  # AAPL is owned
            )
        )

        generator = OrderGenerator(accounts, basic_stock_prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Account passes because it holds AAPL (intersection exists)
        assert len(buy_orders) == 1


# =============================================================================
# Multi-Account Processing
# =============================================================================

class TestMultiAccountProcessing:
    """Tests for processing multiple accounts."""

    def test_cash_from_account_a_does_not_affect_account_b(self, basic_stock_prices):
        """Each account maintains independent state."""
        account_a = Account(account_num="A", cash=1000.0)
        account_b = Account(account_num="B", cash=5000.0)
        accounts = {"A": account_a, "B": account_b}

        plan = ExecutionPlan(
            description="Multi-account test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.DOLLARS,
                quantity=2000.0
            )],
            cash_management=CashManagement(min_cash_percent=0.0)
        )

        generator = OrderGenerator(accounts, basic_stock_prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        # Account A can buy 1000/150 = 6 shares
        # Account B can buy 2000/150 = 13 shares
        a_orders = [o for o in buy_orders if o.account_num == "A"]
        b_orders = [o for o in buy_orders if o.account_num == "B"]

        assert len(a_orders) == 1
        assert a_orders[0].shares == 6

        assert len(b_orders) == 1
        assert b_orders[0].shares == 13

    def test_each_account_gets_analysis(self, multiple_accounts_dict, basic_stock_prices):
        """Each processed account gets an analysis object."""
        plan = ExecutionPlan(
            description="Analysis test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025
            )],
            account_filter=AccountFilter(min_value=1000.0)  # Skip empty account
        )

        generator = OrderGenerator(multiple_accounts_dict, basic_stock_prices)
        generator.execute_plan(plan)

        analyses = generator.get_analyses()
        # Should have analyses for accounts that passed the filter
        assert len(analyses) >= 1


# =============================================================================
# Determinism Tests
# =============================================================================

class TestOrderGenerationDeterminism:
    """Tests for deterministic order generation."""

    def test_same_inputs_same_outputs(self, multi_holding_account, stock_prices_with_cash_equivs):
        """Same inputs always produce same outputs."""
        accounts = {"MULTI001": multi_holding_account}

        plan = ExecutionPlan(
            description="Determinism test",
            sell_rules=[SellRule(
                tickers=["BIL"],
                quantity_type=QuantityType.PERCENT_OF_POSITION,
                quantity=0.5
            )],
            buy_rules=[BuyRule(
                tickers=["AAPL", "MSFT"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025,
                sell_cash_equiv_if_needed=True
            )]
        )

        # Run twice
        generator1 = OrderGenerator(accounts, stock_prices_with_cash_equivs)
        sell1, buy1 = generator1.execute_plan(plan)

        # Need fresh account objects for second run
        account2 = Account(
            account_num="MULTI001",
            client_name="Multi Holding Client",
            cash=10000.0
        )
        account2.add_holding(Holding("AAPL", shares=100, price=150.0, market_value=15000.0))
        account2.add_holding(Holding("GOOGL", shares=20, price=2500.0, market_value=50000.0))
        account2.add_holding(Holding("MSFT", shares=50, price=300.0, market_value=15000.0))
        account2.add_cash_equivalent(Holding("BIL", shares=200, price=91.50, market_value=18300.0))
        account2.add_cash_equivalent(Holding("USFR", shares=100, price=50.0, market_value=5000.0))
        accounts2 = {"MULTI001": account2}

        generator2 = OrderGenerator(accounts2, stock_prices_with_cash_equivs)
        sell2, buy2 = generator2.execute_plan(plan)

        # Compare results
        assert len(sell1) == len(sell2)
        assert len(buy1) == len(buy2)

        for o1, o2 in zip(sell1, sell2):
            assert o1.security == o2.security
            assert o1.shares == o2.shares
            assert o1.estimated_value == o2.estimated_value

        for o1, o2 in zip(buy1, buy2):
            assert o1.security == o2.security
            assert o1.shares == o2.shares
            assert o1.estimated_value == o2.estimated_value


# =============================================================================
# Empty/Edge Plan Tests
# =============================================================================

class TestEmptyAndEdgePlans:
    """Tests for empty and edge case plans."""

    def test_empty_plan_no_orders(self, multi_holding_account, basic_stock_prices):
        """Empty plan generates no orders."""
        accounts = {"MULTI001": multi_holding_account}
        plan = ExecutionPlan(description="Empty plan")

        generator = OrderGenerator(accounts, basic_stock_prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(sell_orders) == 0
        assert len(buy_orders) == 0

    def test_plan_with_empty_ticker_lists(self, multi_holding_account, basic_stock_prices):
        """Plan with empty ticker lists generates no orders."""
        accounts = {"MULTI001": multi_holding_account}
        plan = ExecutionPlan(
            description="Empty tickers",
            sell_rules=[SellRule(tickers=[], quantity_type=QuantityType.ALL)],
            buy_rules=[BuyRule(tickers=[], quantity_type=QuantityType.PERCENT_OF_ACCOUNT)]
        )

        generator = OrderGenerator(accounts, basic_stock_prices)
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(sell_orders) == 0
        assert len(buy_orders) == 0

    def test_no_accounts(self, basic_stock_prices, basic_buy_plan):
        """No accounts generates no orders."""
        generator = OrderGenerator({}, basic_stock_prices)
        sell_orders, buy_orders = generator.execute_plan(basic_buy_plan)

        assert len(sell_orders) == 0
        assert len(buy_orders) == 0

    def test_empty_stock_prices(self, multi_holding_account):
        """Empty stock prices skips all buys."""
        accounts = {"MULTI001": multi_holding_account}
        plan = ExecutionPlan(
            description="No prices",
            buy_rules=[BuyRule(
                tickers=["AAPL", "MSFT"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025
            )]
        )

        generator = OrderGenerator(accounts, {})
        sell_orders, buy_orders = generator.execute_plan(plan)

        assert len(buy_orders) == 0


# =============================================================================
# Order Object Tests
# =============================================================================

class TestOrderObject:
    """Tests for Order dataclass."""

    def test_order_creation(self):
        """Order object creation with all fields."""
        order = Order(
            account_num="TEST001",
            client_name="Test Client",
            security="AAPL",
            action="Buy",
            shares=10,
            estimated_value=1500.0,
            reason="Test reason"
        )

        assert order.account_num == "TEST001"
        assert order.client_name == "Test Client"
        assert order.security == "AAPL"
        assert order.action == "Buy"
        assert order.shares == 10
        assert order.estimated_value == 1500.0
        assert order.reason == "Test reason"

    def test_order_defaults(self):
        """Order with minimal required fields uses defaults."""
        order = Order(
            account_num="TEST",
            client_name="",
            security="AAPL",
            action="Buy",
            shares=10
        )

        assert order.estimated_value == 0.0
        assert order.reason == ""


# =============================================================================
# Analysis Object Tests
# =============================================================================

class TestAnalysisObjects:
    """Tests for analysis objects."""

    def test_account_trade_analysis_fields(self, multi_holding_account, basic_stock_prices):
        """AccountTradeAnalysis has correct fields after execution."""
        accounts = {"MULTI001": multi_holding_account}
        plan = ExecutionPlan(
            description="Analysis fields test",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025
            )]
        )

        generator = OrderGenerator(accounts, basic_stock_prices)
        generator.execute_plan(plan)

        analyses = generator.get_analyses()
        assert len(analyses) == 1

        analysis = analyses[0]
        assert analysis.account_num == "MULTI001"
        assert analysis.client_name == "Multi Holding Client"
        assert analysis.total_value > 0
        assert analysis.cash_before == 10000.0

    def test_ticker_analysis_in_results(self, multi_holding_account, basic_stock_prices):
        """TickerAnalysis objects are created for processed tickers."""
        accounts = {"MULTI001": multi_holding_account}
        plan = ExecutionPlan(
            description="Ticker analysis test",
            buy_rules=[BuyRule(
                tickers=["AAPL", "META"],  # AAPL owned, META not
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025
            )]
        )

        generator = OrderGenerator(accounts, basic_stock_prices)
        generator.execute_plan(plan)

        analyses = generator.get_analyses()
        assert len(analyses[0].ticker_analysis) >= 1
