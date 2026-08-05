from sqlalchemy import select
from app.models import IdempotencyRecord
from app.repositories.base import Repository


class IdempotencyRepository(Repository):
    def get(self, scope: str, request_key: str) -> IdempotencyRecord | None:
        return self.db.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.request_key == request_key,
            )
        )

    def create(self, scope: str, request_key: str) -> IdempotencyRecord:
        record = IdempotencyRecord(scope=scope, request_key=request_key, status="processing")
        self.db.add(record)
        self.db.flush()
        return record

    def complete(
        self,
        record: IdempotencyRecord,
        *,
        entity_type: str | None,
        entity_public_id: str | None,
        result: dict,
    ) -> None:
        record.status = "completed"
        record.entity_type = entity_type
        record.entity_public_id = entity_public_id
        record.result_json = result
