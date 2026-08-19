# Agent Contract V5（历史兼容）

> V5 已于 2026-08-19 退出活动运行链。当前唯一活动契约为
> [`agent-contract-v6`](agent-contract-v6.md)。本文件仅用于读取历史运行记录，
> 不得用于新任务、V6 指标计算或新 Agent 实现。

V5 formerly defined the automated flow:

```text
prepare -> profile analysis -> candidate retrieval -> generation -> dual-model review
-> deterministic quality decision -> at most two local revisions -> atomic publication
```

There is no human-review node, execution mode, API, persistence model, or recovery route.
All generated technical claims must be traceable to the active candidate index. The executable
Pydantic models and generated Schema under `docs/contracts/v5/` preserve the historical
wire format only; they are not an active source of truth.
