# Agent Contract V10 Change Request: Official Quality Gates

- Status: pending contract-maintainer approval
- Requested version: `agent-contract-v10`
- Requested quality rule: `quality-v8-official-gates`
- Supersedes for new runs: `agent-contract-v9` / `quality-v6-20260818`
- Historical compatibility: V9 records remain immutable and readable

## Reason

The official competition evaluates three quality metrics: hallucination rate below 5%,
learner-resource difficulty match at least 85%, and core knowledge coverage at least 90%.
The active V9 quality models additionally require
`evidence_insufficient_claim_count == 0` and `unresolved_claim_count == 0`. That extra
zero-tolerance publication gate can fail a package even when all three official metrics
pass. It also causes repeated retrieval and revision for pedagogical or learner-context
text that should not be treated as a professional fact.

V10 should make the reviewed claim set explicit, count every unsupported reviewable
professional claim in the hallucination metric, and derive package publication only from
the three official package-level thresholds.

## Requested Models And Rules

### `ReviewClaim` (new model)

Fields:

- `claim_id: str`, required, no default. Stable hash of resource type, field path and
  normalized claim text.
- `resource_type: ResourceType`, required, no default.
- `field_path: str`, required, no default. Must resolve inside the generated structured
  resource.
- `claim_kind: ReviewClaimKind`, required, no default.
- `claim: str`, required, no default.
- `source_ref_ids: list[str]`, required, no default. Every ID must belong to the
  resource source whitelist.

`ReviewClaimKind` values:

- `professional_fact`
- `operational_fact`
- `code_behavior`
- `expected_result`
- `error_handling`

Producing node: `generate_resource` constructs the canonical list at the generation
boundary from semantically owned structured fields. The model must not freely decide
whether prose is reviewable.

Consuming node: `review_resource` sends the same canonical list to both review channels.
`finalize_task` consumes only the derived package metrics, not individual claim verdicts.

Compatibility: breaking. V9 resources do not receive a synthetic V10 claim list and must
not resume inside a V10 checkpoint.

### `GeneratedResourceArtifact.review_claims` (new field)

- Type: `list[ReviewClaim]`
- Required for V10, no default.
- Must contain only professional facts, operational conclusions, code behavior, expected
  results and troubleshooting conclusions.
- Teaching actions, organizational prose, personalization wording and learner-state
  descriptions are excluded.
- Every claim must match its field path and cited source IDs; duplicate claim IDs and
  claims outside the resource are invalid.

Producing node: `generate_resource`.

Consuming nodes: `review_resource`, offline evaluation adapters and authorized trace
serialization.

### Structured practice content (breaking field semantics)

Replace ambiguous free-text environment prerequisites with a structured requirement
model that distinguishes:

- runtime or tool facts, which carry source IDs and produce review claims;
- learner prerequisites or preparation actions, which do not assert learner mastery and
  do not produce review claims.

Practice step `instruction` remains a learner action. Technical rationale belongs in an
optional sourced factual field; `code_or_command`, `expected_result` and
`troubleshooting` remain reviewable fields. Acceptance criteria are learner checks;
technical fixed-result assertions remain in `expected_result`.

Producing node: `generate_resource`.

Consuming nodes: `review_resource`, renderers, persistence serializers and resource API
adapters.

Compatibility: breaking JSON shape for newly generated practice guides. Historical V9
structured content remains version-rendered without data migration.

### `ResourceQualityMetrics` and `GenerationPackageQuality` (rule change)

Keep the existing count and score fields, but change deterministic rules for V10:

- `hallucinated_claim_count == contradicted_claim_count +
  evidence_insufficient_claim_count + unresolved_claim_count`.
- `hallucination_rate == 100 * hallucinated_claim_count /
  verifiable_claim_count`, or zero when the denominator is zero.
- `GenerationPackageQuality.passed` is true exactly when there is at least one
  verifiable claim, hallucination rate is below 5%, difficulty match is at least 85%,
  target knowledge is non-empty and core knowledge coverage is at least 90%.
- Evidence-insufficient and unresolved counts have no independent zero-tolerance gate.
- Resource-level reports are diagnostic contributors. Their `passed` value must not be
  required independently when the complete package passes its three aggregate metrics.

Producing node: `review_resource`.

Consuming nodes: `finalize_task`, generation persistence, learning-package publication,
resource APIs, evaluation and stability scripts.

Compatibility: breaking quality semantics. The `quality_rule_version` literal must be
updated; V9 and V10 metrics must never be aggregated in one evaluation run.

### `FinalizeTaskInput` and final decision rule

No new nullable data is required if the existing package-quality object is retained.
Change the rule so a complete expected resource/report set with
`package_quality.passed == true` completes, without requiring
`all(report.passed)` or a separate evidence-insufficient gate.

Producing node: `review_resource` through the contract adapter.

Consuming node: `finalize_task`.

Compatibility: breaking decision semantics; requires V10 checkpoint isolation.

## Package Metric Aggregation

- Hallucination rate uses the canonical review claims from all three package resource
  types. Certified quiz claims use their deterministic certification verdicts.
- Difficulty match aggregates the three requested resource types with equal weight; it
  is not weighted by prose or claim count.
- Core knowledge coverage is the union of correctly supported teaching content in the
  lecture and practice guide. Quiz questions cannot backfill missing teaching coverage.
- Package publication is atomic and depends only on these three metrics.

## Arbitration And Revision

- Re-retrieval and dual-model arbitration run only for conflicting fact verdicts, a
  score difference greater than 10 points, or conflicting pass conclusions.
- Two channels that both return evidence-insufficient contribute to hallucination rate
  without an arbitration loop.
- Revision starts only when package metrics fail, targets contributing fields/resources,
  and remains limited to two rounds.
- A passing package completes immediately; deterministic convergence is not run merely
  to force evidence-insufficient or unresolved counts to zero.

## API And Historical Retry Impact

- Existing response envelopes and metric field names remain stable; the quality and
  contract version values change for new tasks.
- Failed metric details should expose the three failed thresholds and actual values.
- Explicit retry of a terminal V9 policy failure creates a fresh V10 successor task with
  `source_task_id`; it does not mutate the V9 task or reuse its checkpoint.
- Transient same-version failures may continue to use checkpoint recovery.

## Required Generated Artifacts And Tests

The contract maintainer must update and regenerate together:

- executable contracts, State and contract adapters;
- V10 JSON Schema and examples;
- contract tests and active contract documentation;
- compatibility constants used by APIs, workers and evaluation scripts.

Required contract examples include:

- one evidence-insufficient claim out of 36 produces 2.78% hallucination and a passing
  package when difficulty and coverage pass;
- two out of 36 produces 5.56% and a failing package;
- learner-state and teaching-action text is absent from `review_claims`;
- an unsupported code behavior is present and counted;
- a complete passing package may contain a resource-level diagnostic warning;
- a V9 checkpoint cannot resume as V10.

## Approval Record

- Decision: approved
- Approved by: designated Agent contract maintainer (repository owner/user)
- Approval date: 2026-08-28
- Final contract version: `agent-contract-v10`
- Final quality rule version: `quality-v8-official-gates`
