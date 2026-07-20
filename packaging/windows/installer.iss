; AISC Windows Installer — Inno Setup script
; 
; Build: ISCC.exe /DMyAppVersion=<ver> /DMyNumericVersion=<X.Y.Z.W> /DMyExeSource=<path> /DBundleSource=<path> /O<outdir> /F<filename> installer.iss
; Output: AISC-<version>-windows-x86_64-setup.exe
;
; Design:
;   - Per-user install (PrivilegesRequired=lowest), no admin prompt.
;   - Stable AppId GUID — do NOT change after first release.
;   - aisc.exe + aisc-bundle\ installed side-by-side in {app}.
;   - PATH entry added safely in [Code]; case-insensitive exact match;
;     never uses uninsdeletevalue (would wipe entire PATH).
;   - Upgrade replaces aisc.exe and aisc-bundle\ cleanly (deletes old
;     bundle before installing new one).
;   - Uninstall leaves %USERPROFILE%\.aisc and .cc-config untouched.
;   - No desktop shortcut; Start Menu has uninstall entry only.

#define MyAppName      "AISC"
#define MyAppPublisher "AISC Contributors"
#define MyAppURL       "https://github.com/wangyuncepu/AISC"
; Stable AppId GUID — once chosen, never change (Inno uses this for upgrade detection).
; The ISPP double-braces escape to a literal brace, producing {DF3B7C42-...}
#define MyAppId        "{{DF3B7C42-9E11-4F82-88A5-1E6FA0B3D529}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\AISC
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes
Compression=lzma2/max
SolidCompression=yes
OutputBaseFilename=AISC-{#MyAppVersion}-windows-x86_64-setup
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\aisc.exe
; VersionInfoVersion requires a strictly numeric X.Y.Z.W; derive from /DMyNumericVersion
VersionInfoVersion={#MyNumericVersion}
WizardStyle=modern
; No min-version check — this is the first install format

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Onefile executable
Source: "{#MyExeSource}"; DestDir: "{app}"; DestName: "aisc.exe"; Flags: ignoreversion

; Entire aisc-bundle directory (recursive)
Source: "{#MyBundleSource}\*"; DestDir: "{app}\aisc-bundle"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu: uninstall shortcut only (CLI tool, no direct launch icon)
Name: "{group}\Uninstall AISC"; Filename: "{uninstallexe}"

[Code]
// ================================================================
// PATH manipulation — case-insensitive, semicolon-aware, safe
// ================================================================

const
  PATH_REG_PATH = 'Environment';
  PATH_VALUE_NAME = 'PATH';

// ------------------------------------------------------------------
// Helper: split string by delimiter, include empty parts.
// Defined BEFORE first use (PathContains calls this).
// ------------------------------------------------------------------
procedure StringToArray(const S, Delim: string; out Arr: TArrayOfString; IncludeEmpty: Boolean);
var
  I, PosStart, PosEnd: Integer;
  Part: string;
  Tmp: TStringList;
begin
  Tmp := TStringList.Create;
  try
    PosStart := 1;
    while PosStart <= Length(S) do
    begin
      PosEnd := Pos(Delim, Copy(S, PosStart, MaxInt));
      if PosEnd = 0 then
      begin
        Part := Copy(S, PosStart, MaxInt);
        Tmp.Add(Part);
        Break;
      end
      else
      begin
        Part := Copy(S, PosStart, PosEnd - 1);
        if IncludeEmpty or (Part <> '') then
          Tmp.Add(Part);
        PosStart := PosStart + PosEnd + Length(Delim) - 1;
      end;
    end;
    SetArrayLength(Arr, Tmp.Count);
    for I := 0 to Tmp.Count - 1 do
      Arr[I] := Tmp[I];
  finally
    Tmp.Free;
  end;
end;

// Normalise a single PATH entry for comparison:
// trim whitespace, strip surrounding quotes, normalise trailing backslash,
// lower-case.
function NormalisePathEntry(const S: string): string;
var
  T: string;
  L: Integer;
begin
  T := Trim(S);
  // Strip surrounding double-quotes
  if (Length(T) >= 2) and (T[1] = '"') and (T[Length(T)] = '"') then
    T := Copy(T, 2, Length(T) - 2);
  // Normalise backslashes to single
  StringChangeEx(T, '\\', '\', True);
  // Remove trailing backslash for comparison
  L := Length(T);
  if (L > 0) and (T[L] = '\') then
    T := Copy(T, 1, L - 1);
  Result := LowerCase(T);
end;

// Check whether the normalised form of Needle exists in the
// semicolon-separated Haystack PATH value.
function PathContains(const Haystack, Needle: string): Boolean;
var
  Entries: TArrayOfString;
  I: Integer;
  N: string;
begin
  Result := False;
  if Length(Haystack) = 0 then Exit;
  N := NormalisePathEntry(Needle);
  if Length(N) = 0 then Exit;
  StringToArray(Haystack, ';', Entries, True);
  for I := Low(Entries) to High(Entries) do
    if NormalisePathEntry(Entries[I]) = N then
    begin
      Result := True;
      Exit;
    end;
end;

// Remove one exact-matching entry (case-insensitive, normalised) from
// a semicolon-separated PATH.  Returns the new PATH string.
function RemovePathEntry(const Haystack, ToRemove: string): string;
var
  I: Integer;
  NR: string;
  Parts: TStringList;
begin
  Result := Haystack;
  if Length(Haystack) = 0 then Exit;
  NR := NormalisePathEntry(ToRemove);
  if Length(NR) = 0 then Exit;

  Parts := TStringList.Create;
  try
    Parts.LineBreak := ';';
    Parts.Text := StringReplace(Haystack, ';', #13#10, [rfReplaceAll]);
    Result := '';
    for I := 0 to Parts.Count - 1 do
      if NormalisePathEntry(Parts[I]) <> NR then
      begin
        if Result <> '' then
          Result := Result + ';';
        Result := Result + Trim(Parts[I]);
      end;
  finally
    Parts.Free;
  end;
end;

// Add a directory to the user PATH if not already present.
// Uses RegWriteExpandStringValue to preserve REG_EXPAND_SZ type.
procedure AddToPath(const Dir: string);
var
  CurrentPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, PATH_REG_PATH,
                             PATH_VALUE_NAME, CurrentPath) then
    CurrentPath := '';
  if PathContains(CurrentPath, Dir) then Exit;  // already present

  if CurrentPath <> '' then
    CurrentPath := CurrentPath + ';' + Dir
  else
    CurrentPath := Dir;

  if not RegWriteExpandStringValue(HKEY_CURRENT_USER, PATH_REG_PATH,
                                    PATH_VALUE_NAME, CurrentPath) then
    Log('WARNING: Failed to write HKCU PATH');
end;

// Remove a directory from the user PATH.
// If the resulting PATH is empty, delete the value.
procedure RemoveFromPath(const Dir: string);
var
  CurrentPath, NewPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, PATH_REG_PATH,
                             PATH_VALUE_NAME, CurrentPath) then
    Exit;  // no PATH value — nothing to do

  NewPath := RemovePathEntry(CurrentPath, Dir);

  if NewPath = '' then
  begin
    if not RegDeleteValue(HKEY_CURRENT_USER, PATH_REG_PATH, PATH_VALUE_NAME) then
      Log('WARNING: Failed to delete HKCU PATH value');
  end
  else if LowerCase(Trim(NewPath)) <> LowerCase(Trim(CurrentPath)) then
  begin
    if not RegWriteExpandStringValue(HKEY_CURRENT_USER, PATH_REG_PATH,
                                      PATH_VALUE_NAME, NewPath) then
      Log('WARNING: Failed to write updated HKCU PATH');
  end;
end;

// ================================================================
// Install / uninstall event handlers
// ================================================================

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    if FileExists(ExpandConstant('{app}\aisc.exe')) then
      DeleteFile(ExpandConstant('{app}\aisc.exe'));
    if DirExists(ExpandConstant('{app}\aisc-bundle')) then
      DelTree(ExpandConstant('{app}\aisc-bundle'), True, True, True);
  end;

  if CurStep = ssPostInstall then
  begin
    AddToPath(ExpandConstant('{app}'));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RemoveFromPath(ExpandConstant('{app}'));
  end;
end;
