import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import UserAccount, AccountLedgerEntry
from app.schemas import (
    LoginRequest,
    LoginResponse,
    UserProfileResponse,
    AccountMeDetailResponse,
)
from app.security import verify_password, create_access_token, get_current_user_id
from app.config import settings

router = APIRouter(tags=["Authentication & Account Profile"])


@router.post("/auth/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = (
        db.query(UserAccount)
        .filter(UserAccount.username == payload.username.strip())
        .first()
    )

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_CREDENTIALS",
                "message": "Tên đăng nhập hoặc mật khẩu không chính xác.",
            },
        )

    if user.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ACCOUNT_LOCKED",
                "message": "Tài khoản đang bị khóa, không thể thực hiện giao dịch.",
            },
        )

    token_data = {
        "sub": str(user.id),
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "phone_number": user.phone_number,
    }
    access_token = create_access_token(token_data)

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserProfileResponse.model_validate(user),
    )


@router.get(
    "/accounts/me",
    response_model=AccountMeDetailResponse,
    status_code=status.HTTP_200_OK,
)
def get_my_account(
    current_user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        user_uuid = uuid.UUID(current_user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_USER_ID",
                "message": "Định danh người dùng trong token không hợp lệ.",
            },
        )

    user = db.query(UserAccount).filter(UserAccount.id == user_uuid).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ACCOUNT_NOT_FOUND",
                "message": "Không tìm thấy thông tin tài khoản người dùng.",
            },
        )

    recent_entries = (
        db.query(AccountLedgerEntry)
        .filter(AccountLedgerEntry.account_id == user.id)
        .order_by(AccountLedgerEntry.created_at.desc())
        .limit(20)
        .all()
    )

    profile = AccountMeDetailResponse.model_validate(user)
    profile.recent_ledger_entries = recent_entries
    return profile


@router.get("/accounts/demo-users", status_code=status.HTTP_200_OK)
def list_demo_users(db: Session = Depends(get_db)):
    """
    Trả về danh sách tài khoản mẫu phục vụ chọn nhanh trên màn hình Đăng nhập khi Demo.
    """
    users = db.query(UserAccount).order_by(UserAccount.username.asc()).all()
    return {
        "default_password": "Password@123",
        "items": [UserProfileResponse.model_validate(u) for u in users],
    }
