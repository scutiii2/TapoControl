# PyInstaller spec: windowed one-folder build, wrapped into an installer by installer.iss.
# Build with: pyinstaller packaging/build.spec (from project root)
from PyInstaller.utils.hooks import collect_submodules

# kasa and keyring load device/backend modules dynamically, so list them explicitly.
hidden = collect_submodules("kasa") + collect_submodules("tapo") + collect_submodules("keyring.backends") + collect_submodules("win32ctypes")

a = Analysis(
    ["../run.py"],
    pathex=["../src"],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TapoControl",
    debug=False,
    upx=False,
    console=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="TapoControl", upx=False)
