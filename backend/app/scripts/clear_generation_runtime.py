"""Clear local generation/review runtime data without touching learning state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.core.db import SessionLocal
from app.services.generation_runtime_cleanup_service import clear_generation_runtime


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--services-stopped",
        action="store_true",
        help="Acknowledge that backend and generation workers have been stopped.",
    )
    parser.add_argument(
        "--keep-exports",
        action="store_true",
        help="Keep local resource export files while clearing database runtime rows.",
    )
    args = parser.parse_args()
    export_dir = None if args.keep_exports else Path(PROJECT_ROOT) / "storage" / "exports"
    with SessionLocal.begin() as db:
        result = clear_generation_runtime(
            db,
            services_stopped=args.services_stopped,
            export_dir=export_dir,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
