param(
    [string]$Python = 'python',
    [string]$ISCC = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    [string]$SigningPfxPath = '',
    [string]$TimestampServer = 'http://timestamp.digicert.com'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    $version = & $Python desktop/release_metadata.py --version-only
    if ($LASTEXITCODE -ne 0) { throw 'Invalid release version' }
    if (-not (Test-Path -LiteralPath $ISCC)) { throw 'Install Inno Setup 6 or supply -ISCC with its compiler path' }
    if ([Environment]::Is64BitProcess -eq $false) { throw 'Windows releases require x64 Python/PowerShell' }
    & $Python -c "import struct; assert struct.calcsize('P') == 8, 'x64 Python required'"
    if ($LASTEXITCODE -ne 0) { throw 'Windows releases require x64 Python' }
    & "$PSScriptRoot/build.ps1" -Python $Python
    $releaseDir = Join-Path $repo 'dist/release'
    New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
    $certificate = $null
    $signing = 'unsigned'
    if ($SigningPfxPath) {
        if (-not $env:WINDOWS_SIGNING_PFX_PASSWORD) { throw 'WINDOWS_SIGNING_PFX_PASSWORD is required for signing' }
        $certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(
            $SigningPfxPath, $env:WINDOWS_SIGNING_PFX_PASSWORD,
            [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet)
        if (-not $certificate.HasPrivateKey) { throw 'Signing certificate has no private key' }
    }
    function Sign-ReleaseFile([string]$Path) {
        $result = Set-AuthenticodeSignature -FilePath $Path -Certificate $certificate -HashAlgorithm SHA256 -TimestampServer $TimestampServer
        if ($result.Status -ne 'Valid') { throw "Authenticode signing failed: $($result.Status)" }
    }
    if ($certificate) {
        Sign-ReleaseFile (Join-Path $repo 'dist/SentinelCrier/SentinelCrier.exe')
        $signing = 'signed'
    }
    $portable = Join-Path $releaseDir "SentinelCrier-$version-Windows.zip"
    Compress-Archive -Path dist/SentinelCrier -DestinationPath $portable -Force
    & $ISCC "/DAppVersion=$version" "/DSourceDir=$repo\dist\SentinelCrier" desktop/SentinelCrier.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed' }
    $installer = Join-Path $releaseDir "SentinelCrier-$version-Windows-Setup.exe"
    if ($certificate) { Sign-ReleaseFile $installer }
    $manifest = Join-Path $releaseDir "SentinelCrier-$version-Windows-manifest.json"
    & $Python desktop/release_metadata.py --signing $signing --output $manifest $portable $installer
    if ($LASTEXITCODE -ne 0) { throw 'Release manifest generation failed' }
    $checksums = foreach ($file in @($portable, $installer, $manifest)) {
        $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $([IO.Path]::GetFileName($file))"
    }
    $checksums | Set-Content -Encoding ascii -LiteralPath (Join-Path $releaseDir "SentinelCrier-$version-Windows-SHA256SUMS.txt")
    Write-Output "Windows $version release prepared ($signing): $releaseDir"
} finally {
    if ($certificate) { $certificate.Dispose() }
    Pop-Location
}
