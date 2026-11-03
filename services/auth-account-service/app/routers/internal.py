from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models import UserAccount, AccountLedgerEntry
from app.schemas import (
    UserProfileResponse,
    DebitAccountRequest,
    DebitAccountResponse,
    RefundAccountRequest,
    RefundAccountResponse,
)
from app.seed import seed_accounts

router = APIRouter(prefix="/internal/accounts", tags=["Internal Account Operations"])


@router.get(
    "/{account_id}",
    response_model=UserProfileResponse,
    status_code=status.HTTP_200_OK,
)
def get_account_internal(account_id: UUID, db: Session = Depends(get_db)):
    """
    API đọc thông tin tài khoản & số dư phục vụ bước Pre-check khi khởi tạo giao dịch.
    TUYỆT ĐỐI KHÔNG giữ DB Row Lock (SELECT FOR UPDATE) trong suốt 5 phút chờ nhập OTP.
    """
    account = db.query(UserAccount).filter(UserAccount.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ACCOUNT_NOT_FOUND",
                "message": f"Không tìm thấy tài khoản với ID {account_id}.",
            },
        )
    return UserProfileResponse.model_validate(account)


@router.post(
    "/debit",
    response_model=DebitAccountResponse,
    status_code=status.HTTP_200_OK,
)
def debit_account_atomic(payload: DebitAccountRequest, db: Session = Depends(get_db)):
    """
    Thực thi trừ tiền nguyên tử ngay tại thời điểm OTP được xác thực thành công.
    Sử dụng Pessimistic Locking (SELECT ... FOR UPDATE) kết hợp kiểm tra số dư
    để giải quyết triệt để Concurrency 1 (Nhiều giao dịch đồng thời trên cùng 1 tài khoản).
    """
    # 1. Kiểm tra Idempotency-Key (Nếu bút toán này đã thực thi trước đó thì trả kết quả ngay)
    existing_entry = (
        db.query(AccountLedgerEntry)
        .filter(AccountLedgerEntry.idempotency_key == payload.idempotency_key)
        .first()
    )
    if existing_entry:
        account_now = (
            db.query(UserAccount)
            .filter(UserAccount.id == existing_entry.account_id)
            .first()
        )
        return DebitAccountResponse(
            account_id=existing_entry.account_id,
            transaction_id=existing_entry.transaction_id,
            ledger_entry_id=existing_entry.id,
            entry_type=existing_entry.entry_type,
            amount=float(existing_entry.amount),
            balance_before=float(existing_entry.balance_before),
            balance_after=float(existing_entry.balance_after),
            version=account_now.version if account_now else 1,
            processed_at=existing_entry.created_at,
        )

    try:
        # 2. Khóa Pessimistic (SELECT ... FOR UPDATE) trên dòng tài khoản người nộp
        account = (
            db.query(UserAccount)
            .filter(UserAccount.id == payload.account_id)
            .with_for_update()
            .first()
        )

        if not account:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "ACCOUNT_NOT_FOUND",
                    "message": "Không tìm thấy tài khoản người nộp tiền.",
                },
            )

        if account.status != "ACTIVE":
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ACCOUNT_INACTIVE",
                    "message": "Tài khoản không ở trạng thái hoạt động.",
                },
            )

        current_balance = Decimal(str(account.available_balance))
        debit_amount = Decimal(str(payload.amount))

        # 3. Kiểm tra lại số dư khả dụng ngay trong khóa Pessimistic
        if current_balance < debit_amount:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "INSUFFICIENT_BALANCE",
                    "message": "Số dư khả dụng không đủ để thực hiện giao dịch thanh toán học phí.",
                    "details": {
                        "available_balance": float(current_balance),
                        "required_amount": float(debit_amount),
                    },
                },
            )

        # 4. Trừ tiền, tăng version và ghi sổ cái trong cùng 1 Database Transaction
        new_balance = current_balance - debit_amount
        now = datetime.now(timezone.utc)

        account.available_balance = new_balance
        account.version = account.version + 1
        account.updated_at = now

        ledger_entry = AccountLedgerEntry(
            account_id=account.id,
            transaction_id=payload.transaction_id,
            entry_type="DEBIT",
            amount=debit_amount,
            balance_before=current_balance,
            balance_after=new_balance,
            idempotency_key=payload.idempotency_key,
            description=payload.description,
            created_at=now,
        )
        db.add(ledger_entry)
        db.commit()
        db.refresh(ledger_entry)
        db.refresh(account)

        return DebitAccountResponse(
            account_id=account.id,
            transaction_id=payload.transaction_id,
            ledger_entry_id=ledger_entry.id,
            entry_type="DEBIT",
            amount=float(debit_amount),
            balance_before=float(current_balance),
            balance_after=float(new_balance),
            version=account.version,
            processed_at=ledger_entry.created_at,
        )

    except HTTPException:
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CONCURRENT_BALANCE_CONFLICT",
                "message": f"Xung đột dữ liệu khi trừ tiền tài khoản: {str(exc.orig)}",
            },
        )


@router.post(
    "/refund",
    response_model=RefundAccountResponse,
    status_code=status.HTTP_200_OK,
)
def refund_account_compensation(
    payload: RefundAccountRequest, db: Session = Depends(get_db)
):
    """
    Saga Compensating Action: Hoàn trả số tiền vào tài khoản người nộp ngay lập tức
    khi bước gạch nợ học phí tại tuition-service bị từ chối (do tài khoản khác vừa đóng xong).
    """
    existing_refund = (
        db.query(AccountLedgerEntry)
        .filter(AccountLedgerEntry.idempotency_key == payload.idempotency_key)
        .first()
    )
    if existing_refund:
        account_now = (
            db.query(UserAccount)
            .filter(UserAccount.id == existing_refund.account_id)
            .first()
        )
        return RefundAccountResponse(
            account_id=existing_refund.account_id,
            transaction_id=existing_refund.transaction_id,
            ledger_entry_id=existing_refund.id,
            entry_type=existing_refund.entry_type,
            amount=float(existing_refund.amount),
            balance_before=float(existing_refund.balance_before),
            balance_after=float(existing_refund.balance_after),
            version=account_now.version if account_now else 1,
            processed_at=existing_refund.created_at,
        )

    account = (
        db.query(UserAccount)
        .filter(UserAccount.id == payload.account_id)
        .with_for_update()
        .first()
    )
    if not account:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ACCOUNT_NOT_FOUND",
                "message": "Không tìm thấy tài khoản cần hoàn tiền bù trừ.",
            },
        )

    current_balance = Decimal(str(account.available_balance))
    refund_amount = Decimal(str(payload.amount))
    new_balance = current_balance + refund_amount
    now = datetime.now(timezone.utc)

    account.available_balance = new_balance
    account.version = account.version + 1
    account.updated_at = now

    ledger_entry = AccountLedgerEntry(
        account_id=account.id,
        transaction_id=payload.transaction_id,
        entry_type="COMPENSATION_REFUND",
        amount=refund_amount,
        balance_before=current_balance,
        balance_after=new_balance,
        idempotency_key=payload.idempotency_key,
        description=payload.reason,
        created_at=now,
    )
    db.add(ledger_entry)
    db.commit()
    db.refresh(ledger_entry)
    db.refresh(account)

    return RefundAccountResponse(
        account_id=account.id,
        transaction_id=payload.transaction_id,
        ledger_entry_id=ledger_entry.id,
        entry_type="COMPENSATION_REFUND",
        amount=float(refund_amount),
        balance_before=float(current_balance),
        balance_after=float(new_balance),
        version=account.version,
        processed_at=ledger_entry.created_at,
    )


@router.post("/reset-demo", status_code=status.HTTP_200_OK)
def reset_demo_accounts(db: Session = Depends(get_db)):
    """
    Khôi phục số dư mặc định của các tài khoản mẫu phục vụ kiểm thử tự động & demo.
    """
    seed_accounts(db, force_reset=True)
    return {
        "status": "RESET_SUCCESS",
        "message": "Đã khôi phục số dư mặc định cho toàn bộ tài khoản mẫu.",
    }
