"""Launch a verified installer only after normal Crier shutdown and a backup."""
import base64
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess

from .relay_backup import _safe_path
from .update_recovery import create_backup, validate_backup


def _powershell():
    if os.name != 'nt':
        raise ValueError('Installer handoff requires Windows')
    buffer = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetWindowsDirectoryW(buffer,len(buffer)):
        raise ValueError('Cannot locate Windows update helper')
    return str(Path(buffer.value)/'System32/WindowsPowerShell/v1.0/powershell.exe')


def handoff_command(installer, digest, publisher_pins, status_path, *, parent_pid=None, powershell=None, verify_only=False):
    installer, status_path = _safe_path(installer), _safe_path(status_path)
    if (not installer.is_file() or installer.suffix.lower() != '.exe' or status_path.exists()
            or not re.fullmatch('[a-f0-9]{64}',digest)
            or not isinstance(publisher_pins,list) or len(publisher_pins)>8
            or any(not isinstance(p,str) or not re.fullmatch('[A-Fa-f0-9]{64}',p) for p in publisher_pins)):
        raise ValueError('Invalid verified installer handoff')
    parent_pid = os.getpid() if parent_pid is None else parent_pid
    if type(parent_pid) is not int or parent_pid < 1:
        raise ValueError('Invalid parent process')
    data=base64.b64encode(json.dumps(dict(installer=str(installer),sha256=digest,
        publishers=[p.upper() for p in publisher_pins],parent=parent_pid,status=str(status_path),verify_only=bool(verify_only))).encode()).decode()
    # Only a base64 data literal is embedded. Paths/arguments never become code.
    script=r'''
$ErrorActionPreference='Stop'
$data=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__DATA__')) | ConvertFrom-Json
$code='verification_failed'
$stream=$null
$guards=New-Object 'System.Collections.Generic.List[System.IDisposable]'
try {
  if (Get-Process -Id $data.parent -ErrorAction SilentlyContinue) {
    Wait-Process -Id $data.parent -Timeout 120 -ErrorAction Stop
  }
  Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class CrierUpdateGuard {
 [StructLayout(LayoutKind.Sequential)] struct Info {
  public uint attributes; public System.Runtime.InteropServices.ComTypes.FILETIME created, accessed, written;
  public uint volume,sizeHigh,sizeLow,links,indexHigh,indexLow;
 }
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]
 static extern SafeFileHandle CreateFileW(string path,uint access,uint share,IntPtr security,uint disposition,uint flags,IntPtr template);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool GetFileInformationByHandle(SafeFileHandle file,out Info info);
 public static SafeFileHandle Open(string path,bool directory) {
  var file=CreateFileW(path,directory?0x80u:0x80000000u,directory?3u:1u,IntPtr.Zero,3,directory?0x02200000u:0x00200000u,IntPtr.Zero);
  Info info;
  if(file.IsInvalid || !GetFileInformationByHandle(file,out info) || (info.attributes&0x400u)!=0 || ((info.attributes&0x10u)!=0)!=directory) {
   file.Dispose();throw new IOException("Update file identity failed");
  }
  return file;
 }
}
'@
  $ancestors=New-Object 'System.Collections.Generic.List[string]'
  $directory=[IO.DirectoryInfo]([IO.Path]::GetDirectoryName($data.installer))
  while ($directory) {$ancestors.Insert(0,$directory.FullName);$directory=$directory.Parent}
  foreach ($directory in $ancestors) {$guards.Add([CrierUpdateGuard]::Open($directory,$true))}
  $file=[CrierUpdateGuard]::Open($data.installer,$false)
  $guards.Add($file)
  $stream=New-Object IO.FileStream($file,[IO.FileAccess]::Read)
  $hash=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($stream)).Replace('-','').ToLowerInvariant()
  if ($hash -cne $data.sha256) { throw 'invalid' }
  if ($data.publishers.Count -gt 0) {
    $signature=Get-AuthenticodeSignature -LiteralPath $data.installer
    if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate) { throw 'invalid' }
    $cert=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($signature.SignerCertificate.RawData)).Replace('-','')
    if ($data.publishers -cnotcontains $cert) { throw 'invalid' }
  }
  if ($data.verify_only) {$code='verified'} else {
    $process=Start-Process -FilePath $data.installer -WindowStyle Normal -PassThru
    $process.WaitForExit()
    $code=if ($process.ExitCode -in @(0,3010)) {'installed'} else {'installer_failed'}
  }
} catch { $code='verification_or_install_failed' }
finally {
 if ($stream) {$stream.Dispose()}
 for ($index=$guards.Count-1;$index -ge 0;$index--) {$guards[$index].Dispose()}
}
try {
  $bytes=[Text.Encoding]::UTF8.GetBytes((@{schema=1;status=$code} | ConvertTo-Json -Compress))
  $result=[IO.File]::Open($data.status,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try {$result.Write($bytes,0,$bytes.Length);$result.Flush()} finally {$result.Dispose()}
} catch {}
'''.replace('__DATA__',data)
    return [powershell or _powershell(),'-NoProfile','-NonInteractive','-WindowStyle','Hidden',
            '-EncodedCommand',base64.b64encode(script.encode('utf-16le')).decode()]


def prepare_install(client, profile, backup_root, publisher_pins, status_path, *, locked_profile=False):
    client.verify_staged()
    # Expected hash comes only from authenticated manifest metadata, never a
    # fresh hash of potentially replaced local executable bytes.
    expected = client.release['installer']['sha256']
    backup=create_backup(profile,backup_root,locked_profile=locked_profile)
    validate_backup(backup)
    installer=client.verify_staged()
    command=handoff_command(installer,expected,publisher_pins,status_path)
    return {'command':command,'backup':str(backup),'status_path':str(status_path)}


def launch(plan):
    # Fixed encoded helper, no shell, no execution-policy bypass, no silent install.
    return subprocess.Popen(plan['command'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
