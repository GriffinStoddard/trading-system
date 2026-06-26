"""
Client de-identification for the LLM boundary.

The deterministic engine and the UI operate on real client data, but nothing
identifying is ever sent to the Anthropic API. This maps real account numbers
and client names to opaque tokens on the way OUT (system prompt, user messages,
tool results) and maps tokens back to real identities on the way IN (the plan
the model produces, and the text shown to the advisor).

Result: Claude only ever sees structure — tickers, percentages, dollar amounts,
and anonymous account/client tokens like ACCT-001 / Client-001. Account numbers
and client names never leave the machine.

What is and isn't tokenized:
- Tokenized: account numbers, client names (full name, plus a unique surname so
  a surname the advisor types is also caught).
- Left as-is: tickers (public securities), percentages, and dollar amounts —
  none of which identify a person once the name/account linkage is removed.
"""

import re


class Anonymizer:
    """Bidirectional real<->token mapper for account numbers and client names."""

    def __init__(self, accounts: dict):
        self._out: dict[str, str] = {}   # real string -> token  (outbound)
        self._in: dict[str, str] = {}    # token -> real string  (inbound)
        self.account_token: dict[str, str] = {}  # real account_num -> token
        self.client_token: dict[str, str] = {}   # real account_num -> client token

        surnames: dict[str, list] = {}   # surname_lower -> [(surname, token)]

        for i, (num, acct) in enumerate(accounts.items(), 1):
            atok = f"ACCT-{i:03d}"
            ctok = f"Client-{i:03d}"
            self.account_token[num] = atok
            self._register(num, atok)

            name = (acct.client_name or "").strip()
            self.client_token[num] = ctok if name else ""
            if name:
                self._register(name, ctok)
                parts = name.split()
                if len(parts) > 1:
                    surnames.setdefault(parts[-1].lower(), []).append((parts[-1], ctok))

        # Register a surname for OUTBOUND matching only when it's unambiguous,
        # so the advisor typing just "Killeen" still gets tokenized — but the
        # token still expands back to the full name on the way in.
        for entries in surnames.values():
            if len(entries) == 1:
                surname, ctok = entries[0]
                self._register_outbound(surname, ctok)

        out_keys = sorted(self._out, key=len, reverse=True)
        in_keys = sorted(self._in, key=len, reverse=True)
        self._out_re = re.compile(
            "|".join(re.escape(k) for k in out_keys), re.IGNORECASE) if out_keys else None
        self._in_re = re.compile(
            "|".join(re.escape(k) for k in in_keys)) if in_keys else None
        self._out_lower = {k.lower(): v for k, v in self._out.items()}

    def _register(self, real: str, token: str):
        self._out[real] = token
        self._in[token] = real

    def _register_outbound(self, real: str, token: str):
        # outbound only — does not overwrite the token's canonical real value
        self._out.setdefault(real, token)

    # ------------------------------------------------------------------
    # Text mapping
    # ------------------------------------------------------------------

    def anonymize(self, text):
        """Replace every real account number / client name with its token."""
        if not text or self._out_re is None:
            return text
        return self._out_re.sub(
            lambda m: self._out_lower.get(m.group(0).lower(), m.group(0)), text)

    def deanonymize(self, text):
        """Replace every token with its real account number / client name."""
        if not text or self._in_re is None:
            return text
        return self._in_re.sub(lambda m: self._in.get(m.group(0), m.group(0)), text)

    # ------------------------------------------------------------------
    # Plan mapping — de-tokenize the identity fields of account filters so the
    # deterministic engine receives real account numbers / client names.
    # ------------------------------------------------------------------

    _FILTER_ID_FIELDS = ("account_numbers", "client_name_contains", "exclude_client_names")

    def deanonymize_plan(self, plan: dict) -> dict:
        """Return the plan dict with account-filter identity fields de-tokenized."""
        def fix(f):
            if isinstance(f, dict):
                for key in self._FILTER_ID_FIELDS:
                    vals = f.get(key)
                    if isinstance(vals, list):
                        f[key] = [self.deanonymize(str(v)) for v in vals]

        fix(plan.get("account_filter"))
        for group in ("sell_rules", "buy_rules"):
            for rule in plan.get(group, []) or []:
                if isinstance(rule, dict):
                    fix(rule.get("account_filter"))
        return plan
