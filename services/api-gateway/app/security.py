from typing import Dict, Any, Optional
import jwt
from fastapi import HTTPException, Header, status
from app.config import settings


def verify_jwt_token(
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "MISSING_BEARER_TOKEN",
                "message": "Yêu cầu xác thực. Vui lòng đính kèm header 'Authorization: Bearer <token>'.",
            },
        )

    token = authorization.split(" ", 1)[1].strip()
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
                "message": "Phiên đăng nhập (JWT) đã hết hạn. Vui lòng đăng nhập lại.",
            },
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_TOKEN",
                "message": "Chữ ký JWT không hợp lệ.",
            },
        )
