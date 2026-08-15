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
docs/         API、部署、环境和演示账号文档
test_script/  baseline/live 评测与七分支验收入口
storage/      导出文件和运行期本地存储
```

## 部署与启动

部署前需要安装并启动 Docker Desktop（或安装了 Docker Compose v2 的 Docker Engine）。项目提供两种部署方式。

### 方式一：Windows 使用 start.bat 一键部署

双击根目录的 `start.bat`，或在 PowerShell 中运行：

```powershell
.\start.bat
```

首次运行会自动：

- 从 `.env.example` 创建不会提交到 Git 的 `.env`
- 为当前部署生成独立的随机 `JWT_SECRET_KEY`
- 设置初始管理员 `admin / 12345678`
- 构建并启动 MySQL、Redis、ChromaDB、后端和前端
- 执行 Alembic 迁移、管理员初始化、种子导入和 ChromaDB 索引重建

`start.bat` 可以重复运行，不会删除已有数据库，也不会覆盖已经存在的管理员密码。首次登录后应在“用户管理”中立即修改初始密码。模型配置仍需按需填写到 `.env`；真实模型验收必须配置模型名称和 API Key，并保持 `ALLOW_FIXTURE_LLM=false`。

需要主动清空 MySQL、ChromaDB 和相关 Docker 卷时，使用显式重置命令：

```powershell
.\scripts\demo.ps1 reset
```

### 方式二：手动使用 Docker Compose 部署

适用于 Linux、macOS、Windows，或需要自行控制每个部署步骤的场景。

1. 创建本地环境变量文件：

```bash
cp .env.example .env
```

Windows PowerShell 使用：

```powershell
Copy-Item .env.example .env
```

2. 编辑 `.env`，至少替换以下占位值：

```env
JWT_SECRET_KEY=请填写至少32字节的随机密钥
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=请填写至少8位的初始密码
COOKIE_SECURE=false
```

`.env` 不应提交到 Git。HTTPS 正式部署需要设置 `COOKIE_SECURE=true`。如需真实模型调用，还要填写 `OPENAI_API_BASE`、`OPENAI_API_KEY`、三个模型名称和 Embedding 模型。

3. 构建并启动基础服务和后端：

```bash
docker compose up -d --build mysql redis chromadb backend
```

4. 依次执行数据库迁移、管理员初始化、种子导入和索引重建：

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.scripts.init_admin
docker compose exec backend python -m app.scripts.seed_data --json
docker compose exec backend python -m app.scripts.build_chroma_index --reset --json
```

`init_admin` 是幂等命令：管理员已存在时不会重新创建，也不会使用 `.env` 中的新密码覆盖数据库中的旧密码。

5. 启动前端：

```bash
docker compose up -d frontend
```

6. 检查服务状态：

```bash
docker compose ps
curl "http://localhost:8000/api/v1/health"
curl "http://localhost:8000/api/v1/health/dependencies"
```

知识库等管理接口需要先登录管理员账号，不能再通过匿名 `curl` 直接访问。

### 访问地址

- Frontend: http://localhost:5173
- Backend: http://localhost:8000/docs
- Health: http://localhost:8000/api/v1/health
- MySQL host connection: `localhost:13306` by default (`MYSQL_HOST_PORT`); containers continue to use `mysql:3306`.

如果只是重启已经初始化过的本地环境：

```bash
docker compose up -d
```

对已有 Docker 演示数据进行真实验收前，可先执行非破坏性备份：

```powershell
.\scripts\demo.ps1 backup
```

备份会保存到 `reports/preflight/<timestamp>/`，不会执行 reset。

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
