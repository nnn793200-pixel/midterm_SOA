import uuid
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models import UserAccount, AccountLedgerEntry
from app.security import hash_password

DEFAULT_PASSWORD = "Password@123"

SEED_ACCOUNTS = [
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111105"),
        "username": "524K0032",
        "full_name": "Trần Minh Nghĩa",
        "phone_number": "0905240032",
        "email": "524k0032@student.tdtu.edu.vn",
        "available_balance": Decimal("50000000.00"),
        "status": "ACTIVE",
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111106"),
        "username": "524K0033",
        "full_name": "Huỳnh Trung Tín",
        "phone_number": "0905240033",
        "email": "524k0033@student.tdtu.edu.vn",
        "available_balance": Decimal("35000000.00"),
        "status": "ACTIVE",
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111107"),
        "username": "524V0007",
        "full_name": "Phan Nguyễn Thảo Như",
        "phone_number": "0905240007",
        "email": "524v0007@student.tdtu.edu.vn",
        "available_balance": Decimal("50000000.00"),
        "status": "ACTIVE",
    },
    # Hai tài khoản người nộp tiền bổ sung, dùng chung email thật của Nghĩa và Tín để OTP luôn về hộp thư thật.
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111101"),
        "username": "phuhuynh1",
        "full_name": "Nguyễn Văn An",
        "phone_number": "0901234567",
        "email": "524k0032@student.tdtu.edu.vn",
        "available_balance": Decimal("25000000.00"),
        "status": "ACTIVE",
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111102"),
        "username": "phuhuynh2",
        "full_name": "Trần Thị Bình",
        "phone_number": "0902345678",
        "email": "524k0033@student.tdtu.edu.vn",
        "available_balance": Decimal("30000000.00"),
        "status": "ACTIVE",
    },
    # === [CHỖ THÊM TÀI KHOẢN / EMAIL CỦA GIẢNG VIÊN KHI DEMO TRÊN LỚP] ===
    # Bỏ comment, điền thông tin của thầy/cô, lưu file rồi gọi reset-demo (nút "Reset Demo" hoặc
    # POST /api/v1/system/reset-demo) là tài khoản mới được áp dụng ngay (mật khẩu chung: Password@123).
    # {
    #     "id": uuid.UUID("11111111-1111-1111-1111-111111111199"),
    #     "username": "giangvien",
    #     "full_name": "Họ và tên giảng viên",
    #     "phone_number": "0900000000",
    #     "email": "email.cua.giang.vien@tdtu.edu.vn",
    #     "available_balance": Decimal("50000000.00"),
    #     "status": "ACTIVE",
    # },
    # === [HẾT KHỐI THÊM TÀI KHOẢN GIẢNG VIÊN] ===
]


def _remove_stale_accounts(db: Session) -> None:
    """Xóa các tài khoản không còn nằm trong SEED_ACCOUNTS (ví dụ tài khoản mẫu cũ)."""
    seed_usernames = {item["username"] for item in SEED_ACCOUNTS}
    stale = (
        db.query(UserAccount)
        .filter(UserAccount.username.notin_(seed_usernames))
        .all()
    )
    if not stale:
        return
    stale_ids = [u.id for u in stale]
    db.query(AccountLedgerEntry).filter(
        AccountLedgerEntry.account_id.in_(stale_ids)
    ).delete(synchronize_session=False)
    for user in stale:
        db.delete(user)
    db.flush()


def seed_accounts(db: Session, force_reset: bool = False) -> None:
    if force_reset:
        db.query(AccountLedgerEntry).delete()

    _remove_stale_accounts(db)
    hashed_pw = hash_password(DEFAULT_PASSWORD)

    for item in SEED_ACCOUNTS:
        acc = (
            db.query(UserAccount)
            .filter(UserAccount.username == item["username"])
            .first()
        )
        if acc:
            acc.full_name = item["full_name"]
            acc.phone_number = item["phone_number"]
            acc.email = item["email"]
            if force_reset:
                acc.available_balance = item["available_balance"]
                acc.status = item["status"]
                acc.password_hash = hashed_pw
                acc.version = 1
        else:
            db.add(
                UserAccount(
                    id=item["id"],
                    username=item["username"],
                    password_hash=hashed_pw,
                    full_name=item["full_name"],
                    phone_number=item["phone_number"],
                    email=item["email"],
                    available_balance=item["available_balance"],
                    status=item["status"],
                    version=1,
                )
            )
    db.commit()
