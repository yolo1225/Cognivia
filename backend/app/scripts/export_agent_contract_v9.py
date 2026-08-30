from __future__ import annotations

import json
from pathlib import Path

from app.agents.contract_examples import (
    agent_message_example,
    dump_example,
    feedback_flow_example,
    initial_generation_flow_example,
)
from app.agents.contracts import AgentContractSchema


PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = PROJECT_ROOT / "docs" / "contracts" / "v9"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        OUTPUT_DIR / "agent-contract-v9.schema.json": AgentContractSchema.model_json_schema(),
        OUTPUT_DIR / "agent-contract-v9.examples.json": dump_example(
            {
                "agent_message": agent_message_example(),
                "initial_generation": initial_generation_flow_example(),
                "resource_feedback": feedback_flow_example(),
            }
        ),
    }
    for target, payload in outputs.items():
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "outputs": [str(path) for path in outputs]}))


if __name__ == "__main__":
    main()
