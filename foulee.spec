# -*- mode: python ; coding: utf-8 -*-
# PyInstaller : python -m PyInstaller --noconfirm --clean foulee.spec
from PyInstaller.utils.hooks import collect_all

datas = [("assets", "assets")]
binaries = []
hiddenimports = []
for pkg in ("curl_cffi", "garminconnect", "certifi"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "PyQt5", "PyQt6", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Foulee", icon="assets/foulee.ico",
          console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Foulee", upx=False)
