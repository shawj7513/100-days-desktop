; Inno Setup script: wraps dist\100DaysTracker\ in a normal Windows installer.
; Build with build.ps1 (needs the free Inno Setup 6 from jrsoftware.org).

#define AppName "100 Days Tracker"
#define AppVersion "0.1.0"

[Setup]
AppId={{6C1E2D5A-8B1F-4C7E-9A52-100DA75F0001}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\100DaysTracker
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=dist\installer
OutputBaseFilename=100DaysTracker-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayName={#AppName}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\100DaysTracker\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\100DaysTracker.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\100DaysTracker.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\100DaysTracker.exe"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent

; Her data lives in %APPDATA%\100DaysTracker and is deliberately NOT removed on uninstall.
