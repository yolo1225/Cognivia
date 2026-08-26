# Agent Contract V8

V8 preserves the V7 multi-knowledge learning units, multi-agent graph, formal
question-bank policy and review gates while expanding the shared evidence budget for
combined learning units.

## Contract Changes

- `contract_version` is `agent-contract-v8`.
- `RetrievalPlan.n_results` accepts 1–18 results and defaults to 12.
- `RetrieveKnowledgeOutput.chunks` accepts at most 18 chunks.
- `GenerateResourceInput.retrieved_chunks` accepts at most 18 chunks.
- `ReviewResourceInput.evidence` accepts at most 18 chunks.

## Evidence Budget Policy

- Ordinary retrieval remains near 12 chunks.
- Multi-knowledge quiz units dynamically reserve evidence for up to six node knowledge
  items, six formal quiz primary sources and a small prerequisite/unit context allowance.
- The hard limit is 18 chunks. Node targets and selected quiz sources have higher priority
  than prerequisite, related and semantic supplements.
- If required evidence cannot fit, the system must reselect questions or report an explicit
  evidence-budget failure; it must not remove node targets or quiz sources silently.

## Invariants

- A learning unit still contains one to six atomic knowledge items.
- The LangGraph topology, six Agent responsibilities, task/thread identity, formal
  question-bank-only quiz generation, dual-model review and publication quality gates are
  unchanged from V7.

The executable Pydantic models and generated JSON Schema are the source of truth.
