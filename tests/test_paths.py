"""Tests for the data-location layer (paths.py) and legacy migration."""

import json

import pytest

import paths
import config as config_module


class TestUserDataDir:
    def test_isolated_and_created(self, _isolate_user_dirs):
        d = paths.user_data_dir()
        assert d.exists()
        assert d == _isolate_user_dirs

    def test_config_lands_in_user_data_dir(self, _isolate_user_dirs):
        cfg = config_module.load_config()  # creates the default file
        assert (paths.user_data_dir() / "config.json").exists()
        assert cfg["investment_data_path"] == ""


class TestInvestmentDataPath:
    def test_unset_and_no_legacy_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "legacy_data_dir", lambda: tmp_path / "empty")
        assert config_module.get_investment_data_path() is None

    def test_set_and_get_roundtrip(self, tmp_path):
        xlsx = tmp_path / "my_data.xlsx"
        xlsx.write_bytes(b"x")
        assert config_module.set_investment_data_path(str(xlsx)) is True
        assert config_module.get_investment_data_path() == xlsx.resolve()

    def test_legacy_fallback_when_unset(self, tmp_path, monkeypatch):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        (legacy / "investment_data.xlsx").write_bytes(b"x")
        monkeypatch.setattr(paths, "legacy_data_dir", lambda: legacy)
        assert config_module.get_investment_data_path() == \
            legacy / "investment_data.xlsx"


class TestExportsDir:
    def test_default(self):
        assert config_module.get_exports_dir() == paths.default_exports_dir()

    def test_config_override(self, tmp_path):
        cfg = config_module.load_config()
        cfg["exports_dir"] = str(tmp_path / "custom")
        config_module.save_config(cfg)
        assert config_module.get_exports_dir() == tmp_path / "custom"


class TestMigration:
    @pytest.fixture
    def legacy(self, tmp_path, monkeypatch):
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        monkeypatch.setattr(paths, "legacy_data_dir", lambda: legacy)
        return legacy

    def test_migrates_config_and_prices(self, legacy):
        (legacy / "config.json").write_text(json.dumps(
            {"anthropic_api_key": "sk-real-key-1234567890abc",
             "default_excel_file": "investment_data.xlsx"}))
        (legacy / "stock_prices.csv").write_text("TICKER,PRICE\nAAPL,150.0\n")
        (legacy / "investment_data.xlsx").write_bytes(b"x")

        notes = paths.migrate_legacy_files()
        assert len(notes) == 3  # config, prices, excel path

        target = paths.user_data_dir()
        assert (target / "stock_prices.csv").exists()
        migrated = json.loads((target / "config.json").read_text())
        assert migrated["anthropic_api_key"] == "sk-real-key-1234567890abc"
        assert migrated["investment_data_path"] == \
            str((legacy / "investment_data.xlsx").resolve())
        # Originals stay put (copy, not move).
        assert (legacy / "config.json").exists()

    def test_migration_never_overwrites_existing(self, legacy):
        (paths.user_data_dir() / "config.json").write_text(
            json.dumps({"anthropic_api_key": "sk-current-key-9999999999",
                        "investment_data_path": "/already/set.xlsx"}))
        (legacy / "config.json").write_text(
            json.dumps({"anthropic_api_key": "sk-old-key"}))

        paths.migrate_legacy_files()
        kept = json.loads((paths.user_data_dir() / "config.json").read_text())
        assert kept["anthropic_api_key"] == "sk-current-key-9999999999"
        assert kept["investment_data_path"] == "/already/set.xlsx"

    def test_nothing_to_migrate(self, legacy):
        assert paths.migrate_legacy_files() == []

    def test_noop_when_legacy_equals_target(self, monkeypatch):
        monkeypatch.setattr(paths, "legacy_data_dir", paths.user_data_dir)
        assert paths.migrate_legacy_files() == []
