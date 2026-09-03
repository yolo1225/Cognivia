# 可复现评测

当前运行契约为 `agent-contract-v10`。评测分别统计任务执行成功率和已审核学习包的官方质量指标；
不得把生成阶段 warning、空补检索或单项证据能力缺失直接记为任务失败。矛盾、证据不足和未解决
专业声明按 V10 统一进入幻觉率分子。

`data/evaluation_cases/*.json` 是唯一事实来源。运行：

```powershell
python test_script/evaluate.py --xlsx
```

该命令生成 baseline 报告。案例文件中的 `observed_result` 只是可复现基准，不代表真实模型结果。

真实模型必须按顺序运行：

```powershell
python test_script/run_live.py --stage smoke
python test_script/run_live.py --stage regression
python test_script/run_live.py --stage formal --xlsx
python test_script/stability.py
```

每个案例完成后都会写入运行检查点。若客户端或 Docker 在长跑中断，使用报告文件名中的
运行 ID 恢复，脚本会校验阶段、完整案例集与阶段案例集哈希、模型配置、知识库版本、RAG
索引和案例范围后只运行缺失案例：

```powershell
python test_script/run_live.py --stage formal --resume-run-id live-formal-YYYYMMDDTHHMMSSZ --xlsx
```

运行前必须配置三个真实模型并设置 `ALLOW_FIXTURE_LLM=false`。live runner 通过 `/api/v1` 创建任务、等待任务终态、读取脱敏 Agent 运行记录，并将原始运行证据保存到 `reports/evaluation/runs/{run_id}.json`。

`regression` 只接受与当前完整案例集、模型、知识版本和RAG配置完全一致的 `smoke`
通过记录；`formal` 同理只接受当前配置的 `regression`。单案例 `--case-id` 是独立诊断，固定
标记为 `diagnostic_only`，不会成为后续阶段凭据。

脚本会校验案例唯一性，计算幻觉率、难度匹配、核心知识覆盖、审核/画像结论准确率、任务成功率、端到端业务时延 P50/P95、超 120 秒延迟率及各 Agent P50/P95。`run_live.py` 同时记录触发请求返回 `task_id` 的接口确认时延；它与端到端业务时延分开统计，不能用异步入队确认代替资源可用时间。输出：

- `reports/evaluation/latest.json`
- `reports/evaluation/latest.md`
- `reports/evaluation/latest.xlsx`（使用 `--xlsx` 时）
- `reports/evaluation/latest-live.json`
- `reports/evaluation/latest-live.md`
- `reports/evaluation/latest-live.xlsx`（正式运行使用 `--xlsx` 时）

每项比例均保留分子、分母、失败案例 ID 和无法判定声明。

## 阶段 0 主领域基线

普通演示环境必须关闭 `ALLOW_FIXTURE_LLM` 和 `ENABLE_EVALUATION_OVERRIDES`。在提交所有
运行时输入后，设置仅存在于进程环境中的 `EVALUATION_PASSWORD`，再运行：

```powershell
.\scripts\stage0-baseline.ps1 capture
```

脚本会执行 Docker 健康检查、后端/前端静态与测试检查、固定的真实演示分支和正式 50 例
报告指纹校验。后续回归使用 `.\scripts\stage0-baseline.ps1 verify`；该命令不创建任务、
不调用模型。固定演示分支也可以单独运行：

```powershell
python test_script/demo_acceptance.py --suite stage0
```

live 与稳定性报告会将失败归入 `program_defect`、`knowledge_data_gap`、
`case_defect`、`external_service_failure` 或 `operations_failure`，并保存终态、
字段路径和判定依据。`evidence_gap` 会先核对案例合同与本地知识证据能力，不能自动
归咎于知识数据或案例。稳定性报告逐任务写入 `reports/stability/`，包含5次完整生成、
5次部分刷新、唯一主目标映射、完整案例集哈希、知识版本、模型和RAG配置。
