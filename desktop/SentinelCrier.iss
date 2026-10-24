#ifndef AppVersion
  #error AppVersion is required from release.json
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\SentinelCrier"
#endif
[Setup]
AppId={{24760C0D-9A32-46E7-A9EE-BBF3C2EA51AF}
AppName=Sentinel Crier
AppVersion={#AppVersion}
AppPublisher=Sentinel Crier
DefaultDirName={localappdata}\Programs\SentinelCrier
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\release
OutputBaseFilename=SentinelCrier-{#AppVersion}-Windows-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\SentinelCrier.exe
CloseApplications=no
RestartApplications=no
SetupMutex=SentinelCrier.Setup
[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{userprograms}\Sentinel Crier"; Filename: "{app}\SentinelCrier.exe"
[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExistingVersion: String;
  Handle: Integer;
  InstalledPacked, TargetPacked: Int64;
  ProgramFile: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{24760C0D-9A32-46E7-A9EE-BBF3C2EA51AF}_is1', 'DisplayVersion', ExistingVersion) then
    if (not StrToVersion(ExistingVersion, InstalledPacked)) or (not StrToVersion('{#AppVersion}', TargetPacked)) then begin
      Result := 'Cannot verify installed version. Update is blocked.';
      Exit;
    end else if ComparePackedVersion(InstalledPacked, TargetPacked) > 0 then begin
      Result := 'Downgrades are unsupported. Install the same or a newer release.';
      Exit;
    end;
  ProgramFile := ExpandConstant('{app}\SentinelCrier.exe');
  if FileExists(ProgramFile) then begin
    Handle := FileOpen(ProgramFile, fmOpenReadWrite or fmShareExclusive);
    if Handle = -1 then
      Result := 'Close Sentinel Crier before updating. No files have been replaced.'
    else
      FileClose(Handle);
  end;
end;

