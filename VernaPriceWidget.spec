# -*- mode: python ; coding: utf-8 -*-
"""Single-file, console-less VernaPriceWidget.exe. ui/ is inlined from _MEIPASS at startup."""

import os

ROOT = os.path.abspath(SPECPATH)
UI = os.path.join(ROOT, "ui")

a = Analysis(
    [os.path.join(ROOT, "run.pyw")],
    pathex=[ROOT],
    datas=[
        (os.path.join(UI, "index.html"), "ui"),
        (os.path.join(UI, "style.css"), "ui"),
        (os.path.join(UI, "app.js"), "ui"),
        (os.path.join(UI, "fonts"), os.path.join("ui", "fonts")),
        (os.path.join(ROOT, "app.ico"), "."),  # tray icon
    ],
    hiddenimports=["webview", "webview.platforms.edgechromium", "clr_loader", "pythonnet"],
    excludes=["tkinter", "numpy", "PIL", "matplotlib", "pandas", "pytest", "pydoc_data"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="VernaPriceWidget",
    debug=False, strip=False, upx=False, runtime_tmpdir=None,
    console=False,
    icon=os.path.join(ROOT, "app.ico"),
)
