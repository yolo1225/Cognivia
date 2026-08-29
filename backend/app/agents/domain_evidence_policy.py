"""Internal, domain-aware evidence depth policy without contract changes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock

from app.agents.contracts import RetrievedChunk


class EvidenceCapability(StrEnum):
    CONCEPT = "concept"
    OPERATION = "operation"
    COMMAND = "command"
    CODE_EXAMPLE = "code_example"
    EXPECTED_RESULT = "expected_result"
    ERROR_HANDLING = "error_handling"
    VERSION_BOUNDARY = "version_boundary"


CAPABILITY_ALIASES = {
    "concept": EvidenceCapability.CONCEPT,
    "operation": EvidenceCapability.OPERATION,
    "command": EvidenceCapability.COMMAND,
    "code_example": EvidenceCapability.CODE_EXAMPLE,
    "expected_result": EvidenceCapability.EXPECTED_RESULT,
    "error_handling": EvidenceCapability.ERROR_HANDLING,
    "version_boundary": EvidenceCapability.VERSION_BOUNDARY,
}

_DECLARED_CAPABILITIES_BY_DOMAIN: dict[str, dict[str, list[str]]] = {}
_DECLARED_CAPABILITIES_LOCK = RLock()


def register_domain_evidence_capabilities(
    domain_code: str, declared_by_knowledge: dict[str, list[str]]
) -> None:
    """Publish the current domain capability sidecar for generation and review."""
    normalized = {
        str(knowledge_id): normalize_evidence_capabilities(values)
        for knowledge_id, values in declared_by_knowledge.items()
    }
    with _DECLARED_CAPABILITIES_LOCK:
        _DECLARED_CAPABILITIES_BY_DOMAIN[domain_code] = normalized


def normalize_evidence_capabilities(values: object) -> list[str]:
    """Return the canonical, domain-neutral capability vocabulary.

    Unknown and retired values are discarded rather than granting evidence.
    """
    raw = values if isinstance(values, (list, tuple, set, frozenset)) else []
    normalized = {
        CAPABILITY_ALIASES[str(value).strip().lower()].value
        for value in raw
        if str(value).strip().lower() in CAPABILITY_ALIASES
    }
    normalized.add(EvidenceCapability.CONCEPT.value)
    return sorted(normalized)


def classify_evidence_capabilities(content: str) -> list[str]:
    """Derive the evidence vocabulary from the source text itself."""
    return sorted(
        capability.value
        for capability in DomainEvidencePolicy(domain_code="").classify_content(content)
    )


@dataclass(frozen=True, slots=True)
class DomainEvidencePolicy:
    domain_code: str
    declared_by_knowledge: dict[str, frozenset[EvidenceCapability]] | None = None

    def classify(self, chunk: RetrievedChunk) -> frozenset[EvidenceCapability]:
        # Claim-level validation is intentionally chunk-local. Knowledge-level
        # declarations are an aggregate used for discovery and reporting; using
        # them here would let one operational section authorize unrelated chunks.
        return self.classify_content(chunk.content)

    def classify_content(self, content: str) -> frozenset[EvidenceCapability]:
        """Classify explicit evidence structure without relying on domain keywords."""
        text = content.lower()
        capabilities = {EvidenceCapability.CONCEPT}
        for capability, pattern in _GENERIC_PATTERNS.items():
            if pattern.search(text):
                capabilities.add(capability)
        return frozenset(capabilities)


_GENERIC_PATTERNS = {
    EvidenceCapability.OPERATION: re.compile(
        r"(?:^|\n)#{1,6}\s*(?:操作步骤|分步操作|实操|应用任务|实践任务|实验步骤|操作方法)\s*$|"
        r"(?:^|\n)标题\s*[:：].*(?:操作步骤|分步操作|实操|应用任务|实践任务|实验步骤|操作方法)\s*$|"
        r"(?:^|\n)\s*(?:操作步骤|分步操作|实操任务|应用任务|实践任务|实验步骤|操作方法)\s*[:：]|"
        r"(?:^|\n)\s*(?:步骤\s*)?\d+[.、)]\s*(?:执行|运行|创建|配置|安装|输入|选择|检查|调用|提交)|"
        r"(?:执行|运行|创建|配置|安装|输入|选择|检查|调用|提交)(?:以下|下列|该|此)?(?:命令|代码|文件|配置|请求|操作)",
        re.M,
    ),
    EvidenceCapability.COMMAND: re.compile(
        r"```(?:bash|sh|shell|console|powershell|cmd)\s*\n[\s\S]*?```|"
        r"(?:^|\n)\s*(?:\$\s*)?(?:git|curl|docker(?:\s+compose)?|npm|pnpm|yarn|pip|python|pytest|uvicorn)\s+[^\n]+",
        re.M,
    ),
    EvidenceCapability.CODE_EXAMPLE: re.compile(
        r"```(?:python|py|javascript|js|typescript|ts|java|go|rust|sql|json|yaml|yml)\s*\n[\s\S]*?```|"
        r"(?:^|\n)\s*(?:def|class|import|from)\s+\w+|"
        r"(?:^|\n)\s*(?:const|let|var)\s+\w+\s*=",
        re.M,
    ),
    EvidenceCapability.EXPECTED_RESULT: re.compile(
        r"(?:^|\n)#{1,6}\s*(?:预期结果|预期输出|验收结果|输出示例)\s*$|"
        r"(?:^|\n)标题\s*[:：].*(?:预期结果|预期输出|验收结果|输出示例)\s*$|"
        r"(?:^|\n)\s*(?:预期结果|预期输出|验收结果|输出示例)\s*[:：]|"
        r"(?:运行|执行|调用|提交)(?:后|成功后).{0,60}(?:返回|输出|显示|生成|状态)",
        re.M,
    ),
    EvidenceCapability.ERROR_HANDLING: re.compile(
        r"(?:^|\n)#{1,6}\s*(?:常见错误|错误处理|故障排查|排错|异常处理)\s*$|"
        r"(?:^|\n)\s*(?:常见错误|错误处理|故障排查|排错|异常处理)\s*[:：]|"
        r"错误码|异常|故障|失败时|超时|\b(?:4\d\d|5\d\d)\b",
        re.M,
    ),
    EvidenceCapability.VERSION_BOUNDARY: re.compile(r"版本|适用范围|兼容性|能力边界"),
}

def get_domain_evidence_policy(
    domain_code: str,
    declared_by_knowledge: dict[str, list[str]] | None = None,
) -> DomainEvidencePolicy:
    if declared_by_knowledge is None:
        with _DECLARED_CAPABILITIES_LOCK:
            declared_by_knowledge = dict(
                _DECLARED_CAPABILITIES_BY_DOMAIN.get(domain_code, {})
            )
    declared = {
        knowledge_id: frozenset(EvidenceCapability(value) for value in normalize_evidence_capabilities(values))
        for knowledge_id, values in (declared_by_knowledge or {}).items()
    }
    return DomainEvidencePolicy(domain_code=domain_code, declared_by_knowledge=declared)


def evidence_capability_payload(
    chunks: list[RetrievedChunk],
    domain_code: str,
    declared_by_knowledge: dict[str, list[str]] | None = None,
) -> list[dict[str, object]]:
    policy = get_domain_evidence_policy(domain_code, declared_by_knowledge)
    return [
        {
            "source_ref_id": chunk.source.source_ref_id,
            "knowledge_id": chunk.knowledge_id,
            "capabilities": sorted(item.value for item in policy.classify(chunk)),
        }
        for chunk in chunks
    ]
