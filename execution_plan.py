"""
Execution Plan Schema

Defines the structured format that the LLM outputs and the execution engine consumes.
This creates a clear contract between natural language interpretation and deterministic execution.
"""

from dataclasses import dataclass, field
from typing import Optional, Literal
from enum import Enum


class QuantityType(Enum):
    """How to interpret the quantity field."""
    PERCENT_OF_POSITION = "percent_of_position"  # e.g., sell 50% of holding
    PERCENT_OF_ACCOUNT = "percent_of_account"    # e.g., allocate 2.5% of account value
    SHARES = "shares"                             # e.g., sell 100 shares
    DOLLARS = "dollars"                           # e.g., buy $5000 worth
    ALL = "all"                                   # e.g., sell entire position
    TO_TARGET = "to_target"                       # e.g., buy/sell to reach target allocation


class AllocationMethod(Enum):
    """How to allocate among multiple tickers."""
    EQUAL_WEIGHT = "equal_weight"                 # Split evenly
    PROPORTIONAL = "proportional"                 # Based on some factor
    SPECIFIED = "specified"                       # Per-ticker amounts given


class CashSource(Enum):
    """Where to get cash for buys."""
    AVAILABLE_CASH = "available_cash"             # Use existing cash only
    CASH_EQUIVALENTS = "cash_equivalents"         # Sell cash equivalents if needed
    SELL_HOLDINGS = "sell_holdings"               # Sell specified holdings


@dataclass
class SellRule:
    """Rule for selling securities."""
    tickers: list[str]                            # Which tickers to sell
    quantity_type: QuantityType                   # How to interpret quantity
    quantity: Optional[float] = None              # The amount (interpretation depends on type)
    priority: str = "largest_first"               # Which positions to sell first
    
    # Constraints
    min_shares_remaining: Optional[int] = None    # Don't reduce below this
    max_percent_of_position: Optional[float] = None  # Don't sell more than X% of any position


@dataclass
class BuyRule:
    """Rule for buying securities."""
    tickers: list[str]                            # Which tickers to buy
    quantity_type: QuantityType                   # How to interpret quantity
    quantity: Optional[float] = None              # Target amount per ticker
    allocation_method: AllocationMethod = AllocationMethod.EQUAL_WEIGHT
    
    # Conditional logic
    skip_if_allocation_above: Optional[float] = None   # Skip if already own >= X%
    buy_only_to_target: bool = False                   # If true, only buy enough to reach target
    
    # Cash sourcing
    cash_source: CashSource = CashSource.AVAILABLE_CASH
    sell_cash_equiv_if_needed: bool = False


@dataclass 
class AccountFilter:
    """Filter to determine which accounts to process."""
    min_value: Optional[float] = None             # Skip accounts below this value
    max_value: Optional[float] = None             # Skip accounts above this value
    account_numbers: Optional[list[str]] = None   # Only process these accounts
    must_hold_tickers: Optional[list[str]] = None # Only process if holds these


@dataclass
class CashManagement:
    """Rules for cash management."""
    min_cash_percent: float = 0.02                # Minimum cash to maintain (2% default)
    min_cash_dollars: Optional[float] = None      # Minimum cash in dollars
    cash_equiv_sell_order: str = "largest_first"  # How to prioritize selling cash equivalents


@dataclass
class ExecutionPlan:
    """
    The complete execution plan that bridges natural language specs to deterministic execution.
    
    This is what the LLM produces and what the OrderGenerator consumes.
    """
    # Human-readable description of what was requested
    description: str
    
    # Operations to perform
    sell_rules: list[SellRule] = field(default_factory=list)
    buy_rules: list[BuyRule] = field(default_factory=list)
    
    # Filters and constraints
    account_filter: Optional[AccountFilter] = None
    cash_management: CashManagement = field(default_factory=CashManagement)
    
    # Execution order
    sells_before_buys: bool = True                # Execute sells first to free up cash
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "description": self.description,
            "sell_rules": [
                {
                    "tickers": r.tickers,
                    "quantity_type": r.quantity_type.value,
                    "quantity": r.quantity,
                    "priority": r.priority,
                    "min_shares_remaining": r.min_shares_remaining,
                    "max_percent_of_position": r.max_percent_of_position
                }
                for r in self.sell_rules
            ],
            "buy_rules": [
                {
                    "tickers": r.tickers,
                    "quantity_type": r.quantity_type.value,
                    "quantity": r.quantity,
                    "allocation_method": r.allocation_method.value,
                    "skip_if_allocation_above": r.skip_if_allocation_above,
                    "buy_only_to_target": r.buy_only_to_target,
                    "cash_source": r.cash_source.value,
                    "sell_cash_equiv_if_needed": r.sell_cash_equiv_if_needed
                }
                for r in self.buy_rules
            ],
            "account_filter": {
                "min_value": self.account_filter.min_value,
                "max_value": self.account_filter.max_value,
                "account_numbers": self.account_filter.account_numbers,
                "must_hold_tickers": self.account_filter.must_hold_tickers
            } if self.account_filter else None,
            "cash_management": {
                "min_cash_percent": self.cash_management.min_cash_percent,
                "min_cash_dollars": self.cash_management.min_cash_dollars,
                "cash_equiv_sell_order": self.cash_management.cash_equiv_sell_order
            },
            "sells_before_buys": self.sells_before_buys
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ExecutionPlan":
        """Create ExecutionPlan from dictionary (e.g., from LLM JSON output)."""
        sell_rules = []
        for r in data.get("sell_rules", []):
            sell_rules.append(SellRule(
                tickers=r["tickers"],
                quantity_type=QuantityType(r["quantity_type"]),
                quantity=r.get("quantity"),
                priority=r.get("priority", "largest_first"),
                min_shares_remaining=r.get("min_shares_remaining"),
                max_percent_of_position=r.get("max_percent_of_position")
            ))
        
        buy_rules = []
        for r in data.get("buy_rules", []):
            buy_rules.append(BuyRule(
                tickers=r["tickers"],
                quantity_type=QuantityType(r["quantity_type"]),
                quantity=r.get("quantity"),
                allocation_method=AllocationMethod(r.get("allocation_method", "equal_weight")),
                skip_if_allocation_above=r.get("skip_if_allocation_above"),
                buy_only_to_target=r.get("buy_only_to_target", False),
                cash_source=CashSource(r.get("cash_source", "available_cash")),
                sell_cash_equiv_if_needed=r.get("sell_cash_equiv_if_needed", False)
            ))
        
        account_filter = None
        if data.get("account_filter"):
            af = data["account_filter"]
            account_filter = AccountFilter(
                min_value=af.get("min_value"),
                max_value=af.get("max_value"),
                account_numbers=af.get("account_numbers"),
                must_hold_tickers=af.get("must_hold_tickers")
            )
        
        cm_data = data.get("cash_management", {})
        cash_management = CashManagement(
            min_cash_percent=cm_data.get("min_cash_percent", 0.02),
            min_cash_dollars=cm_data.get("min_cash_dollars"),
            cash_equiv_sell_order=cm_data.get("cash_equiv_sell_order", "largest_first")
        )
        
        return cls(
            description=data.get("description", ""),
            sell_rules=sell_rules,
            buy_rules=buy_rules,
            account_filter=account_filter,
            cash_management=cash_management,
            sells_before_buys=data.get("sells_before_buys", True)
        )
