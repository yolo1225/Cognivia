"""Resource-scoped tutoring answers, separate from the frozen Agent contract."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.observability import record_model_call
from app.core.config import settings
from app.models import KnowledgeItem, LearningResource, TutoringMessage, TutoringSession
from app.services.llm_service import ModelGatewayError, gateway

MAX_RESOURCE_CHARS = 12000
MAX_HISTORY = 10
MAX_SOURCES = 3

SYSTEM_PROMPT = """你是人工智能应用开发实训的资源内导学助手。只能根据提供的当前学习资源、来源片段和对话历史回答。回答用中文，简洁但可操作；优先解释概念、给例子和拆解步骤。不得编造材料外的事实、来源、成绩或画像结论。若证据不足，要明确说明。不要自行宣布画像已更新。"""


@dataclass
class TutoringAnswer:
    answer: str
    sources: list[dict[str, str]]
    scope_status: str
    assessment: dict[str, Any] | None


def _source_record(item: KnowledgeItem) -> dict[str, str]:
    return {"knowledge_id": item.public_id, "name": item.name, "source_title": item.source_title}


def _resource_knowledge(db: Session, resource: LearningResource) -> list[KnowledgeItem]:
    ids = [str(item.get("knowledge_id")) for item in resource.sources_json or [] if isinstance(item, dict) and item.get("knowledge_id")]
    if not ids:
        return []
    items = list(db.scalars(select(KnowledgeItem).where(KnowledgeItem.public_id.in_(ids))))
    by_id = {item.public_id: item for item in items}
    return [by_id[item_id] for item_id in ids if item_id in by_id]


def _fallback_search(db: Session, domain_code: str, question: str, excluded_ids: set[str]) -> list[KnowledgeItem]:
    terms = [term for term in question.replace("，", " ").replace("。", " ").split() if len(term) >= 2]
    query = select(KnowledgeItem).where(KnowledgeItem.domain_code == domain_code)
    if excluded_ids:
        query = query.where(KnowledgeItem.public_id.not_in(excluded_ids))
    candidates = list(db.scalars(query.order_by(KnowledgeItem.id.desc()).limit(50)))
    if not terms:
        return candidates[:MAX_SOURCES]
    matched = [item for item in candidates if any(term in f"{item.name} {item.content_md} {' '.join(item.tags_json or [])}" for term in terms)]
    return matched[:MAX_SOURCES]


def _needs_assessment(content: str, turn_count: int) -> dict[str, Any] | None:
    mastery = any(token in content for token in ("我会了", "掌握了", "太简单", "没问题"))
    difficulty = turn_count >= 2 and any(token in content for token in ("还是不懂", "仍然不懂", "不会", "卡住", "太难"))
    if not (mastery or difficulty):
        return None
    return {"assessment_id": "pending", "kind": "mastery" if mastery else "difficulty", "prompt": "请用自己的话说明这一概念的关键步骤，并给出一个应用场景。", "status": "pending"}


def answer_resource_question(db: Session, *, session: TutoringSession, resource: LearningResource, question: str) -> TutoringAnswer:
    scoped = _resource_knowledge(db, resource)
    history = list(db.scalars(select(TutoringMessage).where(TutoringMessage.session_id == session.id).order_by(TutoringMessage.id.desc()).limit(MAX_HISTORY)))
    history.reverse()
    sources = scoped[:MAX_SOURCES]
    scope_status = "resource"
    if not sources:
        sources = _fallback_search(db, "ai_app_dev", question, set())
        scope_status = "knowledge_base" if sources else "uncovered"
    context = [{"knowledge_id": item.public_id, "name": item.name, "content": item.content_md[:4000], "source_title": item.source_title} for item in sources]
    payload = {"resource": {"title": resource.title, "content": resource.content_md[:MAX_RESOURCE_CHARS]}, "knowledge_sources": context, "history": [{"sender": item.sender, "content": item.content[:800]} for item in history], "question": question}
    try:
        answer, metadata = gateway.complete_text(model=settings.primary_llm_model, system_prompt=SYSTEM_PROMPT, payload=payload)
        record_model_call(metadata, role="resource_tutoring_model")
    except ModelGatewayError:
        basis = "当前资源" if scope_status == "resource" else "关联知识库"
        answer = f"我会围绕{basis}协助你理解。你可以指出具体概念、步骤或结果，我会据此逐步解释。"
    return TutoringAnswer(answer=answer[:4000], sources=[_source_record(item) for item in sources], scope_status=scope_status, assessment=_needs_assessment(question, session.turn_count))


def build_resource_tutoring_context(
    db: Session, *, session: TutoringSession, resource: LearningResource, question: str
) -> tuple[dict[str, Any], list[dict[str, str]], str, dict[str, Any] | None]:
    scoped = _resource_knowledge(db, resource)
    history = list(db.scalars(select(TutoringMessage).where(TutoringMessage.session_id == session.id).order_by(TutoringMessage.id.desc()).limit(MAX_HISTORY)))
    history.reverse()
    sources = scoped[:MAX_SOURCES]
    scope_status = "resource"
    if not sources:
        sources = _fallback_search(db, "ai_app_dev", question, set())
        scope_status = "knowledge_base" if sources else "uncovered"
    payload = {
        "resource": {"title": resource.title, "content": resource.content_md[:MAX_RESOURCE_CHARS]},
        "knowledge_sources": [{"knowledge_id": item.public_id, "name": item.name, "content": item.content_md[:4000], "source_title": item.source_title} for item in sources],
        "history": [{"sender": item.sender, "content": item.content[:800]} for item in history],
        "question": question,
    }
    return payload, [_source_record(item) for item in sources], scope_status, _needs_assessment(question, session.turn_count)
