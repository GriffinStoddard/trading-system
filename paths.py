"""
Filesystem locations — the single source of truth for where data lives.

Packaged apps cannot keep data next to the executable (inside a .app bundle
that location is read-only and wiped on every rebuild), so:

- App data (config.json, stock_prices.csv) lives in the OS-standard per-user
  application data directory.
- The holdings Excel file lives wherever the user keeps it; config stores the
  absolute path (set via the in-app file picker).
- Exports default to a visible ~/Documents/TradingSystem folder.
- Bundled assets (the gui/ frontend, design/) ship inside the app and are
  resolved relative to the executable/script.

On first run, files from the legacy layout (everything next to the script) are
migrated automatically so an existing API key and buy list are preserved.
"""

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "TradingSystem"


def user_data_dir() -> Path:
    """Per-user app data directory (created on first use).

    macOS:   ~/Library/Application Support/TradingSystem
    Windows: %APPDATA%\\TradingSystem
    Linux:   $XDG_DATA_HOME/TradingSystem (default ~/.local/share/TradingSystem)
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_exports_dir() -> Path:
    """Where order sheets land unless config overrides it (not auto-created)."""
    return Path.home() / "Documents" / APP_NAME


def app_assets_dir() -> Path:
    """Read-only assets bundled with the program (gui/, design/)."""
    if hasattr(sys, "_MEIPASS"):          # PyInstaller (onefile or onedir)
        return Path(sys._MEIPASS)
    if getattr(sys, "frozen", False):     # other freezers
        return Path(sys.executable).parent
    return Path(__file__).parent


def legacy_data_dir() -> Path:
    """Where data files lived before v3.2 (next to the script / old exe)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def migrate_legacy_files() -> list[str]:
    """One-time migration from the legacy next-to-the-script layout.

    Copies (never moves — the originals stay as a fallback) config.json and
    stock_prices.csv into user_data_dir() when they don't exist there yet, and
    records the legacy Excel file's absolute path in the migrated config so an
    existing setup keeps working unchanged.

    Returns human-readable notes about what was migrated (empty = nothing).
    """
    notes: list[str] = []
    legacy = legacy_data_dir()
    target = user_data_dir()
    if legacy == target:
        return notes

    import json

    for name in ("config.json", "stock_prices.csv"):
        src, dst = legacy / name, target / name
        if src.exists() and not dst.exists():
            try:
                shutil.copy2(src, dst)
                notes.append(f"Migrated {name} to {target}")
            except OSError:
                continue

    # Point the migrated config at the legacy Excel file if no path is set yet.
    config_path = target / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (OSError, ValueError):
            return notes
        if not config.get("investment_data_path"):
            legacy_excel = legacy / config.get("default_excel_file",
                                               "investment_data.xlsx")
            if legacy_excel.exists():
                config["investment_data_path"] = str(legacy_excel.resolve())
                try:
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump(config, f, indent=2)
                    notes.append(f"Holdings file path set to {legacy_excel}")
                except OSError:
                    pass
    return notes
