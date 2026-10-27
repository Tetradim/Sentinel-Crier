param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    $serviceResource = (Join-Path $repo 'crier/connection-service.json') + ';crier'
    $practiceResource = (Join-Path $repo 'crier/customer-practice.json') + ';crier'
    $crierBuildCommit = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $crierBuildCommit -notmatch '^[a-f0-9]{40}$') { throw 'Cannot identify source commit for support diagnostics' }
    New-Item -ItemType Directory -Path (Join-Path $repo 'build') -Force | Out-Null
    $crierBuildInfo = Join-Path $repo 'build/build-info.json'
    @{schema=1;version=(Get-Content -LiteralPath release.json -Raw | ConvertFrom-Json).version;commit=$crierBuildCommit} | ConvertTo-Json | Set-Content -LiteralPath $crierBuildInfo -Encoding UTF8
    $crierBuildResource = $crierBuildInfo + ';crier'
    & $Python -m PyInstaller --noconfirm --clean --windowed --onedir --name SentinelCrier --paths $repo --add-data $serviceResource --add-data $practiceResource --add-data $crierBuildResource --hidden-import pystray._win32 --specpath build desktop/launch.py
    if ($LASTEXITCODE -ne 0) { throw 'Desktop packaging failed' }
    & $Python desktop/third_party.py dist/SentinelCrier/third-party
    if ($LASTEXITCODE -ne 0) { throw 'Desktop dependency source/notice packaging failed' }
    Copy-Item -LiteralPath desktop/README.md -Destination dist/SentinelCrier/README.md
    Copy-Item -LiteralPath release.json -Destination dist/SentinelCrier/release.json
    Copy-Item -LiteralPath LICENSE -Destination dist/SentinelCrier/LICENSE
    $program = Join-Path $repo 'dist/SentinelCrier/SentinelCrier.exe'
    $report = Join-Path $repo 'dist/SentinelCrier/smoke-test.json'
    $process = Start-Process -FilePath $program -ArgumentList @('--self-test', '--report', ('"' + $report + '"')) -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(60000)) {
        Stop-Process -Id $process.Id
        throw 'Packaged desktop smoke test timed out'
    }
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $report)) {
        if (Test-Path -LiteralPath $report) {
            $crierFailure = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
            if ($crierFailure.exception_type -match '^[A-Za-z_][A-Za-z0-9_]{0,99}$') { Write-Output ('Self-test error type: ' + $crierFailure.exception_type) }
            foreach ($crierFrame in $crierFailure.stack) {
                if ($crierFrame.file -match '^[A-Za-z0-9_.-]{1,120}$' -and $crierFrame.function -match '^[A-Za-z0-9_<>.]{1,120}$') {
                    Write-Output ('Self-test location: ' + $crierFrame.file + ':' + $crierFrame.line + ' ' + $crierFrame.function)
                }
            }
        }
        throw 'Packaged desktop smoke test failed'
    }
    $result = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    if (-not $result.ok) { throw 'Packaged desktop smoke test did not pass' }
    Compress-Archive -Path dist/SentinelCrier -DestinationPath dist/SentinelCrier-Windows.zip -Force
    Get-FileHash -LiteralPath dist/SentinelCrier-Windows.zip -Algorithm SHA256
} finally {
    Pop-Location
}
