import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

datas_fastapi, binaries_fastapi, hiddenimports_fastapi = collect_all("fastapi")
datas_uvicorn, binaries_uvicorn, hiddenimports_uvicorn = collect_all("uvicorn")
datas_sqlalchemy, binaries_sqlalchemy, hiddenimports_sqlalchemy = collect_all("sqlalchemy")
datas_pydantic, binaries_pydantic, hiddenimports_pydantic = collect_all("pydantic")
datas_starlette, binaries_starlette, hiddenimports_starlette = collect_all("starlette")

project_datas = [("frontend", "frontend"), ("backend", "backend")]

all_datas = project_datas + datas_fastapi + datas_uvicorn + datas_sqlalchemy + datas_pydantic + datas_starlette
all_binaries = binaries_fastapi + binaries_uvicorn + binaries_sqlalchemy
all_hiddenimports = (
    hiddenimports_fastapi + hiddenimports_uvicorn + hiddenimports_sqlalchemy +
    hiddenimports_pydantic + hiddenimports_starlette +
    collect_submodules("backend") + [
        "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
        "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan", "uvicorn.lifespan.on",
        "anyio", "anyio.from_thread",
        "email.mime.text", "email.mime.multipart",
        "multipart", "python_multipart", "aiofiles",
        "openpyxl", "pandas", "pandas.io.formats.style",
        "holidays", "cryptography", "dotenv",
        "dateutil", "dateutil.parser",
        "sqlalchemy.dialects.sqlite", "cryptography.fernet", "cryptography.hazmat.primitives.kdf.pbkdf2", "cryptography.hazmat.backends", "cryptography.hazmat.backends.openssl", "playwright", "playwright.async_api", "playwright.sync_api", "anthropic", "httpx", "httpcore", "certifi", "charset_normalizer", "idna", "urllib3",
    ]
)

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "PIL", "pytest"],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ReconciliApp", debug=False, strip=False, upx=True, console=False)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=True, name="ReconciliApp")
app = BUNDLE(coll, name="ReconciliApp.app", bundle_identifier="com.reconciliapp.app",
    info_plist={"CFBundleName": "ReconciliApp", "CFBundleVersion": "1.0.0", "NSHighResolutionCapable": True})
