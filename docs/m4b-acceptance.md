# M4B 验收记录

> 验收日期：2026-08-19  
> 验收环境：Docker Compose / MySQL 8 / 真实 OpenAI-compatible 模型通道

## 结论

M4B“真实诊断评分与学习路径推进”通过验收。

## 验收证据

- 数据库迁移：`20260819_0017 (head)`。
- 依赖健康：`status=ok`、`rag.ready=true`、`ready_for_live_demo=true`。
- 真实简答题评分：`provider_mode=live`、`model_name=qwen-plus`，返回完整分项、置信度、评语和不确定标记，耗时约 24 秒。
- 路径案例：低分证据验证失败，补救后的合格证据验证成功，当前节点转为 `completed`，后继节点转为 `current`。
- 一致性：报告序列化和生成 Worker 均读取 `knowledge:accept_k2`。
- 数据隔离：路径验收使用合成数据和回滚事务，验收后学习者和路径残留数均为 0。
- 后端回归：`432 passed, 3 skipped`。
- Ruff、`compileall`、`git diff --check` 通过。
- 前端 `npm run build` 通过。

## 验收中发现并修复

`qwen-plus` 在单题批次首次返回单个评分对象，而不是 `{results: [...]}`。评分服务已加入只包装外层的确定性适配器，内部字段仍经 Pydantic 严格校验，并增加单元测试。

## 隐私边界

真实模型冒烟使用完全合成的公开技术题和答案，未将正式题库题干、rubric、学习者答案或画像发送到外部端点。
