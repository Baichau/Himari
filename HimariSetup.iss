#define MyAppName "Himari"
#define MyAppVersion "2.0.0"

[Setup]
AppId={{4F0573A3-1F86-4BA2-AB19-04E983E81DC4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\Himari
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
OutputDir=installer
OutputBaseFilename=HimariSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "dist\Himari.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Himari"; Filename: "{app}\Himari.exe"
Name: "{autodesktop}\Himari"; Filename: "{app}\Himari.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\Himari.exe"; Description: "Launch Himari"; Flags: postinstall nowait skipifsilent
