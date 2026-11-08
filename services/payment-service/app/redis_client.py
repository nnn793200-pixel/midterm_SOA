import json
import logging
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional
import redis
from fastapi import HTTPException, status
from app.config import settings

logger = logging.getLogger(settings.SERVICE_NAME)

redis_pool = redis.ConnectionPool.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=50,
    socket_connect_timeout=2.0,
    socket_timeout=2.0,
)

# Lua Script giải phóng Distributed Lock an toàn (chỉ xóa khi đúng owner token)
LUA_RELEASE_LOCK = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=redis_pool)


def acquire_distributed_lock(
    r: redis.Redis,
    lock_key: str,
    ttl_ms: int = 15000,
    wait_timeout_s: float = 10.0,
) -> str:
    """
    Giành Distributed Lock bằng Redis `SET lock_key token NX PX ttl_ms`.
    Nếu hết thời gian chờ mà chưa lấy được lock, ném HTTP 409 Conflict.
    """
    token = str(uuid.uuid4())
    deadline = time.monotonic() + wait_timeout_s

    while True:
        if r.set(lock_key, token, nx=True, px=ttl_ms):
            return token
        if time.monotonic() >= deadline:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "CONCURRENT_TRANSACTION_LOCKED",
                    "message": "Hệ thống đang xử lý giao dịch khác trên cùng tài khoản hoặc MSSV. Vui lòng thử lại sau giây lát.",
                },
            )
        time.sleep(0.025)


def release_distributed_lock(
    r: redis.Redis, lock_key: str, token: Optional[str]
) -> None:
    if not token:
        return
    try:
        r.eval(LUA_RELEASE_LOCK, 1, lock_key, token)
    except redis.RedisError as exc:
        logger.warning("Failed to release Redis lock %s: %s", lock_key, str(exc))


@contextmanager
def acquire_payment_locks(
    account_id: str,
    student_id: str,
    ttl_ms: int = 15000,
    wait_timeout_s: float = 10.0,
) -> Iterator[None]:
    """
    Khóa phân tán theo thứ tự cố định:
      1. `lock:account:{user_id}`
      2. `lock:tuition:{student_id}`
    Giúp serialize giao dịch ở tầng điều phối và ngăn deadlock khi kết hợp
    với PostgreSQL `SELECT ... FOR UPDATE`.
    """
    clean_mssv = student_id.strip().upper()
    account_key = f"lock:account:{account_id}"
    tuition_key = f"lock:tuition:{clean_mssv}"

    r = get_redis()
    account_token: Optional[str] = None
    tuition_token: Optional[str] = None
    redis_available = True

    try:
        account_token = acquire_distributed_lock(
            r, account_key, ttl_ms=ttl_ms, wait_timeout_s=wait_timeout_s
        )
        tuition_token = acquire_distributed_lock(
            r, tuition_key, ttl_ms=ttl_ms, wait_timeout_s=wait_timeout_s
        )
    except HTTPException:
        if account_token:
            release_distributed_lock(r, account_key, account_token)
        raise
    except redis.RedisError as exc:
        redis_available = False
        logger.warning(
            "Redis distributed lock unavailable (%s); falling back to PostgreSQL row locks.",
            str(exc),
        )

    try:
        yield
    finally:
        if redis_available:
            release_distributed_lock(r, tuition_key, tuition_token)
            release_distributed_lock(r, account_key, account_token)


def get_idempotency_from_redis(idempotency_key: str) -> Optional[Dict[str, Any]]:
    try:
        r = get_redis()
        raw = r.get(f"idempotency:{idempotency_key}")
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logger.warning("Redis idempotency read skipped: %s", str(exc))
    return None


def set_idempotency_in_redis(
    idempotency_key: str,
    payload: Dict[str, Any],
    ttl_seconds: int = 86400,
) -> None:
    try:
        r = get_redis()
        r.set(
            f"idempotency:{idempotency_key}",
            json.dumps(payload, default=str),
            ex=ttl_seconds,
        )
    except Exception as exc:
        logger.warning("Redis idempotency write skipped: %s", str(exc))


def clear_payment_redis_keys() -> None:
    try:
        r = get_redis()
        for pattern in ("idempotency:*", "lock:account:*", "lock:tuition:*"):
            for key in r.scan_iter(pattern):
                r.delete(key)
    except Exception as exc:
        logger.warning("Redis cleanup skipped: %s", str(exc))
