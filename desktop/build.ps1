param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    & $Python -m PyInstaller --noconfirm --clean --windowed --onedir --name SentinelCrier --paths $repo --specpath build desktop/launch.py
    if ($LASTEXITCODE -ne 0) { throw 'Desktop packaging failed' }
    Copy-Item -LiteralPath desktop/README.md -Destination dist/SentinelCrier/README.md
    Copy-Item -LiteralPath LICENSE -Destination dist/SentinelCrier/LICENSE
    $program = Join-Path $repo 'dist/SentinelCrier/SentinelCrier.exe'
    $report = Join-Path $repo 'dist/SentinelCrier/smoke-test.json'
    $process = Start-Process -FilePath $program -ArgumentList @('--self-test', '--report', ('"' + $report + '"')) -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(60000)) {
        Stop-Process -Id $process.Id
        throw 'Packaged desktop smoke test timed out'
    }
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $report)) { throw 'Packaged desktop smoke test failed' }
    $result = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    if (-not $result.ok) { throw 'Packaged desktop smoke test did not pass' }
    Compress-Archive -Path dist/SentinelCrier -DestinationPath dist/SentinelCrier-Windows.zip -Force
    Get-FileHash -LiteralPath dist/SentinelCrier-Windows.zip -Algorithm SHA256
} finally {
    Pop-Location
}
