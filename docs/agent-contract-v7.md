# Agent Contract V7

V7 preserves the V6 multi-agent graph and review gates while changing learning-path
nodes from one knowledge item to a persisted learning unit.

## Breaking Changes

- `contract_version` is `agent-contract-v7`.
- `LearningPathNodeSnapshot.knowledge_id` is replaced by `knowledge_ids`.
- Path nodes add `focus_knowledge_ids` and `recommendation_reason`.
- Retrieved and generated quiz questions add `related_knowledge_ids` while retaining
  one primary `knowledge_id` for diagnosis attribution.

## Invariants

- A learning unit contains one to six atomic knowledge items.
- Focus knowledge IDs are a subset of unit knowledge IDs.
- The LangGraph topology, agent responsibilities, review arbitration, retry limits,
  task/thread identity and publication quality gates are unchanged from V6.
- Resource and node quizzes use only active formal question-bank records.

The executable Pydantic models and generated JSON Schema are the source of truth.
