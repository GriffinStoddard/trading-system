"""
LLM Interpreter - Converts natural language specifications to ExecutionPlans

Uses the Anthropic API to interpret advisor specifications and produce
structured execution plans that the OrderGenerator can execute.
"""

import json
import os
from typing import Optional
from execution_plan import (
    ExecutionPlan, BuyRule, SellRule, AccountFilter, CashManagement,
    QuantityType, AllocationMethod, CashSource
)


# System prompt that teaches the LLM about our schema
SYSTEM_PROMPT = """You are a financial trading assistant that converts natural language trading specifications into structured execution plans.

Your job is to interpret an advisor's instructions and output a JSON execution plan that a computer program will execute to generate buy/sell orders.

## OUTPUT FORMAT

You must output valid JSON matching this schema:

```json
{
  "description": "Human-readable summary of what was requested",
  "sell_rules": [
    {
      "tickers": ["TICKER1", "TICKER2"],
      "quantity_type": "all|percent_of_position|shares|dollars|to_target",
      "quantity": null or number,
      "priority": "largest_first",
      "min_shares_remaining": null or integer,
      "max_percent_of_position": null or decimal
    }
  ],
  "buy_rules": [
    {
      "tickers": ["TICKER1", "TICKER2"],
      "quantity_type": "percent_of_account|shares|dollars|to_target",
      "quantity": decimal or number,
      "allocation_method": "equal_weight|proportional|specified",
      "skip_if_allocation_above": null or decimal,
      "buy_only_to_target": true|false,
      "cash_source": "available_cash|cash_equivalents",
      "sell_cash_equiv_if_needed": true|false
    }
  ],
  "account_filter": null or {
    "min_value": null or number,
    "max_value": null or number,
    "account_numbers": null or ["acc1", "acc2"],
    "must_hold_tickers": null or ["TICK1"]
  },
  "cash_management": {
    "min_cash_percent": decimal (default 0.02 for 2%),
    "min_cash_dollars": null or number,
    "cash_equiv_sell_order": "largest_first"
  },
  "sells_before_buys": true
}
```

## QUANTITY TYPES EXPLAINED

- `percent_of_account`: quantity is a decimal (0.025 = 2.5% of total account value)
- `percent_of_position`: quantity is a decimal (0.5 = 50% of that holding)
- `shares`: quantity is number of shares
- `dollars`: quantity is dollar amount
- `all`: sell entire position (quantity ignored)
- `to_target`: buy/sell to reach target allocation

## KEY RULES

1. All percentages are expressed as decimals (2.5% = 0.025, 2% = 0.02)
2. "Cash equivalents" are: BIL, USFR, PJLXX
3. When buying to a target allocation and position exists, set `buy_only_to_target: true`
4. When told to maintain X% cash, set `min_cash_percent` to that value
5. When told to sell cash equivalents if needed, set `sell_cash_equiv_if_needed: true`
6. Always set `sells_before_buys: true` unless explicitly told otherwise

## EXAMPLES

### Example 1: "Buy 2.5% of each ticker, skip if already own 2% or more, sell cash equivalents if needed, keep 2% cash"

```json
{
  "description": "Buy to 2.5% allocation per ticker, skip existing positions >= 2%, liquidate cash equivalents if needed, maintain 2% cash floor",
  "sell_rules": [],
  "buy_rules": [
    {
      "tickers": ["PYPL", "MU", "GOOGL"],
      "quantity_type": "percent_of_account",
      "quantity": 0.025,
      "allocation_method": "equal_weight",
      "skip_if_allocation_above": 0.02,
      "buy_only_to_target": true,
      "cash_source": "cash_equivalents",
      "sell_cash_equiv_if_needed": true
    }
  ],
  "account_filter": null,
  "cash_management": {
    "min_cash_percent": 0.02,
    "min_cash_dollars": null,
    "cash_equiv_sell_order": "largest_first"
  },
  "sells_before_buys": true
}
```

### Example 2: "Sell all LUMN and COMM, buy equal amounts of GOOGL and CSCO with proceeds"

```json
{
  "description": "Liquidate LUMN and COMM positions, reinvest proceeds equally into GOOGL and CSCO",
  "sell_rules": [
    {
      "tickers": ["LUMN", "COMM"],
      "quantity_type": "all",
      "quantity": null,
      "priority": "largest_first",
      "min_shares_remaining": null,
      "max_percent_of_position": null
    }
  ],
  "buy_rules": [
    {
      "tickers": ["GOOGL", "CSCO"],
      "quantity_type": "percent_of_account",
      "quantity": 0.025,
      "allocation_method": "equal_weight",
      "skip_if_allocation_above": null,
      "buy_only_to_target": false,
      "cash_source": "available_cash",
      "sell_cash_equiv_if_needed": false
    }
  ],
  "account_filter": null,
  "cash_management": {
    "min_cash_percent": 0.02,
    "min_cash_dollars": null,
    "cash_equiv_sell_order": "largest_first"
  },
  "sells_before_buys": true
}
```

### Example 3: "Raise $150k proportionally, don't sell below 50 shares, max 25% of any position, skip accounts under $25k"

```json
{
  "description": "Raise $150,000 cash by selling proportionally from largest positions, minimum 50 shares remaining, max 25% per position, skip small accounts",
  "sell_rules": [
    {
      "tickers": ["*"],
      "quantity_type": "dollars",
      "quantity": 150000,
      "priority": "largest_first",
      "min_shares_remaining": 50,
      "max_percent_of_position": 0.25
    }
  ],
  "buy_rules": [],
  "account_filter": {
    "min_value": 25000,
    "max_value": null,
    "account_numbers": null,
    "must_hold_tickers": null
  },
  "cash_management": {
    "min_cash_percent": 0.02,
    "min_cash_dollars": null,
    "cash_equiv_sell_order": "largest_first"
  },
  "sells_before_buys": true
}
```

Output ONLY the JSON, no explanation or markdown formatting.
"""


def create_context_prompt(
    accounts_summary: str,
    available_tickers: list[str],
    cash_equivalents: list[str],
    buy_list: list[str]
) -> str:
    """Create the context portion of the prompt with current account data."""
    return f"""
## CURRENT PORTFOLIO STATE

{accounts_summary}

## AVAILABLE INFORMATION

Tickers currently held across accounts: {', '.join(available_tickers) if available_tickers else 'None'}

Cash equivalents (can be liquidated for cash): {', '.join(cash_equivalents)}

Stocks in buy list (with prices available): {', '.join(buy_list) if buy_list else 'None specified'}

## ADVISOR'S SPECIFICATION

"""


class LLMInterpreter:
    """
    Interprets natural language trading specifications using Claude API.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the interpreter.
        
        Args:
            api_key: Anthropic API key. If not provided, looks for config file then env var.
        """
        if api_key:
            self.api_key = api_key
        else:
            # Try config file first, then environment variable
            try:
                from config import get_api_key
                self.api_key = get_api_key()
            except ImportError:
                self.api_key = ""
            
            if not self.api_key:
                self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        
        if not self.api_key:
            print("Warning: No API key found. Check config.json or set ANTHROPIC_API_KEY.")
        
        self.cash_equivalents = ["BIL", "USFR", "PJLXX"]
    
    def interpret(
        self,
        specification: str,
        accounts: dict,
        buy_list: list[str],
        stock_prices: dict[str, float]
    ) -> ExecutionPlan:
        """
        Interpret a natural language specification into an ExecutionPlan.
        
        Args:
            specification: The advisor's natural language request
            accounts: Dictionary of Account objects
            buy_list: List of tickers available to buy
            stock_prices: Dictionary of ticker -> price
            
        Returns:
            ExecutionPlan object ready for execution
        """
        # Build account summary for context
        accounts_summary = self._build_accounts_summary(accounts)
        
        # Get all tickers held
        all_tickers = set()
        for account in accounts.values():
            for h in account.holdings:
                all_tickers.add(h.symbol)
            for ce in account.cash_equivalents:
                all_tickers.add(ce.symbol)
        
        # Build the full prompt
        context = create_context_prompt(
            accounts_summary=accounts_summary,
            available_tickers=sorted(all_tickers),
            cash_equivalents=self.cash_equivalents,
            buy_list=buy_list
        )
        
        user_message = context + specification
        
        # Call the API
        if not self.api_key:
            raise ValueError("No API key available. Cannot interpret specification.")
        
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": user_message}
                ]
            )
            
            # Extract JSON from response
            response_text = response.content[0].text.strip()
            
            # Strip markdown code blocks if present
            if response_text.startswith("```json"):
                response_text = response_text[7:]  # Remove ```json
            elif response_text.startswith("```"):
                response_text = response_text[3:]  # Remove ```
            
            if response_text.endswith("```"):
                response_text = response_text[:-3]  # Remove trailing ```
            
            response_text = response_text.strip()
            
            # Parse JSON
            plan_dict = json.loads(response_text)
            
            # Convert to ExecutionPlan
            return ExecutionPlan.from_dict(plan_dict)
            
        except ImportError:
            print("anthropic package not installed. Using fallback interpreter.")
            return self._fallback_interpret(specification, buy_list)
        except json.JSONDecodeError as e:
            print(f"Failed to parse LLM response as JSON: {e}")
            print(f"Response was: {response_text[:500]}...")
            raise
        except Exception as e:
            print(f"API call failed: {e}")
            raise
    
    def _build_accounts_summary(self, accounts: dict) -> str:
        """Build a text summary of all accounts for the LLM."""
        lines = []
        
        for acc_num, account in accounts.items():
            total = account.get_total_value()
            cash = account.cash
            ce_value = account.get_cash_equivalents_value()
            
            name_str = f" ({account.client_name})" if account.client_name else ""
            lines.append(f"Account {acc_num}{name_str}:")
            lines.append(f"  Total Value: ${total:,.2f}")
            lines.append(f"  Cash: ${cash:,.2f} ({cash/total*100:.1f}%)")
            lines.append(f"  Cash Equivalents: ${ce_value:,.2f} ({ce_value/total*100:.1f}%)")
            
            if account.holdings:
                lines.append("  Holdings:")
                for h in account.holdings:
                    alloc = (h.market_value or 0) / total * 100
                    lines.append(f"    {h.symbol}: {h.shares:.0f} shares, ${h.market_value:,.2f} ({alloc:.1f}%)")
            
            if account.cash_equivalents:
                lines.append("  Cash Equivalents Detail:")
                for ce in account.cash_equivalents:
                    alloc = (ce.market_value or 0) / total * 100
                    lines.append(f"    {ce.symbol}: {ce.shares:.0f} shares, ${ce.market_value:,.2f} ({alloc:.1f}%)")
            
            lines.append("")
        
        return "\n".join(lines)
    
    def _fallback_interpret(self, specification: str, buy_list: list[str]) -> ExecutionPlan:
        """
        Fallback interpreter for when API is not available.
        Handles the most common case: buy to target with cash equivalent liquidation.
        """
        # Default plan matching the user's Specification 1
        return ExecutionPlan(
            description="Buy to 2.5% target allocation, skip if >= 2%, sell cash equivalents if needed, maintain 2% cash",
            buy_rules=[
                BuyRule(
                    tickers=buy_list,
                    quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                    quantity=0.025,
                    allocation_method=AllocationMethod.EQUAL_WEIGHT,
                    skip_if_allocation_above=0.02,
                    buy_only_to_target=True,
                    cash_source=CashSource.CASH_EQUIVALENTS,
                    sell_cash_equiv_if_needed=True
                )
            ],
            cash_management=CashManagement(
                min_cash_percent=0.02,
                cash_equiv_sell_order="largest_first"
            )
        )


def interpret_specification(
    specification: str,
    accounts: dict,
    buy_list: list[str],
    stock_prices: dict[str, float],
    api_key: Optional[str] = None
) -> ExecutionPlan:
    """
    Convenience function to interpret a specification.
    
    Args:
        specification: Natural language trading specification
        accounts: Dictionary of Account objects
        buy_list: List of tickers to buy
        stock_prices: Dictionary of ticker prices
        api_key: Optional API key (uses env var if not provided)
        
    Returns:
        ExecutionPlan ready for execution
    """
    interpreter = LLMInterpreter(api_key)
    return interpreter.interpret(specification, accounts, buy_list, stock_prices)
