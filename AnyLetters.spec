# -*- mode: python ; coding: utf-8 -*-
# AnyLetters PyInstaller spec file
# Includes solutions files and dictionary files

import os

# Collect data files to include
datas = []

# Include solutions folder (new structure: solutions/<lang><length>.txt)
if os.path.isdir('solutions'):
    datas.append(('solutions', 'solutions'))

# Include dictionaries submodule (external/dictionaries/dictionaries/<lang>)
dict_submodule = os.path.join('external', 'dictionaries', 'dictionaries')
if os.path.isdir(dict_submodule):
    datas.append((dict_submodule, dict_submodule))

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
    name='AnyLetters',
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
