"""
Configuration Management

Handles loading and saving configuration from a local config.json file.
This keeps sensitive data (like API keys) out of the code.
"""

import json
import os
from pathlib import Path


DEFAULT_CONFIG = {
    "anthropic_api_key": "",
    "default_excel_file": "investment_data.xlsx",
    "default_prices_file": "stock_prices.csv",
    "cash_equivalents": ["BIL", "USFR", "PJLXX", "JAAA"],
    "default_cash_floor_percent": 0.02,
    "default_target_allocation_percent": 0.025,
    "default_skip_if_above_percent": 0.02
}


def get_config_path() -> Path:
    """Get the path to the config file (same directory as executable/script)."""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe
        base_path = Path(sys.executable).parent
    else:
        # Running as script
        base_path = Path(__file__).parent
    
    return base_path / "config.json"


def load_config() -> dict:
    """
    Load configuration from config.json.
    Creates default config file if it doesn't exist.
    """
    config_path = get_config_path()
    
    if not config_path.exists():
        # Create default config file
        save_config(DEFAULT_CONFIG)
        print(f"Created default config file: {config_path}")
        print("Please edit config.json to add your Anthropic API key.")
        return DEFAULT_CONFIG.copy()
    
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        # Merge with defaults (in case new options were added)
        merged = DEFAULT_CONFIG.copy()
        merged.update(config)
        return merged
    
    except json.JSONDecodeError as e:
        print(f"Error reading config.json: {e}")
        print("Using default configuration.")
        return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> bool:
    """Save configuration to config.json."""
    config_path = get_config_path()
    
    try:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False


def get_api_key() -> str:
    """Get the Anthropic API key from config."""
    config = load_config()
    return config.get("anthropic_api_key", "")


def set_api_key(api_key: str) -> bool:
    """Set the Anthropic API key in config."""
    config = load_config()
    config["anthropic_api_key"] = api_key
    return save_config(config)


def get_cash_equivalents() -> list[str]:
    """Get the list of cash equivalent tickers from config."""
    config = load_config()
    return config.get("cash_equivalents", DEFAULT_CONFIG["cash_equivalents"])


# Need sys for frozen check
import sys
