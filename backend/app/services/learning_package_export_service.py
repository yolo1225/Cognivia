from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GenerationTask, LearningPath, LearningResource, ReviewReport
from app.services.learning_package_service import package_member_rows
from app.services.resource_export_service import EXPORT_ROOT, _safe_stem, write_resource_export


RESOURCE_TYPES = ("lecture", "practice_guide", "graded_quiz")
RESOURCE_LABELS = {
    "lecture": "定制化讲义",
    "practice_guide": "实操指南",
    "graded_quiz": "分阶测试",
}
FORMAT_SUFFIXES = {"markdown": ".md", "pdf": ".pdf", "word": ".docx"}


def export_learning_package(
    db: Session,
    task: GenerationTask,
    export_format: str = "markdown",
) -> dict:
    """Create a learner-safe ZIP with three approved resources in one format."""

    export_format = export_format.lower()
    if export_format not in FORMAT_SUFFIXES:
        raise ValueError("export_format must be markdown, pdf or word")
    resources = _approved_package_resources(db, task)
    reports = _review_reports_by_resource(db, [resource.id for resource in resources.values()])
    learning_path = db.get(LearningPath, task.learning_path_id) if task.learning_path_id else None
    path = _package_export_path(task)
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="cognivia-package-") as temp_dir, ZipFile(
        path, "w", compression=ZIP_DEFLATED
    ) as archive:
        archive.writestr(
            "00_学习包说明.md",
            _package_manifest(task, resources, reports, learning_path),
        )
        for index, resource_type in enumerate(RESOURCE_TYPES, start=1):
            resource = resources[resource_type]
            title = _safe_stem(resource.title) or resource.public_id
            file_name = f"{index:02d}_{RESOURCE_LABELS[resource_type]}_{title}{FORMAT_SUFFIXES[export_format]}"
            rendered = Path(temp_dir) / file_name
            write_resource_export(rendered, resource, export_format, "learner")
            archive.write(rendered, arcname=file_name)

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "package_id": task.public_id,
        "format": export_format,
        "file_name": path.name,
        "file_hash": f"sha256:{digest}",
        "resource_count": len(resources),
        "download_url": f"/api/v1/resources/exports/{path.name}",
    }


def _approved_package_resources(
    db: Session, task: GenerationTask
) -> dict[str, LearningResource]:
    if task.status != "completed" or task.decision != "completed":
        raise ValueError("learning_package_not_completed")
    resources: dict[str, LearningResource] = {}
    for _member, resource in package_member_rows(db, task):
        if resource.resource_type not in RESOURCE_TYPES:
            continue
        if resource.resource_type in resources:
            raise ValueError("learning_package_has_duplicate_resource_type")
        if resource.review_status != "passed":
            raise ValueError("learning_package_contains_unapproved_resource")
        resources[resource.resource_type] = resource

    missing = [resource_type for resource_type in RESOURCE_TYPES if resource_type not in resources]
    if missing:
        raise ValueError("learning_package_is_incomplete")
    return resources


def _review_reports_by_resource(
    db: Session, resource_ids: list[int]
) -> dict[int, ReviewReport]:
    reports = list(
        db.scalars(
            select(ReviewReport)
            .where(ReviewReport.resource_id.in_(resource_ids))
            .order_by(ReviewReport.id.desc())
        )
    )
    latest: dict[int, ReviewReport] = {}
    for report in reports:
        latest.setdefault(report.resource_id, report)
    return latest


def _package_export_path(task: GenerationTask) -> Path:
    return EXPORT_ROOT / f"learning_package_{task.public_id}_{uuid4().hex[:8]}.zip"


def _package_manifest(
    task: GenerationTask,
    resources: dict[str, LearningResource],
    reports: dict[int, ReviewReport],
    path: LearningPath | None,
) -> str:
    lines = [
        "# 个性化学习包",
        "",
        f"- 学习包任务：{task.public_id}",
        f"- 领域：{task.domain_code}",
        f"- 导出时间：{datetime.now(UTC).astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}",
        "- 受众：学习者（分阶测试不含答案与解析）",
        "",
        "## 学习路径",
        *_learning_path_lines(path, task.path_node_id),
        "",
        "## 资源与审核摘要",
    ]
    for resource_type in RESOURCE_TYPES:
        resource = resources[resource_type]
        report = reports.get(resource.id)
        lines.extend(
            [
                f"- {RESOURCE_LABELS[resource_type]}：{resource.title}（难度 {resource.difficulty}/5，版本 V{resource.version}）",
                f"  - 审核状态：{resource.review_status}",
                f"  - 质量摘要：{_quality_summary(report)}",
                f"  - 知识来源：{_source_summary(resource.sources_json or [])}",
            ]
        )
    return "\n".join(lines) + "\n"


def _learning_path_lines(path: LearningPath | None, current_node_id: str | None) -> list[str]:
    if path is None:
        return ["- 当前学习包未绑定学习路径。"]
    payload = path.path_json or {}
    nodes = payload.get("nodes") or []
    if isinstance(nodes, list) and nodes:
        ordered = sorted(nodes, key=lambda item: int(item.get("path_order") or 0))
        return [
            f"- {item.get('title') or item.get('path_node_id') or '未命名节点'}"
            f"（{item.get('status') or ('current' if item.get('path_node_id') == current_node_id else '待学习')}）"
            for item in ordered
            if isinstance(item, dict)
        ] or ["- 学习路径暂无可导出的节点。"]
    stages = payload.get("stages") or []
    if isinstance(stages, list) and stages:
        return [
            f"- {item.get('name') or '未命名阶段'}"
            for item in stages
            if isinstance(item, dict)
        ] or ["- 学习路径暂无可导出的节点。"]
    return ["- 学习路径暂无可导出的节点。"]


def _quality_summary(report: ReviewReport | None) -> str:
    if report is None:
        return "已通过资源发布校验"
    return (
        f"事实错误率 {report.hallucination_rate:.1f}%，"
        f"难度匹配 {report.difficulty_match_score:.1f}%，"
        f"核心覆盖 {report.core_knowledge_coverage:.1f}%"
    )


def _source_summary(sources: list[object]) -> str:
    labels: list[str] = []
    for source in sources:
        if isinstance(source, dict):
            label = source.get("name") or source.get("knowledge_id") or source.get("source_title")
        else:
            label = str(source)
        if label:
            labels.append(str(label))
    return "、".join(labels) if labels else "资源内知识来源"
