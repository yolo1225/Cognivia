# 可导入知识包

生成时间：2026-08-30 17:16:50 +08:00

这些 Markdown 已按系统结构化导入格式校验。每个知识点包含稳定 knowledge_id、类别、难度、标签、来源、许可与能力权重。正文来源于原始 JSON；原正文中的标题已转为粗体标签，避免被解析为额外知识点。
智能制造包中的 TIA Portal、机器人示教、I/O 协同与安全条目已将原始正文中明确给出的流程、结果、错误和适用边界结构化为普通标签行；未新增设备按钮、地址、命令或参数等原文未支持的事实。
另加入 6 条从 OpenPLC Runtime v4 和 Universal Robots 官方公开仓库提炼的仿真与集成知识。每条固定到 Git 提交、源文件 URL 与 Blob SHA；详细来源见 public-source-manifest.json。

## 导入顺序

1. `ai_app_dev/01-ai-application-foundations.md`：在现有“人工智能应用开发实训”领域中以增量模式上传。导入完成后，在变更集内完成候选校验、图谱、Candidate 索引和题库缺口补齐，再一次启用。
2. 新建领域 `smart_manufacturing`，名称为“智能制造实训”，上传 `smart_manufacturing/01-smart-manufacturing-complete.md`，并在同一变更集中完成发布。
3. 知识发布后，从题库管理下载系统生成的 XLSX 缺口模板，填写题目、来源绑定并通过认证；不得预先手写题库模板。

## 稳定 ID 规则

- 后续编辑同一知识点时保留 `knowledge_id`，系统将其识别为更新候选。
- 新知识点应新增 `knowledge_id`，不要复用或改写历史 ID。
- 常规上传是新增/更新，不会因为新文件缺少旧章节而删除已发布知识。替换或撤回旧资料必须走显式操作。

## 内容范围

- `ai_app_dev` 包含 25 个与 AI 应用开发直接相关的基础点，不导入视觉、强化学习、完整优化算法等会扩大正式题库维护范围的条目。
- `smart_manufacturing` 包含 67 个智能制造、工业互联网、PLC 和工业机器人知识点，其中 14 条具备可识别的操作、验收与错误处理证据，用于演示领域迁移。

## 文件清单与校验和

- `ai_app_dev/01-ai-application-foundations.md`：25 个知识点，SHA-256 `a0c866970151301a4e653df83b8b829edc36bb28aba5046b340ec9050cb01b57`
- `smart_manufacturing/01-smart-manufacturing-complete.md`：67 个知识点，SHA-256 `7e1ea33aa3a6f02ffd15d041beb0bb3725d8f22bebbf56d3c6cb572139c1c289`
