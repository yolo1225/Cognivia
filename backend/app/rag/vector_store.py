from typing import Any

import chromadb

from app.core.config import settings


class VectorStore:
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        self.host = host if host is not None else settings.chroma_host
        self.port = port or settings.chroma_port
        if not self.host:
            raise ValueError("CHROMA_HOST is required; ChromaDB runs as an independent service")
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = chromadb.HttpClient(host=self.host, port=self.port)
        return self._client

    def health_check(self) -> dict[str, str | int]:
        collections = self.client.list_collections()
        result: dict[str, str | int] = {
            "status": "ok",
            "collections": len(collections),
        }
        result["mode"] = "http"
        result["host"] = self.host
        result["port"] = self.port
        return result

    def connection_info(self) -> dict[str, str | int]:
        return {"mode": "http", "host": self.host, "port": self.port}


def get_vector_store() -> VectorStore:
    return VectorStore()
