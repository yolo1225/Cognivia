# Agent Contract V6 治理决议

- 生效日期：2026-08-19
- 决议状态：已批准
- 维护角色：项目指定 Agent Contract 维护者
- 活动版本：`agent-contract-v6`

## 决议

生产运行已经统一使用 `backend/app/agents/contracts.py`、`state.py` 和
`contract_adapters.py` 中的 V6 可执行模型。自本决议生效起，V6 是唯一活动 Agent
Contract，`docs/agent-contract-v6.md` 与 `docs/contracts/v6/` 是对应文档和生成物。

V5 已退出活动运行链。V5 文档和 Schema 仅用于读取历史运行记录，不得用于创建新任务、
实现新 Agent、计算 V6 指标或为 V6 测试提供兼容回退。本决议不修改任何 V6 字段、枚举、
必填性、默认值、State 所有权或顶层 LangGraph 结构。

## 兼容性影响

- 现有 V6 任务、资源、审核报告和评测结果保持兼容。
- V5 历史学习包必须按既有规则完整重新生成后才能进入 V6 局部刷新。
- 普通实现人员继续将合同模型、State、适配器、合同测试、V6 Schema 和样例视为只读。
- 后续合同破坏性变更必须提交合同变更申请并升级版本。

## 校验方式

由合同维护者运行：

```powershell
docker compose exec backend python -m app.scripts.export_agent_contract_v6
docker compose exec backend python -m pytest -q tests/contracts/test_agent_contract_v6.py
```

生成后必须确认 `docs/contracts/v6/` 无非预期差异。
