"""Build the V10 review boundary from semantically owned structured fields."""

from __future__ import annotations

import hashlib
import re

from app.agents.contracts import (
    GradedQuizContent,
    LectureContent,
    PracticeGuideContent,
    ResourceType,
    ReviewClaim,
    ReviewClaimKind,
    StructuredResourceContent,
)
from app.agents.claim_policy import (
    ClaimCategory,
    ReviewDisposition,
    classify_claim,
    split_policy_sentences,
)


_SENTENCE_RE = re.compile(r"(?<=[。！？!?；;])\s*")


def _parts(value: str, *, preserve: bool = False) -> list[str]:
    normalized = " ".join(value.split()).strip()
    if not normalized:
        return []
    return [normalized] if preserve else [item for item in _SENTENCE_RE.split(normalized) if item]


def _claim_id(resource_type: ResourceType, field_path: str, claim: str) -> str:
    raw = f"{resource_type.value}\n{field_path}\n{claim}"
    return "clm_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def build_review_claims(
    resource_type: ResourceType,
    content: StructuredResourceContent,
) -> list[ReviewClaim]:
    """Return professional facts only; teaching and personalization prose is excluded."""

    claims: list[ReviewClaim] = []

    def add(
        path: str,
        text: str,
        kind: ReviewClaimKind,
        source_ids: list[str],
        *,
        preserve: bool = False,
    ) -> None:
        for index, part in enumerate(_parts(text, preserve=preserve)):
            field_path = path if preserve else f"{path}[{index}]"
            claims.append(
                ReviewClaim(
                    claim_id=_claim_id(resource_type, field_path, part),
                    resource_type=resource_type,
                    field_path=field_path,
                    claim_kind=kind,
                    claim=part,
                    source_ref_ids=list(dict.fromkeys(source_ids)),
                )
            )

    def add_reviewable(
        path: str,
        text: str,
        field_group: str,
        source_ids: list[str],
    ) -> None:
        kind_by_category = {
            ClaimCategory.OPERATIONAL_FACT: ReviewClaimKind.OPERATIONAL_FACT,
            ClaimCategory.CODE_OR_COMMAND: ReviewClaimKind.CODE_BEHAVIOR,
            ClaimCategory.FIXED_RESULT: ReviewClaimKind.EXPECTED_RESULT,
            ClaimCategory.ERROR_HANDLING: ReviewClaimKind.ERROR_HANDLING,
        }
        for index, part in enumerate(split_policy_sentences(text)):
            decision = classify_claim(field_group, part)
            if decision.review_disposition is not ReviewDisposition.DUAL_REVIEW:
                continue
            claims.append(
                ReviewClaim(
                    claim_id=_claim_id(resource_type, f"{path}[{index}]", part),
                    resource_type=resource_type,
                    field_path=f"{path}[{index}]",
                    claim_kind=kind_by_category.get(
                        decision.category, ReviewClaimKind.PROFESSIONAL_FACT
                    ),
                    claim=part,
                    source_ref_ids=list(dict.fromkeys(source_ids)),
                )
            )

    if isinstance(content, LectureContent):
        for index, block in enumerate(content.core_concepts):
            add(f"core_concepts[{index}].explanation", block.explanation, ReviewClaimKind.PROFESSIONAL_FACT, block.source_ref_ids)
            if block.example:
                add(f"core_concepts[{index}].example", block.example, ReviewClaimKind.PROFESSIONAL_FACT, block.source_ref_ids)
        for index, block in enumerate(content.misconceptions):
            add(
                f"misconceptions[{index}]",
                f"误区陈述：{block.misconception}；纠正：{block.correction}",
                ReviewClaimKind.PROFESSIONAL_FACT,
                block.source_ref_ids,
                preserve=True,
            )
    elif isinstance(content, PracticeGuideContent):
        for index, step in enumerate(content.steps):
            add_reviewable(
                f"steps[{index}].instruction",
                step.instruction,
                "instruction",
                step.source_ref_ids,
            )
            if step.code_or_command:
                add(
                    f"steps[{index}].code_or_command",
                    step.code_or_command,
                    ReviewClaimKind.CODE_BEHAVIOR,
                    step.source_ref_ids,
                    preserve=True,
                )
            add_reviewable(
                f"steps[{index}].expected_result",
                step.expected_result,
                "expected_result",
                step.source_ref_ids,
            )
            if step.troubleshooting:
                add(
                    f"steps[{index}].troubleshooting",
                    step.troubleshooting,
                    ReviewClaimKind.ERROR_HANDLING,
                    step.source_ref_ids,
                )
    elif isinstance(content, GradedQuizContent):
        for index, question in enumerate(content.questions):
            add(
                f"questions[{index}]",
                f"正确答案：{question.correct_answer}；解析：{question.explanation}",
                ReviewClaimKind.PROFESSIONAL_FACT,
                question.source_ref_ids,
                preserve=True,
            )
    if not claims:
        raise ValueError("generated resource must contain at least one reviewable professional claim")
    return claims
