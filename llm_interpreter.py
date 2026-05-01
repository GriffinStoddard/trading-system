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


def get_system_prompt(cash_equivalents: list[str]) -> str:
    """Build the system prompt with the current cash equivalents list."""
    cash_equiv_str = ", ".join(cash_equivalents)
    return f"""You are a financial trading assistant that converts natural language trading specifications into structured execution plans.

Your job is to interpret an advisor's instructions and output a JSON execution plan that a computer program will execute to generate buy/sell orders.

## OUTPUT FORMAT

You must output valid JSON matching this schema:

```json
{{
  "description": "Human-readable summary of what was requested",
  "sell_rules": [
    {{
      "tickers": ["TICKER1", "TICKER2"],
      "quantity_type": "all|percent_of_position|shares|dollars|to_target",
      "quantity": null or number,
      "priority": "largest_first",
      "min_shares_remaining": null or integer,
      "max_percent_of_position": null or decimal,
      "account_filter": null or {{ per-rule filter, same structure as plan-level account_filter }}
    }}
  ],
  "buy_rules": [
    {{
      "tickers": ["TICKER1", "TICKER2"],
      "quantity_type": "percent_of_account|shares|dollars|to_target",
      "quantity": decimal or number,
      "allocation_method": "equal_weight|proportional|specified",
      "skip_if_allocation_above": null or decimal,
      "buy_only_to_target": true|false,
      "buy_only_if_sold": null or ["TICKER1"],
      "use_proceeds_from_sale": true|false,
      "cash_source": "available_cash|cash_equivalents",
      "sell_cash_equiv_if_needed": true|false,
      "min_buy_allocation": null or decimal
    }}
  ],
  "account_filter": null or {{
    "min_value": null or number,
    "max_value": null or number,
    "account_numbers": null or ["acc1", "acc2"],
    "must_hold_tickers": null or ["TICK1"],
    "client_name_contains": null or ["name1", "name2"],
    "exclude_client_names": null or ["name1", "name2"]
  }},
  "cash_management": {{
    "min_cash_percent": decimal (default 0.02 for 2%),
    "min_cash_dollars": null or number,
    "cash_equiv_sell_order": "largest_first"
  }},
  "sells_before_buys": true
}}
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
2. "Cash equivalents" are: {cash_equiv_str}
3. When buying to a target allocation and position exists, set `buy_only_to_target: true`
4. When told to maintain X% cash, set `min_cash_percent` to that value
5. When told to sell cash equivalents if needed, set `sell_cash_equiv_if_needed: true`
6. Always set `sells_before_buys: true` unless explicitly told otherwise

## CONDITIONAL SELL-THEN-BUY

When the user wants to sell a stock and then buy another stock ONLY for accounts that sold:
- Set `buy_only_if_sold: ["TICKER"]` on the buy rule - this ensures the buy only executes for accounts that actually sold that ticker
- Set `use_proceeds_from_sale: true` if the user wants to use the proceeds from the sale (not a target allocation)
- The tickers in `buy_only_if_sold` must match tickers in a sell rule

Example: "Sell GOOGL, then buy AAPL with the proceeds for accounts that sold GOOGL"
- Create a sell rule for GOOGL with quantity_type "all"
- Create a buy rule for AAPL with `buy_only_if_sold: ["GOOGL"]` and `use_proceeds_from_sale: true`

## PER-RULE ACCOUNT FILTERS

Each sell_rule can have its own `account_filter` that applies only to that specific rule. This allows different rules to target different subsets of accounts.

Use cases:
- Sell ticker X from ALL accounts, but sell ticker Y only from specific accounts
- Filter by client name using `client_name_contains` (case-insensitive partial match)

Example: "Sell all AAPL in all accounts. For accounts with 'Smith' in the name, also sell GOOGL"
- First sell rule: tickers ["AAPL"], no account_filter (applies to all)
- Second sell rule: tickers ["GOOGL"], account_filter with client_name_contains ["Smith"]

## CLIENT NAME FILTERING

Use `client_name_contains` in account_filter to filter accounts by client/account name:
- It's an array of strings - account matches if name contains ANY of the strings
- Matching is case-insensitive
- Useful when user says "for accounts named X" or "for client Y"

Use `exclude_client_names` to EXCLUDE accounts by client name:
- It's an array of strings - account is EXCLUDED if name contains ANY of the strings
- Matching is case-insensitive
- Useful when user says "except for client X" or "not for accounts named Y"

## MINIMUM BUY SIZE

Use `min_buy_allocation` in buy_rules to skip small buys:
- Decimal value (0.01 = 1% of account)
- If the calculated buy amount is less than this percentage of the account, the buy is skipped
- Useful when user says "skip buys under X% of account value"

## EXAMPLES

### Example 1: "Buy 2.5% of each ticker, skip if already own 2% or more, sell cash equivalents if needed, keep 2% cash"

```json
{{
  "description": "Buy to 2.5% allocation per ticker, skip existing positions >= 2%, liquidate cash equivalents if needed, maintain 2% cash floor",
  "sell_rules": [],
  "buy_rules": [
    {{
      "tickers": ["PYPL", "MU", "GOOGL"],
      "quantity_type": "percent_of_account",
      "quantity": 0.025,
      "allocation_method": "equal_weight",
      "skip_if_allocation_above": 0.02,
      "buy_only_to_target": true,
      "cash_source": "cash_equivalents",
      "sell_cash_equiv_if_needed": true
    }}
  ],
  "account_filter": null,
  "cash_management": {{
    "min_cash_percent": 0.02,
    "min_cash_dollars": null,
    "cash_equiv_sell_order": "largest_first"
  }},
  "sells_before_buys": true
}}
```

### Example 2: "Sell all LUMN and COMM, buy equal amounts of GOOGL and CSCO with proceeds"

```json
{{
  "description": "Liquidate LUMN and COMM positions, reinvest proceeds equally into GOOGL and CSCO",
  "sell_rules": [
    {{
      "tickers": ["LUMN", "COMM"],
      "quantity_type": "all",
      "quantity": null,
      "priority": "largest_first",
      "min_shares_remaining": null,
      "max_percent_of_position": null
    }}
  ],
  "buy_rules": [
    {{
      "tickers": ["GOOGL", "CSCO"],
      "quantity_type": "percent_of_account",
      "quantity": 0.025,
      "allocation_method": "equal_weight",
      "skip_if_allocation_above": null,
      "buy_only_to_target": false,
      "cash_source": "available_cash",
      "sell_cash_equiv_if_needed": false
    }}
  ],
  "account_filter": null,
  "cash_management": {{
    "min_cash_percent": 0.02,
    "min_cash_dollars": null,
    "cash_equiv_sell_order": "largest_first"
  }},
  "sells_before_buys": true
}}
```

### Example 3: "Raise $150k proportionally, don't sell below 50 shares, max 25% of any position, skip accounts under $25k"

```json
{{
  "description": "Raise $150,000 cash by selling proportionally from largest positions, minimum 50 shares remaining, max 25% per position, skip small accounts",
  "sell_rules": [
    {{
      "tickers": ["*"],
      "quantity_type": "dollars",
      "quantity": 150000,
      "priority": "largest_first",
      "min_shares_remaining": 50,
      "max_percent_of_position": 0.25
    }}
  ],
  "buy_rules": [],
  "account_filter": {{
    "min_value": 25000,
    "max_value": null,
    "account_numbers": null,
    "must_hold_tickers": null
  }},
  "cash_management": {{
    "min_cash_percent": 0.02,
    "min_cash_dollars": null,
    "cash_equiv_sell_order": "largest_first"
  }},
  "sells_before_buys": true
}}
```

### Example 4: "Sell all GOOGL for accounts that own it, buy AAPL with the proceeds for those accounts only"

```json
{{
  "description": "Sell all GOOGL positions, reinvest proceeds into AAPL only for accounts that sold GOOGL",
  "sell_rules": [
    {{
      "tickers": ["GOOGL"],
      "quantity_type": "all",
      "quantity": null,
      "priority": "largest_first",
      "min_shares_remaining": null,
      "max_percent_of_position": null
    }}
  ],
  "buy_rules": [
    {{
      "tickers": ["AAPL"],
      "quantity_type": "dollars",
      "quantity": null,
      "allocation_method": "equal_weight",
      "skip_if_allocation_above": null,
      "buy_only_to_target": false,
      "buy_only_if_sold": ["GOOGL"],
      "use_proceeds_from_sale": true,
      "cash_source": "available_cash",
      "sell_cash_equiv_if_needed": false
    }}
  ],
  "account_filter": null,
  "cash_management": {{
    "min_cash_percent": 0.02,
    "min_cash_dollars": null,
    "cash_equiv_sell_order": "largest_first"
  }},
  "sells_before_buys": true
}}
```

### Example 5: "In all accounts sell DHR, PEP, AAPL. For accounts named 'Smith', also sell VSMIX. For accounts named 'Johnson', also sell MTCIX and PRBLX"

This example shows MULTIPLE sell rules with different account filters - a global rule plus account-specific rules.

```json
{{
  "description": "Sell DHR, PEP, AAPL from all accounts. Additionally sell VSMIX from Smith accounts and MTCIX, PRBLX from Johnson accounts",
  "sell_rules": [
    {{
      "tickers": ["DHR", "PEP", "AAPL"],
      "quantity_type": "all",
      "quantity": null,
      "priority": "largest_first",
      "min_shares_remaining": null,
      "max_percent_of_position": null,
      "account_filter": null
    }},
    {{
      "tickers": ["VSMIX"],
      "quantity_type": "all",
      "quantity": null,
      "priority": "largest_first",
      "min_shares_remaining": null,
      "max_percent_of_position": null,
      "account_filter": {{
        "client_name_contains": ["Smith"]
      }}
    }},
    {{
      "tickers": ["MTCIX", "PRBLX"],
      "quantity_type": "all",
      "quantity": null,
      "priority": "largest_first",
      "min_shares_remaining": null,
      "max_percent_of_position": null,
      "account_filter": {{
        "client_name_contains": ["Johnson"]
      }}
    }}
  ],
  "buy_rules": [],
  "account_filter": null,
  "cash_management": {{
    "min_cash_percent": 0.02,
    "min_cash_dollars": null,
    "cash_equiv_sell_order": "largest_first"
  }},
  "sells_before_buys": true
}}
```

### Example 6: "Sell PRWCX and B from all accounts, except don't sell PRWCX for Virginia Killeen. Buy from buy list to 2.5% targets, skip buys under 1%"

This example shows using `exclude_client_names` to exclude a specific client from a sell rule, and `min_buy_allocation` to skip small buys.

```json
{{
  "description": "Sell PRWCX (except Virginia Killeen) and B from all accounts, buy to 2.5% targets, skip buys under 1%",
  "sell_rules": [
    {{
      "tickers": ["PRWCX"],
      "quantity_type": "all",
      "quantity": null,
      "priority": "largest_first",
      "min_shares_remaining": null,
      "max_percent_of_position": null,
      "account_filter": {{
        "exclude_client_names": ["Killeen"]
      }}
    }},
    {{
      "tickers": ["B"],
      "quantity_type": "all",
      "quantity": null,
      "priority": "largest_first",
      "min_shares_remaining": null,
      "max_percent_of_position": null,
      "account_filter": null
    }}
  ],
  "buy_rules": [
    {{
      "tickers": ["CRDO", "GOOG", "NVDA"],
      "quantity_type": "percent_of_account",
      "quantity": 0.025,
      "allocation_method": "equal_weight",
      "skip_if_allocation_above": null,
      "buy_only_to_target": true,
      "cash_source": "cash_equivalents",
      "sell_cash_equiv_if_needed": true,
      "min_buy_allocation": 0.01
    }}
  ],
  "account_filter": null,
  "cash_management": {{
    "min_cash_percent": 0.02,
    "min_cash_dollars": null,
    "cash_equiv_sell_order": "largest_first"
  }},
  "sells_before_buys": true
}}
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

        # Load cash equivalents from config
        from config import get_cash_equivalents
        self.cash_equivalents = get_cash_equivalents()
    
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
                system=get_system_prompt(self.cash_equivalents),
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


# Conversation-aware prompts for v2.0

INTENT_DETECTION_PROMPT = """Classify this user message into one of these categories:
- QUESTION: Asking about how the program works, what it can do, explaining concepts
- TRADE_REQUEST: Requesting to generate trades, buy/sell orders, rebalancing
- CLARIFICATION_RESPONSE: Answering a question you previously asked them
- COMMAND: System commands like help, exit, settings, view holdings
- CONFIRMATION: Yes/no response to a confirmation prompt
- UNCLEAR: Ambiguous, needs clarification

Message: {message}
Recent context: {context}

Respond with just the category name."""


TRADE_CLARIFICATION_PROMPT = """You are a trading assistant helping to clarify a trade request.

The user wants to generate trades. Based on their message, identify what information is missing
to create a complete trade specification.

Possible missing information:
- Target allocation percentage (e.g., 2.5% per stock)
- Skip threshold (skip if already own X% or more)
- Whether to sell cash equivalents to fund buys
- Specific tickers to buy or sell
- Dollar amounts or share counts

User's message: {message}

Current portfolio context:
{portfolio_summary}

Buy list: {buy_list}

Respond in JSON format:
{{
    "understood": {{
        "action": "buy" or "sell" or "both",
        "target_allocation": null or decimal,
        "skip_threshold": null or decimal,
        "sell_cash_equiv": null or boolean,
        "tickers": null or list,
        "dollar_amount": null or number
    }},
    "missing": ["list of missing required fields"],
    "clarification_questions": ["natural language questions to ask"]
}}"""


class ConversationalInterpreter(LLMInterpreter):
    """
    Extended interpreter with conversation support for v2.0.

    Handles multi-turn dialogue and clarification flows.
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.conversation_history: list[dict] = []

    def detect_intent(self, message: str, context: str = "") -> str:
        """
        Detect the intent of a user message.

        Args:
            message: User's message
            context: Recent conversation context

        Returns:
            Intent category string
        """
        if not self.api_key:
            return self._detect_intent_simple(message)

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)

            prompt = INTENT_DETECTION_PROMPT.format(
                message=message,
                context=context or "No prior context"
            )

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=50,
                messages=[{"role": "user", "content": prompt}]
            )

            return response.content[0].text.strip().upper()

        except Exception:
            return self._detect_intent_simple(message)

    def _detect_intent_simple(self, message: str) -> str:
        """Simple rule-based intent detection fallback."""
        lower = message.lower()

        # Commands
        if any(cmd in lower for cmd in ['exit', 'quit', 'help', 'holdings', 'summary']):
            return "COMMAND"

        # Questions
        if any(q in lower for q in ['how', 'what', 'why', 'when', '?']):
            return "QUESTION"

        # Trade requests
        if any(t in lower for t in ['buy', 'sell', 'trade', 'order', 'default']):
            return "TRADE_REQUEST"

        # Confirmations
        if lower in ['yes', 'no', 'y', 'n', 'ok', 'cancel']:
            return "CONFIRMATION"

        return "UNCLEAR"

    def analyze_trade_request(
        self,
        message: str,
        accounts: dict,
        buy_list: list[str],
        stock_prices: dict[str, float]
    ) -> dict:
        """
        Analyze a trade request and identify missing information.

        Args:
            message: User's trade request
            accounts: Account data
            buy_list: Available tickers to buy
            stock_prices: Ticker prices

        Returns:
            Dictionary with understood info and missing fields
        """
        if not self.api_key:
            return self._analyze_simple(message)

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)

            portfolio_summary = self._build_accounts_summary(accounts)

            prompt = TRADE_CLARIFICATION_PROMPT.format(
                message=message,
                portfolio_summary=portfolio_summary,
                buy_list=", ".join(buy_list) if buy_list else "None"
            )

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text.strip()

            # Strip markdown code blocks if present
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            return json.loads(response_text)

        except Exception as e:
            return self._analyze_simple(message)

    def _analyze_simple(self, message: str) -> dict:
        """Simple rule-based trade request analysis."""
        import re
        lower = message.lower()

        result = {
            "understood": {
                "action": "buy" if "buy" in lower else ("sell" if "sell" in lower else "buy"),
                "target_allocation": None,
                "skip_threshold": None,
                "sell_cash_equiv": None,
                "tickers": None,
                "dollar_amount": None
            },
            "missing": [],
            "clarification_questions": []
        }

        # Extract percentages
        pct_match = re.search(r'(\d+(?:\.\d+)?)\s*%', message)
        if pct_match:
            pct = float(pct_match.group(1)) / 100
            if 'target' in lower or 'allocation' in lower:
                result["understood"]["target_allocation"] = pct
            elif 'skip' in lower:
                result["understood"]["skip_threshold"] = pct

        # Check for cash equivalent selling
        if 'cash equiv' in lower or 'sell cash' in lower:
            result["understood"]["sell_cash_equiv"] = True

        # Identify missing info
        if result["understood"]["action"] == "buy":
            if not result["understood"]["target_allocation"]:
                result["missing"].append("target_allocation")
                result["clarification_questions"].append(
                    "What target allocation per stock? (e.g., 2.5% of account value)"
                )

        return result

    def interpret_with_conversation(
        self,
        specification: str,
        accounts: dict,
        buy_list: list[str],
        stock_prices: dict[str, float],
        conversation_history: list[dict] = None
    ) -> ExecutionPlan:
        """
        Interpret a specification with full conversation context.

        Args:
            specification: The trade specification
            accounts: Account data
            buy_list: Tickers to buy
            stock_prices: Current prices
            conversation_history: Previous conversation turns

        Returns:
            ExecutionPlan ready for execution
        """
        # For now, delegate to the base interpret method
        # Future enhancement: include conversation history for better understanding
        return self.interpret(specification, accounts, buy_list, stock_prices)
