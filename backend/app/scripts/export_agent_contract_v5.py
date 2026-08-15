from __future__ import annotations

import json
from pathlib import Path

from app.agents.contracts import AgentContractSchema


PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = PROJECT_ROOT / "docs" / "contracts" / "v5"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / "agent-contract-v5.schema.json"
    target.write_text(
        json.dumps(AgentContractSchema.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "ok", "output": str(target)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
