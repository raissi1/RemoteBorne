# -*- mode: python ; coding: utf-8 -*-
# Documented PyInstaller spec for Remote Borne Manager (RBM)
# This mirrors the current project build settings while staying easy to read.

from PyInstaller.utils.hooks import collect_all


datas = [("BorneCommander.ico", ".")]
binaries = []
hiddenimports = [
    "debug_logs",
    "energy_manager",
    "network_config",
    "open_help",
    "plink_backend",
    "ssh_manager",
    "ssh_queue",
    "utils_ui",
]

tmp_ret = collect_all("ttkbootstrap")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

tmp_ret = collect_all("reportlab")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]


a = Analysis(
    ["src\\RemoteBorneManager.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RBM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["BorneCommander.ico"],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="RBM",
)
