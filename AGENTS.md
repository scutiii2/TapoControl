# TapoControl

## Agent instructions
This file is the one instruction file for every coding agent. Codex reads it directly; `CLAUDE.md` only imports it (`@AGENTS.md`) for Claude Code. Edit this file, never `CLAUDE.md`.

## Project
- Windows desktop app (PySide6) to discover and control Tapo P110 plugs over the LAN. Code in `src/` (`core/` logic, `ui/` windows, `main.py` entry); build files in `packaging/`.
- `controller.py` is the only module that talks to the plugs: `python-kasa` for credential-free LAN discovery (IPs only), `tapo` for control (the plugs use TPAP, which python-kasa 0.12 cannot drive). UI calls it through `AsyncRunner`, never directly on the Qt thread.
- `store.py`: SQLite at `%APPDATA%\TapoControl\tapo.db` holds the account email and known plugs. The password lives in Windows Credential Manager via `keyring`, never in the DB or a file.
- Credentials are typed into the app at runtime. No `.env`. Never read or print stored credentials.
- Dependencies: `pyproject.toml` + `uv.lock` (uv, not pip; no `requirements.txt`). Set up with `uv sync`; add packages with `uv add <pkg>` and commit the lock. If uv fails with os error 17 (cross-drive temp file), set `UV_CACHE_DIR` to a folder on the project's drive.
- Tests: `.venv/Scripts/python.exe -m pytest`. Tests must not touch the network, real plugs, or the real keyring.
- Build: `packaging/build.bat` → `dist/TapoControl/`, plus `dist/TapoControl-Setup.exe` when Inno Setup is installed.
