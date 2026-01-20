"""
Tests for models.py - Account, Holding, and AccountParser classes.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Account, Holding


class TestHolding:
    """Tests for the Holding dataclass."""

    def test_holding_with_all_fields(self):
        """Holding with all fields populated."""
        holding = Holding("AAPL", shares=100, price=150.0, market_value=15000.0)
        assert holding.symbol == "AAPL"
        assert holding.shares == 100
        assert holding.price == 150.0
        assert holding.market_value == 15000.0

    def test_holding_with_none_price(self):
        """Holding with None price."""
        holding = Holding("AAPL", shares=100, price=None, market_value=15000.0)
        assert holding.price is None
        assert holding.market_value == 15000.0

    def test_holding_with_none_market_value(self):
        """Holding with None market_value."""
        holding = Holding("AAPL", shares=100, price=150.0, market_value=None)
        assert holding.market_value is None

    def test_holding_with_zero_shares(self):
        """Holding with zero shares."""
        holding = Holding("AAPL", shares=0, price=150.0, market_value=0.0)
        assert holding.shares == 0
        assert holding.market_value == 0.0

    def test_holding_with_fractional_shares(self):
        """Holding with fractional shares."""
        holding = Holding("AAPL", shares=10.5, price=150.0, market_value=1575.0)
        assert holding.shares == 10.5

    def test_holding_with_negative_shares(self):
        """Holding with negative shares (short position edge case)."""
        holding = Holding("AAPL", shares=-100, price=150.0, market_value=-15000.0)
        assert holding.shares == -100

    def test_holding_defaults(self):
        """Holding with only required fields uses defaults."""
        holding = Holding("AAPL", shares=100)
        assert holding.price is None
        assert holding.market_value is None


class TestAccount:
    """Tests for the Account dataclass."""

    def test_empty_account(self, empty_account):
        """Account with no holdings."""
        assert empty_account.account_num == "EMPTY001"
        assert empty_account.holdings == []
        assert empty_account.cash == 0.0
        assert empty_account.cash_equivalents == []

    def test_account_total_value_empty(self, empty_account):
        """Total value of empty account is zero."""
        assert empty_account.get_total_value() == 0.0

    def test_account_total_value_cash_only(self, cash_only_account):
        """Total value with only cash."""
        assert cash_only_account.get_total_value() == 50000.0

    def test_account_total_value_with_holdings(self, multi_holding_account):
        """Total value includes cash, holdings, and cash equivalents."""
        # cash: 10000 + holdings: 15000+50000+15000 + CE: 18300+5000 = 113300
        expected = 10000.0 + 15000.0 + 50000.0 + 15000.0 + 18300.0 + 5000.0
        assert multi_holding_account.get_total_value() == expected

    def test_account_holdings_value(self, multi_holding_account):
        """Holdings value calculation."""
        # 15000 + 50000 + 15000 = 80000
        assert multi_holding_account.get_holdings_value() == 80000.0

    def test_account_cash_equivalents_value(self, multi_holding_account):
        """Cash equivalents value calculation."""
        # 18300 + 5000 = 23300
        assert multi_holding_account.get_cash_equivalents_value() == 23300.0

    def test_account_with_none_market_values(self, zero_value_account):
        """Account handles None market values gracefully."""
        assert zero_value_account.get_holdings_value() == 0.0
        assert zero_value_account.get_total_value() == 0.0

    def test_get_holding_exists(self, multi_holding_account):
        """Get existing holding by symbol."""
        holding = multi_holding_account.get_holding("AAPL")
        assert holding is not None
        assert holding.symbol == "AAPL"
        assert holding.shares == 100

    def test_get_holding_not_exists(self, multi_holding_account):
        """Get non-existent holding returns None."""
        holding = multi_holding_account.get_holding("TSLA")
        assert holding is None

    def test_get_holding_case_insensitive(self, multi_holding_account):
        """Symbol lookup is case-insensitive."""
        assert multi_holding_account.get_holding("aapl") is not None
        assert multi_holding_account.get_holding("AAPL") is not None
        assert multi_holding_account.get_holding("Aapl") is not None

    def test_get_cash_equivalent_exists(self, multi_holding_account):
        """Get existing cash equivalent by symbol."""
        ce = multi_holding_account.get_cash_equivalent("BIL")
        assert ce is not None
        assert ce.symbol == "BIL"

    def test_get_cash_equivalent_not_exists(self, multi_holding_account):
        """Get non-existent cash equivalent returns None."""
        ce = multi_holding_account.get_cash_equivalent("PJLXX")
        assert ce is None  # PJLXX not in this account

    def test_get_cash_equivalent_case_insensitive(self, multi_holding_account):
        """Cash equivalent lookup is case-insensitive."""
        assert multi_holding_account.get_cash_equivalent("bil") is not None
        assert multi_holding_account.get_cash_equivalent("BIL") is not None

    def test_get_holding_allocation_exists(self, multi_holding_account):
        """Allocation percentage for existing holding."""
        total = multi_holding_account.get_total_value()
        expected_alloc = 15000.0 / total  # AAPL value / total
        assert multi_holding_account.get_holding_allocation("AAPL") == pytest.approx(expected_alloc)

    def test_get_holding_allocation_not_exists(self, multi_holding_account):
        """Allocation for non-existent holding is zero."""
        assert multi_holding_account.get_holding_allocation("TSLA") == 0.0

    def test_get_holding_allocation_zero_total(self, empty_account):
        """Allocation when total value is zero."""
        assert empty_account.get_holding_allocation("AAPL") == 0.0

    def test_get_holding_allocation_none_market_value(self):
        """Allocation when holding has None market value."""
        account = Account(account_num="TEST", cash=10000.0)
        account.add_holding(Holding("AAPL", shares=100, price=150.0, market_value=None))
        assert account.get_holding_allocation("AAPL") == 0.0

    def test_add_holding(self):
        """Add holding to account."""
        account = Account(account_num="TEST")
        holding = Holding("AAPL", shares=100, price=150.0, market_value=15000.0)
        account.add_holding(holding)
        assert len(account.holdings) == 1
        assert account.holdings[0].symbol == "AAPL"

    def test_add_cash_equivalent(self):
        """Add cash equivalent to account."""
        account = Account(account_num="TEST")
        ce = Holding("BIL", shares=100, price=91.50, market_value=9150.0)
        account.add_cash_equivalent(ce)
        assert len(account.cash_equivalents) == 1
        assert account.cash_equivalents[0].symbol == "BIL"

    def test_account_only_cash_equivalents(self, cash_equiv_only_account):
        """Account with only cash equivalents (no regular holdings)."""
        assert len(cash_equiv_only_account.holdings) == 0
        assert len(cash_equiv_only_account.cash_equivalents) == 2
        # cash: 1000 + CE: 45750 + 1000 = 47750
        assert cash_equiv_only_account.get_total_value() == 47750.0


class TestAccountEdgeCases:
    """Edge case tests for Account."""

    def test_account_with_duplicate_symbols(self):
        """Account with duplicate symbols in holdings."""
        account = Account(account_num="TEST", cash=1000.0)
        account.add_holding(Holding("AAPL", shares=50, price=150.0, market_value=7500.0))
        account.add_holding(Holding("AAPL", shares=50, price=150.0, market_value=7500.0))
        # get_holding returns first match
        holding = account.get_holding("AAPL")
        assert holding.shares == 50
        # But total value includes both
        assert account.get_holdings_value() == 15000.0

    def test_account_with_very_small_values(self):
        """Account with very small dollar values."""
        account = Account(account_num="TEST", cash=0.01)
        account.add_holding(Holding("PENNY", shares=1, price=0.01, market_value=0.01))
        assert account.get_total_value() == pytest.approx(0.02)

    def test_account_with_very_large_values(self):
        """Account with very large dollar values."""
        account = Account(account_num="TEST", cash=1_000_000_000.0)  # 1 billion
        account.add_holding(Holding("BRK.A", shares=1000, price=500000.0, market_value=500_000_000.0))
        assert account.get_total_value() == 1_500_000_000.0

    def test_account_default_client_name(self):
        """Account has empty client name by default."""
        account = Account(account_num="TEST")
        assert account.client_name == ""

    def test_account_with_special_characters_in_name(self):
        """Account with special characters in client name."""
        account = Account(account_num="TEST", client_name="O'Brien & Sons, LLC")
        assert account.client_name == "O'Brien & Sons, LLC"


class TestAccountParser:
    """Tests for AccountParser - mock-based since it requires Excel files."""

    def test_cash_equivalents_constant(self):
        """Verify CASH_EQUIVALENTS constant."""
        from models import AccountParser
        assert "BIL" in AccountParser.CASH_EQUIVALENTS
        assert "USFR" in AccountParser.CASH_EQUIVALENTS
        assert "PJLXX" in AccountParser.CASH_EQUIVALENTS
        assert len(AccountParser.CASH_EQUIVALENTS) == 3

    def test_account_cash_equiv_symbols_constant(self):
        """Verify Account.CASH_EQUIV_SYMBOLS constant."""
        assert "BIL" in Account.CASH_EQUIV_SYMBOLS
        assert "USFR" in Account.CASH_EQUIV_SYMBOLS
        assert "PJLXX" in Account.CASH_EQUIV_SYMBOLS
