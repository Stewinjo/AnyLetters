# -*- mode: python ; coding: utf-8 -*-
# AnyLetters PyInstaller spec file
# Includes solutions files, dictionary files, filters, and baked defaults.json

import json
import os
from PyInstaller.utils.hooks import collect_data_files

# Collect data files to include
datas = []

# Baked runtime defaults (lang / length / difficulty / filters).
if os.path.isfile('defaults.json'):
    datas.append(('defaults.json', '.'))

# Include solutions folder (solutions/<lang><length>.txt)
if os.path.isdir('solutions'):
    datas.append(('solutions', 'solutions'))

# Include dictionaries submodule (external/dictionaries/dictionaries/<lang>)
dict_submodule = os.path.join('external', 'dictionaries', 'dictionaries')
if os.path.isdir(dict_submodule):
    datas.append((dict_submodule, dict_submodule))

# Language filters (countries, names, companies).
filters_dir = 'filters'
if os.path.isdir(filters_dir):
    datas.append((filters_dir, filters_dir))

# Bundled fonts, when the assets tree is present.
assets_dir = 'assets'
if os.path.isdir(assets_dir):
    datas.append((assets_dir, assets_dir))

# Include better_profanity resource files
datas += collect_data_files('better_profanity')

exe_name = 'AnyLetters'
if os.path.isfile('defaults.json'):
    with open('defaults.json', 'r', encoding='utf-8') as handle:
        baked = json.load(handle)
    if isinstance(baked, dict):
        candidate = str(baked.get('exe_name') or '').strip()
        if candidate:
            exe_name = candidate

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
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
    a.binaries,
    a.datas,
    [],
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
