# Agent Contract V10

V10 is the only active runtime contract. Historical database rows keep their stored version, but
superseded contract documentation is not an implementation source and must not be reconstructed.

## Review Boundary

The generation Agent owns professional, personalized resource generation and emits a structured
`review_claims` manifest with each artifact. The manifest contains only professional facts from
semantically reviewable content fields. Learner state, objectives, environment notes, learner
actions, acceptance actions, summaries and personalization prose are excluded by structure.

The review Agent evaluates the manifest through two model channels for factual accuracy and source
traceability, and evaluates package difficulty match and core knowledge coverage. Targeted
re-retrieval and dual-channel recheck occur when channels disagree, evidence is insufficient, a
claim is contradicted, or a target knowledge point lacks a supported professional claim. An empty
supplemental retrieval result does not fail the review; original evidence remains available.

## Publication Decision

A complete package is published atomically when all official metrics pass:

- hallucination rate `< 5%`;
- difficulty match `>= 85%`;
- core knowledge coverage `>= 90%`.

Contradicted, evidence-insufficient and unresolved reviewable claims all contribute to the
hallucination numerator. None, including an empty supplemental retrieval result, is an independent
veto. Automatic local revision runs only when the package fails an official threshold and remains
limited to two rounds. Revision targets affected resources and fields; publication remains atomic.

See `contract-change-request-agent-contract-v10-quality-gates.md` for the approved rationale and
compatibility decision.
