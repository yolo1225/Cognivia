# Stage 0: ai_app_dev baseline

- Status: passed
- Captured at: 2026-08-19T09:17:44.3501677Z
- Git commit: ef2f22616bad865df089f44676f4ffd4e7d42568
- Normal demo: ALLOW_FIXTURE_LLM=false, ENABLE_EVALUATION_OVERRIDES=false.
- Candidate RAG: $(System.Collections.Specialized.OrderedDictionary.environment.rag.index_version), embedding $(System.Collections.Specialized.OrderedDictionary.environment.rag.embedding_model).
- Fixed scenarios: learner_001 initial three-resource generation, first too-hard no-change, and incorrect-content review.

## Formal 50-case evaluation baseline

- Run: $(System.Collections.Specialized.OrderedDictionary.run_id), 50/50 accepted.
- Note: this report ran with valuation_overrides_enabled=True and is a versioned evaluation baseline only, not normal-demo override proof.
- End-to-end: P50 87587 ms, P95 206814 ms.
- Agent P50: generate 58983 ms; review 21072 ms; tutoring 23021 ms.

The redacted frozen manifest is docs/baselines/stage0-ai_app_dev.json; local machine evidence is eports/stage0/latest.json.
