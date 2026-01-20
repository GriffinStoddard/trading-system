"""
Tests for report_generator.py - Formatting functions and report generation.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from report_generator import (
    format_currency, format_percent, generate_summary_report, print_confirmation_prompt
)
from order_generator import Order, AccountTradeAnalysis, TickerAnalysis


class TestFormatCurrency:
    """Tests for format_currency function."""

    def test_format_positive_value(self):
        """Format positive currency value."""
        assert format_currency(1234.56) == "$1,234.56"

    def test_format_negative_value(self):
        """Format negative currency value."""
        assert format_currency(-1234.56) == "-$1,234.56"

    def test_format_zero(self):
        """Format zero."""
        assert format_currency(0) == "$0.00"

    def test_format_small_value(self):
        """Format small decimal value."""
        assert format_currency(0.01) == "$0.01"

    def test_format_large_value(self):
        """Format large value with thousands separator."""
        assert format_currency(1234567.89) == "$1,234,567.89"

    def test_format_negative_small_value(self):
        """Format small negative value."""
        assert format_currency(-0.01) == "-$0.01"

    def test_format_rounds_to_cents(self):
        """Format rounds to two decimal places."""
        assert format_currency(1.999) == "$2.00"
        assert format_currency(1.001) == "$1.00"

    def test_format_very_large_value(self):
        """Format very large value."""
        assert format_currency(1_000_000_000.00) == "$1,000,000,000.00"


class TestFormatPercent:
    """Tests for format_percent function."""

    def test_format_standard_percent(self):
        """Format standard percentage."""
        assert format_percent(0.025) == "2.50%"

    def test_format_zero_percent(self):
        """Format zero percent."""
        assert format_percent(0) == "0.00%"

    def test_format_one_hundred_percent(self):
        """Format 100%."""
        assert format_percent(1.0) == "100.00%"

    def test_format_greater_than_100_percent(self):
        """Format values > 1.0 (> 100%)."""
        assert format_percent(1.5) == "150.00%"
        assert format_percent(2.0) == "200.00%"

    def test_format_small_percent(self):
        """Format small percentage."""
        assert format_percent(0.001) == "0.10%"

    def test_format_negative_percent(self):
        """Format negative percentage."""
        assert format_percent(-0.05) == "-5.00%"

    def test_format_rounds_to_two_decimals(self):
        """Format rounds to two decimal places."""
        assert format_percent(0.12345) == "12.35%"
        assert format_percent(0.12344) == "12.34%"


class TestGenerateSummaryReport:
    """Tests for generate_summary_report function."""

    @pytest.fixture
    def sample_analysis(self):
        """Create a sample AccountTradeAnalysis."""
        analysis = AccountTradeAnalysis(
            account_num="TEST001",
            client_name="Test Client",
            total_value=100000.0,
            cash_before=10000.0,
            cash_equivalents_before=20000.0,
            holdings_before=[
                {"symbol": "AAPL", "shares": 100, "value": 15000.0},
                {"symbol": "MSFT", "shares": 50, "value": 15000.0}
            ]
        )
        analysis.ticker_analysis = [
            TickerAnalysis(
                ticker="AAPL",
                current_shares=100,
                current_value=15000.0,
                current_allocation=0.15,
                target_allocation=0.025,
                action="SKIP",
                shares_to_trade=0,
                estimated_value=0,
                new_allocation=0.15,
                reason="Already above target"
            ),
            TickerAnalysis(
                ticker="META",
                current_shares=0,
                current_value=0,
                current_allocation=0,
                target_allocation=0.025,
                action="BUY",
                shares_to_trade=5,
                estimated_value=2500.0,
                new_allocation=0.025,
                reason="Buying to target"
            )
        ]
        analysis.buy_orders = [
            Order("TEST001", "Test Client", "META", "Buy", 5, 2500.0, "Buy to target")
        ]
        analysis.cash_from_sells = 0.0
        analysis.cash_used_for_buys = 2500.0
        analysis.cash_after = 7500.0
        return analysis

    @pytest.fixture
    def sample_orders(self):
        """Create sample orders."""
        sell_orders = []
        buy_orders = [
            Order("TEST001", "Test Client", "META", "Buy", 5, 2500.0, "Buy to target")
        ]
        return sell_orders, buy_orders

    def test_report_contains_header(self, sample_analysis, sample_orders):
        """Report contains header section."""
        sell_orders, buy_orders = sample_orders
        report = generate_summary_report(
            [sample_analysis], sell_orders, buy_orders,
            "Test plan", "sells.csv", "buys.csv"
        )

        assert "TRADE EXECUTION SUMMARY" in report
        assert "Test plan" in report

    def test_report_contains_account_info(self, sample_analysis, sample_orders):
        """Report contains account information."""
        sell_orders, buy_orders = sample_orders
        report = generate_summary_report(
            [sample_analysis], sell_orders, buy_orders,
            "Test plan", "sells.csv", "buys.csv"
        )

        assert "TEST001" in report
        assert "Test Client" in report
        assert "$100,000.00" in report

    def test_report_contains_ticker_analysis(self, sample_analysis, sample_orders):
        """Report contains ticker analysis table."""
        sell_orders, buy_orders = sample_orders
        report = generate_summary_report(
            [sample_analysis], sell_orders, buy_orders,
            "Test plan", "sells.csv", "buys.csv"
        )

        assert "AAPL" in report
        assert "META" in report
        assert "SKIP" in report
        assert "BUY" in report

    def test_report_contains_cash_flow(self, sample_analysis, sample_orders):
        """Report contains cash flow section."""
        sell_orders, buy_orders = sample_orders
        report = generate_summary_report(
            [sample_analysis], sell_orders, buy_orders,
            "Test plan", "sells.csv", "buys.csv"
        )

        assert "CASH FLOW" in report
        assert "Starting cash" in report
        assert "Ending cash" in report

    def test_report_contains_aggregate_summary(self, sample_analysis, sample_orders):
        """Report contains aggregate summary."""
        sell_orders, buy_orders = sample_orders
        report = generate_summary_report(
            [sample_analysis], sell_orders, buy_orders,
            "Test plan", "sells.csv", "buys.csv"
        )

        assert "AGGREGATE SUMMARY" in report
        assert "Total Accounts Processed: 1" in report
        assert "Total Buy Orders: 1" in report

    def test_report_empty_analyses_list(self):
        """Report handles empty analyses list."""
        report = generate_summary_report(
            [], [], [],
            "Empty plan", "sells.csv", "buys.csv"
        )

        assert "TRADE EXECUTION SUMMARY" in report
        assert "Total Accounts Processed: 0" in report

    def test_report_with_zero_total_value(self):
        """Report handles account with zero total_value (no division by zero)."""
        analysis = AccountTradeAnalysis(
            account_num="ZERO",
            client_name="Zero Client",
            total_value=0.0,
            cash_before=0.0,
            cash_equivalents_before=0.0,
            holdings_before=[]
        )

        report = generate_summary_report(
            [analysis], [], [],
            "Zero value plan", "sells.csv", "buys.csv"
        )

        # Should not raise division by zero
        assert "ZERO" in report
        assert "$0.00" in report

    def test_report_ticker_analysis_with_none_target(self, sample_analysis, sample_orders):
        """Report handles ticker analysis with None target_allocation."""
        sample_analysis.ticker_analysis.append(
            TickerAnalysis(
                ticker="BIL",
                current_shares=100,
                current_value=9150.0,
                current_allocation=0.0915,
                target_allocation=None,  # None target
                action="SELL",
                shares_to_trade=100,
                estimated_value=9150.0,
                new_allocation=0.0,
                reason="Selling cash equivalent"
            )
        )

        sell_orders, buy_orders = sample_orders
        sell_orders_with_bil = [
            Order("TEST001", "Test Client", "BIL", "Sell", 100, 9150.0, "Liquidating")
        ]

        report = generate_summary_report(
            [sample_analysis], sell_orders_with_bil, buy_orders,
            "With None target", "sells.csv", "buys.csv"
        )

        assert "BIL" in report
        assert "SELL" in report

    def test_report_with_warnings(self, sample_analysis, sample_orders):
        """Report displays warnings."""
        sample_analysis.warnings = ["Insufficient cash for NVDA", "Price missing for XYZ"]

        sell_orders, buy_orders = sample_orders
        report = generate_summary_report(
            [sample_analysis], sell_orders, buy_orders,
            "With warnings", "sells.csv", "buys.csv"
        )

        assert "WARNINGS" in report
        assert "Insufficient cash for NVDA" in report


class TestPrintConfirmationPrompt:
    """Tests for print_confirmation_prompt function."""

    @pytest.fixture
    def sample_data(self):
        """Create sample data for confirmation prompt."""
        analysis = AccountTradeAnalysis(
            account_num="TEST001",
            client_name="Test Client",
            total_value=100000.0,
            cash_before=10000.0,
            cash_equivalents_before=20000.0,
            holdings_before=[]
        )
        sell_orders = [
            Order("TEST001", "Test Client", "BIL", "Sell", 100, 9150.0, "Liquidating")
        ]
        buy_orders = [
            Order("TEST001", "Test Client", "AAPL", "Buy", 10, 1500.0, "Buy to target"),
            Order("TEST001", "Test Client", "MSFT", "Buy", 5, 1500.0, "Buy to target")
        ]
        return [analysis], sell_orders, buy_orders

    def test_confirmation_contains_header(self, sample_data):
        """Confirmation prompt contains header."""
        analyses, sell_orders, buy_orders = sample_data
        prompt = print_confirmation_prompt(
            "Test plan", analyses, sell_orders, buy_orders
        )

        assert "EXECUTION PLAN CONFIRMATION" in prompt

    def test_confirmation_contains_counts(self, sample_data):
        """Confirmation prompt contains order counts."""
        analyses, sell_orders, buy_orders = sample_data
        prompt = print_confirmation_prompt(
            "Test plan", analyses, sell_orders, buy_orders
        )

        assert "Accounts to process: 1" in prompt
        assert "Sell orders: 1" in prompt
        assert "Buy orders: 2" in prompt

    def test_confirmation_contains_tickers(self, sample_data):
        """Confirmation prompt lists tickers being traded."""
        analyses, sell_orders, buy_orders = sample_data
        prompt = print_confirmation_prompt(
            "Test plan", analyses, sell_orders, buy_orders
        )

        assert "Selling: BIL" in prompt
        assert "AAPL" in prompt
        assert "MSFT" in prompt

    def test_confirmation_empty_orders(self):
        """Confirmation prompt handles empty orders."""
        prompt = print_confirmation_prompt(
            "Empty plan", [], [], []
        )

        assert "Accounts to process: 0" in prompt
        assert "Sell orders: 0" in prompt
        assert "Buy orders: 0" in prompt
        # Should not contain "Selling:" or "Buying:" lines
        assert "Selling:" not in prompt
        assert "Buying:" not in prompt

    def test_confirmation_contains_plan_description(self, sample_data):
        """Confirmation prompt contains plan description."""
        analyses, sell_orders, buy_orders = sample_data
        prompt = print_confirmation_prompt(
            "Buy 2.5% allocation in AAPL and MSFT",
            analyses, sell_orders, buy_orders
        )

        assert "Buy 2.5% allocation in AAPL and MSFT" in prompt


class TestReportEdgeCases:
    """Edge case tests for report generation."""

    def test_report_with_long_reason(self):
        """Report truncates long reasons."""
        analysis = AccountTradeAnalysis(
            account_num="TEST",
            client_name="Test",
            total_value=100000.0,
            cash_before=10000.0,
            cash_equivalents_before=0.0,
            holdings_before=[]
        )
        analysis.ticker_analysis = [
            TickerAnalysis(
                ticker="AAPL",
                current_shares=0,
                current_value=0,
                current_allocation=0,
                target_allocation=0.025,
                action="BUY",
                shares_to_trade=10,
                estimated_value=1500.0,
                new_allocation=0.015,
                reason="This is a very long reason that should be truncated when displayed in the report table"
            )
        ]

        report = generate_summary_report(
            [analysis], [], [],
            "Long reason test", "sells.csv", "buys.csv"
        )

        # Reason should be truncated (check for ... if over 30 chars)
        assert "..." in report or "This is a very long" in report

    def test_report_with_special_characters_in_name(self):
        """Report handles special characters in client name."""
        analysis = AccountTradeAnalysis(
            account_num="TEST",
            client_name="O'Brien & Sons, LLC",
            total_value=100000.0,
            cash_before=10000.0,
            cash_equivalents_before=0.0,
            holdings_before=[]
        )

        report = generate_summary_report(
            [analysis], [], [],
            "Special chars test", "sells.csv", "buys.csv"
        )

        assert "O'Brien & Sons, LLC" in report

    def test_report_multiple_accounts(self):
        """Report handles multiple accounts."""
        analysis1 = AccountTradeAnalysis(
            account_num="ACC001",
            client_name="Client One",
            total_value=50000.0,
            cash_before=5000.0,
            cash_equivalents_before=0.0,
            holdings_before=[]
        )
        analysis2 = AccountTradeAnalysis(
            account_num="ACC002",
            client_name="Client Two",
            total_value=75000.0,
            cash_before=7500.0,
            cash_equivalents_before=0.0,
            holdings_before=[]
        )

        report = generate_summary_report(
            [analysis1, analysis2], [], [],
            "Multi-account test", "sells.csv", "buys.csv"
        )

        assert "ACC001" in report
        assert "ACC002" in report
        assert "Client One" in report
        assert "Client Two" in report
        assert "Total Accounts Processed: 2" in report

    def test_report_cash_floor_warning(self):
        """Report shows warning when below cash floor."""
        analysis = AccountTradeAnalysis(
            account_num="TEST",
            client_name="Test",
            total_value=100000.0,
            cash_before=10000.0,
            cash_equivalents_before=0.0,
            holdings_before=[]
        )
        analysis.cash_after = 100.0  # Below 2% of 100000 = 2000

        report = generate_summary_report(
            [analysis], [], [],
            "Below floor test", "sells.csv", "buys.csv"
        )

        assert "WARNING" in report or "Below 2% cash floor" in report

    def test_report_above_cash_floor(self):
        """Report shows success when above cash floor."""
        analysis = AccountTradeAnalysis(
            account_num="TEST",
            client_name="Test",
            total_value=100000.0,
            cash_before=10000.0,
            cash_equivalents_before=0.0,
            holdings_before=[]
        )
        analysis.cash_after = 5000.0  # Above 2% of 100000 = 2000

        report = generate_summary_report(
            [analysis], [], [],
            "Above floor test", "sells.csv", "buys.csv"
        )

        assert "Above 2% cash floor" in report
