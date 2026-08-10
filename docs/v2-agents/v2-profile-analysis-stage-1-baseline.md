# V2 学情分析阶段一基线

> 记录日期：2026-07-26
> 分支：`codex/profile-analysis-agent-v2`
> 领域配置版本：`ai_app_dev_profile_v1`

## 阶段一产物

- `ai_app_dev` 的 50 个种子知识点均有显式五维能力权重，单项权重和为 1。
- 配置固定初始画像先验、掌握度阈值、更新上限和检索数量上限；本阶段不执行画像算法。
- 开发集 30 例、冻结验收集 20 例，覆盖首次诊断、薄弱点与前置知识、单次反馈不更新、确认评估更新及资源错误复核。
- fixture 仅包含 V2 正式契约允许的脱敏输入和预期决策断言，不含题干、原始答案或真实学习者信息。

## 验收基线完整性

- 验收 manifest 使用 `canonical-json-sha256-v1`：对完整 JSON 内容按键排序、紧凑序列化后计算 SHA-256，因此 LF/CRLF 换行差异不会改变基线结果。
- manifest 同时保存每个验收案例的规范化哈希；任何案例内容、案例 ID、领域配置版本或种子知识指纹不一致都会阻断评测。
- 正式评测命令为：`python -m app.scripts.evaluate_profile_v2`。该命令先校验冻结 manifest，失败时输出非零状态，不会报告形式上的通过结果。

## Docker 测试记录

Compose `backend` 服务已通过 `./docs:/app/docs:ro` 只读挂载冻结契约 Schema，可执行完整契约测试。推荐命令：

```powershell
docker compose exec -T backend python -m pytest tests/contracts/test_agent_contract_v2.py tests/unit/test_profile_v2_fixtures.py tests/unit/test_profile_v2_case_execution.py -q
docker compose exec -T backend python -m app.scripts.evaluate_profile_v2
docker compose exec -T backend python -m compileall app tests
```
