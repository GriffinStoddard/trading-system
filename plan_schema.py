"""
Execution Plan JSON Schema + planning guidance.

The schema is given to Claude as a strict tool input schema, so every plan the
model produces is structurally valid before it ever reaches ExecutionPlan.from_dict().
The guidance text encodes the domain rules the model must follow when translating
an advisor's natural language into a plan.
"""

_ACCOUNT_FILTER_SCHEMA = {
    "type": ["object", "null"],
    "properties": {
        "min_value": {
            "type": ["number", "null"],
            "description": "Skip accounts with total value below this",
        },
        "max_value": {
            "type": ["number", "null"],
            "description": "Skip accounts with total value above this",
        },
        "account_numbers": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "Only process these account numbers",
        },
        "must_hold_tickers": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "Only process accounts holding at least one of these tickers",
        },
        "client_name_contains": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "Only process accounts whose client name contains any of these strings (case-insensitive)",
        },
        "exclude_client_names": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "Exclude accounts whose client name contains any of these strings (case-insensitive)",
        },
    },
    "required": [
        "min_value", "max_value", "account_numbers",
        "must_hold_tickers", "client_name_contains", "exclude_client_names",
    ],
    "additionalProperties": False,
}

_SELL_RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "tickers": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Tickers to sell. Special tokens: [\"*\"] = all regular stock "
                "holdings (e.g. raising cash); [\"CASH_EQUIVALENTS\"] = all "
                "cash-equivalent holdings, sold as standalone sells (i.e. moved "
                "to cash). [\"*\"] does NOT include cash equivalents — use "
                "CASH_EQUIVALENTS for those, or both tokens to liquidate "
                "everything."),
        },
        "quantity_type": {
            "type": "string",
            "enum": ["all", "percent_of_position", "shares", "dollars", "to_target"],
        },
        "quantity": {
            "type": ["number", "null"],
            "description": "Amount: decimal for percent (0.5 = 50%), share count, or dollar amount. Null for 'all'.",
        },
        "priority": {
            "type": "string",
            "enum": ["largest_first", "smallest_first"],
            "description": "Which positions to sell first when raising cash",
        },
        "min_shares_remaining": {
            "type": ["integer", "null"],
            "description": "Never reduce a position below this many shares",
        },
        "max_percent_of_position": {
            "type": ["number", "null"],
            "description": "Never sell more than this fraction of any position (0.25 = 25%)",
        },
        "account_filter": _ACCOUNT_FILTER_SCHEMA,
    },
    "required": [
        "tickers", "quantity_type", "quantity", "priority",
        "min_shares_remaining", "max_percent_of_position", "account_filter",
    ],
    "additionalProperties": False,
}

_BUY_RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "tickers": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Tickers to buy (must have prices in the buy list)",
        },
        "quantity_type": {
            "type": "string",
            "enum": ["percent_of_account", "shares", "dollars", "to_target"],
        },
        "quantity": {
            "type": ["number", "null"],
            "description": "Target per ticker: decimal for percent (0.025 = 2.5%), share count, or dollar amount",
        },
        "allocation_method": {
            "type": "string",
            "enum": ["equal_weight", "proportional", "specified"],
        },
        "skip_if_allocation_above": {
            "type": ["number", "null"],
            "description": "Skip a ticker if the account already holds >= this fraction of it",
        },
        "buy_only_to_target": {
            "type": "boolean",
            "description": "Only buy the difference needed to reach the target allocation",
        },
        "buy_only_if_sold": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "Only buy in accounts that sold one of these tickers (must match a sell rule)",
        },
        "use_proceeds_from_sale": {
            "type": "boolean",
            "description": "Fund this buy with the proceeds from the buy_only_if_sold tickers",
        },
        "cash_source": {
            "type": "string",
            "enum": ["available_cash", "cash_equivalents", "sell_holdings"],
        },
        "sell_cash_equiv_if_needed": {
            "type": "boolean",
            "description": "Sell cash equivalents to fund this buy if cash is short",
        },
        "min_buy_allocation": {
            "type": ["number", "null"],
            "description": "Skip buys smaller than this fraction of the account (0.01 = 1%)",
        },
    },
    "required": [
        "tickers", "quantity_type", "quantity", "allocation_method",
        "skip_if_allocation_above", "buy_only_to_target", "buy_only_if_sold",
        "use_proceeds_from_sale", "cash_source", "sell_cash_equiv_if_needed",
        "min_buy_allocation",
    ],
    "additionalProperties": False,
}

EXECUTION_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "One-sentence human-readable summary of the plan",
        },
        "sell_rules": {"type": "array", "items": _SELL_RULE_SCHEMA},
        "buy_rules": {"type": "array", "items": _BUY_RULE_SCHEMA},
        "account_filter": _ACCOUNT_FILTER_SCHEMA,
        "cash_management": {
            "type": "object",
            "properties": {
                "min_cash_percent": {
                    "type": "number",
                    "description": "Minimum cash fraction to keep in each account (0.02 = 2%)",
                },
                "min_cash_dollars": {
                    "type": ["number", "null"],
                    "description": "Minimum cash in dollars (used if larger than the percent floor)",
                },
                "cash_equiv_sell_order": {
                    "type": "string",
                    "enum": ["largest_first", "smallest_first"],
                },
            },
            "required": ["min_cash_percent", "min_cash_dollars", "cash_equiv_sell_order"],
            "additionalProperties": False,
        },
        "sells_before_buys": {"type": "boolean"},
    },
    "required": [
        "description", "sell_rules", "buy_rules",
        "account_filter", "cash_management", "sells_before_buys",
    ],
    "additionalProperties": False,
}


PLAN_GUIDANCE = """\
## How to build an execution plan

All percentages are decimals: 2.5% = 0.025, 2% = 0.02.

Defaults (apply unless the advisor says otherwise):
- min_cash_percent: 0.02 (2% cash floor)
- min_buy_allocation: 0.01 (skip buys under 1% of the account); set null only if the \
advisor says "no minimum"
- sells_before_buys: true
- cash_equiv_sell_order: "largest_first"
- When buying to a target allocation, set buy_only_to_target: true so existing \
positions are only topped up
- When the advisor says to sell cash equivalents if needed, set \
sell_cash_equiv_if_needed: true and cash_source: "cash_equivalents"

Conditional sell-then-buy ("sell X, buy Y with the proceeds"):
- Create a sell rule for X, then a buy rule for Y with buy_only_if_sold: ["X"] and \
use_proceeds_from_sale: true. The buy only runs in accounts that actually sold X.

Raising cash ("raise $150k"):
- One sell rule with tickers: ["*"], quantity_type "dollars", quantity = amount.
- Honor constraints like "don't sell below 50 shares" (min_shares_remaining) and \
"max 25% of any position" (max_percent_of_position).

Selling cash equivalents as standalone sells (moving them to cash):
- The configured cash equivalents can be SOLD directly, not only drawn \
down to fund buys. Use the ticker token "CASH_EQUIVALENTS".
- "Sell all cash equivalents" -> sell rule tickers ["CASH_EQUIVALENTS"], \
quantity_type "all".
- "Raise $50k by selling cash equivalents" -> tickers ["CASH_EQUIVALENTS"], \
quantity_type "dollars", quantity 50000 (raises up to that amount per account \
from the cash-equivalent basket, capped at what each account holds).
- This is a real, supported operation — never tell the user the tool cannot \
sell cash equivalents. The plain ["*"] wildcard does NOT include them; use \
["CASH_EQUIVALENTS"] (or list both to liquidate everything).

Per-rule account filters:
- A sell rule can carry its own account_filter, overriding the plan-level one. Use \
this for instructions like "sell X everywhere, but also sell Y for client Smith" \
(second rule with client_name_contains: ["Smith"]) or "except for client Jones" \
(exclude_client_names: ["Jones"]).

Only use tickers from the buy list for buy rules — those are the only ones with \
prices. Sell rules may reference any held ticker.
"""
