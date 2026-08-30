param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet("capture", "verify")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$ReportDirectory = Join-Path $ProjectRoot "reports/stage0"
$MachineReportPath = Join-Path $ReportDirectory "latest.json"
$FrozenDirectory = Join-Path $ProjectRoot "docs/baselines"
$FrozenReportPath = Join-Path $FrozenDirectory "stage0-ai_app_dev.json"
$SummaryPath = Join-Path $ProjectRoot "docs/stage0-baseline.md"
$FormalReportPath = Join-Path $ProjectRoot "reports/evaluation/latest-live.json"
$FingerprintPaths = @(
    "AGENTS.md",
    "docker-compose.yml",
    ".env.example",
    "backend/pyproject.toml",
    "scripts/stage0-baseline.ps1",
    "test_script/demo_acceptance.py",
    "data/seed/ai_app_dev_domain.json",
    "data/seed/knowledge_items.json",
    "data/seed/diagnostic_questions.json",
    "data/evaluation_cases/p0_cases.json"
)
$BaselineScope = @(
    "backend",
    "frontend",
    "scripts",
    "test_script",
    "data/seed",
    "data/evaluation_cases",
    "docker-compose.yml",
    ".env.example",
    "AGENTS.md",
    "docs/project-conventions.md",
    "docs/agent-contract-v10.md",
    "docs/contracts/v10"
)

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Write-Host "==> $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

function Get-FingerprintMap {
    $fingerprints = @{}
    foreach ($relativePath in $FingerprintPaths) {
        $absolutePath = Join-Path $ProjectRoot $relativePath
        if (-not (Test-Path -LiteralPath $absolutePath)) {
            throw "Baseline input is missing: $relativePath"
        }
        $fingerprints[$relativePath] = (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return $fingerprints
}

function Assert-CleanBaselineScope {
    $changes = @(& git status --porcelain -- $BaselineScope)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect Git status for the baseline scope."
    }
    if ($changes.Count -gt 0) {
        throw "Baseline capture requires committed runtime inputs. Commit or stash these scoped changes first:`n$($changes -join "`n")"
    }
}

function Get-Health {
    $response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health/dependencies" -TimeoutSec 15
    if (-not $response.data) {
        throw "Health response has no data payload."
    }
    return $response.data
}

function Assert-DemoHealth {
    param([Parameter(Mandatory = $true)]$Health)

    if ($Health.database.status -ne "ok" -or $Health.chroma.status -ne "ok") {
        throw "Database or ChromaDB is not healthy."
    }
    if (-not $Health.ready_for_live_demo -or -not $Health.rag.ready) {
        throw "Live model channels or Candidate RAG are not ready."
    }
    if ($Health.fixture_enabled) {
        throw "ALLOW_FIXTURE_LLM must be false for stage0."
    }
    if ($Health.evaluation_overrides_enabled) {
        throw "ENABLE_EVALUATION_OVERRIDES must be false for the normal demo baseline."
    }
    if ($Health.evaluation_runner_enabled) {
        throw "ENABLE_EVALUATION_RUNNER must be false for the normal demo baseline."
    }
    if (-not $Health.review_models_distinct) {
        throw "Primary and secondary review models must be distinct."
    }
}

function Get-CurrentCaseSetHash {
    $pythonCode = "import sys; sys.path.insert(0, '/app/test_script'); import evaluate; from run_live import _case_set_sha256; cases, _ = evaluate.load_cases(); print(_case_set_sha256(cases))"
    $output = @(& docker compose exec --no-TTY backend python -c $pythonCode)
    if ($LASTEXITCODE -ne 0 -or $output.Count -eq 0) {
        throw "Could not calculate the current evaluation case-set hash."
    }
    return [string]$output[-1]
}

function Get-FormalEvaluationEvidence {
    param([Parameter(Mandatory = $true)]$Health)

    if (-not (Test-Path -LiteralPath $FormalReportPath)) {
        throw "Formal 50-case report is missing: $FormalReportPath"
    }
    $formal = Get-Content -LiteralPath $FormalReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($formal.status -ne "passed" -or -not $formal.run_complete -or -not $formal.run_valid) {
        throw "The formal evaluation report is not a valid completed pass."
    }
    if ([int]$formal.case_count -ne 50 -or [int]$formal.evaluated_case_count -ne 50 -or -not $formal.competition_acceptance.accepted) {
        throw "The formal evaluation report does not prove a 50/50 accepted run."
    }
    $currentCaseHash = Get-CurrentCaseSetHash
    if ($formal.full_suite_case_sha256 -ne $currentCaseHash) {
        throw "Formal evaluation case-set hash differs from the current suite; rerun smoke, regression, then formal."
    }
    $formalRag = $formal.rag_configuration
    if (
        $formalRag.source_data_version -ne $Health.rag.source_data_version -or
        $formalRag.index_version -ne $Health.rag.index_version -or
        $formalRag.embedding_model -ne $Health.rag.embedding_model -or
        [int]$formalRag.embedding_dimensions -ne [int]$Health.rag.embedding_dimensions
    ) {
        throw "Formal evaluation RAG fingerprint differs from the current Candidate RAG; rerun smoke, regression, then formal."
    }
    $models = $formal.model_configuration
    if (
        $models.generation_model -ne $Health.generation_model.model_name -or
        $models.primary_review_model -ne $Health.primary_review_model.model_name -or
        $models.secondary_review_model -ne $Health.secondary_review_model.model_name -or
        $models.evaluation_overrides_enabled -or
        -not $models.evaluation_runner_enabled
    ) {
        throw "Formal evaluation model configuration differs from the current runtime, or was not an isolated runner run."
    }
    return [ordered]@{
        report_path = "reports/evaluation/latest-live.json"
        run_id = $formal.run_id
        case_count = $formal.case_count
        evaluated_case_count = $formal.evaluated_case_count
        accepted = $formal.competition_acceptance.accepted
        case_set_sha256 = $formal.full_suite_case_sha256
        evaluation_overrides_enabled = $models.evaluation_overrides_enabled
        evaluation_runner_enabled = $models.evaluation_runner_enabled
        role = "versioned isolated evaluation baseline; no learning-goal profile override"
        latency_ms = $formal.metrics.latency_ms
        agent_latency_ms = $formal.metrics.agent_latency_ms
    }
}

function Invoke-StaticChecks {
    Invoke-Checked "Backend Ruff" { docker compose exec --no-TTY backend python -m ruff check app tests }
    Invoke-Checked "Backend compileall" { docker compose exec --no-TTY backend python -m compileall -q app tests }
    Invoke-Checked "Backend tests" { docker compose exec --no-TTY backend python -m pytest -q }
    Invoke-Checked "Frontend lint" { docker compose exec --no-TTY frontend npm run lint }
    Invoke-Checked "Frontend tests" { docker compose exec --no-TTY frontend npm run test }
    Invoke-Checked "Frontend build" { docker compose exec --no-TTY frontend npm run build }
}

function Assert-SeedData {
    $knowledge = Get-Content -LiteralPath (Join-Path $ProjectRoot "data/seed/knowledge_items.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $questions = Get-Content -LiteralPath (Join-Path $ProjectRoot "data/seed/diagnostic_questions.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($knowledge.Count -lt 50 -or $questions.Count -lt 60) {
        throw "Seed data does not meet the stage0 minimum knowledge/question counts."
    }
    $missingSources = @($knowledge | Where-Object { [string]::IsNullOrWhiteSpace($_.source_title) })
    if ($missingSources.Count -gt 0) {
        throw "Knowledge seed contains items without source_title."
    }
    return [ordered]@{
        knowledge_item_count = $knowledge.Count
        diagnostic_question_count = $questions.Count
        missing_source_title_count = $missingSources.Count
    }
}

function Invoke-Stage0DemoAcceptance {
    if ([string]::IsNullOrWhiteSpace($env:EVALUATION_PASSWORD)) {
        throw "Set EVALUATION_PASSWORD before capture; it is read only from the process environment."
    }
    $venvPython = Join-Path $ProjectRoot "backend/.venv/Scripts/python.exe"
    $python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
    # The acceptance script writes its human-readable JSON to stdout. Route that
    # stream to the host so it cannot become a second function return value and
    # obscure the parsed, redacted report returned below.
    Invoke-Checked "Stage0 live demo acceptance" {
        & $python test_script/demo_acceptance.py --suite stage0 | Out-Host
    }
    $demoReportPath = Join-Path $ProjectRoot "reports/demo/latest.json"
    if (-not (Test-Path -LiteralPath $demoReportPath)) {
        throw "Stage0 demo acceptance did not create reports/demo/latest.json."
    }
    return (Get-Content -LiteralPath $demoReportPath -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Get-RouteStatus {
    $routes = @("/", "/dashboard", "/resources", "/report", "/metrics", "/domain-hub")
    $result = @{}
    foreach ($route in $routes) {
        try {
            $response = Invoke-WebRequest -Uri ("http://localhost:5173" + $route) -TimeoutSec 15 -UseBasicParsing
            $result[$route] = $response.StatusCode
        } catch {
            throw "Frontend route $route is not reachable: $($_.Exception.Message)"
        }
    }
    return $result
}

function Write-FrozenSummary {
    param([Parameter(Mandatory = $true)]$Artifact)

    New-Item -ItemType Directory -Path $FrozenDirectory -Force | Out-Null
    $Artifact | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $FrozenReportPath -Encoding UTF8
    $formal = $Artifact.formal_evaluation
    $lines = @(
        "# Stage 0: ai_app_dev baseline",
        "",
        "- Status: $($Artifact.status)",
        "- Captured at: $($Artifact.captured_at)",
        "- Git commit: $($Artifact.git.commit)",
        "- Normal demo: `ALLOW_FIXTURE_LLM=false`, `ENABLE_EVALUATION_OVERRIDES=false`, `ENABLE_EVALUATION_RUNNER=false`.",
        "- Candidate RAG: `$($Artifact.environment.rag.index_version)`, embedding `$($Artifact.environment.rag.embedding_model)`.",
        "- Fixed scenarios: `learner_001` initial three-resource generation, first too-hard no-change, and incorrect-content review.",
        "",
        "## Formal 50-case evaluation baseline",
        "",
        "- Run: `$($formal.run_id)`, $($formal.evaluated_case_count)/$($formal.case_count) accepted.",
        "- Note: this report used the isolated evaluation runner; learning-goal profile overrides remained disabled.",
        "- End-to-end: P50 $($formal.latency_ms.p50) ms, P95 $($formal.latency_ms.p95) ms.",
        "- Agent P50: generate $($formal.agent_latency_ms.generate_resource.p50) ms; review $($formal.agent_latency_ms.review_resource.p50) ms; tutoring $($formal.agent_latency_ms.interpret_feedback.p50) ms.",
        "",
        "The redacted frozen manifest is `docs/baselines/stage0-ai_app_dev.json`; local machine evidence is `reports/stage0/latest.json`."
    )
    $lines | Set-Content -LiteralPath $SummaryPath -Encoding UTF8
}

function Assert-FrozenArtifact {
    if (-not (Test-Path -LiteralPath $FrozenReportPath)) {
        throw "Frozen stage0 artifact is missing. Run capture after committing runtime inputs."
    }
    $artifact = Get-Content -LiteralPath $FrozenReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($artifact.status -ne "passed" -or $artifact.schema_version -ne "stage0-baseline-v1") {
        throw "Frozen stage0 artifact is not a passed stage0-baseline-v1 result."
    }
    $current = Get-FingerprintMap
    foreach ($name in $current.Keys) {
        $frozenValue = $artifact.fingerprints.PSObject.Properties[$name].Value
        if ($frozenValue -ne $current[$name]) {
            throw "Frozen fingerprint drift detected: $name"
        }
    }
    $health = Get-Health
    Assert-DemoHealth $health
    $formal = Get-FormalEvaluationEvidence $health
    if ($artifact.formal_evaluation.case_set_sha256 -ne $formal.case_set_sha256) {
        throw "Frozen formal evaluation fingerprint drift detected."
    }
    Write-Host "Stage0 verification passed."
}

if ($Action -eq "verify") {
    Assert-FrozenArtifact
    exit 0
}

Assert-CleanBaselineScope
Invoke-Checked "Docker service check" { docker compose ps --status running }
$health = Get-Health
Assert-DemoHealth $health
$routes = Get-RouteStatus
Invoke-StaticChecks
$seed = Assert-SeedData
$formal = Get-FormalEvaluationEvidence $health
$demo = Invoke-Stage0DemoAcceptance
if ($demo.status -ne "passed" -or $demo.suite -ne "stage0") {
    throw "Stage0 demo acceptance failed."
}

New-Item -ItemType Directory -Path $ReportDirectory -Force | Out-Null
$artifact = [ordered]@{
    schema_version = "stage0-baseline-v1"
    status = "passed"
    domain_code = "ai_app_dev"
    captured_at = (Get-Date).ToUniversalTime().ToString("o")
    git = [ordered]@{
        commit = (& git rev-parse HEAD).Trim()
        working_tree_clean = $true
    }
    fingerprints = Get-FingerprintMap
    environment = [ordered]@{
        frontend_routes = $routes
        database_status = $health.database.status
        chroma_status = $health.chroma.status
        fixture_enabled = [bool]$health.fixture_enabled
        evaluation_overrides_enabled = [bool]$health.evaluation_overrides_enabled
        evaluation_runner_enabled = [bool]$health.evaluation_runner_enabled
        generation_model = $health.generation_model.model_name
        primary_review_model = $health.primary_review_model.model_name
        secondary_review_model = $health.secondary_review_model.model_name
        rag = [ordered]@{
            ready = [bool]$health.rag.ready
            source_data_version = $health.rag.source_data_version
            index_version = $health.rag.index_version
            embedding_model = $health.rag.embedding_model
            embedding_dimensions = $health.rag.embedding_dimensions
        }
    }
    seed = $seed
    formal_evaluation = $formal
    demo_acceptance = $demo
    commands = @(
        ".\\scripts\\stage0-baseline.ps1 capture",
        "python test_script/demo_acceptance.py --suite stage0",
        ".\\scripts\\stage0-baseline.ps1 verify"
    )
}
$artifact | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $MachineReportPath -Encoding UTF8
Write-FrozenSummary $artifact
Write-Host "Stage0 baseline capture passed."
