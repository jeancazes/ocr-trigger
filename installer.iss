[Setup]
AppName=OCR Trigger
AppVersion=2.0.0
AppPublisher=OCR Trigger
DefaultDirName={autopf}\OCR Trigger
DefaultGroupName=OCR Trigger
OutputDir=dist
OutputBaseFilename=OCR_Trigger_Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\OCR_Trigger.exe
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
WizardStyle=modern

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"

[Files]
Source: "dist\OCR_Trigger.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\OCR Trigger"; Filename: "{app}\OCR_Trigger.exe"
Name: "{autodesktop}\OCR Trigger"; Filename: "{app}\OCR_Trigger.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OCR_Trigger.exe"; Description: "OCR Trigger"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "schtasks"; Parameters: "/Delete /TN OCRTrigger /F"; Flags: runhidden; RunOnceId: "DelTask"
