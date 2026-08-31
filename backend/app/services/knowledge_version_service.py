"""Stable knowledge-version fingerprints shared by import and update flows."""

from __future__ import annotations

import hashlib
import json

from app.models import KnowledgeItem


def knowledge_item_content_hash(item: KnowledgeItem) -> str:
    payload = {
        "knowledge_id": item.public_id,
        "domain_code": item.domain_code,
        "name": item.name,
        "category": item.category,
        "difficulty": item.difficulty,
        "tags": list(item.tags_json or []),
        "evidence_capabilities": list(item.evidence_capabilities_json or []),
        "content": item.content_md,
        "source_title": item.source_title,
        "source_url": item.source_url,
        "license_note": item.license_note,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
