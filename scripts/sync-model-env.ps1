param()

# Exports the effective model config from the running backend and upserts it
# into the repo root `.env`. Run this after saving model config in the web UI
# when you want the host `.env` to stay in sync (e.g. before a `down -v` reset).
#
# The backend itself never writes the host `.env`; this host-side script owns
# that write, so the app process has no write access to the secrets file.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$EnvFile = Join-Path $ProjectRoot ".env"

# 1. Export the effective config from the backend container.
$exported = @(& docker compose exec --no-TTY backend python -m app.scripts.export_model_env 2>$null)
if ($LASTEXITCODE -ne 0) {
    throw "Failed to export model config. Ensure the backend container is running (docker compose up -d)."
}

$values = [ordered]@{}
foreach ($line in $exported) {
    $line = [string]$line
    if ($line -match '^([A-Za-z0-9_]+)=(.*)$') {
        $values[$matches[1]] = $matches[2]
    }
}
if ($values.Count -eq 0) {
    throw "Exported model config is empty; nothing to sync."
}

# 2. Upsert into .env, preserving existing lines and appending missing keys.
$result = @()
$seen = @{}
if (Test-Path $EnvFile) {
    foreach ($line in (Get-Content $EnvFile -Encoding UTF8)) {
        if ($line -match '^([A-Za-z0-9_]+)\s*=') {
            $key = $matches[1]
            if ($values.Contains($key)) {
                $result += "$key=$($values[$key])"
                $seen[$key] = $true
                continue
            }
        }
        $result += $line
    }
}
foreach ($key in $values.Keys) {
    if (-not $seen.ContainsKey($key)) {
        $result += "$key=$($values[$key])"
    }
}

# 3. Write back with UTF-8 (no BOM) and LF line endings.
$content = ($result -join "`n") + "`n"
[System.IO.File]::WriteAllText($EnvFile, $content, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "Model config synced to .env:"
foreach ($key in $values.Keys) {
    if ($key -eq "OPENAI_API_KEY") {
        Write-Host "  OPENAI_API_KEY = (updated; hidden)"
    } else {
        Write-Host "  $key = $($values[$key])"
    }
}
