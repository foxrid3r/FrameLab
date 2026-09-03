# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all

repo_root = os.path.abspath(os.path.join(SPECPATH, '..', '..'))

datas = [
    (os.path.join(repo_root, 'release-licenses'), 'licenses'),
    (os.path.join(repo_root, 'LICENSE'), 'licenses'),
    (os.path.join(repo_root, 'vendor', 'ffmpeg', 'BUILD-INFO.txt'), 'licenses\\ffmpeg'),
    (os.path.join(repo_root, 'vendor', 'ffmpeg', 'FFmpeg-COPYING.GPLv2.txt'), 'licenses\\ffmpeg'),
    (os.path.join(repo_root, 'vendor', 'ffmpeg', 'x264-COPYING.txt'), 'licenses\\ffmpeg'),
]
binaries = [(os.path.join(repo_root, 'vendor', 'ffmpeg', 'ffmpeg.exe'), 'ffmpeg')]
hiddenimports = []
tmp_ret = collect_all('sv_ttk')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [os.path.join(repo_root, 'src', 'framelab', '__main__.py')],
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
    name='FrameLab',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FrameLab',
)
