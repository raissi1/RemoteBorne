# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\RemoteBorneManager.py'],
    pathex=[],
    binaries=[],
    datas=[('BorneCommander.ico', '.'), ('tools', 'tools')],
    hiddenimports=['debug_logs', 'energy_manager', 'network_config', 'plink_backend', 'ssh_manager'],
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
