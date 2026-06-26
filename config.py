"""
Configuration Management

config.json lives in the per-user app data directory (see paths.py), never
next to the executable — packaged apps can't write there.
"""

import json
from pathlib import Path
from typing import Optional

import paths


DEFAULT_CONFIG = {
    "anthropic_api_key": "",
    "model": "claude-opus-4-8",
    "advisor_name": "",
    "investment_data_path": "",          # absolute path, set via the file picker
    "default_excel_file": "investment_data.xlsx",  # legacy fallback (pre-3.2)
    "default_prices_file": "stock_prices.csv",
    "exports_dir": "",                   # empty = ~/Documents/TradingSystem
    "cash_equivalents": ["BIL", "USFR", "PJLXX", "JAAA"],
    "default_cash_floor_percent": 0.02,
    "default_target_allocation_percent": 0.025,
    "default_skip_if_above_percent": 0.02,
    "default_min_buy_percent": 0.01,
}


def get_config_path() -> Path:
    """Path to config.json in the per-user app data directory."""
    return paths.user_data_dir() / "config.json"


def load_config() -> dict:
    """Load configuration from config.json, creating it with defaults if missing."""
    config_path = get_config_path()

    if not config_path.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        # Merge with defaults so new options get picked up after upgrades.
        merged = DEFAULT_CONFIG.copy()
        merged.update(config)
        return merged
    except json.JSONDecodeError as e:
        print(f"Error reading config.json: {e}")
        print("Using default configuration.")
        return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> bool:
    """Save configuration to config.json."""
    try:
        with open(get_config_path(), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False


_PLACEHOLDER_KEYS = {"", "blank", "none", "your_api_key_here", "your-api-key-here"}


def get_api_key() -> str:
    """Get the Anthropic API key from config (placeholder values don't count)."""
    key = load_config().get("anthropic_api_key", "") or ""
    if key.strip().lower() in _PLACEHOLDER_KEYS:
        return ""
    return key


def set_api_key(api_key: str) -> bool:
    """Set the Anthropic API key in config."""
    config = load_config()
    config["anthropic_api_key"] = api_key
    return save_config(config)


def get_cash_equivalents() -> list[str]:
    """Get the list of cash equivalent tickers from config."""
    return load_config().get("cash_equivalents", DEFAULT_CONFIG["cash_equivalents"])


def get_investment_data_path() -> Optional[Path]:
    """Absolute path to the holdings Excel file, or None if not configured.

    Falls back to the legacy location (default_excel_file next to the script)
    so pre-3.2 setups keep working without migration.
    """
    config = load_config()
    stored = (config.get("investment_data_path") or "").strip()
    if stored:
        return Path(stored)
    legacy = paths.legacy_data_dir() / config.get(
        "default_excel_file", "investment_data.xlsx")
    if legacy.exists():
        return legacy
    return None


def set_investment_data_path(path: str) -> bool:
    """Store the absolute path to the holdings Excel file."""
    config = load_config()
    config["investment_data_path"] = str(Path(path).resolve())
    return save_config(config)


def get_exports_dir() -> Path:
    """Where order exports go (config override or ~/Documents/TradingSystem)."""
    override = (load_config().get("exports_dir") or "").strip()
    return Path(override) if override else paths.default_exports_dir()
