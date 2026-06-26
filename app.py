#!/usr/bin/env python3
"""
Trading System — Desktop App entry point.

Launches the pywebview window with the GUI frontend. The terminal version
remains available via `python main.py`.

Usage:
    python app.py [--debug]
"""

import sys
from pathlib import Path

import webview

import paths
from gui_api import Api, VERSION


def gui_path() -> Path:
    """Locate the bundled frontend (script dir, or inside the app bundle)."""
    return paths.app_assets_dir() / "gui"


def main():
    api = Api()
    index = gui_path() / "index.html"
    if not index.exists():
        print(f"Frontend not found at {index}")
        sys.exit(1)

    window = webview.create_window(
        f"Stoddard Financial — Trading System v{VERSION}",
        str(index),
        js_api=api,
        width=1320,
        height=880,
        min_size=(1024, 700),
        background_color="#101418",
    )
    api.attach_window(window)
    # On Windows, force the Chromium/WebView2 backend so a missing WebView2
    # runtime fails loudly instead of silently falling back to legacy MSHTML,
    # which would render the modern GUI as a broken/blank window. macOS uses Cocoa.
    gui = "edgechromium" if sys.platform == "win32" else None
    webview.start(gui=gui, debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
