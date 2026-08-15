# 云川智汇 - 多智能体个性化知识生成系统

主验证领域为 `ai_app_dev`（人工智能应用开发实训）。系统闭环为：

```text
诊断 -> 能力画像与学习路线 -> Candidate RAG 检索 -> 三类资源生成
-> 双模型审核 -> 自动局部修订 -> 原子发布 -> 反馈更新
```

## Docker 启动

```powershell
.\start.bat
```

启动只执行迁移、管理员初始化和种子导入。未配置真实模型或 candidate index 时，服务、诊断和知识管理仍可用，但资源生成会返回 `CANDIDATE_RAG_NOT_READY`，不会回退到 mock 索引。

配置 `OPENAI_API_BASE`、`OPENAI_API_KEY`、三个审核/生成模型及 `EMBEDDING_MODEL` 后，显式构建真实索引：

```powershell
docker compose exec backend python -m app.scripts.build_chroma_candidate_index --domain-code ai_app_dev --reset --live --json
```

访问地址：

- Frontend: http://localhost:5173/
- Backend docs: http://localhost:8000/docs
- Health: http://localhost:8000/api/v1/health
- Dependencies: http://localhost:8000/api/v1/health/dependencies

## 验证

```powershell
docker compose exec backend python -m ruff check app tests
docker compose exec backend python -m compileall -q app tests
docker compose exec backend python -m pytest -q
docker compose exec backend python -m app.scripts.evaluate_rag --split development --live --json
```

`evaluate_rag` 只评测 active candidate index，真实评测会发送查询文本至配置的 embedding 服务。人工复核、mock embedding、旧 hash 检索和 V1/V2 运行链已移除。
