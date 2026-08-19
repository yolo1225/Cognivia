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
OUTPUT_DIR = PROJECT_ROOT / "docs" / "contracts" / "v6"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    schema_target = OUTPUT_DIR / "agent-contract-v6.schema.json"
    examples_target = OUTPUT_DIR / "agent-contract-v6.examples.json"
    schema_target.write_text(
        json.dumps(AgentContractSchema.model_json_schema(), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    examples_target.write_text(
        json.dumps(
            dump_example(
                {
                    "agent_message": agent_message_example(),
                    "initial_generation": initial_generation_flow_example(),
                    "resource_feedback": feedback_flow_example(),
                }
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"status": "ok", "outputs": [str(schema_target), str(examples_target)]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
