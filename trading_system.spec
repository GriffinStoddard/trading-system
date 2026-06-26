# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for Trading System
#
# macOS:   builds dist/TradingSystem.app (double-clickable, onedir for fast
#          launch) plus dist/TradingSystemCLI (terminal binary)
# Windows: builds dist/TradingSystem.exe (windowed, onefile) plus
#          dist/TradingSystemCLI.exe
#
# Data files (config.json, stock_prices.csv) live in the per-user app data
# directory (see paths.py) — nothing is read from inside the bundle except
# the gui/ frontend and design assets.

import sys

from PyInstaller.utils.hooks import collect_all

IS_MAC = sys.platform == "darwin"

# Native deps PyInstaller's static analysis misses (must be collected in full):
#   yfinance  -> curl_cffi     (vendored libcurl DLL loaded via cffi/_cffi_backend)
#   anthropic -> jiter         (Rust ext, submodule jiter.jiter)
#   anthropic -> pydantic_core (native ext)
# NOTE: pywebview's WebView2 DLLs and pythonnet/Python.Runtime.dll are handled
# automatically by the bundled hook-webview.py and pythonnet's entry-point hook,
# so they are intentionally NOT collected manually here (doing so only produces
# duplicate-file warnings).
_native_datas, _native_binaries, _native_hidden = [], [], []
for _pkg in ("curl_cffi", "jiter", "pydantic_core"):
    _d, _b, _h = collect_all(_pkg)
    _native_datas += _d
    _native_binaries += _b
    _native_hidden += _h

_native_hidden += [
    "_cffi_backend",
    "platformdirs.windows",   # yfinance cache dir; lazy per-OS import PyInstaller misses
    "multitasking",
    "frozendict",
    "peewee",
    "openpyxl.cell._writer",  # lazy import on the .xlsx write path
]

gui_hidden = [
    'anthropic',
    'pandas',
    'openpyxl',
    'webview',
    'yfinance',
]
if IS_MAC:
    gui_hidden += ['webview.platforms.cocoa']
else:
    gui_hidden += ['webview.platforms.winforms', 'webview.platforms.edgechromium']

gui_analysis = Analysis(
    ['app.py'],
    pathex=[],
    binaries=_native_binaries,
    datas=[('gui', 'gui'), ('design', 'design')] + _native_datas,
    hiddenimports=gui_hidden + _native_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

gui_pyz = PYZ(gui_analysis.pure)

if IS_MAC:
    # onedir + BUNDLE: the .app launches fast (no per-launch unpack)
    gui_exe = EXE(
        gui_pyz,
        gui_analysis.scripts,
        [],
        exclude_binaries=True,
        name='TradingSystem',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    gui_collect = COLLECT(
        gui_exe,
        gui_analysis.binaries,
        gui_analysis.datas,
        strip=False,
        upx=False,
        name='TradingSystem',
    )
    app = BUNDLE(
        gui_collect,
        name='TradingSystem.app',
        icon='design/TradingSystem.icns',
        bundle_identifier='com.stoddardfinancial.tradingsystem',
        info_plist={
            'CFBundleName': 'TradingSystem',
            'CFBundleDisplayName': 'Trading System',
            'CFBundleShortVersionString': '3.6.0',
            'NSHighResolutionCapable': True,
            'NSRequiresAquaSystemAppearance': False,
        },
    )
else:
    gui_exe = EXE(
        gui_pyz,
        gui_analysis.scripts,
        gui_analysis.binaries,
        gui_analysis.datas,
        [],
        name='TradingSystem',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,  # UPX corrupts CFG/.NET/WebView2 native DLLs (silent blank-window crash since console=False) and trips Defender; size win not worth it
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,  # windowed GUI app
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon='design/TradingSystem.ico',
    )

cli_analysis = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_native_binaries,
    datas=[('design', 'design')] + _native_datas,
    hiddenimports=[
        'anthropic',
        'pandas',
        'openpyxl',
        'rich',
        'yfinance',
    ] + _native_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

cli_pyz = PYZ(cli_analysis.pure)

cli_exe = EXE(
    cli_pyz,
    cli_analysis.scripts,
    cli_analysis.binaries,
    cli_analysis.datas,
    [],
    name='TradingSystemCLI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # disable UPX on Windows too: avoids native .pyd/libcurl corruption and AV false positives
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None if IS_MAC else 'design/TradingSystem.ico',
)
