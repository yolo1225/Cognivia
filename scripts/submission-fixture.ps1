[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("verify", "bootstrap")]
    [string]$Action,
    [string]$FixtureDir = "data/submission_fixtures/ai_app_dev_v1",
    [string]$ComposeProject,
    [string[]]$ComposeFile = @(),
    [switch]$SkipIndex
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $composePrefix = @()
    if ($ComposeProject) {
        $env:SUBMISSION_STACK_NAME = $ComposeProject -replace '[^a-zA-Z0-9_-]', ''
        $composePrefix += @("-p", $ComposeProject)
    }
    if ($ComposeFile.Count -gt 0) {
        $composePrefix += @("-f", "docker-compose.yml")
    }
    foreach ($file in $ComposeFile) {
        $composePrefix += @("-f", $file)
    }
    & docker compose @composePrefix @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed: $($Arguments -join ' ')"
    }
}

function Invoke-Backend {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $composeArguments = @("exec", "--no-TTY", "backend", "python", "-m", "app.scripts.seed_data")
    $composeArguments += $Arguments
    Invoke-Compose -Arguments $composeArguments
}

function Invoke-ComposeWithRetry {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [int]$Attempts = 10
    )
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            Invoke-Compose -Arguments $Arguments
            return
        }
        catch {
            if ($attempt -eq $Attempts) {
                throw
            }
            Start-Sleep -Seconds 3
        }
    }
}

function Get-ContainerFixtureDir {
    param([string]$LocalPath)
    $absolute = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $LocalPath))
    $dataRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot "data"))
    if (-not $absolute.StartsWith($dataRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "FixtureDir must be located under the repository data directory."
    }
    $relativePath = $absolute.Substring($dataRoot.Length).TrimStart([char[]]@('\', '/')) -replace '\\', '/'
    return "/app/data/$relativePath"
}

$containerFixtureDir = Get-ContainerFixtureDir -LocalPath $FixtureDir
if ($Action -eq "verify") {
    Invoke-Backend -Arguments @("--fixture-dir", $containerFixtureDir, "--verify", "--json")
    exit 0
}

Write-Host "Bootstrap never clears Docker volumes. Use a new clone or an already empty database."
Invoke-Compose -Arguments @("up", "--detach", "mysql", "redis", "chromadb", "backend")
Invoke-ComposeWithRetry -Arguments @("exec", "--no-TTY", "backend", "alembic", "upgrade", "head")
Invoke-ComposeWithRetry -Arguments @("exec", "--no-TTY", "backend", "python", "-m", "app.scripts.init_admin")
$fixtureLoad = Invoke-Backend -Arguments @("--fixture-dir", $containerFixtureDir, "--json") | ConvertFrom-Json

$indexResult = $null
if (-not $SkipIndex) {
    Write-Host "Building the Candidate index requires the configured embedding provider."
    $indexResult = Invoke-Compose -Arguments @("exec", "--no-TTY", "backend", "python", "-m", "app.scripts.build_chroma_candidate_index", "--domain-code", $fixtureLoad.domain_code, "--live", "--json") | ConvertFrom-Json
}

$verification = Invoke-Backend -Arguments @("--fixture-dir", $containerFixtureDir, "--verify", "--json") | ConvertFrom-Json
[ordered]@{
    status = "bootstrapped"
    fixture_version = $verification.fixture_version
    fixture_sha256 = $verification.fixture_sha256
    domain_code = $verification.domain_code
    counts = $verification.counts
    database_status = $fixtureLoad.database.status
    index_status = if ($null -eq $indexResult) { "skipped" } else { $indexResult.status }
    index_version = if ($null -eq $indexResult) { $null } else { $indexResult.index_version }
} | ConvertTo-Json -Depth 8
