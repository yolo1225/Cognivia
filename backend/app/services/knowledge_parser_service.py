from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeDocument, KnowledgeItemSource
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
        "metadata": {},
        "structured": False,
    }


_META_LINE = re.compile(r"^-\s*\*\*([a-zA-Z_]+):\*\*\s*(.*?)\s*$")


def _structured_metadata(text: str) -> tuple[dict[str, Any], str]:
    metadata: dict[str, Any] = {}
    body: list[str] = []
    for line in text.splitlines():
        match = _META_LINE.match(line.strip())
        if not match:
            body.append(line)
            continue
        key, value = match.group(1).lower(), match.group(2).strip().strip("`")
        if key in {"tags", "prerequisites"}:
            metadata[key] = [item.strip().strip("`") for item in value.split(",") if item.strip()]
        elif key == "difficulty":
            try:
                metadata[key] = int(value)
            except ValueError:
                metadata[key] = value
        elif key == "source":
            link = re.match(r"\[([^]]+)]\(([^)]+)\)", value)
            metadata["source_title"] = link.group(1) if link else value
            metadata["source_url"] = link.group(2) if link else None
        else:
            metadata[key] = value
    return metadata, "\n".join(body).strip()


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
        sections = sections or [_section(text, heading_path=[Path(document.original_name).stem])]
        structured = []
        for section in sections:
            metadata, body = _structured_metadata(section["text"])
            section["metadata"] = metadata
            if metadata.get("knowledge_id"):
                section["text"] = body
                section["checksum"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
                section["structured"] = True
                structured.append(section)
        return structured or sections
    return [
        _section(paragraph, heading_path=[f"段落 {index}"])
        for index, paragraph in enumerate(re.split(r"\n\s*\n", text), start=1)
        if len(paragraph.strip()) >= 10
    ]


def replace_chunks(
    db: Session, document: KnowledgeDocument, sections: list[dict[str, Any]]
) -> list[KnowledgeChunk]:
    existing = {
        chunk.chunk_index: chunk
        for chunk in db.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
        )
    }
    chunks: list[KnowledgeChunk] = []
    for index, section in enumerate(sections):
        stable = hashlib.sha256(
            f"{document.public_id}:{index}:{section['checksum']}".encode()
        ).hexdigest()[:20]
        chunk = existing.pop(index, None)
        if chunk is None:
            chunk = KnowledgeChunk(
                public_id=f"kchunk_{stable}",
                document_id=document.id,
                domain_code=document.domain_code,
                chunk_index=index,
                heading_path_json=section["heading_path"],
                page_start=section.get("page_start"),
                page_end=section.get("page_end"),
                content=section["text"],
                checksum=section["checksum"],
            )
            db.add(chunk)
        elif chunk.checksum != section["checksum"]:
            referenced = db.scalar(
                select(KnowledgeItemSource.id).where(KnowledgeItemSource.chunk_id == chunk.id)
            )
            if referenced is not None:
                raise KnowledgeDocumentError("已引用的来源切片内容不可覆盖，请创建新的文档版本")
            chunk.public_id = f"kchunk_{stable}"
            chunk.heading_path_json = section["heading_path"]
            chunk.page_start = section.get("page_start")
            chunk.page_end = section.get("page_end")
            chunk.content = section["text"]
            chunk.checksum = section["checksum"]
        db.flush()
        section["chunk_id"] = chunk.id
        section["chunk_public_id"] = chunk.public_id
        chunks.append(chunk)
    for chunk in existing.values():
        referenced = db.scalar(
            select(KnowledgeItemSource.id).where(KnowledgeItemSource.chunk_id == chunk.id)
        )
        if referenced is not None:
            raise KnowledgeDocumentError("已引用的来源切片不可删除，请创建新的文档版本")
        chunk.previous_chunk_id = None
        chunk.next_chunk_id = None
        db.delete(chunk)
    for index, chunk in enumerate(chunks):
        chunk.previous_chunk_id = chunks[index - 1].id if index else None
        chunk.next_chunk_id = chunks[index + 1].id if index + 1 < len(chunks) else None
    document.chunk_count = len(chunks)
    db.flush()
    return chunks
