# Agent Contract V5

V5 is the only active Agent contract. It defines the automated flow:

```text
prepare -> profile analysis -> candidate retrieval -> generation -> dual-model review
-> deterministic quality decision -> at most two local revisions -> atomic publication
```

There is no human-review node, execution mode, API, persistence model, or recovery route.
All generated technical claims must be traceable to the active candidate index. The executable
Pydantic models in `backend/app/agents/contracts.py` and the generated schema under
`docs/contracts/v5/` are the source of truth.
