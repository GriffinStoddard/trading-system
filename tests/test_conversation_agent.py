"""
Tests for the ConversationAgent (v2.0 conversational interface)
"""

import pytest
from conversation_agent import (
    ConversationAgent, IntentType, ConversationState
)
from models import Account, Holding
from system_knowledge import SYSTEM_KNOWLEDGE, CAPABILITIES_SUMMARY, WELCOME_MESSAGE


class TestIntentType:
    """Test IntentType enum values."""

    def test_all_intent_types_exist(self):
        """Verify all expected intent types are defined."""
        assert IntentType.QUESTION.value == "question"
        assert IntentType.TRADE_REQUEST.value == "trade_request"
        assert IntentType.CLARIFICATION_RESPONSE.value == "clarification"
        assert IntentType.COMMAND.value == "command"
        assert IntentType.CONFIRMATION.value == "confirmation"
        assert IntentType.UNCLEAR.value == "unclear"


class TestConversationState:
    """Test ConversationState dataclass."""

    def test_default_state(self):
        """Test default state values."""
        state = ConversationState()
        assert state.messages == []
        assert state.pending_trade is None
        assert state.awaiting_clarification is False
        assert state.clarification_questions == []
        assert state.awaiting_confirmation is False
        assert state.pending_plan is None
        assert state.pending_orders is None


class TestSystemKnowledge:
    """Test system knowledge content."""

    def test_system_knowledge_exists(self):
        """Verify system knowledge is not empty."""
        assert len(SYSTEM_KNOWLEDGE) > 100

    def test_capabilities_summary_exists(self):
        """Verify capabilities summary is not empty."""
        assert len(CAPABILITIES_SUMMARY) > 50

    def test_welcome_message_exists(self):
        """Verify welcome message is not empty."""
        assert len(WELCOME_MESSAGE) > 50
        assert "2.1.0" in WELCOME_MESSAGE

    def test_system_knowledge_contains_key_concepts(self):
        """Verify system knowledge covers key concepts."""
        assert "cash floor" in SYSTEM_KNOWLEDGE.lower()
        assert "cash equivalent" in SYSTEM_KNOWLEDGE.lower()
        assert "target allocation" in SYSTEM_KNOWLEDGE.lower()


class TestConversationAgentSetup:
    """Test ConversationAgent initialization."""

    @pytest.fixture
    def sample_accounts(self):
        """Create sample accounts for testing."""
        account = Account(account_num="12345", client_name="Test Client")
        account.cash = 10000.0
        account.add_holding(Holding("AAPL", 100, 150.0, 15000.0))
        account.add_cash_equivalent(Holding("BIL", 200, 100.0, 20000.0))
        return {"12345": account}

    @pytest.fixture
    def sample_prices(self):
        """Create sample stock prices."""
        return {"GOOGL": 100.0, "MSFT": 300.0, "AAPL": 150.0}

    @pytest.fixture
    def sample_buy_list(self):
        """Create sample buy list."""
        return ["GOOGL", "MSFT"]

    @pytest.fixture
    def sample_config(self):
        """Create sample config."""
        return {
            "default_target_allocation_percent": 0.025,
            "default_skip_if_above_percent": 0.02,
            "default_cash_floor_percent": 0.02,
            "cash_equivalents": ["BIL", "USFR", "PJLXX"]
        }

    @pytest.fixture
    def agent(self, sample_accounts, sample_prices, sample_buy_list, sample_config):
        """Create a ConversationAgent for testing."""
        return ConversationAgent(
            sample_accounts, sample_prices, sample_buy_list, sample_config
        )

    def test_agent_initialization(self, agent, sample_accounts, sample_buy_list):
        """Test agent initializes correctly."""
        assert agent.accounts == sample_accounts
        assert agent.buy_list == sample_buy_list
        assert agent.should_exit is False
        assert isinstance(agent.state, ConversationState)

    def test_get_welcome_message(self, agent):
        """Test welcome message is returned."""
        welcome = agent.get_welcome_message()
        assert "2.1.0" in welcome
        assert "Conversational" in welcome


class TestIntentDetection:
    """Test intent detection logic (using fallback without API key)."""

    @pytest.fixture
    def agent(self):
        """Create a minimal agent for intent detection testing."""
        account = Account(account_num="12345")
        account.cash = 10000.0
        return ConversationAgent(
            {"12345": account},
            {"GOOGL": 100.0},
            ["GOOGL"],
            {}
        )

    def test_detect_exit_command(self, agent):
        """Test exit command detection."""
        # These use direct string matching, not LLM
        assert agent._detect_intent("exit") == IntentType.COMMAND
        assert agent._detect_intent("quit") == IntentType.COMMAND
        assert agent._detect_intent("goodbye") == IntentType.COMMAND

    def test_detect_help_command(self, agent):
        """Test help command detection via fallback."""
        # Without API key, uses fallback which checks for 'help' in string
        intent = agent._detect_intent_fallback("help")
        assert intent == IntentType.COMMAND

    def test_detect_holdings_command(self, agent):
        """Test holdings command detection via fallback."""
        assert agent._detect_intent_fallback("show holdings") == IntentType.COMMAND
        assert agent._detect_intent_fallback("holdings") == IntentType.COMMAND

    def test_detect_summary_command(self, agent):
        """Test summary command detection via fallback."""
        assert agent._detect_intent_fallback("summary") == IntentType.COMMAND

    def test_detect_question(self, agent):
        """Test question detection via fallback."""
        assert agent._detect_intent_fallback("how does the cash floor work?") == IntentType.QUESTION
        assert agent._detect_intent_fallback("what are cash equivalents?") == IntentType.QUESTION

    def test_detect_trade_request(self, agent):
        """Test trade request detection via fallback."""
        assert agent._detect_intent_fallback("buy the stocks on my list") == IntentType.TRADE_REQUEST
        assert agent._detect_intent_fallback("sell all LUMN") == IntentType.TRADE_REQUEST
        assert agent._detect_intent_fallback("use default") == IntentType.TRADE_REQUEST

    def test_detect_unclear(self, agent):
        """Test unclear message detection via fallback."""
        assert agent._detect_intent_fallback("hello there") == IntentType.UNCLEAR
        assert agent._detect_intent_fallback("thanks") == IntentType.UNCLEAR


class TestCommandHandling:
    """Test command handling."""

    @pytest.fixture
    def agent(self):
        """Create agent for command testing."""
        account = Account(account_num="12345", client_name="Test Client")
        account.cash = 10000.0
        account.add_holding(Holding("AAPL", 100, 150.0, 15000.0))
        return ConversationAgent(
            {"12345": account},
            {"GOOGL": 100.0, "MSFT": 300.0},
            ["GOOGL", "MSFT"],
            {}
        )

    def test_exit_command_sets_flag(self, agent):
        """Test that exit command sets should_exit flag."""
        response = agent.chat("exit")
        assert agent.should_exit is True
        assert "Goodbye" in response

    def test_help_command_returns_capabilities(self, agent):
        """Test help command returns capabilities."""
        response = agent.chat("help")
        assert "Generate Trade Orders" in response or "trade" in response.lower()

    def test_holdings_command_shows_holdings(self, agent):
        """Test holdings command shows account holdings."""
        response = agent.chat("show holdings")
        assert "12345" in response
        assert "AAPL" in response

    def test_summary_command_shows_summary(self, agent):
        """Test summary command shows account summary."""
        response = agent.chat("summary")
        assert "12345" in response
        assert "Total Value" in response

    def test_buy_list_command(self, agent):
        """Test buy list command shows buy list."""
        response = agent.chat("show buy list")
        assert "GOOGL" in response
        assert "MSFT" in response


class TestQuestionHandling:
    """Test question handling (requires API key for full functionality)."""

    @pytest.fixture
    def agent(self):
        """Create agent for question testing (no API key - limited functionality)."""
        account = Account(account_num="12345")
        account.cash = 10000.0
        return ConversationAgent(
            {"12345": account},
            {"GOOGL": 100.0},
            ["GOOGL"],
            {}
        )

    def test_question_returns_response(self, agent):
        """Test that questions return some response (even without API key)."""
        response = agent.chat("how does the cash floor work?")
        # Without API key, should return an error message or fallback
        assert response is not None
        assert len(response) > 0

    def test_question_handling_does_not_crash(self, agent):
        """Test that question handling doesn't crash without API key."""
        # These should not raise exceptions
        response1 = agent.chat("what are cash equivalents?")
        response2 = agent.chat("what are the output files?")
        assert response1 is not None
        assert response2 is not None

    def test_portfolio_context_built(self, agent):
        """Test that portfolio context is built correctly."""
        context = agent._build_portfolio_context()
        assert "12345" in context
        assert "10,000" in context or "10000" in context


class TestConversationFlow:
    """Test multi-turn conversation flows."""

    @pytest.fixture
    def agent(self):
        """Create agent for conversation flow testing."""
        account = Account(account_num="12345", client_name="Test Client")
        account.cash = 50000.0
        account.add_holding(Holding("AAPL", 50, 150.0, 7500.0))
        account.add_cash_equivalent(Holding("BIL", 500, 100.0, 50000.0))
        return ConversationAgent(
            {"12345": account},
            {"GOOGL": 100.0, "MSFT": 300.0},
            ["GOOGL", "MSFT"],
            {"default_target_allocation_percent": 0.025}
        )

    def test_conversation_history_tracked(self, agent):
        """Test that conversation history is tracked."""
        agent.chat("hello")
        agent.chat("show summary")
        assert len(agent.state.messages) == 4  # 2 user + 2 assistant

    def test_default_trade_triggers_confirmation(self, agent):
        """Test that default trade request triggers confirmation."""
        response = agent.chat("use default")
        assert agent.state.awaiting_confirmation is True
        assert "yes" in response.lower() or "confirm" in response.lower()

    def test_confirmation_yes_generates_orders(self, agent):
        """Test that confirming generates orders."""
        # Set up a mock export callback
        exported_files = []

        def mock_export(sell_orders, buy_orders, prefix=None):
            exported_files.append((len(sell_orders), len(buy_orders)))
            return "sell.csv", "buy.csv"

        agent.export_orders_callback = mock_export

        # Request default trade
        agent.chat("use default")

        # Confirm
        response = agent.chat("yes")
        assert agent.state.awaiting_confirmation is False
        assert len(exported_files) == 1 or "generated" in response.lower() or "order" in response.lower()

    def test_confirmation_no_cancels(self, agent):
        """Test that declining cancels the trade."""
        agent.chat("use default")
        response = agent.chat("no")
        assert agent.state.awaiting_confirmation is False
        assert "cancel" in response.lower()


class TestFormatting:
    """Test output formatting methods."""

    @pytest.fixture
    def agent(self):
        """Create agent with sample data for formatting tests."""
        account = Account(account_num="12345", client_name="Test Client")
        account.cash = 10000.0
        account.add_holding(Holding("AAPL", 100, 150.0, 15000.0))
        account.add_holding(Holding("GOOGL", 50, 100.0, 5000.0))
        account.add_cash_equivalent(Holding("BIL", 200, 100.0, 20000.0))
        return ConversationAgent(
            {"12345": account},
            {"GOOGL": 100.0, "MSFT": 300.0},
            ["GOOGL", "MSFT"],
            {}
        )

    def test_format_holdings_includes_all_data(self, agent):
        """Test holdings format includes all account data."""
        output = agent._format_holdings()
        assert "12345" in output
        assert "AAPL" in output
        assert "GOOGL" in output
        assert "BIL" in output

    def test_format_summary_includes_totals(self, agent):
        """Test summary format includes totals."""
        output = agent._format_summary()
        assert "Total Value" in output
        assert "Cash" in output

    def test_format_buy_list_includes_prices(self, agent):
        """Test buy list format includes prices."""
        output = agent._format_buy_list()
        assert "GOOGL" in output
        assert "MSFT" in output
        assert "$" in output


class TestSettingsHandling:
    """Test settings and API key handling."""

    @pytest.fixture
    def agent(self):
        """Create agent for settings testing."""
        account = Account(account_num="12345")
        account.cash = 10000.0
        return ConversationAgent(
            {"12345": account},
            {"GOOGL": 100.0},
            ["GOOGL"],
            {}
        )

    def test_check_api_key_detected_as_command(self, agent):
        """Test that 'check api key' is detected as a command."""
        assert agent._detect_intent("check api key") == IntentType.COMMAND

    def test_settings_detected_as_command(self, agent):
        """Test that 'settings' is detected as a command."""
        assert agent._detect_intent("settings") == IntentType.COMMAND

    def test_configure_api_key_detected_as_command(self, agent):
        """Test that 'configure api key' is detected as a command."""
        assert agent._detect_intent("configure api key") == IntentType.COMMAND

    def test_api_key_status_shown(self, agent):
        """Test that API key status is shown."""
        response = agent.chat("check api key")
        assert "API Key Status" in response

    def test_set_api_key_prompts_for_key(self, agent):
        """Test that 'set api key' prompts for the key."""
        response = agent.chat("set api key")
        assert agent.state.awaiting_clarification is True
        assert "enter" in response.lower() or "paste" in response.lower()


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_accounts(self):
        """Test agent with no accounts."""
        agent = ConversationAgent({}, {"GOOGL": 100.0}, ["GOOGL"], {})
        response = agent.chat("show holdings")
        # Should not crash
        assert response is not None

    def test_empty_buy_list(self):
        """Test agent with empty buy list."""
        account = Account(account_num="12345")
        account.cash = 10000.0
        agent = ConversationAgent({"12345": account}, {}, [], {})
        response = agent.chat("show buy list")
        assert "No stocks" in response or "empty" in response.lower()

    def test_empty_input_handled(self):
        """Test that empty input is handled gracefully."""
        account = Account(account_num="12345")
        account.cash = 10000.0
        agent = ConversationAgent({"12345": account}, {}, [], {})
        # The main loop filters empty input, but chat should handle it
        response = agent.chat("")
        assert response is not None

    def test_special_characters_in_input(self):
        """Test handling of special characters in input."""
        account = Account(account_num="12345")
        account.cash = 10000.0
        agent = ConversationAgent({"12345": account}, {}, [], {})
        response = agent.chat("What about <script>alert('xss')</script>?")
        # Should not crash and should return some response
        assert response is not None
