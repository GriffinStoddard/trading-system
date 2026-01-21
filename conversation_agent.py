"""
Conversation Agent - Core Conversational AI Logic

Provides natural back-and-forth dialogue with users for the trading system.
Routes user messages to appropriate handlers based on intent.
"""

import json
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

from models import Account
from execution_plan import (
    ExecutionPlan, BuyRule, SellRule, CashManagement,
    QuantityType, AllocationMethod, CashSource
)
from order_generator import OrderGenerator, Order
from report_generator import generate_summary_report, print_confirmation_prompt
from system_knowledge import SYSTEM_KNOWLEDGE, CAPABILITIES_SUMMARY, WELCOME_MESSAGE
from config import get_api_key


class IntentType(Enum):
    """Classification of user message intent."""
    QUESTION = "question"                     # Asking about how the program works
    TRADE_REQUEST = "trade_request"           # Requesting to generate trades
    CLARIFICATION_RESPONSE = "clarification"  # Answering a previous question
    COMMAND = "command"                       # System commands (help, exit, etc.)
    CONFIRMATION = "confirmation"             # Yes/no response to confirmation prompt
    UNCLEAR = "unclear"                       # Ambiguous, needs clarification


@dataclass
class ConversationState:
    """Tracks multi-turn conversation context."""
    messages: list = field(default_factory=list)      # Full conversation history
    pending_trade: Optional[dict] = None              # Trade being clarified
    awaiting_clarification: bool = False              # Flag for clarification mode
    clarification_questions: list = field(default_factory=list)  # Outstanding questions
    awaiting_confirmation: bool = False               # Waiting for trade confirmation
    pending_plan: Optional[ExecutionPlan] = None      # Plan awaiting confirmation
    pending_orders: Optional[tuple] = None            # (sell_orders, buy_orders, analyses)


class ConversationAgent:
    """
    Main conversational agent for the trading system.

    Routes user messages to appropriate handlers based on detected intent.
    Maintains conversation state across multiple turns.
    """

    def __init__(
        self,
        accounts: dict[str, Account],
        stock_prices: dict[str, float],
        buy_list: list[str],
        config: dict
    ):
        self.accounts = accounts
        self.stock_prices = stock_prices
        self.buy_list = buy_list
        self.config = config
        self.state = ConversationState()
        self.should_exit = False
        self.api_key = get_api_key()

        # Load cash equivalents from config
        from config import get_cash_equivalents
        self.cash_equivalents = get_cash_equivalents()

        # For exporting orders
        self.export_orders_callback = None

    def get_welcome_message(self) -> str:
        """Return the welcome message for starting the conversation."""
        return WELCOME_MESSAGE

    def get_brief_greeting(self) -> str:
        """Return a brief personalized greeting."""
        return "\n\033[94m   Hello, Kevin. Let's trade.\033[0m"

    def chat(self, user_input: str) -> str:
        """
        Main entry point for processing user messages.

        Args:
            user_input: The user's message

        Returns:
            Agent's response string
        """
        # Add to conversation history
        self.state.messages.append({"role": "user", "content": user_input})

        # Handle confirmation state first
        if self.state.awaiting_confirmation:
            response = self._handle_confirmation(user_input)
            self.state.messages.append({"role": "assistant", "content": response})
            return response

        # Handle clarification state
        if self.state.awaiting_clarification:
            response = self._handle_clarification_response(user_input)
            self.state.messages.append({"role": "assistant", "content": response})
            return response

        # Detect intent
        intent = self._detect_intent(user_input)

        # Route to appropriate handler
        if intent == IntentType.COMMAND:
            response = self._handle_command(user_input)
        elif intent == IntentType.QUESTION:
            response = self._handle_question(user_input)
        elif intent == IntentType.TRADE_REQUEST:
            response = self._handle_trade_request(user_input)
        else:
            response = self._handle_unclear(user_input)

        self.state.messages.append({"role": "assistant", "content": response})
        return response

    def _detect_intent(self, message: str) -> IntentType:
        """
        Detect the intent of a user message using the LLM.
        """
        lower = message.lower().strip()

        # Quick check for obvious commands (these don't need LLM)
        if lower in ['exit', 'quit', 'bye', 'goodbye']:
            return IntentType.COMMAND

        # Check for API key / settings questions - route to command handler
        if 'api key' in lower or 'api-key' in lower or 'apikey' in lower:
            return IntentType.COMMAND

        # Use LLM for intent detection
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)

            # Build context from recent messages
            recent_context = ""
            if len(self.state.messages) >= 2:
                recent = self.state.messages[-4:] if len(self.state.messages) >= 4 else self.state.messages
                recent_context = "\n".join([f"{m['role']}: {m['content'][:100]}" for m in recent])

            prompt = f"""Classify this user message into exactly one of these categories:

QUESTION - Asking about how the program works, what it can do, explaining concepts, asking for information
TRADE_REQUEST - Requesting to generate trades, buy/sell orders, rebalancing, using default specification
COMMAND - System commands: help, exit, quit, settings, api key, show holdings, show summary, show buy list, view data
UNCLEAR - Ambiguous message that doesn't fit other categories, greetings, thanks, etc.

Recent conversation context:
{recent_context if recent_context else "No prior context"}

User message: {message}

Respond with ONLY the category name (QUESTION, TRADE_REQUEST, COMMAND, or UNCLEAR), nothing else."""

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=20,
                messages=[{"role": "user", "content": prompt}]
            )

            intent_str = response.content[0].text.strip().upper()

            # Map to IntentType
            intent_map = {
                "QUESTION": IntentType.QUESTION,
                "TRADE_REQUEST": IntentType.TRADE_REQUEST,
                "COMMAND": IntentType.COMMAND,
                "UNCLEAR": IntentType.UNCLEAR
            }
            return intent_map.get(intent_str, IntentType.UNCLEAR)

        except Exception as e:
            # If LLM fails, use basic fallback
            return self._detect_intent_fallback(lower)

    def _detect_intent_fallback(self, lower: str) -> IntentType:
        """Fallback intent detection if LLM fails."""
        command_patterns = [
            'exit', 'quit', 'bye', 'goodbye', 'help', 'holdings',
            'summary', 'buy list', 'prices', 'settings', 'api key'
        ]
        for pattern in command_patterns:
            if pattern in lower:
                return IntentType.COMMAND

        if '?' in lower or any(q in lower for q in ['how', 'what', 'why', 'explain']):
            return IntentType.QUESTION

        if any(t in lower for t in ['buy', 'sell', 'trade', 'default', 'order']):
            return IntentType.TRADE_REQUEST

        return IntentType.UNCLEAR

    def _handle_command(self, message: str) -> str:
        """Handle system commands."""
        lower = message.lower().strip()

        # Exit commands
        if any(cmd in lower for cmd in ['exit', 'quit', 'bye', 'goodbye']):
            self.should_exit = True
            return "Goodbye! Your order files have been saved."

        # Help
        if 'help' in lower or 'what can you do' in lower or 'commands' in lower:
            return CAPABILITIES_SUMMARY

        # Show holdings
        if any(cmd in lower for cmd in ['holdings', 'show holdings', 'view holdings']):
            return self._format_holdings()

        # Show summary
        if 'summary' in lower:
            return self._format_summary()

        # Show buy list
        if any(cmd in lower for cmd in ['buy list', 'prices']):
            return self._format_buy_list()

        # Settings / API key
        if any(cmd in lower for cmd in ['settings', 'api key', 'configure', 'config']):
            return self._handle_settings(lower)

        return "I didn't recognize that command. Type 'help' to see what I can do."

    def _handle_question(self, message: str) -> str:
        """Handle questions about how the system works using the LLM."""
        return self._answer_question_with_llm(message)

    def _answer_question_with_llm(self, question: str) -> str:
        """Use the LLM to answer a question with system knowledge."""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)

            # Include current portfolio context
            portfolio_context = self._build_portfolio_context()

            system_prompt = f"""You are a helpful AI assistant for a trading order generation system.
Answer the user's question based on this knowledge base and the current portfolio state.

## System Knowledge Base
{SYSTEM_KNOWLEDGE}

## Current Portfolio State
{portfolio_context}

## Guidelines
- Be concise but thorough
- Use specific numbers from the portfolio when relevant
- If the question is outside the scope of this trading system, say so politely and suggest what you can help with
- When explaining calculations, use concrete examples from their actual data when possible"""

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": question}]
            )

            return response.content[0].text

        except Exception as e:
            return f"I encountered an error answering your question: {e}\n\nPlease try rephrasing or ask a different question."

    def _build_portfolio_context(self) -> str:
        """Build a context string describing the current portfolio."""
        lines = []
        total_all = 0

        for account_num, account in self.accounts.items():
            total = account.get_total_value()
            total_all += total
            name = f" ({account.client_name})" if account.client_name else ""
            lines.append(f"Account {account_num}{name}: ${total:,.2f} total")
            lines.append(f"  - Cash: ${account.cash:,.2f}")
            lines.append(f"  - Cash Equivalents: ${account.get_cash_equivalents_value():,.2f}")
            lines.append(f"  - Holdings: {len(account.holdings)} positions")

        lines.append(f"\nTotal Portfolio Value: ${total_all:,.2f}")
        lines.append(f"Buy List: {', '.join(self.buy_list) if self.buy_list else 'Empty'}")

        return "\n".join(lines)

    def _handle_trade_request(self, message: str) -> str:
        """Handle a trade request - routes to LLM interpreter."""
        lower = message.lower()

        # Check for default mode request
        if 'default' in lower or ('use' in lower and 'standard' in lower):
            return self._execute_default_trade()

        # Route all custom trade requests through the LLM interpreter
        try:
            return self._process_trade_with_interpreter(message)
        except Exception as e:
            return f"I encountered an error processing your trade request: {e}\n\nPlease try rephrasing, or say 'use default' to use the default specification."

    def _process_trade_with_interpreter(self, message: str) -> str:
        """Process a trade request using the full LLM interpreter."""
        from llm_interpreter import LLMInterpreter

        interpreter = LLMInterpreter(self.api_key)
        plan = interpreter.interpret(
            message,
            self.accounts,
            self.buy_list,
            self.stock_prices
        )

        # Execute plan to get orders
        generator = OrderGenerator(self.accounts, self.stock_prices)
        sell_orders, buy_orders = generator.execute_plan(plan)
        analyses = generator.get_analyses()

        # Store for confirmation
        self.state.pending_plan = plan
        self.state.pending_orders = (sell_orders, buy_orders, analyses)
        self.state.awaiting_confirmation = True

        # Build confirmation message
        confirmation = print_confirmation_prompt(plan.description, analyses, sell_orders, buy_orders)

        return f"""Here's what I'll do:

{plan.description}

{confirmation}

Would you like me to generate these orders? (yes/no)"""

    def _handle_clarification_response(self, message: str) -> str:
        """Handle user's response to clarification questions."""
        lower = message.lower()

        # Check if we're waiting for an API key
        if self.state.pending_trade and self.state.pending_trade.get('action') == 'set_api_key':
            return self._save_api_key(message.strip())

        # Check for "use defaults"
        if 'default' in lower:
            self.state.awaiting_clarification = False
            self.state.pending_trade = None
            return self._execute_default_trade()

        # For any other clarification, treat it as a new trade request
        self.state.awaiting_clarification = False
        original = self.state.pending_trade.get('original_request', '') if self.state.pending_trade else ''
        self.state.pending_trade = None

        # Combine original request with clarification for context
        combined_request = f"{original} {message}".strip() if original else message
        return self._handle_trade_request(combined_request)

    def _handle_confirmation(self, message: str) -> str:
        """Handle yes/no confirmation response."""
        lower = message.lower().strip()

        if lower in ['yes', 'y', 'yeah', 'yep', 'sure', 'ok', 'okay', 'proceed', 'do it']:
            self.state.awaiting_confirmation = False
            return self._execute_trade()
        elif lower in ['no', 'n', 'nope', 'cancel', 'stop', 'nevermind']:
            self.state.awaiting_confirmation = False
            self.state.pending_plan = None
            self.state.pending_orders = None
            return "Cancelled. No orders were generated. What else can I help you with?"
        else:
            return "Please answer yes or no. Would you like me to generate these orders?"

    def _execute_trade(self) -> str:
        """Execute the pending trade and generate order files."""
        if not self.state.pending_orders:
            return "No pending orders to execute."

        sell_orders, buy_orders, analyses = self.state.pending_orders
        plan = self.state.pending_plan

        if not sell_orders and not buy_orders:
            self.state.pending_plan = None
            self.state.pending_orders = None
            return "No orders were generated. This might be because all stocks on the buy list are already owned above the skip threshold."

        # Export orders using callback if set
        if self.export_orders_callback:
            sell_file, buy_file = self.export_orders_callback(sell_orders, buy_orders)

            # Generate report
            report = generate_summary_report(
                analyses, sell_orders, buy_orders,
                plan.description, sell_file, buy_file
            )

            # Save report to the same folder as the order files
            from pathlib import Path
            # Extract the folder from sell_file path (e.g., "01-20-2026/sell_order.csv" -> "01-20-2026")
            date_folder = sell_file.split('/')[0] if '/' in sell_file else ""
            report_filename = "trade_report.txt"

            if date_folder:
                report_path = Path.cwd() / date_folder / report_filename
                report_file = f"{date_folder}/{report_filename}"
            else:
                report_path = Path.cwd() / report_filename
                report_file = report_filename

            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report)

            result = f"""Orders generated successfully!

Files created in '{date_folder}/' folder:
- sell_order.csv ({len(sell_orders)} sell orders)
- buy_order.csv ({len(buy_orders)} buy orders)
- trade_report.txt (summary report)

What else can I help you with?"""
        else:
            result = f"""Orders ready!
- {len(sell_orders)} sell orders
- {len(buy_orders)} buy orders

(Note: Export callback not set - files were not saved)"""

        self.state.pending_plan = None
        self.state.pending_orders = None

        return result

    def _execute_default_trade(self) -> str:
        """Execute the default trade specification."""
        if not self.buy_list:
            return "No stocks in buy list. Please add stocks to stock_prices.csv first."

        target_alloc = self.config.get("default_target_allocation_percent", 0.025)
        skip_above = self.config.get("default_skip_if_above_percent", 0.02)
        cash_floor = self.config.get("default_cash_floor_percent", 0.02)

        plan = ExecutionPlan(
            description=f"Buy to {target_alloc*100}% target allocation per stock. Skip if >= {skip_above*100}% owned. "
                        f"Sell cash equivalents (largest first) if needed. Maintain {cash_floor*100}% cash floor.",
            buy_rules=[
                BuyRule(
                    tickers=self.buy_list,
                    quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                    quantity=target_alloc,
                    allocation_method=AllocationMethod.EQUAL_WEIGHT,
                    skip_if_allocation_above=skip_above,
                    buy_only_to_target=True,
                    cash_source=CashSource.CASH_EQUIVALENTS,
                    sell_cash_equiv_if_needed=True
                )
            ],
            cash_management=CashManagement(
                min_cash_percent=cash_floor,
                cash_equiv_sell_order="largest_first"
            )
        )

        # Generate orders
        generator = OrderGenerator(self.accounts, self.stock_prices)
        sell_orders, buy_orders = generator.execute_plan(plan)
        analyses = generator.get_analyses()

        # Store for confirmation
        self.state.pending_plan = plan
        self.state.pending_orders = (sell_orders, buy_orders, analyses)
        self.state.awaiting_confirmation = True

        confirmation = print_confirmation_prompt(plan.description, analyses, sell_orders, buy_orders)

        return f"""Using default specification:
{plan.description}

{confirmation}

Would you like me to generate these orders? (yes/no)"""

    def _handle_unclear(self, message: str) -> str:
        """Handle unclear or ambiguous messages using LLM."""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)

            portfolio_context = self._build_portfolio_context()

            system_prompt = f"""You are a helpful AI assistant for a trading order generation system.

The user sent a message that wasn't clearly a question, trade request, or command.
Respond naturally and helpfully, and guide them toward what you can help with.

## What You Can Do
1. Generate trade orders (buy/sell orders for their portfolio)
2. Answer questions about how the trading system works
3. Show their holdings, account summary, or buy list
4. Configure settings like API key

## Current Portfolio
{portfolio_context}

## Guidelines
- Be friendly and helpful
- If they greeted you, greet them back and offer to help
- If they thanked you, acknowledge it graciously
- If they seem confused, explain what you can do
- Keep responses concise"""

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                system=system_prompt,
                messages=[{"role": "user", "content": message}]
            )

            return response.content[0].text

        except Exception as e:
            return f"""I'm not sure what you'd like to do. I can help you with:

1. **Generate Trades**: Tell me what trades you want
   - "Buy stocks on my buy list at 2.5% each"
   - "Use default" to run the default specification

2. **Answer Questions**: Ask about how the system works
   - "How does the cash floor work?"

3. **View Data**:
   - "Show my holdings"
   - "Show the buy list"

What would you like to do?"""

    def _format_holdings(self) -> str:
        """Format holdings for display."""
        lines = []
        lines.append("=" * 70)
        lines.append("DETAILED HOLDINGS")
        lines.append("=" * 70)

        for account_num, account in self.accounts.items():
            name_str = f" - {account.client_name}" if account.client_name else ""
            lines.append(f"\n--- Account {account_num}{name_str} ---")
            total = account.get_total_value()

            if account.holdings:
                lines.append("\n  Stock Holdings:")
                lines.append(f"  {'Symbol':<10} {'Shares':<12} {'Price':<12} {'Value':<15} {'Alloc':<8}")
                lines.append(f"  {'-' * 57}")

                for h in account.holdings:
                    alloc = (h.market_value or 0) / total * 100 if total > 0 else 0
                    lines.append(f"  {h.symbol:<10} {h.shares:<12,.0f} ${h.price or 0:<10,.2f} ${h.market_value or 0:<13,.2f} {alloc:.1f}%")

            if account.cash_equivalents:
                lines.append("\n  Cash Equivalents:")
                lines.append(f"  {'Symbol':<10} {'Shares':<12} {'Price':<12} {'Value':<15} {'Alloc':<8}")
                lines.append(f"  {'-' * 57}")

                for ce in account.cash_equivalents:
                    alloc = (ce.market_value or 0) / total * 100 if total > 0 else 0
                    lines.append(f"  {ce.symbol:<10} {ce.shares:<12,.0f} ${ce.price or 0:<10,.2f} ${ce.market_value or 0:<13,.2f} {alloc:.1f}%")

            lines.append(f"\n  Cash Balance: ${account.cash:,.2f}")

        return "\n".join(lines)

    def _format_summary(self) -> str:
        """Format account summary for display."""
        lines = []
        lines.append("=" * 70)
        lines.append("PORTFOLIO OVERVIEW")
        lines.append("=" * 70)

        total_value_all = 0

        for account_num, account in self.accounts.items():
            total_value = account.get_total_value()
            cash = account.cash
            ce_value = account.get_cash_equivalents_value()

            name_str = f" ({account.client_name})" if account.client_name else ""

            lines.append(f"\nAccount {account_num}{name_str}:")
            lines.append(f"  Total Value: ${total_value:,.2f}")
            lines.append(f"  Cash: ${cash:,.2f} ({cash/total_value*100:.1f}%)")
            lines.append(f"  Cash Equivalents: ${ce_value:,.2f} ({ce_value/total_value*100:.1f}%)")
            lines.append(f"  Holdings: {len(account.holdings)} positions")

            total_value_all += total_value

        lines.append(f"\n{'=' * 40}")
        lines.append(f"TOTAL PORTFOLIO VALUE: ${total_value_all:,.2f}")
        lines.append("=" * 70)

        return "\n".join(lines)

    def _save_api_key(self, api_key: str) -> str:
        """Save an API key provided by the user."""
        from config import set_api_key

        self.state.awaiting_clarification = False
        self.state.pending_trade = None

        # Basic validation
        if not api_key or len(api_key) < 10:
            return "That doesn't look like a valid API key. API keys are typically longer. Please try again by saying 'set api key'."

        if api_key.lower() in ['cancel', 'nevermind', 'no', 'stop']:
            return "Cancelled. No changes made to your API key."

        # Save the key
        if set_api_key(api_key):
            self.api_key = api_key  # Update the agent's key too
            masked = api_key[:10] + "..." + api_key[-4:]
            return f"""API key saved successfully!

Saved key: {masked}

You can now use custom trade specifications and get AI-powered answers to your questions.

What would you like to do?"""
        else:
            return "Failed to save the API key. Please check that config.json is writable."

    def _handle_settings(self, message: str) -> str:
        """Handle settings and API key configuration."""
        from config import get_api_key, set_api_key

        # Check if they want to set a new key
        if 'set' in message or 'input' in message or 'enter' in message or 'add' in message:
            self.state.awaiting_clarification = True
            self.state.pending_trade = {'action': 'set_api_key'}
            return """Please enter your Anthropic API key.

You can get an API key from: https://console.anthropic.com/

Paste your key here (it will be saved to config.json):"""

        # Check current API key status
        current_key = get_api_key()
        if current_key:
            masked = current_key[:10] + "..." + current_key[-4:]
            return f"""API Key Status: Configured

Current API key: {masked}

With an API key, you can:
- Use custom natural language trade specifications
- Get AI-powered answers to your questions

To update your API key, say "set api key" or "enter new api key"."""
        else:
            return """API Key Status: Not configured

No API key found. Without an API key, you can still:
- Use the default trade specification ("use default")
- View holdings and account summaries
- Get basic answers to common questions

To add your API key, say "set api key" or "enter api key".
You can get an API key from: https://console.anthropic.com/"""

    def _format_buy_list(self) -> str:
        """Format buy list for display."""
        lines = []
        lines.append("-" * 40)
        lines.append("CURRENT BUY LIST")
        lines.append("-" * 40)

        if not self.buy_list:
            lines.append("No stocks in buy list.")
            return "\n".join(lines)

        lines.append(f"{'#':<4} {'Ticker':<10} {'Price':<12}")
        lines.append("-" * 26)

        for i, ticker in enumerate(self.buy_list, 1):
            price = self.stock_prices.get(ticker, 0)
            lines.append(f"{i:<4} {ticker:<10} ${price:,.2f}")

        return "\n".join(lines)
