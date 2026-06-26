"""Tests for the client de-identification layer."""

import pytest

from anonymizer import Anonymizer
from models import Account


@pytest.fixture
def anon():
    accounts = {
        "4543-8088": Account(account_num="4543-8088", client_name="Linda Johnson"),
        "7952-2709": Account(account_num="7952-2709", client_name="Sarah Thomas"),
        "3954-4883": Account(account_num="3954-4883", client_name="Virginia Killeen"),
    }
    return Anonymizer(accounts)


class TestTokens:
    def test_each_account_gets_distinct_tokens(self, anon):
        toks = set(anon.account_token.values())
        assert len(toks) == 3
        assert all(t.startswith("ACCT-") for t in toks)
        ctoks = set(anon.client_token.values())
        assert len(ctoks) == 3
        assert all(t.startswith("Client-") for t in ctoks)


class TestAnonymize:
    def test_replaces_account_number(self, anon):
        out = anon.anonymize("sell all in 4543-8088")
        assert "4543-8088" not in out
        assert anon.account_token["4543-8088"] in out

    def test_replaces_full_client_name(self, anon):
        out = anon.anonymize("raise cash for Linda Johnson")
        assert "Linda Johnson" not in out
        assert anon.client_token["4543-8088"] in out

    def test_replaces_unique_surname(self, anon):
        # "Killeen" is a unique surname -> should tokenize
        out = anon.anonymize("don't sell PRWCX for Killeen")
        assert "Killeen" not in out
        assert anon.client_token["3954-4883"] in out

    def test_case_insensitive_name(self, anon):
        out = anon.anonymize("raise cash for linda johnson")
        assert "linda johnson" not in out.lower().replace(
            anon.client_token["4543-8088"].lower(), "")

    def test_leaves_tickers_and_dollars_alone(self, anon):
        out = anon.anonymize("sell all LUMN and raise $50,000")
        assert "LUMN" in out
        assert "$50,000" in out


class TestDeanonymize:
    def test_round_trip_account(self, anon):
        tok = anon.account_token["4543-8088"]
        assert anon.deanonymize(f"order in {tok}") == "order in 4543-8088"

    def test_token_expands_to_full_name_even_from_surname(self, anon):
        # advisor typed surname -> token -> expands back to the FULL name
        tok = anon.anonymize("for Killeen").split()[-1]
        assert anon.deanonymize(tok) == "Virginia Killeen"

    def test_text_with_no_tokens_unchanged(self, anon):
        assert anon.deanonymize("just some text") == "just some text"


class TestDeanonymizePlan:
    def test_detokenizes_account_filter_fields(self, anon):
        plan = {
            "account_filter": {
                "client_name_contains": [anon.client_token["4543-8088"]],
                "account_numbers": [anon.account_token["7952-2709"]],
                "exclude_client_names": [anon.client_token["3954-4883"]],
            },
            "sell_rules": [{
                "account_filter": {
                    "client_name_contains": [anon.client_token["7952-2709"]],
                },
            }],
            "buy_rules": [],
        }
        fixed = anon.deanonymize_plan(plan)
        assert fixed["account_filter"]["client_name_contains"] == ["Linda Johnson"]
        assert fixed["account_filter"]["account_numbers"] == ["7952-2709"]
        assert fixed["account_filter"]["exclude_client_names"] == ["Virginia Killeen"]
        assert fixed["sell_rules"][0]["account_filter"]["client_name_contains"] == ["Sarah Thomas"]

    def test_tolerates_missing_filters(self, anon):
        plan = {"sell_rules": [{}], "buy_rules": [{}], "account_filter": None}
        anon.deanonymize_plan(plan)  # must not raise


def test_empty_accounts_is_noop():
    anon = Anonymizer({})
    assert anon.anonymize("Linda Johnson 4543-8088") == "Linda Johnson 4543-8088"
    assert anon.deanonymize("ACCT-001") == "ACCT-001"
