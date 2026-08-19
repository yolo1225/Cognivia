from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.models import KnowledgeDocument
from app.services.knowledge_document_service import KnowledgeDocumentError, _document_path


def _section(
    text: str, *, heading_path: list[str], page_start: int | None = None
) -> dict[str, Any]:
    normalized = text.replace("\x00", "").strip()
    return {
        "heading_path": heading_path,
        "page_start": page_start,
        "page_end": page_start,
        "text": normalized,
        "checksum": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    }


def parse_document(document: KnowledgeDocument) -> list[dict[str, Any]]:
    path = _document_path(document)
    if document.file_type == "pdf":
        sections = []
        for page_number, page in enumerate(PdfReader(str(path)).pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                sections.append(
                    _section(text, heading_path=[f"第 {page_number} 页"], page_start=page_number)
                )
        if not sections:
            raise KnowledgeDocumentError("PDF 未提取到有效文本，当前版本暂不支持扫描件 OCR")
        return sections

    try:
        text = path.read_text(encoding="utf-8-sig").replace("\x00", "").strip()
    except UnicodeDecodeError as exc:
        raise KnowledgeDocumentError("文本文件必须使用 UTF-8 编码") from exc
    if len(text) < 10:
        raise KnowledgeDocumentError("文件没有足够的有效文本")
    if document.file_type == "markdown":
        sections: list[dict[str, Any]] = []
        headings: list[str] = []
        buffer: list[str] = []

        def flush() -> None:
            body = "\n".join(buffer).strip()
            if body:
                sections.append(
                    _section(
                        body, heading_path=list(headings) or [Path(document.original_name).stem]
                    )
                )

        for line in text.splitlines():
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if match:
                flush()
                buffer.clear()
                level = len(match.group(1))
                headings[:] = headings[: level - 1] + [match.group(2).strip()]
            else:
                buffer.append(line)
        flush()
        return sections or [_section(text, heading_path=[Path(document.original_name).stem])]
    return [
        _section(paragraph, heading_path=[f"段落 {index}"])
        for index, paragraph in enumerate(re.split(r"\n\s*\n", text), start=1)
        if len(paragraph.strip()) >= 10
    ]
