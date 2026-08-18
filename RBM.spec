# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = [('BorneCommander.ico', '.')]
binaries = []

hiddenimports = [
    'debug_logs',
    'energy_manager',
    'network_config',
    'plink_backend',
    'ssh_manager'
]

# ============================================================
# TTKBOOTSTRAP
# ============================================================

ttk_datas, ttk_binaries, ttk_hiddenimports = collect_all('ttkbootstrap')

datas += ttk_datas
binaries += ttk_binaries
hiddenimports += ttk_hiddenimports

# Force inclusion of ttkbootstrap resources/fonts
datas += collect_data_files('ttkbootstrap', include_py_files=False)

# ============================================================
# PILLOW
# ============================================================

pil_datas, pil_binaries, pil_hiddenimports = collect_all('PIL')

datas += pil_datas
binaries += pil_binaries
hiddenimports += pil_hiddenimports

# ============================================================
# REPORTLAB
# ============================================================

reportlab_datas, reportlab_binaries, reportlab_hiddenimports = collect_all('reportlab')

datas += reportlab_datas
binaries += reportlab_binaries
hiddenimports += reportlab_hiddenimports


a = Analysis(
    ['src\\RemoteBorneManager.py'],
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
    name='RBM',
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
    icon=['BorneCommander.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RBM',
)