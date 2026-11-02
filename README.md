# TapoControl

Windows app to discover and control Tapo P110 plugs on your LAN (on/off, live power draw). Control is local, no cloud calls.

## Install
Run `dist\TapoControl-Setup.exe` (build it first, see below). It installs per user, no admin needed.

## First run
Enter your Tapo app email and password when asked. The email and known plugs go in `%APPDATA%\TapoControl\tapo.db`. The password goes in Windows Credential Manager. Use `Account...` to change them.

## Develop
```
python -m pip install uv
uv sync
uv run run.py
uv run pytest
```

## Build the installer
```
packaging/build.bat
```
Needs [Inno Setup](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`) for the final `Setup.exe`. Without it the build stops at `dist\TapoControl\`.
