"""
Order Generator - Deterministic Execution Engine

Takes an ExecutionPlan and account data, produces concrete buy/sell orders.
All calculations are deterministic - no LLM involvement here.
"""

import math
from dataclasses import dataclass, field
from typing import Optional
from models import Account, Holding
from execution_plan import (
    ExecutionPlan, BuyRule, SellRule, 
    QuantityType, CashSource, AllocationMethod
)


@dataclass
class Order:
    """A single trade order."""
    account_num: str
    client_name: str
    security: str
    action: str  # "Buy" or "Sell"
    shares: int
    estimated_value: float = 0.0
    reason: str = ""


@dataclass
class AccountTradeAnalysis:
    """Detailed analysis of trades for a single account."""
    account_num: str
    client_name: str
    total_value: float
    cash_before: float
    cash_equivalents_before: float
    holdings_before: list
    
    # Analysis per ticker
    ticker_analysis: list = field(default_factory=list)
    
    # Orders generated
    sell_orders: list = field(default_factory=list)
    buy_orders: list = field(default_factory=list)
    
    # Cash flow
    cash_from_sells: float = 0.0
    cash_used_for_buys: float = 0.0
    cash_after: float = 0.0
    
    # Warnings/notes
    warnings: list = field(default_factory=list)


@dataclass
class TickerAnalysis:
    """Analysis for a single ticker in an account."""
    ticker: str
    current_shares: float
    current_value: float
    current_allocation: float  # As decimal (0.025 = 2.5%)
    target_allocation: Optional[float]
    action: str  # "BUY", "SELL", "SKIP", "HOLD"
    shares_to_trade: int
    estimated_value: float
    new_allocation: float
    reason: str


class OrderGenerator:
    """
    Generates concrete orders from an execution plan.
    
    This is the deterministic engine - given the same inputs, 
    it will always produce the same outputs.
    """
    
    def __init__(self, accounts: dict[str, Account], stock_prices: dict[str, float]):
        self.accounts = accounts
        self.stock_prices = stock_prices  # {ticker: price}
        self.analyses: list[AccountTradeAnalysis] = []
    
    def execute_plan(self, plan: ExecutionPlan) -> tuple[list[Order], list[Order]]:
        """
        Execute an execution plan and generate orders.
        
        Returns:
            Tuple of (sell_orders, buy_orders)
        """
        all_sell_orders = []
        all_buy_orders = []
        self.analyses = []
        
        for account_num, account in self.accounts.items():
            # Check account filter
            if not self._passes_filter(account, plan.account_filter):
                continue
            
            # Create analysis object
            analysis = AccountTradeAnalysis(
                account_num=account_num,
                client_name=account.client_name,
                total_value=account.get_total_value(),
                cash_before=account.cash,
                cash_equivalents_before=account.get_cash_equivalents_value(),
                holdings_before=[
                    {"symbol": h.symbol, "shares": h.shares, "value": h.market_value}
                    for h in account.holdings
                ]
            )
            
            # Track available cash through the process
            available_cash = account.cash
            
            # Process sell rules first (if sells_before_buys)
            if plan.sells_before_buys:
                for sell_rule in plan.sell_rules:
                    orders, cash_generated = self._process_sell_rule(
                        account, sell_rule, analysis
                    )
                    all_sell_orders.extend(orders)
                    analysis.sell_orders.extend(orders)
                    analysis.cash_from_sells += cash_generated
                    available_cash += cash_generated
            
            # Process buy rules
            for buy_rule in plan.buy_rules:
                orders, cash_used, ce_sell_orders = self._process_buy_rule(
                    account, buy_rule, available_cash, plan.cash_management, analysis
                )
                all_buy_orders.extend(orders)
                all_sell_orders.extend(ce_sell_orders)
                analysis.buy_orders.extend(orders)
                analysis.sell_orders.extend(ce_sell_orders)
                analysis.cash_used_for_buys += cash_used
                analysis.cash_from_sells += sum(o.estimated_value for o in ce_sell_orders)
                available_cash -= cash_used
            
            # Calculate final cash position
            analysis.cash_after = (
                analysis.cash_before 
                + analysis.cash_from_sells 
                - analysis.cash_used_for_buys
            )
            
            self.analyses.append(analysis)
        
        return all_sell_orders, all_buy_orders
    
    def _passes_filter(self, account: Account, filter_obj) -> bool:
        """Check if account passes the filter criteria."""
        if filter_obj is None:
            return True
        
        total_value = account.get_total_value()
        
        if filter_obj.min_value and total_value < filter_obj.min_value:
            return False
        if filter_obj.max_value and total_value > filter_obj.max_value:
            return False
        if filter_obj.account_numbers and account.account_num not in filter_obj.account_numbers:
            return False
        if filter_obj.must_hold_tickers:
            held = {h.symbol.upper() for h in account.holdings}
            required = {t.upper() for t in filter_obj.must_hold_tickers}
            if not required.intersection(held):
                return False
        
        return True
    
    def _process_sell_rule(
        self, 
        account: Account, 
        rule: SellRule,
        analysis: AccountTradeAnalysis
    ) -> tuple[list[Order], float]:
        """Process a sell rule for an account."""
        orders = []
        cash_generated = 0.0
        
        for ticker in rule.tickers:
            ticker = ticker.upper()
            
            # Check regular holdings
            holding = account.get_holding(ticker)
            if not holding:
                # Check cash equivalents
                holding = account.get_cash_equivalent(ticker)
            
            if not holding or holding.shares <= 0:
                continue
            
            # Calculate shares to sell based on quantity type
            shares_to_sell = self._calculate_sell_shares(
                holding, rule, account.get_total_value()
            )
            
            if shares_to_sell <= 0:
                continue
            
            # Get price
            price = holding.price or self.stock_prices.get(ticker, 0)
            estimated_value = shares_to_sell * price
            
            order = Order(
                account_num=account.account_num,
                client_name=account.client_name,
                security=ticker,
                action="Sell",
                shares=shares_to_sell,
                estimated_value=estimated_value,
                reason=f"Sell rule: {rule.quantity_type.value}"
            )
            orders.append(order)
            cash_generated += estimated_value
            
            # Add to analysis
            current_alloc = (holding.market_value or 0) / account.get_total_value()
            remaining_value = (holding.shares - shares_to_sell) * price
            new_alloc = remaining_value / account.get_total_value()
            
            analysis.ticker_analysis.append(TickerAnalysis(
                ticker=ticker,
                current_shares=holding.shares,
                current_value=holding.market_value or 0,
                current_allocation=current_alloc,
                target_allocation=None,
                action="SELL",
                shares_to_trade=shares_to_sell,
                estimated_value=estimated_value,
                new_allocation=new_alloc,
                reason=f"Selling {rule.quantity_type.value}"
            ))
        
        return orders, cash_generated
    
    def _calculate_sell_shares(
        self, 
        holding: Holding, 
        rule: SellRule,
        account_total: float
    ) -> int:
        """Calculate number of shares to sell based on rule."""
        if rule.quantity_type == QuantityType.ALL:
            shares = int(holding.shares)
        
        elif rule.quantity_type == QuantityType.PERCENT_OF_POSITION:
            pct = rule.quantity or 1.0
            shares = int(holding.shares * pct)
        
        elif rule.quantity_type == QuantityType.SHARES:
            shares = int(min(rule.quantity or 0, holding.shares))
        
        elif rule.quantity_type == QuantityType.DOLLARS:
            price = holding.price or self.stock_prices.get(holding.symbol, 0)
            if price > 0:
                shares = int((rule.quantity or 0) / price)
                shares = min(shares, int(holding.shares))
            else:
                shares = 0
        
        else:
            shares = 0
        
        # Apply constraints
        if rule.min_shares_remaining:
            max_sellable = int(holding.shares) - rule.min_shares_remaining
            shares = min(shares, max(0, max_sellable))
        
        if rule.max_percent_of_position:
            max_from_pct = int(holding.shares * rule.max_percent_of_position)
            shares = min(shares, max_from_pct)
        
        return max(0, shares)
    
    def _process_buy_rule(
        self,
        account: Account,
        rule: BuyRule,
        available_cash: float,
        cash_mgmt,
        analysis: AccountTradeAnalysis
    ) -> tuple[list[Order], float, list[Order]]:
        """
        Process a buy rule for an account.
        
        Returns:
            Tuple of (buy_orders, cash_used, cash_equiv_sell_orders)
        """
        buy_orders = []
        ce_sell_orders = []
        total_cash_used = 0.0
        
        total_value = account.get_total_value()
        min_cash_required = total_value * cash_mgmt.min_cash_percent
        if cash_mgmt.min_cash_dollars:
            min_cash_required = max(min_cash_required, cash_mgmt.min_cash_dollars)
        
        # Calculate what we need to buy for each ticker
        buy_needs = []  # [(ticker, shares_to_buy, cost, reason)]
        
        for ticker in rule.tickers:
            ticker = ticker.upper()
            price = self.stock_prices.get(ticker)
            
            if not price or price <= 0:
                analysis.warnings.append(f"No price found for {ticker}, skipping")
                analysis.ticker_analysis.append(TickerAnalysis(
                    ticker=ticker,
                    current_shares=0,
                    current_value=0,
                    current_allocation=0,
                    target_allocation=rule.quantity,
                    action="SKIP",
                    shares_to_trade=0,
                    estimated_value=0,
                    new_allocation=0,
                    reason="No price available"
                ))
                continue
            
            # Get current holding info
            current_holding = account.get_holding(ticker)
            current_shares = current_holding.shares if current_holding else 0
            current_value = current_holding.market_value if current_holding else 0
            current_alloc = current_value / total_value if total_value > 0 else 0
            
            # Check skip condition
            if rule.skip_if_allocation_above and current_alloc >= rule.skip_if_allocation_above:
                analysis.ticker_analysis.append(TickerAnalysis(
                    ticker=ticker,
                    current_shares=current_shares,
                    current_value=current_value,
                    current_allocation=current_alloc,
                    target_allocation=rule.quantity,
                    action="SKIP",
                    shares_to_trade=0,
                    estimated_value=0,
                    new_allocation=current_alloc,
                    reason=f"Already owns >= {rule.skip_if_allocation_above*100:.1f}%"
                ))
                continue
            
            # Calculate target
            if rule.quantity_type == QuantityType.PERCENT_OF_ACCOUNT:
                target_alloc = rule.quantity or 0
                target_value = total_value * target_alloc
                
                if rule.buy_only_to_target:
                    # Only buy the difference to reach target
                    value_to_buy = max(0, target_value - current_value)
                else:
                    # Buy full allocation amount
                    value_to_buy = target_value
                
                shares_to_buy = math.floor(value_to_buy / price)
                
            elif rule.quantity_type == QuantityType.SHARES:
                shares_to_buy = int(rule.quantity or 0)
                target_alloc = (current_value + shares_to_buy * price) / total_value
                
            elif rule.quantity_type == QuantityType.DOLLARS:
                value_to_buy = rule.quantity or 0
                shares_to_buy = math.floor(value_to_buy / price)
                target_alloc = (current_value + shares_to_buy * price) / total_value
                
            else:
                shares_to_buy = 0
                target_alloc = current_alloc
            
            if shares_to_buy <= 0:
                # Determine the actual reason for no shares to buy
                if rule.quantity_type == QuantityType.PERCENT_OF_ACCOUNT:
                    target_value = total_value * (rule.quantity or 0)
                    if rule.buy_only_to_target:
                        value_to_buy = max(0, target_value - current_value)
                    else:
                        value_to_buy = target_value

                    if price > value_to_buy and current_alloc < target_alloc:
                        # Share price exceeds what we want to buy
                        reason = "Share price exceeds target"
                    else:
                        reason = "Already at target allocation"
                else:
                    reason = "No shares to buy"

                analysis.ticker_analysis.append(TickerAnalysis(
                    ticker=ticker,
                    current_shares=current_shares,
                    current_value=current_value,
                    current_allocation=current_alloc,
                    target_allocation=target_alloc,
                    action="SKIP",
                    shares_to_trade=0,
                    estimated_value=0,
                    new_allocation=current_alloc,
                    reason=reason
                ))
                continue
            
            cost = shares_to_buy * price
            buy_needs.append((ticker, shares_to_buy, cost, current_shares, current_value, current_alloc, target_alloc))
        
        # Calculate total cash needed
        total_cash_needed = sum(need[2] for need in buy_needs)
        
        # Determine usable cash (respecting minimum)
        usable_cash = max(0, available_cash - min_cash_required)
        
        # If we need more cash and rule allows selling cash equivalents
        cash_shortfall = total_cash_needed - usable_cash
        
        if cash_shortfall > 0 and rule.sell_cash_equiv_if_needed:
            # Sell cash equivalents to cover shortfall
            ce_orders, cash_raised = self._sell_cash_equivalents_for_cash(
                account, 
                cash_shortfall,
                cash_mgmt.cash_equiv_sell_order,
                analysis
            )
            ce_sell_orders.extend(ce_orders)
            usable_cash += cash_raised
        
        # Now create buy orders with available cash
        remaining_cash = usable_cash
        
        for ticker, shares, cost, curr_shares, curr_value, curr_alloc, target_alloc in buy_needs:
            price = self.stock_prices[ticker]
            
            # Adjust if we don't have enough cash
            if cost > remaining_cash:
                shares = math.floor(remaining_cash / price)
                cost = shares * price
            
            if shares <= 0:
                analysis.ticker_analysis.append(TickerAnalysis(
                    ticker=ticker,
                    current_shares=curr_shares,
                    current_value=curr_value,
                    current_allocation=curr_alloc,
                    target_allocation=target_alloc,
                    action="SKIP",
                    shares_to_trade=0,
                    estimated_value=0,
                    new_allocation=curr_alloc,
                    reason="Insufficient cash"
                ))
                analysis.warnings.append(f"Insufficient cash to buy {ticker}")
                continue
            
            new_value = curr_value + cost
            new_alloc = new_value / total_value
            
            order = Order(
                account_num=account.account_num,
                client_name=account.client_name,
                security=ticker,
                action="Buy",
                shares=shares,
                estimated_value=cost,
                reason=f"Buy to {target_alloc*100:.1f}% target"
            )
            buy_orders.append(order)
            total_cash_used += cost
            remaining_cash -= cost
            
            analysis.ticker_analysis.append(TickerAnalysis(
                ticker=ticker,
                current_shares=curr_shares,
                current_value=curr_value,
                current_allocation=curr_alloc,
                target_allocation=target_alloc,
                action="BUY",
                shares_to_trade=shares,
                estimated_value=cost,
                new_allocation=new_alloc,
                reason=f"Buying to target allocation"
            ))
        
        return buy_orders, total_cash_used, ce_sell_orders
    
    def _sell_cash_equivalents_for_cash(
        self,
        account: Account,
        amount_needed: float,
        sell_order: str,
        analysis: AccountTradeAnalysis
    ) -> tuple[list[Order], float]:
        """Sell cash equivalents to raise needed cash."""
        orders = []
        cash_raised = 0.0
        
        # Sort cash equivalents
        cash_equivs = list(account.cash_equivalents)
        if sell_order == "largest_first":
            cash_equivs.sort(key=lambda x: x.market_value or 0, reverse=True)
        else:
            cash_equivs.sort(key=lambda x: x.market_value or 0)
        
        remaining_needed = amount_needed
        
        for ce in cash_equivs:
            if remaining_needed <= 0:
                break
            
            if not ce.market_value or ce.market_value <= 0:
                continue
            
            price = ce.price or self.stock_prices.get(ce.symbol, 0)
            if price <= 0:
                continue
            
            # Calculate shares to sell
            if ce.market_value <= remaining_needed:
                # Sell entire position
                shares_to_sell = int(ce.shares)
            else:
                # Sell just enough
                shares_to_sell = math.ceil(remaining_needed / price)
                shares_to_sell = min(shares_to_sell, int(ce.shares))
            
            if shares_to_sell <= 0:
                continue
            
            value = shares_to_sell * price
            
            order = Order(
                account_num=account.account_num,
                client_name=account.client_name,
                security=ce.symbol,
                action="Sell",
                shares=shares_to_sell,
                estimated_value=value,
                reason="Liquidating to fund buys"
            )
            orders.append(order)
            cash_raised += value
            remaining_needed -= value
            
            # Add to analysis
            curr_alloc = (ce.market_value or 0) / account.get_total_value()
            remaining_value = (ce.shares - shares_to_sell) * price
            new_alloc = remaining_value / account.get_total_value()
            
            analysis.ticker_analysis.append(TickerAnalysis(
                ticker=ce.symbol,
                current_shares=ce.shares,
                current_value=ce.market_value or 0,
                current_allocation=curr_alloc,
                target_allocation=None,
                action="SELL",
                shares_to_trade=shares_to_sell,
                estimated_value=value,
                new_allocation=new_alloc,
                reason="Selling cash equivalent to fund purchases"
            ))
        
        return orders, cash_raised
    
    def get_analyses(self) -> list[AccountTradeAnalysis]:
        """Get the detailed analyses for all processed accounts."""
        return self.analyses
