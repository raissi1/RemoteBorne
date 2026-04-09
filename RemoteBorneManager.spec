# RemoteBorneManager.spec
# Build PyInstaller pour Remote Borne Manager (V3)

import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# On suppose que PyInstaller est lancé depuis la racine du projet
project_root = os.path.abspath(".")
src_dir = os.path.join(project_root, "src")

# Script principal (V3)
main_script = os.path.join(src_dir, "RemoteBorneManager.py")

# ---------- BINARIES (EXE externes : plink / pscp) ----------
binaries = []
plink_path = os.path.join(project_root, "tools", "plink.exe")
pscp_path = os.path.join(project_root, "tools", "pscp.exe")
if os.path.isfile(plink_path):
    binaries.append((plink_path, "tools"))
if os.path.isfile(pscp_path):
    binaries.append((pscp_path, "tools"))

# ---------- DATAS (fichiers copiés tels quels) ----------
datas = []

# Aide HTML
help_html = os.path.join(src_dir, "help.html")
if os.path.isfile(help_html):
    datas.append((help_html, "src"))

# Dossier des logos (imgs) à la racine du projet
imgs_src = os.path.join(project_root, "imgs")
if os.path.isdir(imgs_src):
    # => sera copié comme dist/RemoteBorneManager/imgs/...
    datas.append((imgs_src, "imgs"))

# config.ini par défaut (facultatif)
config_ini = os.path.join(project_root, "config", "config.ini")
if os.path.isfile(config_ini):
    datas.append((config_ini, "config"))

imgs_src = os.path.join(project_root, "imgs")
if os.path.isdir(imgs_src):
    datas.append((imgs_src, "imgs"))

app_icon = os.path.join(project_root, "BorneCommander.ico")
if os.path.isfile(app_icon):
    datas.append((app_icon, "."))

# ---------- HIDDENIMPORTS ----------
hiddenimports = [
    "ssh_manager",
    "plink_backend",
    "debug_logs",
    "energy_manager",
    "network_config",
    "open_help",
    "log_manager",
    "src.ssh_manager",
    "src.plink_backend",
    "src.debug_logs",
    "src.energy_manager",
    "src.network_config",
    "src.open_help",
    "src.log_manager",
] + collect_submodules("ttkbootstrap")

a = Analysis(
    [main_script],
    pathex=[project_root, src_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RemoteBorneManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # pas de console
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(project_root, "BorneCommander.ico") if os.path.isfile(os.path.join(project_root, "BorneCommander.ico")) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="RemoteBorneManager",
)
