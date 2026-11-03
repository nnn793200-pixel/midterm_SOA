import uuid
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models import UserAccount, AccountLedgerEntry
from app.security import hash_password

DEFAULT_PASSWORD = "Password@123"

SEED_ACCOUNTS = [
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111101"),
        "username": "nguyenvana",
        "full_name": "Nguyễn Văn A",
        "phone_number": "0901234567",
        "email": "nguyenvana@tdtu.edu.vn",
        "available_balance": Decimal("25000000.00"),
        "status": "ACTIVE",
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111102"),
        "username": "tranvanb",
        "full_name": "Trần Văn B",
        "phone_number": "0902345678",
        "email": "tranvanb@tdtu.edu.vn",
        "available_balance": Decimal("30000000.00"),
        "status": "ACTIVE",
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111103"),
        "username": "lethic",
        "full_name": "Lê Thị C",
        "phone_number": "0903456789",
        "email": "lethic@tdtu.edu.vn",
        "available_balance": Decimal("5000000.00"),
        "status": "ACTIVE",
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111104"),
        "username": "phamvand",
        "full_name": "Phạm Văn D",
        "phone_number": "0904567890",
        "email": "phamvand@tdtu.edu.vn",
        "available_balance": Decimal("100000000.00"),
        "status": "ACTIVE",
    },
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
        "available_balance": Decimal("50000000.00"),
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
]


def seed_accounts(db: Session, force_reset: bool = False) -> None:
    if force_reset:
        db.query(AccountLedgerEntry).delete()
        for item in SEED_ACCOUNTS:
            acc = (
                db.query(UserAccount)
                .filter(UserAccount.username == item["username"])
                .first()
            )
            if acc:
                acc.available_balance = item["available_balance"]
                acc.status = item["status"]
                acc.version = 1
            else:
                db.add(
                    UserAccount(
                        id=item["id"],
                        username=item["username"],
                        password_hash=hash_password(DEFAULT_PASSWORD),
                        full_name=item["full_name"],
                        phone_number=item["phone_number"],
                        email=item["email"],
                        available_balance=item["available_balance"],
                        status=item["status"],
                        version=1,
                    )
                )
        db.commit()
        return

    hashed_pw = hash_password(DEFAULT_PASSWORD)
    for item in SEED_ACCOUNTS:
        exists = (
            db.query(UserAccount)
            .filter(UserAccount.username == item["username"])
            .first()
        )
        if not exists:
            account = UserAccount(
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
            db.add(account)
    db.commit()
