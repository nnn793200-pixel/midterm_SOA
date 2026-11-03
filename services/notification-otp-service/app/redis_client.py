import json
import secrets
from datetime import datetime
from typing import Set, Tuple
import redis
from app.config import settings

redis_pool = redis.ConnectionPool.from_url(
    settings.REDIS_URL, decode_responses=True, max_connections=50
)


def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=redis_pool)


# Lua Script đảm bảo kiểm tra và tiêu hủy OTP nguyên tử (One-time use)
LUA_VERIFY_AND_CONSUME_OTP = """
local tx_key = KEYS[1]
local submitted_code = ARGV[1]

local raw = redis.call('GET', tx_key)
if not raw then
    return 'EXPIRED_OR_MISSING'
end

local data = cjson.decode(raw)
if data['is_used'] == true then
    return 'ALREADY_USED'
end

local pttl = redis.call('PTTL', tx_key)
if pttl <= 0 then
    return 'EXPIRED_OR_MISSING'
end

if data['otp_code'] ~= submitted_code then
    local attempts = (data['attempt_count'] or 0) + 1
    data['attempt_count'] = attempts
    if attempts >= 5 then
        data['is_used'] = true
        local active_key = 'otp:active_code:' .. data['otp_code']
        redis.call('DEL', active_key)
    end
    redis.call('SET', tx_key, cjson.encode(data), 'PX', pttl)
    if attempts >= 5 then
        return 'MAX_ATTEMPTS_EXCEEDED'
    end
    return 'INVALID_CODE'
end

-- Khớp mã OTP -> Đánh dấu đã dùng 1 lần (is_used = true) và giải phóng active_code
data['is_used'] = true
redis.call('SET', tx_key, cjson.encode(data), 'PX', pttl)
local active_key = 'otp:active_code:' .. data['otp_code']
redis.call('DEL', active_key)

return 'VERIFIED'
"""


def generate_unique_otp_in_redis(
    transaction_id: str,
    recipient_email: str,
    expires_at: datetime,
    active_db_codes: Set[str],
) -> str:
    """
    Sinh mã OTP 6 chữ số gắn với transaction_id, đảm bảo KHÔNG trùng với bất kỳ
    OTP nào đang có hiệu lực (trong Redis lẫn PostgreSQL) với TTL tối đa 300s (5 phút).
    """
    r = get_redis()
    rng = secrets.SystemRandom()
    ttl = settings.OTP_TTL_SECONDS

    # Nếu giao dịch này đã từng có OTP cũ trên Redis thì thu hồi trước
    old_tx_raw = r.get(f"otp:tx:{transaction_id}")
    if old_tx_raw:
        try:
            old_data = json.loads(old_tx_raw)
            old_code = old_data.get("otp_code")
            if old_code:
                r.delete(f"otp:active_code:{old_code}")
        except Exception:
            pass

    for _ in range(100):
        candidate = f"{rng.randint(100000, 999999)}"
        if candidate in active_db_codes:
            continue

        # SET NX EX 300 đảm bảo không trùng với bất kỳ OTP nào đang active trên Redis
        claimed = r.set(
            f"otp:active_code:{candidate}",
            transaction_id,
            nx=True,
            ex=ttl,
        )
        if claimed:
            tx_payload = {
                "transaction_id": transaction_id,
                "otp_code": candidate,
                "recipient_email": recipient_email,
                "expires_at": expires_at.isoformat(),
                "is_used": False,
                "attempt_count": 0,
            }
            r.set(f"otp:tx:{transaction_id}", json.dumps(tx_payload), ex=ttl)
            return candidate

    raise RuntimeError("Không thể sinh mã OTP duy nhất sau 100 lần thử.")


def verify_and_consume_otp_in_redis(
    transaction_id: str, submitted_code: str
) -> str:
    r = get_redis()
    tx_key = f"otp:tx:{transaction_id}"
    result = r.eval(LUA_VERIFY_AND_CONSUME_OTP, 1, tx_key, submitted_code)
    return str(result)
