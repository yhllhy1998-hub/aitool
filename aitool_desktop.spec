# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['_tkinter', 'json', 'uuid', 'datetime', 'shutil', 'subprocess']
hiddenimports += collect_submodules('tkinter')


a = Analysis(
    ['D:\\LHYsAuto\\AiTool\\run_desktop_tool.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python312\\tcl', 'tcl'), ('C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python312\\DLLs\\_tkinter.pyd', '.'), ('D:\\LHYsAuto\\AiTool\\src\\aitool_desktop', 'aitool_desktop')],
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
    a.binaries,
    a.datas,
    [],
    name='aitool_desktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
