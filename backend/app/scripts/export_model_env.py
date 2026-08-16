"""Print the effective model config as ``KEY=value`` lines.

The host-side ``scripts/sync-model-env.ps1`` captures this output and upserts
it into the repo root ``.env``. This keeps the running backend from needing
write access to the host ``.env`` file.
"""

from app.services.model_config_service import export_env_lines, reload_from_db


def main() -> None:
    # Ensure the in-memory settings reflect any persisted DB overrides before
    # exporting, so the output always mirrors what the service actually uses.
    reload_from_db()
    print("\n".join(export_env_lines()))


if __name__ == "__main__":
    main()
