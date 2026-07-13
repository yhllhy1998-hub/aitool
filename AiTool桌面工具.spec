# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = ['_tkinter', 'json', 'uuid', 'datetime', 'shutil', 'subprocess', 're', 'ctypes', 'webbrowser']
hiddenimports += collect_submodules('tkinter')
hiddenimports += collect_submodules('tkinterdnd2')

datas = [('data', 'data')]
datas += collect_data_files('tkinterdnd2')


a = Analysis(
    ['run_desktop_tool.py'],
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'matplotlib', 'multiprocessing', 'IPython', 'scipy', 'test', 'unittest', 'pydoc', 'sqlite3', 'tkinter.test', 'tkinter.tix', 'distutils', 'lib2to3', 'turtle', 'turtledemo', 'pydoc_data'],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AiTool桌面工具',
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
