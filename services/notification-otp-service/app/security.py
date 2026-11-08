import secrets
from typing import Optional
from fastapi import Header, HTTPException, status
from app.config import settings


def verify_internal_service_token(
    x_internal_service_token: Optional[str] = Header(
        default=None, alias="X-Internal-Service-Token"
    ),
) -> None:
    if not x_internal_service_token or not secrets.compare_digest(
        x_internal_service_token, settings.INTERNAL_SERVICE_SECRET
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN_INTERNAL_API",
                "message": "Truy cập bị từ chối: thiếu hoặc sai X-Internal-Service-Token.",
            },
        )
