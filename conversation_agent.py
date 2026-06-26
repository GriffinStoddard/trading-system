"""
Conversation Agent — single tool-use agent loop.

One Claude conversation drives everything: questions are answered directly from
the system prompt context, and trade requests become `propose_execution_plan`
tool calls whose input is a strict JSON schema — so every plan is structurally
valid before it reaches the deterministic order generator.

Trades are never executed by the model. A proposed plan is simulated, previewed
to the user, and only exported after an explicit local yes/no confirmation.
"""

import json
from dataclasses import dataclass, field
from typing import Optional

from models import Account
from execution_plan import (
    ExecutionPlan, BuyRule, CashManagement,
    QuantityType, AllocationMethod, CashSource,
)
from order_generator import OrderGenerator
from report_generator import generate_summary_report
from plan_schema import EXECUTION_PLAN_SCHEMA, PLAN_GUIDANCE
from system_knowledge import SYSTEM_KNOWLEDGE
from config import get_api_key, get_cash_equivalents

DEFAULT_MODEL = "claude-opus-4-8"
MAX_AGENT_TURNS = 8

YES_WORDS = {"yes", "y", "yeah", "yep", "sure", "ok", "okay", "proceed",
             "do it", "confirm", "go ahead"}
NO_WORDS = {"no", "n", "nope", "cancel", "stop", "nevermind", "never mind", "abort"}


@dataclass
class AgentReply:
    """Structured reply that main.py renders with the UI layer."""
    text: str = ""
    view: Optional[str] = None          # 'summary' | 'holdings' | 'buy_list' | 'help'
    preview: Optional[tuple] = None     # (plan, analyses, sell_orders, buy_orders)
    exported: Optional[dict] = None     # {'folder', 'n_sells', 'n_buys'}
    needs_confirmation: bool = False
    alerts: list = field(default_factory=list)   # pre-flight sanity check alerts
    diff: Optional[str] = None          # change summary vs the previous proposal


@dataclass
class ConversationState:
    """Tracks multi-turn conversation context."""
    messages: list = field(default_factory=list)       # API-format message history
    awaiting_confirmation: bool = False
    pending_plan: Optional[ExecutionPlan] = None
    pending_orders: Optional[tuple] = None             # (sell_orders, buy_orders, analyses)
    last_simulation: Optional[tuple] = None            # (sell_orders, buy_orders) being revised


class ConversationAgent:
    """Conversational front-end over the deterministic order generator."""

    def __init__(
        self,
        accounts: dict[str, Account],
        stock_prices: dict[str, float],
        buy_list: list[str],
        config: dict,
    ):
        self.accounts = accounts
        self.stock_prices = stock_prices
        self.buy_list = buy_list
        self.config = config
        self.state = ConversationState()
        self.should_exit = False
        self.api_key = get_api_key()
        self.model = config.get("model", DEFAULT_MODEL)
        self.cash_equivalents = config.get("cash_equivalents") or get_cash_equivalents()
        self.export_orders_callback = None
        # De-identifies everything sent to the Anthropic API: account numbers and
        # client names become opaque tokens (ACCT-001 / Client-001) on the way
        # out, and are mapped back locally on the way in.
        from anonymizer import Anonymizer
        self.anon = Anonymizer(accounts)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def chat(self, user_input: str) -> AgentReply:
        text = user_input.strip()
        if not text:
            return AgentReply()

        if self.state.awaiting_confirmation:
            reply = self._handle_confirmation(text)
            if reply is not None:
                return reply
            # Not a typed yes/no. Local commands (views, help) run WITHOUT
            # touching the pending proposal.
            local = self.handle_command(text)
            if local is not None:
                if local.preview is None and not self.should_exit:
                    local.needs_confirmation = True
                    local.text = ((local.text + "\n\n") if local.text else "") + (
                        "Your proposed trades are still staged — confirm or "
                        "dismiss them on the plan card above.")
                return local
            if not self.api_key:
                return AgentReply(
                    text=("I need an Anthropic API key to revise the proposal — "
                          "it's still staged. Confirm or dismiss it on the plan "
                          "card above, or add a key to enable revisions."),
                    needs_confirmation=True)
            # A typed message while a plan is staged is a revision request or a
            # question. Stash the current simulation so a NEW plan can be diffed
            # against it, but do NOT discard the staged proposal: if Claude only
            # answers (or re-proposes), the staged plan stays confirmable until
            # the user acts on it via the buttons.
            if self.state.pending_orders:
                sells, buys, _ = self.state.pending_orders
                self.state.last_simulation = (sells, buys)
            return self._chat_with_claude(text)

        local = self.handle_command(text)
        if local is not None:
            return local

        if not self.api_key:
            return AgentReply(text=(
                "I need an Anthropic API key for natural-language requests. "
                "Add one in Settings (desktop app) or config.json (terminal). "
                "The `default` specification works without a key."))

        return self._chat_with_claude(text)

    # ------------------------------------------------------------------
    # Local commands (instant, no API call)
    # ------------------------------------------------------------------

    def handle_command(self, text: str) -> Optional[AgentReply]:
        lower = text.lower().strip().rstrip("?!.")

        if lower in ("exit", "quit", "bye", "goodbye"):
            self.should_exit = True
            return AgentReply(text="Goodbye!")

        if lower in ("help", "commands", "what can you do"):
            return AgentReply(view="help")

        if lower in ("holdings", "show holdings", "view holdings", "positions",
                     "show positions"):
            return AgentReply(view="holdings")

        if lower in ("summary", "show summary", "overview", "accounts",
                     "show accounts"):
            return AgentReply(view="summary")

        if lower in ("buy list", "buylist", "show buy list", "prices",
                     "show prices"):
            return AgentReply(view="buy_list")

        if lower in ("default", "use default", "run default",
                     "use default specification", "use the default"):
            return self._execute_default_trade()

        if lower in ("api key", "set api key", "check api key"):
            return self._api_key_status()

        return None

    def _api_key_status(self) -> AgentReply:
        if self.api_key:
            masked = self.api_key[:10] + "..." + self.api_key[-4:]
            return AgentReply(text=(
                f"API key configured: `{masked}`\n\n"
                "To change it, use Settings (desktop app) or edit "
                "`anthropic_api_key` in config.json (terminal)."))
        return AgentReply(text=(
            "No API key configured. Add one in Settings (desktop app) or in "
            "config.json (get a key at https://console.anthropic.com/). "
            "Until then, `default` still works without a key."))

    # ------------------------------------------------------------------
    # Confirmation flow (deterministic — no LLM)
    # ------------------------------------------------------------------

    def _handle_confirmation(self, text: str) -> Optional[AgentReply]:
        lower = text.lower().strip().rstrip("!.")
        if lower in YES_WORDS:
            return self.confirm_pending()
        if lower in NO_WORDS:
            return self.cancel_pending()
        # Anything else: not a typed confirmation. chat() decides whether it's a
        # harmless local command or a revision — the staged plan stays put.
        return None

    def confirm_pending(self) -> AgentReply:
        """Confirm and export the staged proposal — deterministic, no LLM.

        The GUI Confirm button calls this directly, so confirmation can never be
        lost to the chat flow (the bug where typing anything but 'yes' stranded
        the plan).
        """
        if not self.state.awaiting_confirmation or not self.state.pending_orders:
            return AgentReply(text="There's no staged proposal to confirm.")
        self.state.awaiting_confirmation = False
        return self._export_pending()

    def cancel_pending(self) -> AgentReply:
        """Discard the staged proposal without exporting — deterministic."""
        if not (self.state.awaiting_confirmation or self.state.pending_orders):
            return AgentReply(text="There's no staged proposal to dismiss.")
        self.state.awaiting_confirmation = False
        self.state.pending_plan = None
        self.state.pending_orders = None
        self.state.last_simulation = None
        self._note_to_model(
            "The user dismissed the proposed trades. Nothing was exported.")
        return AgentReply(text=(
            "Dismissed — nothing was written. Tell me what to change, or start "
            "a new request."))

    def _export_pending(self) -> AgentReply:
        if not self.state.pending_orders:
            return AgentReply(text="There's nothing pending to export.")

        sell_orders, buy_orders, analyses = self.state.pending_orders
        plan = self.state.pending_plan
        self.state.pending_plan = None
        self.state.pending_orders = None

        if not sell_orders and not buy_orders:
            return AgentReply(text=(
                "No orders were generated — every ticker was skipped "
                "(already at target, above the skip threshold, or below the "
                "minimum buy size)."))

        if not self.export_orders_callback:
            return AgentReply(text="Export callback is not configured — files were not saved.")

        sell_file, buy_file, folder = self.export_orders_callback(sell_orders, buy_orders)

        report = generate_summary_report(
            analyses, sell_orders, buy_orders, plan.description, sell_file, buy_file)
        with open(folder / "trade_report.txt", "w", encoding="utf-8") as f:
            f.write(report)

        self._note_to_model(
            f"The user confirmed. Orders were exported to '{folder}' "
            f"({len(sell_orders)} sells, {len(buy_orders)} buys).")

        return AgentReply(exported={
            "folder": str(folder),
            "n_sells": len(sell_orders),
            "n_buys": len(buy_orders),
        })

    def _note_to_model(self, note: str):
        """Keep the model's conversation history in sync with local actions."""
        if self.state.messages:
            self.state.messages.append(
                {"role": "user", "content": f"[system note: {note}]"})

    # ------------------------------------------------------------------
    # Default specification (works without an API key)
    # ------------------------------------------------------------------

    def _execute_default_trade(self) -> AgentReply:
        if not self.buy_list:
            return AgentReply(text=(
                "The buy list is empty — add tickers first (`add TICKER PRICE`)."))

        target = self.config.get("default_target_allocation_percent", 0.025)
        skip_above = self.config.get("default_skip_if_above_percent", 0.02)
        cash_floor = self.config.get("default_cash_floor_percent", 0.02)
        min_buy = self.config.get("default_min_buy_percent", 0.01)

        plan = ExecutionPlan(
            description=(
                f"Buy to {target * 100:g}% target per stock, skip if >= "
                f"{skip_above * 100:g}% owned, skip buys under {min_buy * 100:g}%, "
                f"sell cash equivalents if needed, keep {cash_floor * 100:g}% cash"),
            buy_rules=[BuyRule(
                tickers=self.buy_list,
                quantity_type=QuantityType.PERCENT_OF_ACCOUNT,
                quantity=target,
                allocation_method=AllocationMethod.EQUAL_WEIGHT,
                skip_if_allocation_above=skip_above,
                buy_only_to_target=True,
                cash_source=CashSource.CASH_EQUIVALENTS,
                sell_cash_equiv_if_needed=True,
                min_buy_allocation=min_buy,
            )],
            cash_management=CashManagement(
                min_cash_percent=cash_floor,
                cash_equiv_sell_order="largest_first",
            ),
        )
        return self._simulate_and_stage(plan, intro="Using the default specification.")

    def _simulate_and_stage(self, plan: ExecutionPlan, intro: str = "") -> AgentReply:
        """Run a plan through the deterministic engine and stage it for confirmation."""
        from sanity_checks import run_sanity_checks

        generator = OrderGenerator(self.accounts, self.stock_prices)
        sell_orders, buy_orders = generator.execute_plan(plan)
        analyses = generator.get_analyses()

        if not sell_orders and not buy_orders:
            return AgentReply(text=(
                (intro + "\n\n" if intro else "") +
                "No orders would be generated — every ticker was skipped "
                "(already at target, above the skip threshold, or below the "
                "minimum buy size)."))

        alerts = run_sanity_checks(
            self.accounts, sell_orders, buy_orders, self.stock_prices, analyses)

        diff = None
        if self.state.last_simulation is not None:
            diff = self._diff_simulations(
                self.state.last_simulation, (sell_orders, buy_orders))
            self.state.last_simulation = None

        self.state.pending_plan = plan
        self.state.pending_orders = (sell_orders, buy_orders, analyses)
        self.state.awaiting_confirmation = True

        return AgentReply(
            text=intro,
            preview=(plan, analyses, sell_orders, buy_orders),
            needs_confirmation=True,
            alerts=alerts,
            diff=diff,
        )

    @staticmethod
    def _diff_simulations(previous: tuple, current: tuple) -> str:
        """One-line change summary between two staged simulations."""
        prev_sells, prev_buys = previous
        cur_sells, cur_buys = current

        def total(orders):
            return sum(o.estimated_value for o in orders)

        def delta(label, prev_orders, cur_orders):
            d_count = len(cur_orders) - len(prev_orders)
            d_value = total(cur_orders) - total(prev_orders)
            return (f"{label} {len(prev_orders)}→{len(cur_orders)} "
                    f"({d_count:+d} orders, {'+' if d_value >= 0 else '−'}"
                    f"${abs(d_value):,.0f})")

        prev_tickers = {o.security for o in prev_sells + prev_buys}
        cur_tickers = {o.security for o in cur_sells + cur_buys}
        parts = [
            delta("sells", prev_sells, cur_sells),
            delta("buys", prev_buys, cur_buys),
        ]
        added = sorted(cur_tickers - prev_tickers)
        removed = sorted(prev_tickers - cur_tickers)
        if added:
            parts.append(f"now includes {', '.join(added)}")
        if removed:
            parts.append(f"no longer includes {', '.join(removed)}")
        return "vs previous proposal: " + "; ".join(parts)

    # ------------------------------------------------------------------
    # Claude agent loop
    # ------------------------------------------------------------------

    def _chat_with_claude(self, text: str) -> AgentReply:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        # Tokenize the advisor's message before it enters the model channel,
        # in case they typed a client name or account number.
        self.state.messages.append(
            {"role": "user", "content": self.anon.anonymize(text)})

        proposed: Optional[AgentReply] = None
        final_text = ""

        try:
            for _ in range(MAX_AGENT_TURNS):
                response = client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    system=[{
                        "type": "text",
                        "text": self._system_prompt(),
                        "cache_control": {"type": "ephemeral"},
                    }],
                    tools=self._tools(),
                    messages=self.state.messages,
                )

                self.state.messages.append(
                    {"role": "assistant", "content": response.content})

                tool_uses = [b for b in response.content if b.type == "tool_use"]
                if not tool_uses:
                    final_text = "".join(
                        b.text for b in response.content if b.type == "text")
                    break

                results = []
                for tool in tool_uses:
                    if tool.name == "propose_execution_plan":
                        result_text, reply = self._tool_propose_plan(tool.input)
                        if reply is not None:
                            proposed = reply
                    elif tool.name == "get_account_details":
                        result_text = self._tool_account_details(tool.input)
                    else:
                        result_text = f"Unknown tool: {tool.name}"
                    # Tool results (e.g. pre-flight alerts naming an account,
                    # account-detail dumps) are the other identity leak point —
                    # tokenize before they go back to the model.
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": tool.id,
                        "content": self.anon.anonymize(result_text),
                    })
                self.state.messages.append({"role": "user", "content": results})
            else:
                final_text = "I wasn't able to finish that — please try rephrasing."

        except anthropic.AuthenticationError:
            self.state.messages.pop()  # drop the failed user turn
            return AgentReply(text=(
                "Your API key was rejected. Check `anthropic_api_key` in config.json."))
        except anthropic.RateLimitError:
            return AgentReply(text="Rate limited by the API — wait a moment and try again.")
        except anthropic.APIConnectionError:
            return AgentReply(text="Couldn't reach the Anthropic API — check your internet connection.")
        except anthropic.APIStatusError as e:
            return AgentReply(text=f"API error ({e.status_code}): {e.message}")

        # The model speaks in tokens; map them back to real names/numbers for
        # the advisor. (History keeps the tokenized form for the next turn.)
        final_text = self.anon.deanonymize(final_text)

        if proposed is not None:
            proposed.text = final_text or proposed.text
            return proposed
        # No new plan was staged this turn, so drop any diff baseline we stashed
        # for a revision. The staged proposal (if any) is untouched and still
        # confirmable; tell the UI to keep its confirm affordances.
        self.state.last_simulation = None
        return AgentReply(text=final_text or "(no response)",
                          needs_confirmation=self.state.awaiting_confirmation)

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def _tools(self) -> list:
        return [
            {
                "name": "propose_execution_plan",
                "description": (
                    "Propose a trade execution plan for the advisor's request. "
                    "Call this whenever the user asks to generate, change, or "
                    "re-run trades. The plan is simulated deterministically and "
                    "previewed to the user for confirmation — it is never "
                    "executed directly. If the simulation result doesn't match "
                    "the user's intent, call this again with a corrected plan."),
                # Not strict: the compiled grammar for this schema exceeds the
                # API's size limit. The handler validates via from_dict() and
                # feeds errors back so the model can self-correct.
                "input_schema": EXECUTION_PLAN_SCHEMA,
            },
            {
                "name": "get_account_details",
                "description": (
                    "Get full position-level detail for one account. Call this "
                    "when the user asks about a specific account or client and "
                    "the summary context isn't enough."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "account_number": {
                            "type": "string",
                            "description": "Account number, e.g. '4543-8088'",
                        },
                    },
                    "required": ["account_number"],
                    "additionalProperties": False,
                },
            },
        ]

    def _tool_propose_plan(self, plan_dict: dict) -> tuple[str, Optional[AgentReply]]:
        """Simulate a proposed plan. Returns (tool_result_text, staged_reply)."""
        try:
            # The model expresses account/client filters in tokens; map them
            # back to real values so the deterministic engine can match.
            plan = ExecutionPlan.from_dict(
                self.anon.deanonymize_plan(dict(plan_dict)))
        except Exception as e:
            return f"Invalid plan: {e}. Fix the plan and call the tool again.", None

        # Validate buy tickers against the price list before simulating.
        missing = sorted({
            t.upper() for rule in plan.buy_rules for t in rule.tickers
            if t.upper() not in self.stock_prices
        })
        if missing:
            return (
                f"These buy tickers have no price and cannot be bought: "
                f"{', '.join(missing)}. Only tickers on the buy list "
                f"({', '.join(self.buy_list)}) can be bought. "
                "Adjust the plan or tell the user the ticker needs a price first.",
                None,
            )

        reply = self._simulate_and_stage(plan)
        if reply.preview is None:
            # Simulation produced no orders — report back so the model can explain.
            self.state.awaiting_confirmation = False
            return (
                "Simulation produced ZERO orders. Reasons per ticker:\n"
                + self._skip_reasons() +
                "\nExplain this to the user briefly. Do not call the tool again "
                "unless they change the request.",
                None,
            )

        _, analyses, sell_orders, buy_orders = reply.preview
        sell_total = sum(o.estimated_value for o in sell_orders)
        buy_total = sum(o.estimated_value for o in buy_orders)
        warnings = [
            f"{a.account_num}"
            + (f" ({a.client_name})" if a.client_name else "")
            + f": {w}"
            for a in analyses for w in a.warnings
        ]
        summary = (
            f"Simulation complete: {len(analyses)} accounts, "
            f"{len(sell_orders)} sell orders (${sell_total:,.0f}), "
            f"{len(buy_orders)} buy orders (${buy_total:,.0f})."
            + (f"\nChange summary: {reply.diff}" if reply.diff else "")
            + (f"\nPre-flight alerts: {'; '.join(reply.alerts)}" if reply.alerts else "")
            + (f"\nWarnings: {'; '.join(warnings[:8])}" if warnings else "")
            + "\nThe full preview is shown to the user on a plan card with "
            "Confirm and Request-changes buttons. Reply with a one-to-two "
            "sentence summary of what the plan does — mention any pre-flight "
            "alerts — and invite them to review and confirm it on the card "
            "(or tell you what to change). Do not repeat the order table and "
            "do not claim it is confirmed."
        )
        return summary, reply

    def _skip_reasons(self) -> str:
        lines = []
        # Use the most recent simulation's analyses if present.
        if self.state.pending_orders:
            analyses = self.state.pending_orders[2]
        else:
            analyses = []
        seen = set()
        for a in analyses:
            for ta in a.ticker_analysis:
                key = (ta.ticker, ta.reason)
                if ta.action == "SKIP" and key not in seen:
                    seen.add(key)
                    lines.append(f"- {ta.ticker}: {ta.reason}")
        return "\n".join(lines) if lines else "- (no per-ticker detail available)"

    def _tool_account_details(self, tool_input: dict) -> str:
        # The model passes a token (ACCT-001 / Client-001); map back to real.
        # The returned text is tokenized again at the send boundary.
        num = self.anon.deanonymize(str(tool_input.get("account_number", "")).strip())
        account = self.accounts.get(num)
        if account is None:
            # Try a fuzzy match on client name too.
            for acct in self.accounts.values():
                if num.lower() in (acct.client_name or "").lower():
                    account = acct
                    break
        if account is None:
            return (f"No account found for '{num}'. Known accounts: "
                    f"{', '.join(self.accounts.keys())}")

        total = account.get_total_value()
        lines = [
            f"Account {account.account_num} ({account.client_name}): "
            f"${total:,.2f} total, ${account.cash:,.2f} cash",
            "Holdings:",
        ]
        for h in account.holdings:
            alloc = (h.market_value or 0) / total * 100 if total else 0
            lines.append(f"  {h.symbol}: {h.shares:,.0f} sh @ ${h.price or 0:,.2f} "
                         f"= ${h.market_value or 0:,.2f} ({alloc:.1f}%)")
        if account.cash_equivalents:
            lines.append("Cash equivalents:")
            for ce in account.cash_equivalents:
                alloc = (ce.market_value or 0) / total * 100 if total else 0
                lines.append(f"  {ce.symbol}: {ce.shares:,.0f} sh = "
                             f"${ce.market_value or 0:,.2f} ({alloc:.1f}%)")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def _system_prompt(self) -> str:
        return (
            "You are the assistant inside a trading order generation tool used by "
            "a financial advisor. You help in two ways:\n"
            "1. Trade requests: translate the advisor's instructions into an "
            "execution plan via the propose_execution_plan tool. All math is done "
            "by deterministic code — you only express intent in the plan.\n"
            "2. Questions: answer from the knowledge base and portfolio context "
            "below, using real numbers from the data when helpful.\n\n"
            "Be concise and professional. Never invent tickers, prices, or "
            "account data. If a request is ambiguous in a way that changes the "
            "trades (amount, which accounts, which tickers), ask one short "
            "clarifying question instead of guessing.\n\n"
            "PRIVACY: For client confidentiality, account numbers and client "
            "names are shown to you only as anonymized tokens (e.g. ACCT-001, "
            "Client-001) — you never see real identities. Refer to accounts and "
            "clients by these tokens; the app maps them back to the real names "
            "for the advisor. In account filters (account_numbers, "
            "client_name_contains, exclude_client_names), use the exact tokens "
            "you were given.\n\n"
            "If the user asks to modify a previously proposed plan (e.g. 'make "
            "it 3%', 'leave out the Smith accounts'), call "
            "propose_execution_plan again with the complete revised plan — "
            "keep everything from the previous plan that they didn't ask to "
            "change.\n\n"
            "IMPORTANT — confirmation is handled by the app, not by you. While "
            "a plan is staged, a bar is pinned at the bottom of the screen with "
            "'View full plan', 'Confirm & export', and 'Discard' buttons; the "
            "full order table also opens from there. Never claim a plan is "
            "confirmed, approved, executed, or exported, and never say you "
            "cannot show the plan — if the user asks to see it, tell them to "
            "click 'View full plan' on the staged-plan bar. When a plan is "
            "already staged and the user types something, either revise it "
            "(call the tool again) or answer their question — the staged plan "
            "stays pinned for them to confirm. Do not say you have done "
            "anything to the orders.\n\n"
            f"{PLAN_GUIDANCE}\n\n"
            f"## Knowledge base\n{SYSTEM_KNOWLEDGE}\n\n"
            f"## Cash equivalents\n{', '.join(self.cash_equivalents)}\n\n"
            f"## Buy list (only these tickers can be bought)\n{self._buy_list_context()}\n\n"
            f"## Portfolio\n{self._portfolio_context()}"
        )

    def _buy_list_context(self) -> str:
        if not self.buy_list:
            return "(empty)"
        return "\n".join(
            f"{t}: ${self.stock_prices.get(t, 0):,.2f}" for t in self.buy_list)

    def _portfolio_context(self) -> str:
        lines = []
        total_all = 0.0
        for num, acct in self.accounts.items():
            total = acct.get_total_value()
            total_all += total
            # Account numbers and client names are tokenized — Claude never sees
            # real identities. Tickers/percentages/dollars are not identifying.
            atok = self.anon.account_token.get(num, num)
            ctok = self.anon.client_token.get(num, "")
            name = f" ({ctok})" if ctok else ""
            cash_pct = acct.cash / total * 100 if total else 0
            lines.append(f"Account {atok}{name}: ${total:,.2f} total, "
                         f"${acct.cash:,.2f} cash ({cash_pct:.1f}%)")
            holdings = ", ".join(
                f"{h.symbol} {((h.market_value or 0) / total * 100 if total else 0):.1f}%"
                for h in acct.holdings)
            if holdings:
                lines.append(f"  holdings: {holdings}")
            ces = ", ".join(
                f"{ce.symbol} ${ce.market_value or 0:,.0f}"
                for ce in acct.cash_equivalents)
            if ces:
                lines.append(f"  cash equivalents: {ces}")
        lines.append(f"\nTotal across {len(self.accounts)} accounts: ${total_all:,.2f}")
        return "\n".join(lines)
