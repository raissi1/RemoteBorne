# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for the complete RBM V16 runtime."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path(SPECPATH)
datas = [
    (str(ROOT / "BorneCommander.ico"), "."),
    (str(ROOT / "src" / "config"), "config"),
    (str(ROOT / "src" / "tools"), "tools"),
    (str(ROOT / "src" / "imgs"), "imgs"),
    (str(ROOT / "tools" / "simulator"), "tools/simulator"),
]
for language in ("FR", "EN"):
    for document in (ROOT / "src" / "documents" / language).glob("RBM_V16_*.docx"):
        datas.append((str(document), f"documents/{language}"))

binaries = []
hiddenimports = [
    "debug_logs",
    "energy_manager",
    "network_config",
    "plink_backend",
    "setpoint_validation",
    "ssh_manager",
    "test_sequence",
]
for package in ("ttkbootstrap", "reportlab", "paramiko"):
    collected = collect_all(package)
    datas += collected[0]
    binaries += collected[1]
    hiddenimports += collected[2]


a = Analysis(
    ["src\\RemoteBorneManager.py"],
    pathex=[str(ROOT / "src")],
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
