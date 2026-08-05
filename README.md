# 云川智汇 - 多智能体个性化知识生成系统

本仓库是“领域知识个性化生成与多智能体协同决策系统”的 MVP 原型工程，主验证领域为 `ai_app_dev`（人工智能应用开发实训）。

## MVP 闭环

```text
learner profile -> diagnosis -> retrieval -> generation -> review -> decision -> feedback -> update
```

## 项目结构

```text
backend/      FastAPI + SQLAlchemy + LangGraph 统一八节点工作流
frontend/     Vue 3 + TypeScript + Vite + Element Plus 演示工作台
data/         领域包、50 个知识点、60 道诊断题和 50 个评测案例
docs/         API、部署、环境和工程规范文档
test_script/  baseline/live 评测与七分支验收入口
storage/      导出文件和运行期本地存储
```

## 快速启动

1. 复制环境变量并填写真实模型配置：

```bash
cp .env.example .env
```

正式验收必须设置三个模型名，并使用 `ALLOW_FIXTURE_LLM=false`。密钥只保存在未提交的 `.env`。

Windows 可以一键完成构建、迁移、种子初始化和索引重建：

```powershell
./scripts/demo.ps1 start
```

对已有 Docker 演示数据进行真实验收前，先执行非破坏性备份：

```powershell
./scripts/demo.ps1 backup
```

它会将 MySQL、Chroma、Compose 状态和 V2 candidate manifest 保存到 `reports/preflight/<timestamp>/`，不会执行 reset。

2. 使用 Docker Compose 构建并启动：

```bash
docker compose up -d --build
```

3. 初始化数据库表、种子数据和 ChromaDB 索引：

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.scripts.seed_data --json
docker compose exec backend python -m app.scripts.build_chroma_index --reset --json
```

4. 验证：

```bash
curl "http://localhost:8000/api/v1/health"
curl "http://localhost:8000/api/v1/health/dependencies"
curl "http://localhost:8000/api/v1/knowledge/items?domain_code=ai_app_dev&limit=60"
curl "http://localhost:8000/api/v1/knowledge/search?query=RAG文档切片&n_results=3"
```

5. 访问：

- Frontend: http://localhost:5173
- Backend: http://localhost:8000/docs
- Health: http://localhost:8000/api/v1/health
- MySQL host connection: `localhost:13306` by default (`MYSQL_HOST_PORT`); containers continue to use `mysql:3306`.

如果只是重启已经初始化过的本地环境：

```bash
docker compose up -d
```

## 演示账号与现场运行

MVP 使用以下内置演示账号和角色，不提供注册、密码找回或复杂权限审批：

| user_id | role | 用途 |
| --- | --- | --- |
| `demo_learner` | learner | 学习者视角 |
| `demo_instructor` | instructor | 培训者视角 |
| `demo_admin` | admin | 管理员视角 |

`demo_learner` 是演示账号；`learner_001` 是业务 API 默认使用的演示学习者实体，两者用途不同。

### 真实模型验收

现场真实验收前，保持 `ALLOW_FIXTURE_LLM=false`，依次执行备份、启动和环境校验：

```powershell
./scripts/demo.ps1 backup
./scripts/demo.ps1 start
./scripts/demo.ps1 verify
```

确认 `live_models_ready=True`、知识点数为 50、诊断题数为 60 后，完成下文的 V2 Candidate 索引验收，再按低成本到高成本的顺序执行：

```powershell
python test_script/run_live.py --stage smoke
python test_script/run_live.py --stage regression
python test_script/run_live.py --stage formal --xlsx
python test_script/probe_sse.py
python test_script/demo_acceptance.py
```

评测结果写入 `reports/evaluation/`，原始运行证据写入 `reports/evaluation/runs/`。SSE 探针会额外创建一个讲义任务并产生模型费用，验证 V2 节点事件顺序、审核仲裁摘要和终态事件；其预检结果写入 `reports/preflight/`。所有 Agent 运行记录必须显示 `provider_mode=live`。

`demo_acceptance.py` 覆盖首次生成、仅解释不更新、多轮证据更新画像、错误复核、挑战任务、两轮修订失败、双模型冲突与原线程人工恢复七类分支，并输出到 `reports/demo/latest.json` 和 `reports/demo/latest.md`。如果异常分支无法在现场稳定复现，可使用历史真实快照：

```powershell
python test_script/demo_acceptance.py --snapshot reports/demo/live-exception-snapshot.json
```

快照中的 `revision_exhausted` 和 `manual_review_resume` 必须包含 `task_id`、`recorded_at`、`model_names` 与 `provider_mode=live`；脚本拒绝 fixture 或未标识快照。

### 10 分钟展示路线

1. 诊断与三类画像，1 分钟。
2. 启动生成任务并观察八节点协作图，2 分钟。
3. 查看三类资源、知识来源和双模型审核，2 分钟。
4. 演示导学消息、画像不更新和证据充分更新，2 分钟。
5. 展示人工复核、资源版本和导出，1.5 分钟。
6. 展示知识增量重建与 live 评测 P50/P95，1.5 分钟。

### 常见故障

- `ready_for_live_demo=false`：检查五个模型环境变量和 `ALLOW_FIXTURE_LLM`。
- Chroma 异常：执行 `docker compose restart chromadb backend`，再重建知识索引。
- 数据不完整：执行 `./scripts/demo.ps1 reset`，输入 `RESET` 后重新初始化。
- 端口 5173 被占用：停止本机 Vite 服务，避免与 Docker 前端同时运行。

## V2 Candidate 索引真实验收

候选索引与 V1/mock collection 隔离。以下命令会调用真实 embedding 服务并产生费用；仅在
已填写模型配置、Docker 服务已启动时执行：

```powershell
docker compose exec backend python -m app.scripts.check_embedding_provider --live --json
docker compose exec backend python -m app.scripts.build_chroma_candidate_index --domain-code ai_app_dev --reset --live --json
docker compose exec -e RUN_LIVE_EMBEDDING_TESTS=true backend python -m pytest tests/integration -m live -q
```

重建成功后，检查容器内 `/app/storage/candidate-index/ai_app_dev/manifest.json`：其领域、模型名、
实际向量维度、`cosine` 距离、chunker 版本、数据版本和 active collection 必须一致。此流程不会修改 V1 collection。


真实评测必须按顺序执行，避免直接进行高成本的 50 案例调用：

```powershell
python test_script/run_live.py --stage smoke
python test_script/run_live.py --stage regression
python test_script/run_live.py --stage formal --xlsx
python test_script/demo_acceptance.py
python test_script/probe_sse.py
```

`demo_acceptance.py` 会显式产生真实模型费用。异常分支可使用带模型名、任务 ID、时间和 `provider_mode=live` 的历史真实快照；未标识 fixture 不得作为验收证据。

## 本地开发

后端：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## 已实现能力

- 唯一八节点 LangGraph、同一 task/thread ID 和可恢复人工复核
- 三类资源并行生成、两路真实模型审核、冲突复审和资源版本链
- 证据驱动反馈、导学会话、局部画像/路径/资源更新
- MySQL、独立 ChromaDB、增量索引重建和来源追溯
- SSE Agent 状态、协同图、资源导出、报告和指标页面
- 50 个 JSON 金标准案例、baseline/live 报告和任务/Agent P50/P95

当前仓库没有真实模型密钥，因此只完成了代码和自动化验证；真实 6/15/50 案例及七分支运行需在填写 `.env` 后执行。

## V2 检索算法验收

V2 检索智能体是当前唯一运行链的一部分，只读取 candidate manifest 指向的 active collection，
不会读取、修改或替换历史 V1/mock collection。V2 评测会调用真实 embedding，必须显式传入
`--live`；请先完成 candidate 索引验收。

```powershell
docker compose exec backend python -m pytest tests/unit/test_v2_retrieval.py -q
docker compose exec -e RUN_LIVE_EMBEDDING_TESTS=true backend python -m pytest tests/integration/test_v2_retrieval_live.py -m live -q
docker compose exec backend python -m app.scripts.evaluate_rag --engine v2-candidate --mode full --split development --live --json
```

JSON 报告会记录 embedding 模型、candidate `index_version`、检索路径、来源完整性、P50/P95 与失败 case ID。
开发集可用于阶段四调参；冻结 acceptance 集只在算法版本冻结后运行，不能用于逐例调参。
