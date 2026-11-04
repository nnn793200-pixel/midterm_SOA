from typing import Dict, Any, Optional
import jwt
from fastapi import HTTPException, Header, status
from app.config import settings


def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "TOKEN_EXPIRED",
                "message": "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.",
            },
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_TOKEN",
                "message": "Token xác thực không hợp lệ.",
            },
        )


def get_current_user_id(
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-ID"),
) -> str:
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        payload = decode_access_token(token)
        sub = payload.get("sub")
        if sub:
            return str(sub)

    if x_user_id:
        return x_user_id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "UNAUTHORIZED",
            "message": "Thiếu thông tin xác thực JWT Bearer Token.",
        },
    )
