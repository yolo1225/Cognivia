# V2 交互导学智能体：阶段一共同基线

> 状态：已完成  
> 日期：2026-07-28  
> 关联方案：`docs/v2-agents/v2-tutoring-agent-algorithm-implementation-plan.md`

本记录完成路线图“阶段一：共同基线”的导学 Agent 工作包。阶段一只确认契约和可测试输入，不实现导学策略、模型调用、图节点或持久化。

## 已确认的冻结边界

| 项目 | 阶段二实现约束 |
|---|---|
| 正式执行边界 | `InterpretFeedbackInput -> V2TutoringAgent.execute() -> InterpretFeedbackOutput` |
| 契约版本 | `agent-contract-v2` |
| State 所有权 | `interpret_feedback` 节点拥有 `interpret_feedback` State 字段 |
| 可读类型 | `app.agents.contracts`、`app.agents.state` 中的 V2 类型 |
| 禁止修改 | `contracts.py`、`state.py`、适配器、`legacy_*`、`tests/contracts/`、V2 Schema/示例、图节点和 worker |

## 新增基线资产

- `backend/tests/fixtures/v2_tutoring/minimal_feedback_input.json`：首轮 `too_hard` 的最小合法 `InterpretFeedbackInput`。
- `backend/tests/unit/test_v2_tutoring_baseline.py`：仅用冻结 Pydantic 契约验证 fixture；不导入 legacy 类型，也不假定任何导学策略输出。

该 fixture 刻意不携带 `InterpretFeedbackOutput`。`recommended_action`、`needs_generation` 和回复内容属于阶段二算法的责任，不能在阶段一通过写死期望输出来替代实现。

## 基线验证

在项目已有虚拟环境中执行：

```powershell
cd backend
.venv\Scripts\python.exe -m pytest tests/contracts tests/unit/test_agent_execution.py tests/unit/test_v2_tutoring_baseline.py -q
```

验收条件：冻结契约测试、现有 V1 Agent 执行测试和新增 fixture 验证均通过。`pytest-asyncio` 的默认 event-loop scope 仅产生弃用警告，不影响本阶段结果。

## 进入阶段二的门槛

1. 所有上述测试通过；
2. 后续实现只消费该 V2 fixture 和冻结 Input/Output；
3. 模型语义 DTO、策略函数和 fake/mock 模型测试都新增在非冻结文件；
4. 尚未完成阶段三前，不把导学输出接入 Profile Analysis Agent 的实际交叉验证。
