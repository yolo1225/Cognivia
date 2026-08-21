# 冻结基线

`stage0-ai_app_dev.json` 由以下命令在已提交的运行时输入上生成：

```powershell
.\scripts\stage0-baseline.ps1 capture
```

该文件只保存脱敏的版本、指纹、状态、模型名称、RAG 元数据和指标摘要；完整本地执行
证据写入被 Git 忽略的 `reports/stage0/latest.json`。后续改造前后使用以下命令验证基线
是否发生漂移：

```powershell
.\scripts\stage0-baseline.ps1 verify
```
