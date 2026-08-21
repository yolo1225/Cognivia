"""Deterministic, domain-neutral policy for reviewable resource claims."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


CLAIM_POLICY_VERSION = "review-v5-claim-policy"
QUALITY_POLICY_VERSION = "quality-v7-20260821"


class ClaimCategory(StrEnum):
    TEACHING_ACTION = "teaching_action"
    ORGANIZATIONAL_TEXT = "organizational_text"
    STRUCTURAL_REQUIREMENT = "structural_requirement"
    VERIFIABLE_FACT = "verifiable_fact"
    OPERATIONAL_FACT = "operational_fact"
    CODE_OR_COMMAND = "code_or_command"
    FIXED_RESULT = "fixed_result"
    ERROR_HANDLING = "error_handling"
    VERSION_BOUNDARY = "version_boundary"
    QUIZ_FACT = "quiz_fact"


class ReviewDisposition(StrEnum):
    EXCLUDE = "exclude"
    DETERMINISTIC_VALIDATE = "deterministic_validate"
    DUAL_REVIEW = "dual_review"


class RiskLevel(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ClaimPolicyDecision:
    category: ClaimCategory
    risk_level: RiskLevel
    review_disposition: ReviewDisposition
    evidence_capabilities: tuple[str, ...] = ()
    violation_code: str | None = None


_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;\n]*")
_PLACEHOLDERS = {"待补充", "暂无", "无", "todo", "tbd", "示例内容", "模板内容"}
_INTERNAL_SOURCE_RE = re.compile(r"\b[A-Za-z0-9_-]+::(?:chunk|source)::\d+\b")
_PROVENANCE_META_RE = re.compile(
    r"(?:所有|全部|以上|本(?:讲义|资源|内容)).{0,24}"
    r"(?:均|都|严格)?(?:源自|来自|基于|依据).{0,24}"
    r"(?:官方|所列|所提供|输入|引用|检索)(?:文档|资料|材料|来源|证据|内容|知识片段)|"
    r"(?:未|没有)(?:引入|使用).{0,16}(?:外部常识|外部知识|工具能力|额外推断|自行推断)|"
    r"(?:引用|来源).{0,12}(?:完整|齐全|全部覆盖|均可追溯)|"
    r"\b(?:all|every|the above|this (?:lecture|resource|content)).{0,40}"
    r"(?:comes?|is derived|is based).{0,40}(?:official|cited|retrieved)"
    r"(?: documents?| sources?| evidence)\b",
    re.I,
)
_ORGANIZATIONAL_RE = re.compile(
    r"^(?:本节|本章|下面|以下|接下来)(?:将|会|带你|帮助你|我们将).{0,100}"
    r"(?:介绍|讲解|学习|了解|掌握|回顾|总结).{0,50}$|"
    r"^(?:this (?:section|chapter)|next|below).{0,120}"
    r"(?:introduces?|explains?|covers?|reviews?)\b.*$",
    re.I,
)
_ACTION_START_RE = re.compile(
    r"^(?:(?:学习者|学员|你)(?:应|需|需要|可以|可)?|请|可以|可|please\s+)?\s*"
    r"(?:(?:在|于).{1,60}(?:中|内|旁|上)\s*)?"
    r"(?:阅读|浏览|观察|记录|保存|提交|提供|整理|梳理|比较|对比|讨论|思考|分析|检查|核对|"
    r"完成|尝试|练习|复述|列出|总结|标注|注明|选择|填写|形成|准备|回顾|识别|描述|说明|映射|"
    r"访问|查阅|打开|确认|确保|避免|保护|"
    r"read|review|observe|record|save|submit|organize|compare|discuss|analyze|check|"
    r"complete|practice|summarize|label|list|describe)(?:\b|(?=[\u4e00-\u9fff]))",
    re.I,
)
_CONDITIONAL_ACTION_RE = re.compile(
    r"^(?:如|若|如果|假如|需要时|练习前|开始前).{0,140}[，,]\s*(?:请)?"
    r"(?:阅读|观察|记录|整理|比较|核对|检查|说明|解释|描述|标注|选择|填写|提交|确认|避免).{0,180}$|"
    r"^(?:if|when|before).{0,180},\s*(?:please\s+)?"
    r"(?:read|observe|record|organize|compare|check|explain|describe|submit|confirm|avoid)\b.*$",
    re.I,
)
_TRANSFORM_ACTION_RE = re.compile(
    r"^(?:将|把).{1,180}(?:映射|记录|整理|核对|标注|描述|说明|列入|填入|写入).{0,180}$",
    re.I,
)
_DELIVERABLE_ACTION_RE = re.compile(
    r"^(?:(?:学习者|学员|你)(?:应|需|需要|可以|可)?\s*)?"
    r"(?:(?:完成|提交|形成)(?:一份)?\s*)?"
    r"(?:学习记录|练习记录|检查表|自查清单|清单|报告|表格|提交内容|错误响应分析)"
    r".{0,220}(?:包含|记录|列出|标注|覆盖|附有|核对|说明|描述).{0,180}$",
    re.I,
)
_TECHNICAL_ASSERTION_RE = re.compile(
    r"(?:将会|将在|会自动|自动|固定|默认|必须|只能|不能|支持|不支持|兼容|不兼容|"
    r"返回|导致|触发|包含|等于|意味着|保证|始终|无需|规定|指出|属于|用于|决定|"
    r"implemented|enforced|guaranteed|returns?|causes?|triggers?|contains?|defaults?|"
    r"supports?|requires?|must|shall|always|never|"
    r"\b\d+(?:\.\d+)+(?:\+|以上|以下)?\b|\d+(?:\.\d+)?\s*(?:秒|毫秒|次|%|mb|gb)\b|"
    r"\b(?:get|post|put|patch|delete)\b.{0,24}\b(?:2\d\d|4\d\d|5\d\d)\b)",
    re.I,
)
_EMBEDDED_FACT_RE = re.compile(
    r"(?:将会|将在|会自动|自动|固定|默认|只能|不能|支持|不支持|兼容|不兼容|"
    r"返回|导致|触发|等于|意味着|保证|始终|无需|决定|"
    r"implemented|enforced|guaranteed|returns?|causes?|triggers?|defaults?|"
    r"supports?|always|never|"
    r"(?:接口|api|响应|命令|模型|系统|工具|函数|服务).{0,40}(?:包含|属于|共同|核心)|"
    r"\b\d+(?:\.\d+)+(?:\+|以上|以下)?\b|\d+(?:\.\d+)?\s*(?:秒|毫秒|次|%|mb|gb)\b|"
    r"\b(?:get|post|put|patch|delete)\b.{0,24}\b(?:2\d\d|4\d\d|5\d\d)\b)",
    re.I,
)
_HARD_FACT_RE = re.compile(
    r"(?:将会|将在|会自动|自动|固定|默认|只能|不能|支持|不支持|兼容|不兼容|"
    r"返回|导致|触发|等于|意味着|保证|始终|无需|决定|"
    r"implemented|enforced|guaranteed|returns?|causes?|triggers?|defaults?|"
    r"supports?|always|never|"
    r"\b\d+(?:\.\d+)+(?:\+|以上|以下)?\b|\d+(?:\.\d+)?\s*(?:秒|毫秒|次|%|mb|gb)\b|"
    r"\b(?:get|post|put|patch|delete)\b.{0,24}\b(?:2\d\d|4\d\d|5\d\d)\b)",
    re.I,
)
_NORMATIVE_DIRECTIVE_RE = re.compile(
    r"(?:应当|应该|必须|不得|务必|需要|(?<!响)应(?=[\u4e00-\u9fff])|"
    r"\bshould\b|\bmust\b|\bshall\b|\bneed(?:s)?\s+to\b)",
    re.I,
)
_SAFE_OBSERVATION_RE = re.compile(
    r"^(?:记录|整理|比较|核对|形成|提交|观察).{0,160}"
    r"(?:记录|清单|笔记|差异|材料|描述|实际结果|表格|核对|对照|观察|响应).{0,60}$|"
    r"^(?:record|organize|compare|check|observe|submit).{0,180}"
    r"(?:result|observation|difference|record|notes?|table|response).*$",
    re.I,
)
_QUESTION_DIRECTIVE_RE = re.compile(
    r"^(?:请)?(?:概括|说明|列举|回答|选择|判断|完成|写出|指出).{1,220}[？?]?$|"
    r"^(?:please\s+)?(?:summarize|explain|list|answer|choose|decide|complete|write|identify)\b.*[?]?$",
    re.I,
)
_QUESTION_CONTEXT_RE = re.compile(
    r"^(?:当|若|如果|假如|在|面向|针对|对于|根据|依据).{1,220}"
    r"(?:时|情况下|场景中|过程中|期间|材料|资料)?$|"
    r"^(?:when|if|given|based on|according to|for|in).{1,240}$",
    re.I,
)
_VERSION_RE = re.compile(r"\b\d+(?:\.\d+)+(?:\+|以上|以下)?\b|\bversion\s+\d", re.I)
_FIXED_RESULT_RE = re.compile(
    r"(?:返回|输出|显示|生成|状态码|成功状态|失败状态|字段值|固定|"
    r"returns?|outputs?|displays?|status\s*code|fixed\s+result)",
    re.I,
)


def split_policy_sentences(value: str) -> list[str]:
    return [item.strip() for item in _SENTENCE_RE.findall(value) if item.strip()]


def field_group_for_path(path: str) -> str:
    parent = re.sub(r"\[\d+\]$", "", path)
    if parent.endswith(".code_or_command"):
        return "code_or_command"
    if parent.endswith(".troubleshooting"):
        return "troubleshooting"
    if parent.endswith(".expected_result"):
        return "expected_result"
    if parent.endswith(".instruction"):
        return "instruction"
    if parent.endswith(".correct_answer"):
        return "quiz_answer"
    if parent.endswith(".explanation") and parent.startswith("questions["):
        return "quiz_explanation"
    if parent.endswith(".prompt") and parent.startswith("questions["):
        return "quiz_prompt"
    if parent == "environment_requirements" or parent.startswith("environment_requirements["):
        return "environment_requirement"
    if parent == "acceptance_criteria" or parent.startswith("acceptance_criteria["):
        return "acceptance_criterion"
    if parent == "summary":
        return "summary"
    if parent == "title" or parent.endswith(".title"):
        return "title"
    return "factual"


def classify_claim(
    field_group: str,
    text: str,
    *,
    evidence_capabilities: tuple[str, ...] = (),
) -> ClaimPolicyDecision:
    raw_sentence = text.strip()
    has_question_mark = bool(re.search(r"[？?]", raw_sentence))
    sentence = raw_sentence.strip("。！？!?；;\n ")
    compact = re.sub(r"\s+", "", sentence).lower()
    common = {"evidence_capabilities": tuple(sorted(set(evidence_capabilities)))}
    if not sentence or compact in _PLACEHOLDERS:
        return ClaimPolicyDecision(
            ClaimCategory.STRUCTURAL_REQUIREMENT,
            RiskLevel.LOW,
            ReviewDisposition.DETERMINISTIC_VALIDATE,
            violation_code="placeholder_content",
            **common,
        )
    if _INTERNAL_SOURCE_RE.search(sentence) or _PROVENANCE_META_RE.search(sentence):
        return ClaimPolicyDecision(
            ClaimCategory.STRUCTURAL_REQUIREMENT,
            RiskLevel.LOW,
            ReviewDisposition.DETERMINISTIC_VALIDATE,
            violation_code="forbidden_meta_claim",
            **common,
        )
    if field_group == "title" or _ORGANIZATIONAL_RE.fullmatch(sentence):
        return ClaimPolicyDecision(
            ClaimCategory.ORGANIZATIONAL_TEXT,
            RiskLevel.LOW,
            ReviewDisposition.EXCLUDE,
            **common,
        )
    if field_group == "code_or_command":
        return ClaimPolicyDecision(
            ClaimCategory.CODE_OR_COMMAND,
            RiskLevel.HIGH,
            ReviewDisposition.DUAL_REVIEW,
            **common,
        )
    if field_group == "troubleshooting":
        return ClaimPolicyDecision(
            ClaimCategory.ERROR_HANDLING,
            RiskLevel.HIGH,
            ReviewDisposition.DUAL_REVIEW,
            **common,
        )
    if field_group in {"quiz_answer", "quiz_explanation"}:
        return ClaimPolicyDecision(
            ClaimCategory.QUIZ_FACT,
            RiskLevel.HIGH if field_group == "quiz_answer" else RiskLevel.NORMAL,
            ReviewDisposition.DUAL_REVIEW,
            **common,
        )
    if _VERSION_RE.search(sentence):
        return ClaimPolicyDecision(
            ClaimCategory.VERSION_BOUNDARY,
            RiskLevel.HIGH,
            ReviewDisposition.DUAL_REVIEW,
            **common,
        )
    if field_group == "quiz_prompt":
        exclude_question = bool(_QUESTION_DIRECTIVE_RE.fullmatch(sentence))
        if has_question_mark:
            clauses = [
                item.strip()
                for item in re.split(r"[,，;；:：]", sentence)
                if item.strip()
            ]
            premises = clauses[:-1]
            independent_fact = any(
                _TECHNICAL_ASSERTION_RE.search(item)
                and not _QUESTION_CONTEXT_RE.fullmatch(item)
                for item in premises
            )
            exclude_question = not independent_fact
        if exclude_question:
            return ClaimPolicyDecision(
                ClaimCategory.TEACHING_ACTION,
                RiskLevel.LOW,
                ReviewDisposition.EXCLUDE,
                **common,
            )
        return ClaimPolicyDecision(
            ClaimCategory.QUIZ_FACT,
            RiskLevel.NORMAL,
            ReviewDisposition.DUAL_REVIEW,
            **common,
        )
    if field_group == "expected_result":
        if _SAFE_OBSERVATION_RE.fullmatch(sentence) and not _FIXED_RESULT_RE.search(sentence):
            return ClaimPolicyDecision(
                ClaimCategory.TEACHING_ACTION,
                RiskLevel.LOW,
                ReviewDisposition.EXCLUDE,
                **common,
            )
        if _NORMATIVE_DIRECTIVE_RE.search(sentence) or (
            _ACTION_START_RE.match(sentence) and not _FIXED_RESULT_RE.search(sentence)
        ):
            return ClaimPolicyDecision(
                ClaimCategory.STRUCTURAL_REQUIREMENT,
                RiskLevel.LOW,
                ReviewDisposition.DETERMINISTIC_VALIDATE,
                violation_code="misplaced_field_content",
                **common,
            )
        return ClaimPolicyDecision(
            ClaimCategory.FIXED_RESULT,
            RiskLevel.HIGH,
            ReviewDisposition.DUAL_REVIEW,
            **common,
        )
    if field_group in {"instruction", "environment_requirement", "acceptance_criterion"}:
        deliverable_action = bool(_DELIVERABLE_ACTION_RE.fullmatch(sentence))
        pedagogical_action = bool(
            _ACTION_START_RE.match(sentence)
            or _CONDITIONAL_ACTION_RE.fullmatch(sentence)
            or _TRANSFORM_ACTION_RE.fullmatch(sentence)
            or deliverable_action
        )
        contains_auditable_fact = bool(
            (_HARD_FACT_RE if deliverable_action else _EMBEDDED_FACT_RE).search(sentence)
        )
        if pedagogical_action and not contains_auditable_fact:
            return ClaimPolicyDecision(
                ClaimCategory.TEACHING_ACTION,
                RiskLevel.LOW,
                ReviewDisposition.EXCLUDE,
                **common,
            )
        if field_group == "acceptance_criterion" and _FIXED_RESULT_RE.search(sentence):
            return ClaimPolicyDecision(
                ClaimCategory.FIXED_RESULT,
                RiskLevel.HIGH,
                ReviewDisposition.DUAL_REVIEW,
                **common,
            )
        category = (
            ClaimCategory.OPERATIONAL_FACT
            if field_group in {"instruction", "environment_requirement"}
            else ClaimCategory.VERIFIABLE_FACT
        )
        return ClaimPolicyDecision(
            category,
            RiskLevel.HIGH if category is ClaimCategory.OPERATIONAL_FACT else RiskLevel.NORMAL,
            ReviewDisposition.DUAL_REVIEW,
            **common,
        )
    if field_group == "summary" and _ACTION_START_RE.match(sentence):
        return ClaimPolicyDecision(
            ClaimCategory.TEACHING_ACTION,
            RiskLevel.LOW,
            ReviewDisposition.EXCLUDE,
            **common,
        )
    return ClaimPolicyDecision(
        ClaimCategory.VERIFIABLE_FACT,
        RiskLevel.NORMAL,
        ReviewDisposition.DUAL_REVIEW,
        **common,
    )


def capability_violation_for_claim(
    field_group: str,
    text: str,
    evidence_capabilities: set[str],
) -> str | None:
    """Return the one domain-neutral evidence violation for a structured field."""
    decision = classify_claim(
        field_group,
        text,
        evidence_capabilities=tuple(evidence_capabilities),
    )
    if decision.review_disposition is not ReviewDisposition.DUAL_REVIEW:
        return None
    if decision.category is ClaimCategory.OPERATIONAL_FACT:
        return (
            None
            if "operation" in evidence_capabilities
            else (
                "environment_evidence_missing"
                if field_group == "environment_requirement"
                else "operation_evidence_missing"
            )
        )
    if decision.category is ClaimCategory.CODE_OR_COMMAND:
        return (
            None
            if evidence_capabilities.intersection({"command", "code_example"})
            else "executable_evidence_missing"
        )
    if decision.category is ClaimCategory.FIXED_RESULT:
        return (
            None
            if "expected_result" in evidence_capabilities
            else (
                "acceptance_evidence_missing"
                if field_group == "acceptance_criterion"
                else "expected_result_evidence_missing"
            )
        )
    if decision.category is ClaimCategory.ERROR_HANDLING:
        return (
            None
            if "error_handling" in evidence_capabilities
            else "error_evidence_missing"
        )
    if decision.category is ClaimCategory.VERSION_BOUNDARY:
        return (
            None
            if "version_boundary" in evidence_capabilities
            else "version_boundary_missing"
        )
    return None


def sanitize_deterministic_text(path: str, value: str) -> tuple[str, list[str]]:
    """Remove only sentences assigned to deterministic rejection by the policy."""
    group = field_group_for_path(path)
    kept: list[str] = []
    codes: list[str] = []
    for sentence in split_policy_sentences(value):
        decision = classify_claim(group, sentence)
        if (
            decision.review_disposition is ReviewDisposition.DETERMINISTIC_VALIDATE
            and decision.violation_code
        ):
            codes.append(decision.violation_code)
            continue
        kept.append(sentence)
    return "".join(kept).strip(" \t\r\n。！？!?；;"), list(dict.fromkeys(codes))
