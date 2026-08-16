import json
from hashlib import sha256
from redis import Redis
from redis.exceptions import RedisError
from app.core.config import settings


class SessionUnavailable(RuntimeError):
    pass


class SessionStore:
    def __init__(self) -> None:
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True)

    def _call(self, method, *args):
        try:
            return method(*args)
        except RedisError as exc:
            raise SessionUnavailable("认证会话服务不可用") from exc

    def put(self, sid: str, payload: dict) -> None:
        pipe = self.redis.pipeline()
        pipe.setex(f"auth:session:{sid}", settings.refresh_token_days * 86400, json.dumps(payload))
        pipe.sadd(f"auth:user_sessions:{payload['user_id']}", sid)
        pipe.expire(f"auth:user_sessions:{payload['user_id']}", settings.refresh_token_days * 86400)
        self._call(pipe.execute)

    def get(self, sid: str) -> dict | None:
        value = self._call(self.redis.get, f"auth:session:{sid}")
        return json.loads(value) if value else None

    def delete(self, sid: str) -> None:
        data = self.get(sid)
        pipe = self.redis.pipeline()
        pipe.delete(f"auth:session:{sid}")
        if data:
            pipe.srem(f"auth:user_sessions:{data['user_id']}", sid)
        self._call(pipe.execute)

    def revoke_user(self, user_id: str) -> None:
        key = f"auth:user_sessions:{user_id}"
        ids = self._call(self.redis.smembers, key) or set()
        pipe = self.redis.pipeline()
        for sid in ids:
            pipe.delete(f"auth:session:{sid}")
        pipe.delete(key)
        self._call(pipe.execute)

    def login_blocked(self, username: str, ip: str) -> bool:
        return bool(
            self._call(self.redis.exists, f"auth:blocked:user:{username}")
            or self._call(
                self.redis.exists, f"auth:blocked:ip:{sha256(ip.encode()).hexdigest()[:16]}"
            )
        )

    def record_failure(self, username: str, ip: str) -> None:
        for key in (
            f"auth:fail:user:{username}",
            f"auth:fail:ip:{sha256(ip.encode()).hexdigest()[:16]}",
        ):
            count = self._call(self.redis.incr, key)
            self._call(self.redis.expire, key, 900)
            if count >= 5:
                self._call(self.redis.setex, key.replace("fail", "blocked"), 900, "1")

    def clear_failures(self, username: str) -> None:
        self._call(self.redis.delete, f"auth:fail:user:{username}", f"auth:blocked:user:{username}")


session_store = SessionStore()
