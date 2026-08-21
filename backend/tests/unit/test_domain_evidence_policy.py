from app.agents.contract_examples import initial_generation_flow_example
from app.agents.domain_evidence_policy import (
    EvidenceCapability,
    get_domain_evidence_policy,
)


def test_ai_app_dev_classifies_direct_code_and_error_evidence() -> None:
    chunk = initial_generation_flow_example()["retrieve_knowledge"]["output"].chunks[0]
    chunk = chunk.model_copy(
        update={"content": "代码示例：\n```python\nimport json\n```\n超时时记录失败并停止。"}
    )
    capabilities = get_domain_evidence_policy("ai_app_dev").classify(chunk)

    assert EvidenceCapability.CODE_EXAMPLE in capabilities
    assert EvidenceCapability.ERROR_HANDLING in capabilities


def test_unknown_domain_uses_explicit_structure_for_executable_capability() -> None:
    chunk = initial_generation_flow_example()["retrieve_knowledge"]["output"].chunks[0]
    chunk = chunk.model_copy(update={"content": "代码示例：```python\nimport json\n```"})
    capabilities = get_domain_evidence_policy("unknown_domain").classify(chunk)

    assert EvidenceCapability.CODE_EXAMPLE in capabilities


def test_broad_terms_and_negated_examples_do_not_grant_deep_evidence() -> None:
    chunk = initial_generation_flow_example()["retrieve_knowledge"]["output"].chunks[0]
    chunk = chunk.model_copy(
        update={"content": "本文介绍 API 流程与验证，但不构成代码示例，也未提供命令。"}
    )

    capabilities = get_domain_evidence_policy("ai_app_dev").classify(chunk)

    assert capabilities == {EvidenceCapability.CONCEPT}


def test_numbered_steps_and_shell_fence_grant_operational_capabilities() -> None:
    chunk = initial_generation_flow_example()["retrieve_knowledge"]["output"].chunks[0]
    chunk = chunk.model_copy(
        update={
            "content": "## 操作步骤\n1. 执行以下命令。\n```bash\npython -m pytest\n```"
        }
    )

    capabilities = get_domain_evidence_policy("other_domain").classify(chunk)

    assert EvidenceCapability.OPERATION in capabilities
    assert EvidenceCapability.COMMAND in capabilities
