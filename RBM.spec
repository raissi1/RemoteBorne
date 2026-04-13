# -*- mode: python ; coding: utf-8 -*-

import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# 🔥 Inclure tous les modules dynamiques
hiddenimports = []
hiddenimports += collect_submodules('ttkbootstrap')

# 🔥 Données (dossiers importants)
datas = [
    ('tools', 'tools'),
    ('configs', 'configs'),
    ('images', 'images'),
    ('BorneCommander.ico', '.'),
]

a = Analysis(
    ['src/RemoteBorneManager.py'],
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports + [
        'debug_logs',
        'energy_manager',
        'network_config',
        'plink_backend',
        'ssh_manager',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    icon='BorneCommander.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RBM',
)