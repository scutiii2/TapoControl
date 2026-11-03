; Inno Setup script. Compile after PyInstaller: ISCC packaging/installer.iss  ->  dist\TapoControl-Setup.exe
[Setup]
AppName=TapoControl
AppVersion=0.1.0
DefaultDirName={autopf}\TapoControl
DefaultGroupName=TapoControl
PrivilegesRequired=lowest
OutputDir=../dist
OutputBaseFilename=TapoControl-Setup
Compression=lzma
SolidCompression=yes
UninstallDisplayIcon={app}\TapoControl.exe
SetupIconFile=TapoControl.ico

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Files]
Source: "../dist\TapoControl\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\TapoControl"; Filename: "{app}\TapoControl.exe"
Name: "{autodesktop}\TapoControl"; Filename: "{app}\TapoControl.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TapoControl.exe"; Description: "Launch TapoControl"; Flags: nowait postinstall skipifsilent
