# 第一领域可执行测试数据包

本目录用于从空库复现比赛主领域 `ai_app_dev`，与运行快照不同，它是可加载的规范化数据夹具。

## 两种互斥使用方式

1. **启动夹具**：运行 `scripts/submission-fixture.ps1 verify` 校验文件；在新克隆或已清空的 Docker 卷中运行 `scripts/submission-fixture.ps1 bootstrap`。脚本不会删除现有卷，发现非本版本领域数据会失败。
2. **导入能力演示**：上传 `deliverables/knowledge-import-packages/ai_app_dev/01-ai-app-dev-complete.md`，发布知识后下载当次题库模板，再使用 `scripts/fill_submission_question_template.py` 将 `template_question_source.json` 填入模板。`import_source/` 中保存同哈希副本，供容器内夹具校验使用。

两种方式不得在同一数据库叠加执行。启动夹具复现 465 道当前活动题；模板导入演示复现每个知识点 1 道诊断、3 道分阶测验和 2 道掌握检查，共 450 道。剩余 15 道诊断题只用于完整运行基线。

## 内容

- `knowledge_items.json`、`relations.json`、`diagnostic_questions.json`：空库启动的完整数据。
- `template_question_source.json`：从系统刚下载的题库模板生成 XLSX 所需的 450 条题源。
- `evaluation_cases_v4.json`：锁定的 50 例离线评测输入。
- `manual_demo_cases.json`：初始生成、反馈复核和挑战任务三组手工演示输入与业务断言。
- `manifest.json`：所有受管 JSON 的哈希、数量和版本。

本阶段不包含真实模型运行结果、完整学习者答题文本、密钥、数据库备份或正式评测结论。
