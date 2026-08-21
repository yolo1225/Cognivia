from typing import Annotated
from fastapi import Header


def require_idempotency_key(
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
) -> str:
    return idempotency_key
