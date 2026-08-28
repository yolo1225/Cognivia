# Agent Contract V10

V10 is the active runtime contract. V9 and earlier contracts are historical artifacts and must
not be resumed or mixed with V10 quality results.

## Review Boundary

The generation Agent owns professional, personalized resource generation and emits a structured
`review_claims` manifest with each artifact. The manifest contains only professional facts from
semantically reviewable content fields. Learner state, objectives, environment notes, learner
actions, acceptance actions, summaries and personalization prose are excluded by structure.

The review Agent evaluates the manifest through two model channels for factual accuracy and source
traceability, and evaluates package difficulty match and core knowledge coverage. Re-retrieval and
arbitration occur only when channels conflict, differ by more than 10 points, or disagree on pass
status.

## Publication Decision

A complete package is published atomically when all official metrics pass:

- hallucination rate `< 5%`;
- difficulty match `>= 85%`;
- core knowledge coverage `>= 90%`.

Contradicted, evidence-insufficient and unresolved reviewable claims all contribute to the
hallucination numerator. None is an independent veto. Automatic local revision runs only when the
package fails an official threshold and remains limited to two rounds.

See `contract-change-request-agent-contract-v10-quality-gates.md` for the approved rationale and
compatibility decision.
