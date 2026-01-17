"""
Summary Report Generator

Produces detailed, human-readable reports of trade execution for advisor review.
"""

from typing import Optional
from order_generator import AccountTradeAnalysis, Order


def format_currency(value: float) -> str:
    """Format a number as currency."""
    if value < 0:
        return f"-${abs(value):,.2f}"
    return f"${value:,.2f}"


def format_percent(value: float) -> str:
    """Format a decimal as percentage."""
    return f"{value * 100:.2f}%"


def generate_summary_report(
    analyses: list[AccountTradeAnalysis],
    sell_orders: list[Order],
    buy_orders: list[Order],
    plan_description: str,
    sell_filename: str,
    buy_filename: str
) -> str:
    """
    Generate a comprehensive summary report.
    
    Args:
        analyses: List of AccountTradeAnalysis objects
        sell_orders: All sell orders generated
        buy_orders: All buy orders generated
        plan_description: Description of the execution plan
        sell_filename: Name of the sell orders file
        buy_filename: Name of the buy orders file
        
    Returns:
        Formatted string report
    """
    lines = []
    
    # Header
    lines.append("═" * 80)
    lines.append("                         TRADE EXECUTION SUMMARY")
    lines.append("═" * 80)
    lines.append("")
    lines.append(f"SPECIFICATION: \"{plan_description}\"")
    lines.append("")
    
    # Process each account
    for analysis in analyses:
        lines.append("─" * 80)
        
        # Account header with client name
        name_display = f" - {analysis.client_name}" if analysis.client_name else ""
        lines.append(f"ACCOUNT: {analysis.account_num}{name_display}")
        lines.append(f"Total Value: {format_currency(analysis.total_value)}")
        lines.append("─" * 80)
        lines.append("")
        
        # Current state
        lines.append("  CURRENT STATE:")
        cash_pct = analysis.cash_before / analysis.total_value if analysis.total_value > 0 else 0
        ce_pct = analysis.cash_equivalents_before / analysis.total_value if analysis.total_value > 0 else 0
        holdings_value = analysis.total_value - analysis.cash_before - analysis.cash_equivalents_before
        holdings_pct = holdings_value / analysis.total_value if analysis.total_value > 0 else 0
        
        lines.append(f"  ├── Cash:              {format_currency(analysis.cash_before):>15}  ({format_percent(cash_pct)})")
        lines.append(f"  ├── Cash Equivalents:  {format_currency(analysis.cash_equivalents_before):>15}  ({format_percent(ce_pct)})")
        lines.append(f"  └── Holdings:          {format_currency(holdings_value):>15}  ({format_percent(holdings_pct)})")
        lines.append("")
        
        # Ticker analysis table
        if analysis.ticker_analysis:
            lines.append("  ANALYSIS:")
            lines.append("  ┌" + "─" * 10 + "┬" + "─" * 12 + "┬" + "─" * 12 + "┬" + "─" * 10 + "┬" + "─" * 32 + "┐")
            lines.append(f"  │ {'Ticker':<8} │ {'Current %':>10} │ {'Target %':>10} │ {'Action':<8} │ {'Reasoning':<30} │")
            lines.append("  ├" + "─" * 10 + "┼" + "─" * 12 + "┼" + "─" * 12 + "┼" + "─" * 10 + "┼" + "─" * 32 + "┤")
            
            for ta in analysis.ticker_analysis:
                current_pct = f"{ta.current_allocation * 100:.2f}%"
                # Hide target % if it doesn't make sense (None, >= 100%, or negative)
                if ta.target_allocation and 0 < ta.target_allocation < 1.0:
                    target_pct = f"{ta.target_allocation * 100:.2f}%"
                else:
                    target_pct = "--"
                reason = ta.reason[:30] if len(ta.reason) <= 30 else ta.reason[:27] + "..."
                lines.append(f"  │ {ta.ticker:<8} │ {current_pct:>10} │ {target_pct:>10} │ {ta.action:<8} │ {reason:<30} │")
            
            lines.append("  └" + "─" * 10 + "┴" + "─" * 12 + "┴" + "─" * 12 + "┴" + "─" * 10 + "┴" + "─" * 32 + "┘")
            lines.append("")
        
        # Cash flow calculation
        lines.append("  CASH FLOW:")
        lines.append(f"  ├── Starting cash:         {format_currency(analysis.cash_before):>15}")
        if analysis.cash_from_sells > 0:
            lines.append(f"  ├── + Cash from sells:     {format_currency(analysis.cash_from_sells):>15}")
        if analysis.cash_used_for_buys > 0:
            lines.append(f"  ├── - Cash used for buys:  {format_currency(analysis.cash_used_for_buys):>15}")
        lines.append(f"  └── = Ending cash:         {format_currency(analysis.cash_after):>15}")
        
        # Check cash floor
        min_cash_required = analysis.total_value * 0.02
        if analysis.cash_after >= min_cash_required:
            lines.append(f"       ✓ Above 2% cash floor ({format_currency(min_cash_required)})")
        else:
            lines.append(f"       ⚠ WARNING: Below 2% cash floor ({format_currency(min_cash_required)})")
        lines.append("")
        
        # Orders table
        account_sells = [o for o in analysis.sell_orders]
        account_buys = [o for o in analysis.buy_orders]
        
        if account_sells or account_buys:
            lines.append("  ORDERS GENERATED:")
            lines.append("  ┌" + "─" * 8 + "┬" + "─" * 10 + "┬" + "─" * 12 + "┬" + "─" * 15 + "┬" + "─" * 18 + "┐")
            lines.append(f"  │ {'Action':<6} │ {'Ticker':<8} │ {'Shares':>10} │ {'Est. Value':>13} │ {'New Allocation':>16} │")
            lines.append("  ├" + "─" * 8 + "┼" + "─" * 10 + "┼" + "─" * 12 + "┼" + "─" * 15 + "┼" + "─" * 18 + "┤")
            
            for order in account_sells:
                # Find the matching ticker analysis
                ta = next((t for t in analysis.ticker_analysis if t.ticker == order.security), None)
                new_alloc = format_percent(ta.new_allocation) if ta else "--"
                lines.append(f"  │ {'SELL':<6} │ {order.security:<8} │ {order.shares:>10,} │ {format_currency(order.estimated_value):>13} │ {new_alloc:>16} │")
            
            for order in account_buys:
                ta = next((t for t in analysis.ticker_analysis if t.ticker == order.security), None)
                new_alloc = format_percent(ta.new_allocation) if ta else "--"
                lines.append(f"  │ {'BUY':<6} │ {order.security:<8} │ {order.shares:>10,} │ {format_currency(order.estimated_value):>13} │ {new_alloc:>16} │")
            
            lines.append("  └" + "─" * 8 + "┴" + "─" * 10 + "┴" + "─" * 12 + "┴" + "─" * 15 + "┴" + "─" * 18 + "┘")
        else:
            lines.append("  NO ORDERS GENERATED FOR THIS ACCOUNT")
        
        # Warnings
        if analysis.warnings:
            lines.append("")
            lines.append("  ⚠ WARNINGS:")
            for warning in analysis.warnings:
                lines.append(f"     - {warning}")
        
        lines.append("")
    
    # Aggregate summary
    lines.append("═" * 80)
    lines.append("                              AGGREGATE SUMMARY")
    lines.append("═" * 80)
    lines.append("")
    
    total_sell_value = sum(o.estimated_value for o in sell_orders)
    total_buy_value = sum(o.estimated_value for o in buy_orders)
    
    lines.append(f"  Total Accounts Processed: {len(analyses)}")
    lines.append(f"  Total Sell Orders: {len(sell_orders)} ({format_currency(total_sell_value)})")
    lines.append(f"  Total Buy Orders: {len(buy_orders)} ({format_currency(total_buy_value)})")
    lines.append("")
    
    lines.append("═" * 80)
    lines.append("  ⚠ REVIEW REMINDER: Please verify all orders before uploading to platform.")
    lines.append("  ⚠ EXECUTION ORDER: Execute SELL orders first, wait for settlement,")
    lines.append("                     then execute BUY orders.")
    lines.append("═" * 80)
    
    return "\n".join(lines)


def print_confirmation_prompt(
    plan_description: str,
    analyses: list[AccountTradeAnalysis],
    sell_orders: list[Order],
    buy_orders: list[Order]
) -> str:
    """
    Generate a concise confirmation prompt before execution.
    
    Args:
        plan_description: What the plan does
        analyses: Account analyses
        sell_orders: Proposed sell orders
        buy_orders: Proposed buy orders
        
    Returns:
        Confirmation prompt string
    """
    lines = []
    lines.append("")
    lines.append("═" * 60)
    lines.append("              EXECUTION PLAN CONFIRMATION")
    lines.append("═" * 60)
    lines.append("")
    lines.append(f"Plan: {plan_description}")
    lines.append("")
    lines.append(f"Accounts to process: {len(analyses)}")
    lines.append(f"Sell orders: {len(sell_orders)}")
    lines.append(f"Buy orders: {len(buy_orders)}")
    lines.append("")
    
    # Quick summary by ticker
    if sell_orders:
        sell_tickers = set(o.security for o in sell_orders)
        lines.append(f"Selling: {', '.join(sorted(sell_tickers))}")
    
    if buy_orders:
        buy_tickers = set(o.security for o in buy_orders)
        lines.append(f"Buying: {', '.join(sorted(buy_tickers))}")
    
    lines.append("")
    lines.append("═" * 60)
    
    return "\n".join(lines)
