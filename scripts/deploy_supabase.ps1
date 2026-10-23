param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-z]{20}$')][string]$ProjectRef,
    [string]$Python = 'python',
    [switch]$SkipLogin
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    # Interactive CLI login and database-password prompts keep secrets out of
    # this script, command arguments, source configuration, and output files.
    if (-not $SkipLogin) {
        & npx --yes supabase@2.122.0 login
        if ($LASTEXITCODE -ne 0) { throw 'Supabase login did not complete.' }
    }
    & npx --yes supabase@2.122.0 link --project-ref $ProjectRef
    if ($LASTEXITCODE -ne 0) { throw 'Could not link the selected Supabase project.' }
    & npx --yes supabase@2.122.0 db push --linked
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed; connection URL was not changed.' }
    & npx --yes supabase@2.122.0 functions deploy crier --project-ref $ProjectRef
    if ($LASTEXITCODE -ne 0) { throw 'Function deployment failed; connection URL was not changed.' }
    $serviceBase = "https://$ProjectRef.supabase.co/functions/v1/crier"
    & $Python scripts/configure_connection_service.py $serviceBase --verify
    if ($LASTEXITCODE -ne 0) { throw 'Deployed service readiness failed; connection URL was not changed.' }
    Write-Output 'Deployment verified. Rebuild each app to bundle the shared service URL.'
} finally {
    Pop-Location
}
