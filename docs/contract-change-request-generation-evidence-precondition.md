# Agent Contract V3 Change Request: Generation Evidence Precondition

## Requested rule

When `GenerationRequirements` is constructed, every value in
`required_knowledge_ids` must be present in the immediately preceding
`RetrieveKnowledgeOutput.covered_knowledge_ids`, and at least one retrieved
source must map to each required knowledge ID. `resource_knowledge_targets`
must remain non-empty per requested resource type and its union must continue
to equal `required_knowledge_ids`.

The adapter must reject the transition before `generate_resource` when this
cross-node precondition is not satisfied. It must not silently remove an
unavailable target or ask the model to generate content without evidence.

## Affected contracts

- Input/output: `RetrieveKnowledgeOutput` -> `GenerateResourceInput`
- Nested model: `GenerationRequirements`
- Review input constructed from the same requirements: `ReviewResourceInput`

## Producing and consuming nodes

- Producer: `retrieve_knowledge`
- Consumers: `generate_resource`, `review_resource`

## Reason and expected behavior

The current adapter can select ten planned targets while retrieval is limited
to eight chunks. This creates resources that can never reach the 90% coverage
threshold and triggers expensive, ineffective generation/review revisions.

Profile analysis must size `n_results` to cover the bounded generation target
set. If an indexed source is genuinely unavailable, the task fails with a
controlled `generation_missing_target_evidence` error before any generation
model call.

## Nullability and defaults

No field, nullability, enum, or default change is requested.

## Compatibility impact

This is a backward-compatible V3 invariant tightening. Valid V3 payloads are
unchanged. Payloads that previously reached generation without evidence are
rejected earlier. The contract maintainer must update the executable adapter,
contract examples, generated Schema artifacts if their metadata changes, and
contract tests together.
