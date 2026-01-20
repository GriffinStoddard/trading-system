"""
Tests for execution_plan.py - ExecutionPlan schema and serialization.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution_plan import (
    ExecutionPlan, BuyRule, SellRule, AccountFilter, CashManagement,
    QuantityType, AllocationMethod, CashSource
)


class TestQuantityTypeEnum:
    """Tests for QuantityType enum."""

    def test_all_enum_values(self):
        """All expected enum values exist."""
        assert QuantityType.PERCENT_OF_POSITION.value == "percent_of_position"
        assert QuantityType.PERCENT_OF_ACCOUNT.value == "percent_of_account"
        assert QuantityType.SHARES.value == "shares"
        assert QuantityType.DOLLARS.value == "dollars"
        assert QuantityType.ALL.value == "all"
        assert QuantityType.TO_TARGET.value == "to_target"

    def test_enum_from_value(self):
        """Create enum from string value."""
        assert QuantityType("percent_of_position") == QuantityType.PERCENT_OF_POSITION
        assert QuantityType("all") == QuantityType.ALL

    def test_invalid_enum_value(self):
        """Invalid enum value raises ValueError."""
        with pytest.raises(ValueError):
            QuantityType("invalid_type")


class TestAllocationMethodEnum:
    """Tests for AllocationMethod enum."""

    def test_all_enum_values(self):
        """All expected enum values exist."""
        assert AllocationMethod.EQUAL_WEIGHT.value == "equal_weight"
        assert AllocationMethod.PROPORTIONAL.value == "proportional"
        assert AllocationMethod.SPECIFIED.value == "specified"


class TestCashSourceEnum:
    """Tests for CashSource enum."""

    def test_all_enum_values(self):
        """All expected enum values exist."""
        assert CashSource.AVAILABLE_CASH.value == "available_cash"
        assert CashSource.CASH_EQUIVALENTS.value == "cash_equivalents"
        assert CashSource.SELL_HOLDINGS.value == "sell_holdings"


class TestSellRule:
    """Tests for SellRule dataclass."""

    def test_sell_rule_minimal(self):
        """SellRule with only required fields."""
        rule = SellRule(
            tickers=["AAPL"],
            quantity_type=QuantityType.ALL
        )
        assert rule.tickers == ["AAPL"]
        assert rule.quantity_type == QuantityType.ALL
        assert rule.quantity is None
        assert rule.priority == "largest_first"
        assert rule.min_shares_remaining is None
        assert rule.max_percent_of_position is None

    def test_sell_rule_full(self):
        """SellRule with all fields populated."""
        rule = SellRule(
            tickers=["AAPL", "GOOGL"],
            quantity_type=QuantityType.PERCENT_OF_POSITION,
            quantity=0.5,
            priority="smallest_first",
            min_shares_remaining=10,
            max_percent_of_position=0.75
        )
        assert rule.tickers == ["AAPL", "GOOGL"]
        assert rule.quantity == 0.5
        assert rule.priority == "smallest_first"
        assert rule.min_shares_remaining == 10
        assert rule.max_percent_of_position == 0.75

    def test_sell_rule_empty_tickers(self):
        """SellRule with empty tickers list."""
        rule = SellRule(tickers=[], quantity_type=QuantityType.ALL)
        assert rule.tickers == []


class TestBuyRule:
    """Tests for BuyRule dataclass."""

    def test_buy_rule_minimal(self):
        """BuyRule with only required fields."""
        rule = BuyRule(
            tickers=["AAPL"],
            quantity_type=QuantityType.PERCENT_OF_ACCOUNT
        )
        assert rule.tickers == ["AAPL"]
        assert rule.quantity_type == QuantityType.PERCENT_OF_ACCOUNT
        assert rule.quantity is None
        assert rule.allocation_method == AllocationMethod.EQUAL_WEIGHT
        assert rule.skip_if_allocation_above is None
        assert rule.buy_only_to_target is False
        assert rule.cash_source == CashSource.AVAILABLE_CASH
        assert rule.sell_cash_equiv_if_needed is False

    def test_buy_rule_full(self):
        """BuyRule with all fields populated."""
        rule = BuyRule(
            tickers=["AAPL", "MSFT"],
            quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
            quantity=0.025,
            allocation_method=AllocationMethod.SPECIFIED,
            skip_if_allocation_above=0.02,
            buy_only_to_target=True,
            cash_source=CashSource.CASH_EQUIVALENTS,
            sell_cash_equiv_if_needed=True
        )
        assert rule.quantity == 0.025
        assert rule.allocation_method == AllocationMethod.SPECIFIED
        assert rule.skip_if_allocation_above == 0.02
        assert rule.buy_only_to_target is True
        assert rule.sell_cash_equiv_if_needed is True


class TestAccountFilter:
    """Tests for AccountFilter dataclass."""

    def test_account_filter_defaults(self):
        """AccountFilter with default values."""
        filter_obj = AccountFilter()
        assert filter_obj.min_value is None
        assert filter_obj.max_value is None
        assert filter_obj.account_numbers is None
        assert filter_obj.must_hold_tickers is None

    def test_account_filter_min_greater_than_max(self):
        """AccountFilter with min_value > max_value (impossible filter)."""
        filter_obj = AccountFilter(min_value=100000.0, max_value=50000.0)
        # This is valid to construct - filtering logic handles the impossibility
        assert filter_obj.min_value > filter_obj.max_value

    def test_account_filter_empty_account_numbers(self):
        """AccountFilter with empty account_numbers list."""
        filter_obj = AccountFilter(account_numbers=[])
        assert filter_obj.account_numbers == []

    def test_account_filter_full(self):
        """AccountFilter with all fields populated."""
        filter_obj = AccountFilter(
            min_value=10000.0,
            max_value=1000000.0,
            account_numbers=["ACC001", "ACC002"],
            must_hold_tickers=["AAPL", "GOOGL"]
        )
        assert filter_obj.min_value == 10000.0
        assert filter_obj.max_value == 1000000.0
        assert len(filter_obj.account_numbers) == 2
        assert len(filter_obj.must_hold_tickers) == 2


class TestCashManagement:
    """Tests for CashManagement dataclass."""

    def test_cash_management_defaults(self):
        """CashManagement default values."""
        cm = CashManagement()
        assert cm.min_cash_percent == 0.02
        assert cm.min_cash_dollars is None
        assert cm.cash_equiv_sell_order == "largest_first"

    def test_cash_management_full(self):
        """CashManagement with all fields."""
        cm = CashManagement(
            min_cash_percent=0.05,
            min_cash_dollars=5000.0,
            cash_equiv_sell_order="smallest_first"
        )
        assert cm.min_cash_percent == 0.05
        assert cm.min_cash_dollars == 5000.0
        assert cm.cash_equiv_sell_order == "smallest_first"

    def test_cash_management_100_percent(self):
        """CashManagement with 100% cash floor."""
        cm = CashManagement(min_cash_percent=1.0)
        assert cm.min_cash_percent == 1.0


class TestExecutionPlan:
    """Tests for ExecutionPlan dataclass."""

    def test_execution_plan_minimal(self):
        """ExecutionPlan with only description."""
        plan = ExecutionPlan(description="Test plan")
        assert plan.description == "Test plan"
        assert plan.sell_rules == []
        assert plan.buy_rules == []
        assert plan.account_filter is None
        assert plan.cash_management.min_cash_percent == 0.02
        assert plan.sells_before_buys is True

    def test_execution_plan_empty_rules(self, empty_plan):
        """ExecutionPlan with no sell_rules and no buy_rules."""
        assert empty_plan.sell_rules == []
        assert empty_plan.buy_rules == []

    def test_execution_plan_with_rules(self, basic_buy_plan):
        """ExecutionPlan with buy rules."""
        assert len(basic_buy_plan.buy_rules) == 1
        assert basic_buy_plan.buy_rules[0].tickers == ["AAPL", "MSFT"]


class TestExecutionPlanSerialization:
    """Tests for ExecutionPlan to_dict() and from_dict() serialization."""

    def test_to_dict_minimal(self):
        """to_dict() with minimal plan."""
        plan = ExecutionPlan(description="Minimal")
        d = plan.to_dict()
        assert d["description"] == "Minimal"
        assert d["sell_rules"] == []
        assert d["buy_rules"] == []
        assert d["account_filter"] is None
        assert d["sells_before_buys"] is True

    def test_to_dict_with_rules(self):
        """to_dict() includes all rule fields."""
        plan = ExecutionPlan(
            description="Test",
            sell_rules=[SellRule(
                tickers=["BIL"],
                quantity_type=QuantityType.ALL,
                min_shares_remaining=5
            )],
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.025,
                skip_if_allocation_above=0.02
            )]
        )
        d = plan.to_dict()

        assert len(d["sell_rules"]) == 1
        assert d["sell_rules"][0]["tickers"] == ["BIL"]
        assert d["sell_rules"][0]["quantity_type"] == "all"
        assert d["sell_rules"][0]["min_shares_remaining"] == 5

        assert len(d["buy_rules"]) == 1
        assert d["buy_rules"][0]["tickers"] == ["AAPL"]
        assert d["buy_rules"][0]["quantity_type"] == "percent_of_account"
        assert d["buy_rules"][0]["quantity"] == 0.025
        assert d["buy_rules"][0]["skip_if_allocation_above"] == 0.02

    def test_to_dict_with_account_filter(self):
        """to_dict() includes account filter."""
        plan = ExecutionPlan(
            description="Test",
            account_filter=AccountFilter(
                min_value=10000.0,
                account_numbers=["ACC001"]
            )
        )
        d = plan.to_dict()
        assert d["account_filter"]["min_value"] == 10000.0
        assert d["account_filter"]["account_numbers"] == ["ACC001"]

    def test_from_dict_minimal(self):
        """from_dict() with minimal data."""
        data = {"description": "From dict test"}
        plan = ExecutionPlan.from_dict(data)
        assert plan.description == "From dict test"
        assert plan.sell_rules == []
        assert plan.buy_rules == []

    def test_from_dict_with_rules(self):
        """from_dict() parses rules correctly."""
        data = {
            "description": "Test",
            "sell_rules": [{
                "tickers": ["BIL"],
                "quantity_type": "all",
                "priority": "largest_first"
            }],
            "buy_rules": [{
                "tickers": ["AAPL"],
                "quantity_type": "percent_of_account",
                "quantity": 0.025,
                "buy_only_to_target": True
            }]
        }
        plan = ExecutionPlan.from_dict(data)

        assert len(plan.sell_rules) == 1
        assert plan.sell_rules[0].quantity_type == QuantityType.ALL

        assert len(plan.buy_rules) == 1
        assert plan.buy_rules[0].quantity_type == QuantityType.PERCENT_OF_ACCOUNT
        assert plan.buy_rules[0].quantity == 0.025
        assert plan.buy_rules[0].buy_only_to_target is True

    def test_from_dict_default_values(self):
        """from_dict() applies default values for missing fields."""
        data = {
            "description": "Test",
            "buy_rules": [{
                "tickers": ["AAPL"],
                "quantity_type": "percent_of_account"
            }]
        }
        plan = ExecutionPlan.from_dict(data)

        # Check defaults are applied
        rule = plan.buy_rules[0]
        assert rule.allocation_method == AllocationMethod.EQUAL_WEIGHT
        assert rule.buy_only_to_target is False
        assert rule.cash_source == CashSource.AVAILABLE_CASH
        assert rule.sell_cash_equiv_if_needed is False

    def test_from_dict_with_cash_management(self):
        """from_dict() parses cash management."""
        data = {
            "description": "Test",
            "cash_management": {
                "min_cash_percent": 0.05,
                "min_cash_dollars": 5000.0,
                "cash_equiv_sell_order": "smallest_first"
            }
        }
        plan = ExecutionPlan.from_dict(data)
        assert plan.cash_management.min_cash_percent == 0.05
        assert plan.cash_management.min_cash_dollars == 5000.0
        assert plan.cash_management.cash_equiv_sell_order == "smallest_first"

    def test_serialization_round_trip(self, complex_plan):
        """to_dict() -> from_dict() preserves all fields."""
        d = complex_plan.to_dict()
        restored = ExecutionPlan.from_dict(d)

        assert restored.description == complex_plan.description
        assert len(restored.sell_rules) == len(complex_plan.sell_rules)
        assert len(restored.buy_rules) == len(complex_plan.buy_rules)
        assert restored.sells_before_buys == complex_plan.sells_before_buys

        # Check sell rule details
        orig_sell = complex_plan.sell_rules[0]
        rest_sell = restored.sell_rules[0]
        assert rest_sell.tickers == orig_sell.tickers
        assert rest_sell.quantity_type == orig_sell.quantity_type

        # Check buy rule details
        orig_buy = complex_plan.buy_rules[0]
        rest_buy = restored.buy_rules[0]
        assert rest_buy.tickers == orig_buy.tickers
        assert rest_buy.quantity_type == orig_buy.quantity_type
        assert rest_buy.skip_if_allocation_above == orig_buy.skip_if_allocation_above
        assert rest_buy.sell_cash_equiv_if_needed == orig_buy.sell_cash_equiv_if_needed

    def test_serialization_round_trip_with_account_filter(self):
        """Round trip preserves account filter."""
        original = ExecutionPlan(
            description="Filter test",
            account_filter=AccountFilter(
                min_value=10000.0,
                max_value=500000.0,
                account_numbers=["A1", "A2"],
                must_hold_tickers=["AAPL"]
            )
        )
        d = original.to_dict()
        restored = ExecutionPlan.from_dict(d)

        assert restored.account_filter is not None
        assert restored.account_filter.min_value == 10000.0
        assert restored.account_filter.max_value == 500000.0
        assert restored.account_filter.account_numbers == ["A1", "A2"]
        assert restored.account_filter.must_hold_tickers == ["AAPL"]

    def test_from_dict_invalid_quantity_type(self):
        """from_dict() with invalid quantity_type raises ValueError."""
        data = {
            "description": "Test",
            "buy_rules": [{
                "tickers": ["AAPL"],
                "quantity_type": "invalid_type"
            }]
        }
        with pytest.raises(ValueError):
            ExecutionPlan.from_dict(data)

    def test_from_dict_empty_description(self):
        """from_dict() with missing description uses empty string."""
        data = {"buy_rules": []}
        plan = ExecutionPlan.from_dict(data)
        assert plan.description == ""

    def test_from_dict_sells_before_buys_false(self):
        """from_dict() respects sells_before_buys=False."""
        data = {
            "description": "Test",
            "sells_before_buys": False
        }
        plan = ExecutionPlan.from_dict(data)
        assert plan.sells_before_buys is False


class TestExecutionPlanEdgeCases:
    """Edge case tests for ExecutionPlan."""

    def test_plan_with_many_tickers(self):
        """Plan with many tickers in a single rule."""
        tickers = [f"TICK{i}" for i in range(100)]
        plan = ExecutionPlan(
            description="Many tickers",
            buy_rules=[BuyRule(
                tickers=tickers,
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.01
            )]
        )
        d = plan.to_dict()
        assert len(d["buy_rules"][0]["tickers"]) == 100

        restored = ExecutionPlan.from_dict(d)
        assert len(restored.buy_rules[0].tickers) == 100

    def test_plan_with_zero_quantity(self):
        """Plan with zero quantity."""
        plan = ExecutionPlan(
            description="Zero quantity",
            buy_rules=[BuyRule(
                tickers=["AAPL"],
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=0.0
            )]
        )
        assert plan.buy_rules[0].quantity == 0.0

    def test_plan_with_negative_values(self):
        """Plan with negative values (edge case, not typical)."""
        plan = ExecutionPlan(
            description="Negative",
            account_filter=AccountFilter(min_value=-1000.0)
        )
        assert plan.account_filter.min_value == -1000.0

    def test_sell_rule_max_percent_zero(self):
        """SellRule with max_percent_of_position = 0."""
        rule = SellRule(
            tickers=["AAPL"],
            quantity_type=QuantityType.ALL,
            max_percent_of_position=0.0
        )
        assert rule.max_percent_of_position == 0.0
