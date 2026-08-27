# Agent Contract V9

V9 keeps the V8 graph topology, six Agent responsibilities, task/thread identity,
formal certified question-bank policy, eighteen-Chunk evidence budget and dual-model
review gates. It changes only the graded-quiz package constraint.

## Contract changes

- `contract_version` is `agent-contract-v9`.
- `GradedQuizContent.questions` accepts **3–8** formal questions.
- A single quiz no longer requires every `QuizLevel`; each question still carries
  `level`, immutable certified `difficulty`, primary `knowledge_id`, and sources.

## Runtime policy

The deterministic selector maps two through six unit knowledge items to an expected
four through eight questions, but emits a valid shorter three-to-five-question quiz
when that is all the matching certified bank can support. Fewer than three matching
questions is a preflight failure: unrelated or temporary questions are never used.

Priority is primary knowledge hit, focus knowledge hit, relation-only supplement,
target-difficulty proximity, uncovered unit members, type balance, then stable ID.
`difficulty` is certified content difficulty and is never rewritten at runtime;
`QuizLevel` describes pedagogical use only.
