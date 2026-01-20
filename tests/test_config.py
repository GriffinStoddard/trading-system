"""
Tests for config.py - Configuration management.
"""

import pytest
import json
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    DEFAULT_CONFIG, get_config_path, load_config, save_config,
    get_api_key, set_api_key
)


class TestDefaultConfig:
    """Tests for DEFAULT_CONFIG constant."""

    def test_default_config_has_api_key(self):
        """DEFAULT_CONFIG has anthropic_api_key field."""
        assert "anthropic_api_key" in DEFAULT_CONFIG
        assert DEFAULT_CONFIG["anthropic_api_key"] == ""

    def test_default_config_has_file_paths(self):
        """DEFAULT_CONFIG has default file paths."""
        assert "default_excel_file" in DEFAULT_CONFIG
        assert "default_prices_file" in DEFAULT_CONFIG
        assert DEFAULT_CONFIG["default_excel_file"] == "investment_data.xlsx"
        assert DEFAULT_CONFIG["default_prices_file"] == "stock_prices.csv"

    def test_default_config_has_cash_equivalents(self):
        """DEFAULT_CONFIG has cash_equivalents list."""
        assert "cash_equivalents" in DEFAULT_CONFIG
        assert "BIL" in DEFAULT_CONFIG["cash_equivalents"]
        assert "USFR" in DEFAULT_CONFIG["cash_equivalents"]
        assert "PJLXX" in DEFAULT_CONFIG["cash_equivalents"]

    def test_default_config_has_trading_defaults(self):
        """DEFAULT_CONFIG has trading default values."""
        assert "default_cash_floor_percent" in DEFAULT_CONFIG
        assert "default_target_allocation_percent" in DEFAULT_CONFIG
        assert "default_skip_if_above_percent" in DEFAULT_CONFIG
        assert DEFAULT_CONFIG["default_cash_floor_percent"] == 0.02
        assert DEFAULT_CONFIG["default_target_allocation_percent"] == 0.025
        assert DEFAULT_CONFIG["default_skip_if_above_percent"] == 0.02


class TestGetConfigPath:
    """Tests for get_config_path function."""

    def test_config_path_is_path_object(self):
        """get_config_path returns a Path object."""
        path = get_config_path()
        assert isinstance(path, Path)

    def test_config_path_ends_with_config_json(self):
        """get_config_path returns path ending in config.json."""
        path = get_config_path()
        assert path.name == "config.json"

    def test_config_path_frozen_executable(self):
        """get_config_path handles frozen executable."""
        with patch.object(sys, 'frozen', True, create=True):
            with patch.object(sys, 'executable', '/path/to/TradingSystem.exe'):
                path = get_config_path()
                assert path.name == "config.json"


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_missing_file_creates_default(self):
        """Missing config file creates default and returns it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            with patch('config.get_config_path', return_value=config_path):
                config = load_config()

            # Should have created the file
            assert config_path.exists()

            # Should return default config values
            assert config["anthropic_api_key"] == ""
            assert "cash_equivalents" in config

    def test_load_config_reads_existing_file(self):
        """load_config reads existing config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            # Create config file with custom value
            custom_config = {"anthropic_api_key": "test-key-123"}
            with open(config_path, 'w') as f:
                json.dump(custom_config, f)

            with patch('config.get_config_path', return_value=config_path):
                config = load_config()

            assert config["anthropic_api_key"] == "test-key-123"

    def test_load_config_malformed_json_uses_defaults(self):
        """Malformed JSON uses defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            # Create malformed JSON file
            with open(config_path, 'w') as f:
                f.write("{ this is not valid json }")

            with patch('config.get_config_path', return_value=config_path):
                config = load_config()

            # Should return default config
            assert config["anthropic_api_key"] == ""
            assert config["default_cash_floor_percent"] == 0.02

    def test_load_config_partial_config_merges_defaults(self):
        """Partial config (missing keys) merges with defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            # Create partial config (missing most keys)
            partial_config = {"anthropic_api_key": "my-key"}
            with open(config_path, 'w') as f:
                json.dump(partial_config, f)

            with patch('config.get_config_path', return_value=config_path):
                config = load_config()

            # Should have custom value
            assert config["anthropic_api_key"] == "my-key"
            # Should have merged defaults for missing keys
            assert config["default_excel_file"] == "investment_data.xlsx"
            assert config["cash_equivalents"] == ["BIL", "USFR", "PJLXX", "JAAA"]

    def test_load_config_empty_file_uses_defaults(self):
        """Empty config file uses defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            # Create empty JSON object
            with open(config_path, 'w') as f:
                json.dump({}, f)

            with patch('config.get_config_path', return_value=config_path):
                config = load_config()

            # Should return default config
            assert config["default_cash_floor_percent"] == 0.02


class TestSaveConfig:
    """Tests for save_config function."""

    def test_save_config_creates_file(self):
        """save_config creates config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            with patch('config.get_config_path', return_value=config_path):
                result = save_config({"test_key": "test_value"})

            assert result is True
            assert config_path.exists()

            with open(config_path, 'r') as f:
                saved = json.load(f)
            assert saved["test_key"] == "test_value"

    def test_save_config_overwrites_existing(self):
        """save_config overwrites existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            # Create initial config
            with open(config_path, 'w') as f:
                json.dump({"old_key": "old_value"}, f)

            with patch('config.get_config_path', return_value=config_path):
                save_config({"new_key": "new_value"})

            with open(config_path, 'r') as f:
                saved = json.load(f)

            assert "new_key" in saved
            assert "old_key" not in saved

    def test_save_config_returns_false_on_error(self):
        """save_config returns False on write error."""
        with patch('config.get_config_path', return_value=Path("/nonexistent/dir/config.json")):
            result = save_config({"test": "value"})

        assert result is False

    def test_save_config_formats_json(self):
        """save_config formats JSON with indentation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            with patch('config.get_config_path', return_value=config_path):
                save_config({"key1": "value1", "key2": "value2"})

            with open(config_path, 'r') as f:
                content = f.read()

            # Should be formatted with newlines (indentation)
            assert "\n" in content


class TestGetApiKey:
    """Tests for get_api_key function."""

    def test_get_api_key_returns_key(self):
        """get_api_key returns the API key from config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            with open(config_path, 'w') as f:
                json.dump({"anthropic_api_key": "sk-test-key"}, f)

            with patch('config.get_config_path', return_value=config_path):
                key = get_api_key()

            assert key == "sk-test-key"

    def test_get_api_key_returns_empty_if_missing(self):
        """get_api_key returns empty string if key not in config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            with open(config_path, 'w') as f:
                json.dump({}, f)

            with patch('config.get_config_path', return_value=config_path):
                key = get_api_key()

            assert key == ""


class TestSetApiKey:
    """Tests for set_api_key function."""

    def test_set_api_key_saves_key(self):
        """set_api_key saves the API key to config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            # Create initial config
            with open(config_path, 'w') as f:
                json.dump(DEFAULT_CONFIG.copy(), f)

            with patch('config.get_config_path', return_value=config_path):
                result = set_api_key("sk-new-key")

            assert result is True

            with open(config_path, 'r') as f:
                saved = json.load(f)
            assert saved["anthropic_api_key"] == "sk-new-key"

    def test_set_api_key_preserves_other_config(self):
        """set_api_key preserves other config values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            # Create config with custom values
            initial = DEFAULT_CONFIG.copy()
            initial["custom_field"] = "custom_value"
            with open(config_path, 'w') as f:
                json.dump(initial, f)

            with patch('config.get_config_path', return_value=config_path):
                set_api_key("sk-new-key")

            with open(config_path, 'r') as f:
                saved = json.load(f)

            assert saved["anthropic_api_key"] == "sk-new-key"
            assert saved["custom_field"] == "custom_value"


class TestConfigEdgeCases:
    """Edge case tests for configuration."""

    def test_config_with_unicode_characters(self):
        """Config handles unicode characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            config = {"note": "Unicode test: \u00e9\u00e8\u00ea"}
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f)

            with patch('config.get_config_path', return_value=config_path):
                loaded = load_config()

            assert "Unicode test" in loaded["note"]

    def test_config_with_nested_structures(self):
        """Config handles nested structures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            config = {
                "anthropic_api_key": "",
                "nested": {
                    "level1": {
                        "level2": "deep_value"
                    }
                }
            }
            with open(config_path, 'w') as f:
                json.dump(config, f)

            with patch('config.get_config_path', return_value=config_path):
                loaded = load_config()

            assert loaded["nested"]["level1"]["level2"] == "deep_value"

    def test_config_with_list_values(self):
        """Config handles list values correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            config = {
                "anthropic_api_key": "",
                "cash_equivalents": ["CUSTOM1", "CUSTOM2", "CUSTOM3"]
            }
            with open(config_path, 'w') as f:
                json.dump(config, f)

            with patch('config.get_config_path', return_value=config_path):
                loaded = load_config()

            assert loaded["cash_equivalents"] == ["CUSTOM1", "CUSTOM2", "CUSTOM3"]

    def test_config_with_numeric_strings(self):
        """Config handles numeric-looking strings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            config = {"anthropic_api_key": "12345"}
            with open(config_path, 'w') as f:
                json.dump(config, f)

            with patch('config.get_config_path', return_value=config_path):
                key = get_api_key()

            assert key == "12345"
            assert isinstance(key, str)

    def test_default_config_is_not_mutated(self):
        """Loading config does not mutate DEFAULT_CONFIG."""
        original_key = DEFAULT_CONFIG["anthropic_api_key"]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            with open(config_path, 'w') as f:
                json.dump({"anthropic_api_key": "modified"}, f)

            with patch('config.get_config_path', return_value=config_path):
                loaded = load_config()
                loaded["anthropic_api_key"] = "further_modified"

        # DEFAULT_CONFIG should be unchanged
        assert DEFAULT_CONFIG["anthropic_api_key"] == original_key
