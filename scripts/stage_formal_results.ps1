[CmdletBinding()]
param(
    [string]$SourceRoot = "reports/evaluation",
    [string]$FreezeInputRoot = "",
    [switch]$Replace
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($FreezeInputRoot)) {
    $FreezeInputRoot = Join-Path (Split-Path -Parent $ProjectRoot) "Cognivia_比赛最终提交包_待冻结\_冻结输入"
}
$source = Join-Path $ProjectRoot $SourceRoot
$destination = Join-Path $FreezeInputRoot "06_正式运行结果与评测报告"

$mapping = @{
    "latest-live.json" = "formal-result.json"
    "latest-live.xlsx" = "formal-result.xlsx"
    "latest-live.md" = "metric-report.md"
}

foreach ($sourceName in $mapping.Keys) {
    $sourcePath = Join-Path $source $sourceName
    if (-not (Test-Path -LiteralPath $sourcePath)) { throw "Formal evaluation output missing: $sourcePath" }
}

$report = Get-Content -LiteralPath (Join-Path $source "latest-live.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ($report.run_mode -ne "live" -or $report.stage -ne "formal" -or $report.case_count -ne 50 -or -not $report.run_valid -or -not $report.competition_acceptance.accepted) {
    throw "Formal evaluation report is not an accepted 50-case live result."
}

New-Item -ItemType Directory -Path $destination -Force | Out-Null
foreach ($sourceName in $mapping.Keys) {
    $target = Join-Path $destination $mapping[$sourceName]
    if ((Test-Path -LiteralPath $target) -and -not $Replace) {
        throw "Target already exists; use -Replace after reviewing it: $target"
    }
    Copy-Item -LiteralPath (Join-Path $source $sourceName) -Destination $target -Force
}

[ordered]@{
    status = "staged"
    source = $source
    destination = $destination
    case_count = $report.case_count
    run_id = $report.run_id
    metrics = $report.metrics
} | ConvertTo-Json -Depth 8
