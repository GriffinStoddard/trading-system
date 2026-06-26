"""Tests for order export — same-day exports must never overwrite each other."""

import pandas as pd
import pytest

import main as main_module
from main import export_orders
from order_generator import Order


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "get_exports_dir", lambda: tmp_path)
    return tmp_path


def make_order(action="Buy", ticker="AAPL", shares=10):
    return Order(account_num="A1", client_name="Pat", security=ticker,
                 action=action, shares=shares, estimated_value=shares * 100.0)


class TestExportOrders:
    def test_first_export_uses_date_folder(self, base):
        sell_file, buy_file, folder = export_orders([make_order("Sell")], [make_order()])
        assert folder.parent == base
        assert "_" not in folder.name  # plain MM-DD-YYYY
        assert (folder / "sell_order.csv").exists()
        assert (folder / "buy_order.csv").exists()
        assert sell_file == f"{folder.name}/sell_order.csv"

    def test_second_export_same_day_does_not_overwrite(self, base):
        _, _, first = export_orders([], [make_order(shares=10)])
        # Simulate the report the agent writes alongside the CSVs.
        (first / "trade_report.txt").write_text("report 1")

        _, _, second = export_orders([], [make_order(shares=99)])
        assert second != first
        assert second.name.startswith(first.name)  # date prefix + timestamp

        # The morning's files are intact.
        df_first = pd.read_csv(first / "buy_order.csv")
        assert df_first["Share Quantity"].tolist() == [10]
        df_second = pd.read_csv(second / "buy_order.csv")
        assert df_second["Share Quantity"].tolist() == [99]
        assert (first / "trade_report.txt").read_text() == "report 1"

    def test_account_numbers_have_no_hyphens(self, base):
        """Broker upload needs bare account numbers — display hyphens are stripped."""
        order = Order(account_num="2527-3072", client_name="Pat", security="AAPL",
                      action="Buy", shares=5, estimated_value=500.0)
        _, _, folder = export_orders([order], [order])
        for name in ("sell_order.csv", "buy_order.csv"):
            df = pd.read_csv(folder / name, dtype=str)
            assert df["Account Number"].tolist() == ["25273072"]

    def test_empty_orders_still_write_headers(self, base):
        _, _, folder = export_orders([], [])
        df = pd.read_csv(folder / "sell_order.csv")
        assert list(df.columns) == ["Account Number", "Security", "Action",
                                    "Share Quantity", "Dollar Amount"]
        assert len(df) == 0
