"""
Tests for the conversation agent (v3 tool-use architecture).

Everything tested here runs locally — no API calls. The Claude loop itself is
exercised through its tool handlers (_tool_propose_plan, _tool_account_details),
which is where all the deterministic logic lives.
"""

import pytest

from conversation_agent import (
    ConversationAgent, ConversationState, AgentReply,
)
from models import Account, Holding
from system_knowledge import SYSTEM_KNOWLEDGE, CAPABILITIES_SUMMARY, WELCOME_MESSAGE
from plan_schema import EXECUTION_PLAN_SCHEMA


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_accounts():
    account = Account(account_num="12345", client_name="Test Client")
    account.cash = 10000.0
    account.add_holding(Holding("AAPL", 100, 150.0, 15000.0))
    account.add_cash_equivalent(Holding("BIL", 200, 100.0, 20000.0))
    return {"12345": account}


@pytest.fixture
def sample_prices():
    return {"GOOGL": 100.0, "MSFT": 300.0, "AAPL": 150.0}


@pytest.fixture
def sample_buy_list():
    return ["GOOGL", "MSFT"]


@pytest.fixture
def sample_config():
    return {
        "default_target_allocation_percent": 0.025,
        "default_skip_if_above_percent": 0.02,
        "default_cash_floor_percent": 0.02,
        "default_min_buy_percent": 0.0,
        "cash_equivalents": ["BIL", "USFR", "PJLXX"],
    }


@pytest.fixture
def agent(sample_accounts, sample_prices, sample_buy_list, sample_config):
    a = ConversationAgent(sample_accounts, sample_prices, sample_buy_list, sample_config)
    a.api_key = ""  # force local-only behavior in tests
    return a


def make_plan_dict(**overrides):
    """A minimal valid plan dict matching the strict schema."""
    plan = {
        "description": "Buy GOOGL to 5%",
        "sell_rules": [],
        "buy_rules": [{
            "tickers": ["GOOGL"],
            "quantity_type": "percent_of_account",
            "quantity": 0.05,
            "allocation_method": "equal_weight",
            "skip_if_allocation_above": None,
            "buy_only_to_target": True,
            "buy_only_if_sold": None,
            "use_proceeds_from_sale": False,
            "cash_source": "available_cash",
            "sell_cash_equiv_if_needed": False,
            "min_buy_allocation": None,
        }],
        "account_filter": None,
        "cash_management": {
            "min_cash_percent": 0.02,
            "min_cash_dollars": None,
            "cash_equiv_sell_order": "largest_first",
        },
        "sells_before_buys": True,
    }
    plan.update(overrides)
    return plan


# =============================================================================
# Knowledge base
# =============================================================================

class TestSystemKnowledge:
    def test_knowledge_exists(self):
        assert len(SYSTEM_KNOWLEDGE) > 500

    def test_capabilities_summary_exists(self):
        assert len(CAPABILITIES_SUMMARY) > 50

    def test_welcome_message_exists(self):
        assert len(WELCOME_MESSAGE) > 50

    def test_knowledge_contains_key_concepts(self):
        lower = SYSTEM_KNOWLEDGE.lower()
        assert "cash floor" in lower
        assert "cash equivalent" in lower
        assert "target allocation" in lower


class TestPlanSchema:
    def test_schema_is_strict(self):
        assert EXECUTION_PLAN_SCHEMA["additionalProperties"] is False
        assert set(EXECUTION_PLAN_SCHEMA["required"]) == set(
            EXECUTION_PLAN_SCHEMA["properties"].keys())

    def test_schema_round_trips_through_execution_plan(self):
        from execution_plan import ExecutionPlan
        plan = ExecutionPlan.from_dict(make_plan_dict())
        assert plan.description == "Buy GOOGL to 5%"
        assert len(plan.buy_rules) == 1
        assert plan.buy_rules[0].tickers == ["GOOGL"]


# =============================================================================
# Setup
# =============================================================================

class TestAgentSetup:
    def test_agent_initialization(self, agent, sample_accounts, sample_buy_list):
        assert agent.accounts == sample_accounts
        assert agent.buy_list == sample_buy_list
        assert agent.should_exit is False
        assert isinstance(agent.state, ConversationState)

    def test_default_state(self):
        state = ConversationState()
        assert state.messages == []
        assert state.awaiting_confirmation is False
        assert state.pending_plan is None
        assert state.pending_orders is None


# =============================================================================
# Local commands
# =============================================================================

class TestLocalCommands:
    def test_exit_sets_flag(self, agent):
        reply = agent.chat("exit")
        assert agent.should_exit is True
        assert isinstance(reply, AgentReply)

    @pytest.mark.parametrize("word", ["quit", "bye", "goodbye"])
    def test_exit_variants(self, agent, word):
        agent.chat(word)
        assert agent.should_exit is True

    def test_help_returns_help_view(self, agent):
        assert agent.chat("help").view == "help"

    def test_holdings_view(self, agent):
        assert agent.chat("holdings").view == "holdings"
        assert agent.chat("show holdings").view == "holdings"

    def test_summary_view(self, agent):
        assert agent.chat("summary").view == "summary"

    def test_buy_list_view(self, agent):
        assert agent.chat("buy list").view == "buy_list"
        assert agent.chat("prices").view == "buy_list"

    def test_unknown_text_without_api_key(self, agent):
        reply = agent.chat("please rebalance everything")
        assert "API key" in reply.text

    def test_api_key_status_when_unset(self, agent):
        reply = agent.chat("api key")
        assert "No API key" in reply.text


# =============================================================================
# Default trade flow
# =============================================================================

class TestDefaultTrade:
    def test_default_stages_orders_for_confirmation(self, agent):
        reply = agent.chat("default")
        assert reply.needs_confirmation is True
        assert reply.preview is not None
        assert agent.state.awaiting_confirmation is True
        assert agent.state.pending_plan is not None
        plan, analyses, sells, buys = reply.preview
        assert len(buys) > 0  # GOOGL and MSFT not owned, plenty of cash

    def test_default_with_empty_buy_list(self, sample_accounts, sample_prices,
                                         sample_config):
        agent = ConversationAgent(sample_accounts, sample_prices, [], sample_config)
        agent.api_key = ""
        reply = agent.chat("default")
        assert reply.needs_confirmation is False
        assert "empty" in reply.text.lower()

    def test_confirmation_no_cancels(self, agent):
        agent.chat("default")
        reply = agent.chat("no")
        assert agent.state.awaiting_confirmation is False
        assert agent.state.pending_plan is None
        assert "dismiss" in reply.text.lower()

    def test_view_command_keeps_pending_then_confirm_button(self, agent, tmp_path):
        """Regression for the screenshot bug: typing chatter while a plan is
        staged must NOT strand it — the Confirm button still exports it."""
        folder = tmp_path / "x"
        folder.mkdir()
        agent.export_orders_callback = lambda s, b: ("x/s.csv", "x/b.csv", folder)
        agent.chat("default")
        # User types something that is neither yes/no nor a known command.
        # Without an API key this can't go to Claude, but the proposal must
        # remain staged and confirmable via the deterministic button path.
        agent.chat("hmm let me think")
        assert agent.state.awaiting_confirmation is True
        assert agent.state.pending_orders is not None
        reply = agent.confirm_pending()
        assert reply.exported is not None

    def test_confirm_pending_button(self, agent, tmp_path):
        folder = tmp_path / "x"
        folder.mkdir()
        agent.export_orders_callback = lambda s, b: ("x/s.csv", "x/b.csv", folder)
        agent.chat("default")
        reply = agent.confirm_pending()
        assert reply.exported is not None
        assert agent.state.pending_plan is None
        assert agent.state.awaiting_confirmation is False

    def test_confirm_pending_with_nothing_staged(self, agent):
        reply = agent.confirm_pending()
        assert reply.exported is None
        assert "no staged proposal" in reply.text.lower()

    def test_cancel_pending_button(self, agent):
        agent.chat("default")
        reply = agent.cancel_pending()
        assert agent.state.pending_plan is None
        assert agent.state.awaiting_confirmation is False
        assert "dismiss" in reply.text.lower()

    def test_cancel_pending_with_nothing_staged(self, agent):
        reply = agent.cancel_pending()
        assert "no staged proposal" in reply.text.lower()

    def test_confirmation_yes_exports(self, agent, tmp_path):
        exported = {}
        folder = tmp_path / "06-09-2026"
        folder.mkdir()

        def fake_export(sells, buys):
            exported["sells"], exported["buys"] = sells, buys
            return "06-09-2026/sell_order.csv", "06-09-2026/buy_order.csv", folder

        agent.export_orders_callback = fake_export
        agent.chat("default")
        reply = agent.chat("yes")

        assert reply.exported is not None
        assert reply.exported["n_buys"] == len(exported["buys"])
        assert (tmp_path / "06-09-2026" / "trade_report.txt").exists()
        assert agent.state.pending_plan is None

    def test_view_command_keeps_pending_proposal(self, agent):
        agent.chat("default")
        reply = agent.chat("show holdings")
        assert reply.view == "holdings"
        # The pending proposal must survive a harmless view command.
        assert agent.state.awaiting_confirmation is True
        assert agent.state.pending_plan is not None
        assert reply.needs_confirmation is True
        assert "still staged" in reply.text

    def test_no_key_revision_keeps_pending_proposal(self, agent):
        agent.chat("default")
        reply = agent.chat("actually make it 3 percent")  # no API key set
        assert agent.state.awaiting_confirmation is True
        assert agent.state.pending_plan is not None
        assert reply.needs_confirmation is True
        assert "API key" in reply.text

    def test_yes_still_works_after_view_command(self, agent, tmp_path):
        folder = tmp_path / "x"
        folder.mkdir()
        agent.export_orders_callback = lambda s, b: ("x/s.csv", "x/b.csv", folder)
        agent.chat("default")
        agent.chat("summary")
        reply = agent.chat("yes")
        assert reply.exported is not None


# =============================================================================
# Revision flow (#2): diff vs previous proposal
# =============================================================================

class TestDeIdentification:
    """The privacy guarantee: nothing identifying reaches the Anthropic API."""

    def _fake_anthropic(self, captured, blocks):
        """Build a fake anthropic.Anthropic that records create() kwargs."""
        from types import SimpleNamespace

        class FakeMessages:
            def create(self, **kwargs):
                captured.append(kwargs)
                return SimpleNamespace(content=blocks)

        class FakeClient:
            def __init__(self, *a, **k):
                self.messages = FakeMessages()

        return FakeClient

    def test_no_real_identity_in_payload(self, agent, monkeypatch):
        import anthropic
        from types import SimpleNamespace
        agent.api_key = "sk-test-key-long-enough-000"
        captured = []
        text_block = SimpleNamespace(type="text", text="Your total is $45,000.")
        monkeypatch.setattr(anthropic, "Anthropic",
                            self._fake_anthropic(captured, [text_block]))

        # advisor references the client by name in their own message, too
        agent.chat("what is the total for Test Client?")

        # Flatten everything sent to the API into one string.
        kw = captured[0]
        payload = repr(kw["system"]) + repr(kw["messages"])
        assert "Test Client" not in payload          # real client name absent
        assert "12345" not in payload                # real account number absent
        assert "Client-001" in payload               # token present instead
        assert "ACCT-001" in payload

    def test_model_text_is_reidentified_for_display(self, agent, monkeypatch):
        import anthropic
        from types import SimpleNamespace
        agent.api_key = "sk-test-key-long-enough-000"
        captured = []
        # model replies referring to the account by its token
        tok = agent.anon.client_token["12345"]
        reply_block = SimpleNamespace(type="text", text=f"{tok} holds $45,000.")
        monkeypatch.setattr(anthropic, "Anthropic",
                            self._fake_anthropic(captured, [reply_block]))

        reply = agent.chat("how much does my client have?")
        # the advisor sees the real name, not the token
        assert "Test Client" in reply.text
        assert tok not in reply.text


class TestScreenshotBug:
    """The reported bug: after a plan is staged, typing a non-yes/no message
    (e.g. 'hi') must not destroy it, and confirmation must still work after."""

    def test_chatter_then_confirm(self, agent, monkeypatch, tmp_path):
        from conversation_agent import AgentReply
        agent.api_key = "sk-test-key-long-enough-000"

        # Claude just chats (no tool call) — simulates answering 'hi'.
        monkeypatch.setattr(agent, "_chat_with_claude",
                            lambda text: AgentReply(
                                text="Hi! Your plan is still staged.",
                                needs_confirmation=agent.state.awaiting_confirmation))
        folder = tmp_path / "x"
        folder.mkdir()
        agent.export_orders_callback = lambda s, b: ("x/s.csv", "x/b.csv", folder)

        agent.chat("default")
        assert agent.state.awaiting_confirmation is True

        r = agent.chat("hi")  # the message that used to strand the plan
        assert agent.state.awaiting_confirmation is True   # still staged!
        assert agent.state.pending_orders is not None
        assert r.needs_confirmation is True

        # And confirming now actually exports.
        done = agent.confirm_pending()
        assert done.exported is not None

    def test_revision_replaces_plan_and_stays_confirmable(self, agent, monkeypatch):
        from conversation_agent import AgentReply
        agent.api_key = "sk-test-key-long-enough-000"
        agent.chat("default")
        first_plan = agent.state.pending_plan

        # Claude re-proposes via the real staging path.
        def fake_revision(text):
            from execution_plan import (ExecutionPlan, BuyRule, QuantityType,
                                        AllocationMethod)
            plan = ExecutionPlan(
                description="Revised: buy GOOGL to 1%",
                buy_rules=[BuyRule(tickers=["GOOGL"],
                                   quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                                   quantity=0.01,
                                   allocation_method=AllocationMethod.EQUAL_WEIGHT)])
            return agent._simulate_and_stage(plan)

        monkeypatch.setattr(agent, "_chat_with_claude", fake_revision)
        r = agent.chat("make it 1%")
        assert agent.state.pending_plan is not first_plan
        assert r.needs_confirmation is True
        assert agent.state.awaiting_confirmation is True


class TestRevisionDiff:
    def test_revision_keeps_previous_simulation_for_diff(self, agent, monkeypatch):
        from conversation_agent import AgentReply
        agent.api_key = "sk-test-key-long-enough-000"
        captured = {}

        def fake_claude(text):
            captured["last_sim"] = agent.state.last_simulation
            captured["pending"] = agent.state.pending_plan
            return AgentReply(text="revised")

        monkeypatch.setattr(agent, "_chat_with_claude", fake_claude)
        agent.chat("default")
        agent.chat("actually make it 3 percent")  # not yes/no -> revision
        # At the moment the revision goes to the model, the old simulation is
        # stashed for diffing. The staged proposal is intentionally KEPT (the
        # fix for the stranded-plan bug) so it stays confirmable if Claude only
        # answers instead of re-proposing.
        assert captured["last_sim"] is not None
        assert captured["pending"] is not None

    def test_cancel_clears_previous_simulation(self, agent):
        agent.chat("default")
        agent.chat("no")
        assert agent.state.last_simulation is None

    def test_next_proposal_carries_diff(self, agent):
        agent.chat("default")
        sells, buys, _ = agent.state.pending_orders
        agent.state.last_simulation = (sells, buys)
        agent.state.awaiting_confirmation = False
        agent.state.pending_orders = None

        # Re-propose via the tool handler, as the model would.
        plan = make_plan_dict()
        _, reply = agent._tool_propose_plan(plan)
        assert reply is not None
        assert reply.diff is not None
        assert "vs previous proposal" in reply.diff
        assert agent.state.last_simulation is None  # consumed

    def test_diff_reports_ticker_changes(self, agent):
        prev_buys = [type("O", (), {"security": "MSFT", "estimated_value": 1000.0})()]
        diff = agent._diff_simulations(([], prev_buys), ([], []))
        assert "no longer includes MSFT" in diff
        assert "buys 1→0" in diff


# =============================================================================
# Pre-flight alerts (#9) surface in replies
# =============================================================================

class TestPreflightAlerts:
    def test_reply_carries_alerts_field(self, agent):
        reply = agent.chat("default")
        assert isinstance(reply.alerts, list)

    def test_large_sell_plan_triggers_alert(self, agent):
        # Sell the whole AAPL position: 15k of a 45k account = 33%... not enough.
        # Sell AAPL and BIL: 35k of 45k = 78% -> alert.
        plan = make_plan_dict(
            description="Liquidate most of the account",
            buy_rules=[],
            sell_rules=[{
                "tickers": ["AAPL", "BIL"],
                "quantity_type": "all",
                "quantity": None,
                "priority": "largest_first",
                "min_shares_remaining": None,
                "max_percent_of_position": None,
                "account_filter": None,
            }],
        )
        result, reply = agent._tool_propose_plan(plan)
        assert reply is not None
        assert any("Large liquidation" in a for a in reply.alerts)
        assert "Pre-flight alerts" in result  # the model is told too


# =============================================================================
# Tool handlers (what the Claude loop calls)
# =============================================================================

class TestProposePlanTool:
    def test_valid_plan_stages_orders(self, agent):
        result, reply = agent._tool_propose_plan(make_plan_dict())
        assert reply is not None
        assert reply.needs_confirmation is True
        assert "buy orders" in result
        assert agent.state.awaiting_confirmation is True

    def test_unknown_buy_ticker_rejected(self, agent):
        plan = make_plan_dict()
        plan["buy_rules"][0]["tickers"] = ["ZZZTOP"]
        result, reply = agent._tool_propose_plan(plan)
        assert reply is None
        assert "ZZZTOP" in result
        assert agent.state.awaiting_confirmation is False

    def test_invalid_plan_returns_error(self, agent):
        plan = make_plan_dict()
        plan["buy_rules"][0]["quantity_type"] = "bogus_type"
        result, reply = agent._tool_propose_plan(plan)
        assert reply is None
        assert "Invalid plan" in result

    def test_plan_producing_no_orders_reports_skips(self, agent):
        # AAPL is ~33% of the account, far above the skip threshold.
        plan = make_plan_dict()
        plan["buy_rules"][0]["tickers"] = ["AAPL"]
        plan["buy_rules"][0]["skip_if_allocation_above"] = 0.02
        result, reply = agent._tool_propose_plan(plan)
        assert reply is None
        assert "ZERO orders" in result
        assert agent.state.awaiting_confirmation is False

    def test_sell_all_plan(self, agent):
        plan = make_plan_dict(
            description="Sell all AAPL",
            buy_rules=[],
            sell_rules=[{
                "tickers": ["AAPL"],
                "quantity_type": "all",
                "quantity": None,
                "priority": "largest_first",
                "min_shares_remaining": None,
                "max_percent_of_position": None,
                "account_filter": None,
            }],
        )
        result, reply = agent._tool_propose_plan(plan)
        assert reply is not None
        _, _, sells, buys = reply.preview
        assert len(sells) == 1
        assert sells[0].security == "AAPL"
        assert sells[0].shares == 100


class TestAccountDetailsTool:
    def test_lookup_by_number(self, agent):
        result = agent._tool_account_details({"account_number": "12345"})
        assert "Test Client" in result
        assert "AAPL" in result
        assert "BIL" in result

    def test_lookup_by_client_name(self, agent):
        result = agent._tool_account_details({"account_number": "Test Client"})
        assert "12345" in result

    def test_unknown_account(self, agent):
        result = agent._tool_account_details({"account_number": "99999"})
        assert "No account found" in result
        assert "12345" in result  # lists known accounts


# =============================================================================
# System prompt / context
# =============================================================================

class TestContext:
    def test_system_prompt_includes_portfolio_tokenized(self, agent):
        prompt = agent._system_prompt()
        # real identity is tokenized; tokens + buy list + structure remain
        assert "12345" not in prompt
        assert "Test Client" not in prompt
        assert agent.anon.account_token["12345"] in prompt
        assert agent.anon.client_token["12345"] in prompt
        assert "GOOGL" in prompt  # buy list (not identifying)

    def test_portfolio_context_has_totals(self, agent):
        context = agent._portfolio_context()
        assert "$45,000.00" in context  # 10k cash + 15k AAPL + 20k BIL

    def test_tools_include_plan_schema(self, agent):
        tools = agent._tools()
        plan_tool = next(t for t in tools if t["name"] == "propose_execution_plan")
        assert plan_tool["input_schema"] == EXECUTION_PLAN_SCHEMA
        # strict mode must stay off — the compiled grammar for this schema
        # exceeds the API's size limit (400: "compiled grammar is too large")
        assert "strict" not in plan_tool
