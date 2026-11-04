import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import PaymentTransaction, SagaStepLog, IdempotencyRecord
from app.schemas import (
    InitiatePaymentRequest,
    InitiatePaymentResponse,
    PayerSummarySchema,
    TuitionSummarySchema,
    OtpInfoSchema,
    ConfirmOtpRequest,
    ConfirmOtpResponse,
    TransactionHistoryListResponse,
    TransactionHistoryItemSchema,
    TransactionDetailSchema,
)
from app.security import get_current_user_id
from app.saga import (
    check_idempotency,
    save_idempotency,
    append_saga_step,
    call_precheck_account,
    call_precheck_tuition,
    call_generate_otp,
    call_verify_otp,
    call_debit_account,
    call_mark_tuition_paid,
    call_refund_account_compensation,
    call_send_receipt_email,
    extract_downstream_error,
)

router = APIRouter(tags=["Payment Saga Orchestrator"])


def generate_transaction_code() -> str:
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    rand_digits = f"{secrets.SystemRandom().randint(100000, 999999)}"
    return f"TXN-{now_str}-{rand_digits}"


@router.post(
    "/payments/initiate",
    response_model=InitiatePaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
def initiate_payment(
    request: Request,
    payload: InitiatePaymentRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Bước 1 của Luồng Thanh toán:
    - Kiểm tra Idempotency-Key chống double-submit
    - Thực hiện Pre-check đọc thông tin Người nộp tiền & Học phí (TUYỆT ĐỐI KHÔNG giữ DB Row Lock)
    - Kiểm tra điều kiện: đã tick điều khoản, học phí UNPAID, đóng 100% học phí, số dư >= học phí
    - Tạo giao dịch PENDING_OTP và yêu cầu notification-otp-service sinh OTP (TTL 5 phút) + gửi Email
    """
    if not idempotency_key or len(idempotency_key.strip()) < 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "MISSING_IDEMPOTENCY_KEY",
                "message": "Header 'Idempotency-Key' là bắt buộc để chống gửi trùng giao dịch.",
            },
        )

    clean_idem_key = idempotency_key.strip()
    payer_uuid = uuid.UUID(current_user_id)
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))

    # 1. Kiểm tra Idempotency-Key
    payload_dict = payload.model_dump(mode="json")
    cached = check_idempotency(
        db=db,
        idempotency_key=clean_idem_key,
        account_id=payer_uuid,
        endpoint="POST:/payments/initiate",
        payload_dict=payload_dict,
    )
    if cached:
        cached_status, cached_body = cached
        return JSONResponse(status_code=cached_status, content=cached_body)

    # 2. Kiểm tra điều khoản hệ thống
    if not payload.terms_accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "TERMS_NOT_ACCEPTED",
                "message": "Bạn phải đồng ý với các thỏa thuận và điều khoản của hệ thống trước khi xác nhận giao dịch.",
            },
        )

    # 3. Pre-check thông tin người nộp tiền (Read-only, không giữ lock)
    account_data = call_precheck_account(payer_uuid, correlation_id)
    available_balance = Decimal(str(account_data["available_balance"]))

    # 4. Pre-check thông tin học phí theo MSSV (Read-only, không giữ lock)
    clean_mssv = payload.student_id.strip().upper()
    tuition_lookup = call_precheck_tuition(clean_mssv, correlation_id)
    student_data = tuition_lookup["student"]
    bill_data = tuition_lookup["tuition_bill"]

    if str(bill_data["id"]) != str(payload.tuition_bill_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "TUITION_BILL_MISMATCH",
                "message": "Mã khoản học phí không khớp với MSSV đã tra cứu.",
            },
        )

    if bill_data["status"] != "UNPAID":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TUITION_ALREADY_PAID",
                "message": f"Khoản học phí của sinh viên {clean_mssv} đã được thanh toán.",
            },
        )

    bill_amount = Decimal(str(bill_data["amount"]))
    submitted_amount = Decimal(str(payload.amount))

    # Chỉ cho phép thanh toán TOÀN BỘ khoản học phí
    if submitted_amount != bill_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "PARTIAL_PAYMENT_NOT_ALLOWED",
                "message": "Hệ thống chỉ cho phép thanh toán toàn bộ khoản học phí, không thực hiện thanh toán một phần.",
                "details": {
                    "required_amount": float(bill_amount),
                    "submitted_amount": float(submitted_amount),
                },
            },
        )

    # Số dư khả dụng phải >= số tiền cần thanh toán
    if available_balance < bill_amount:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "INSUFFICIENT_BALANCE",
                "message": "Số dư khả dụng của người nộp tiền không đủ để thanh toán khoản học phí này.",
                "details": {
                    "available_balance": float(available_balance),
                    "required_amount": float(bill_amount),
                },
            },
        )

    # 5. Khởi tạo bản ghi giao dịch ở trạng thái PENDING_OTP
    now = datetime.now(timezone.utc)
    otp_expires_at = now + timedelta(seconds=settings.OTP_TTL_SECONDS)
    tx_code = generate_transaction_code()

    tx = PaymentTransaction(
        transaction_code=tx_code,
        payer_account_id=payer_uuid,
        payer_full_name=account_data["full_name"],
        payer_phone=account_data["phone_number"],
        payer_email=account_data["email"],
        student_id=student_data["student_id"],
        student_full_name=student_data["full_name"],
        tuition_bill_id=uuid.UUID(str(bill_data["id"])),
        semester_code=bill_data["semester_code"],
        semester_name=bill_data["semester_name"],
        amount=bill_amount,
        terms_accepted=True,
        status="PENDING_OTP",
        idempotency_key=clean_idem_key,
        correlation_id=correlation_id,
        otp_expires_at=otp_expires_at,
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(tx)
    db.flush()

    append_saga_step(
        db=db,
        transaction_id=tx.id,
        step_order=1,
        step_name="PRECHECK_ACCOUNT",
        target_service="auth-account-service",
        step_status="SUCCESS",
        detail_payload={"available_balance": float(available_balance)},
    )
    append_saga_step(
        db=db,
        transaction_id=tx.id,
        step_order=2,
        step_name="PRECHECK_TUITION",
        target_service="tuition-service",
        step_status="SUCCESS",
        detail_payload={
            "student_id": tx.student_id,
            "tuition_status": bill_data["status"],
            "amount": float(bill_amount),
        },
    )

    # 6. Yêu cầu notification-otp-service sinh OTP (TTL 5 phút, không trùng lặp) & gửi Email
    otp_resp = call_generate_otp(
        payload={
            "transaction_id": str(tx.id),
            "transaction_code": tx.transaction_code,
            "recipient_email": tx.payer_email,
            "payer_name": tx.payer_full_name,
            "student_id": tx.student_id,
            "student_name": tx.student_full_name,
            "semester_name": tx.semester_name,
            "amount": float(tx.amount),
        },
        correlation_id=correlation_id,
    )

    append_saga_step(
        db=db,
        transaction_id=tx.id,
        step_order=3,
        step_name="GENERATE_AND_SEND_OTP",
        target_service="notification-otp-service",
        step_status="SUCCESS",
        detail_payload=otp_resp,
    )

    response_obj = InitiatePaymentResponse(
        transaction_id=tx.id,
        transaction_code=tx.transaction_code,
        status=tx.status,
        payer=PayerSummarySchema(
            account_id=tx.payer_account_id,
            full_name=tx.payer_full_name,
            phone_number=tx.payer_phone,
            email=tx.payer_email,
            balance_before=float(available_balance),
        ),
        tuition=TuitionSummarySchema(
            tuition_bill_id=tx.tuition_bill_id,
            student_id=tx.student_id,
            student_full_name=tx.student_full_name,
            semester_code=tx.semester_code,
            semester_name=tx.semester_name,
            amount=float(tx.amount),
            tuition_status="UNPAID",
        ),
        otp_info=OtpInfoSchema(
            sent_to_email=tx.payer_email,
            expires_in_seconds=otp_resp["expires_in_seconds"],
            expires_at=tx.otp_expires_at,
        ),
        message="Mã OTP đã được gửi đến địa chỉ email của người nộp tiền. Mã có hiệu lực tối đa 5 phút.",
    )

    save_idempotency(
        db=db,
        idempotency_key=clean_idem_key,
        account_id=payer_uuid,
        endpoint="POST:/payments/initiate",
        payload_dict=payload_dict,
        status_code=status.HTTP_201_CREATED,
        response_body=response_obj.model_dump(mode="json"),
    )

    return response_obj


@router.post(
    "/payments/{transaction_id}/confirm-otp",
    response_model=ConfirmOtpResponse,
    status_code=status.HTTP_200_OK,
)
def confirm_otp_and_execute_saga(
    request: Request,
    transaction_id: uuid.UUID,
    payload: ConfirmOtpRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Bước 2 của Luồng Thanh toán (Sau khi người dùng nhập OTP):
    1. Kiểm tra Idempotency-Key & trạng thái giao dịch
    2. Xác thực mã OTP nguyên tử (còn hạn 5 phút, dùng 1 lần)
    3. Kích hoạt Saga Orchestration với Pessimistic Locking tức thời:
       - Bước Saga 1: Khóa bản ghi tài khoản & trừ tiền (Chống Concurrency 1 - Không vượt số dư)
       - Bước Saga 2: Khóa bản ghi học phí & gạch nợ PAID (Chống Concurrency 2 - Chỉ đóng 1 lần)
       - Nếu Bước Saga 2 bị 409 Conflict (người khác vừa đóng xong): Lập tức gọi Saga Compensating Refund hoàn tiền 100%!
       - Bước Saga 3: Lưu lịch sử giao dịch & Gửi email biên lai xác nhận thành công.
    """
    if not idempotency_key or len(idempotency_key.strip()) < 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "MISSING_IDEMPOTENCY_KEY",
                "message": "Header 'Idempotency-Key' là bắt buộc khi xác nhận OTP.",
            },
        )

    clean_idem_key = idempotency_key.strip()
    payer_uuid = uuid.UUID(current_user_id)
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))

    payload_dict = {
        "transaction_id": str(transaction_id),
        "otp_code": payload.otp_code,
    }
    cached = check_idempotency(
        db=db,
        idempotency_key=clean_idem_key,
        account_id=payer_uuid,
        endpoint=f"POST:/payments/{transaction_id}/confirm-otp",
        payload_dict=payload_dict,
    )
    if cached:
        cached_status, cached_body = cached
        return JSONResponse(status_code=cached_status, content=cached_body)

    # 1. Khóa dòng giao dịch để chống 2 request confirm-otp chạy song song trên cùng 1 transaction_id
    tx = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.id == transaction_id)
        .with_for_update()
        .first()
    )
    if not tx:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "TRANSACTION_NOT_FOUND",
                "message": "Không tìm thấy giao dịch thanh toán.",
            },
        )

    if tx.payer_account_id != payer_uuid:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN_TRANSACTION",
                "message": "Bạn không có quyền xác nhận giao dịch của người dùng khác.",
            },
        )

    if tx.status != "PENDING_OTP":
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TRANSACTION_ALREADY_PROCESSED",
                "message": f"Giao dịch này đã được xử lý trước đó (Trạng thái hiện tại: {tx.status}).",
                "details": {
                    "status": tx.status,
                    "failure_reason": tx.failure_reason,
                },
            },
        )

    now = datetime.now(timezone.utc)
    if now > tx.otp_expires_at:
        tx.status = "EXPIRED"
        tx.failure_reason = "Mã OTP đã hết thời hạn hiệu lực 5 phút."
        tx.updated_at = now
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "OTP_EXPIRED",
                "message": "Mã OTP đã hết thời hạn hiệu lực 5 phút. Vui lòng khởi tạo giao dịch mới.",
            },
        )

    # 2. Xác thực mã OTP (One-Time Use trên Redis Lua Script + PostgreSQL)
    try:
        otp_verify_resp = call_verify_otp(
            transaction_id=tx.id,
            otp_code=payload.otp_code,
            correlation_id=correlation_id,
        )
    except HTTPException as exc:
        err_code = (
            exc.detail.get("code", "OTP_ERROR")
            if isinstance(exc.detail, dict)
            else "OTP_ERROR"
        )
        err_msg = (
            exc.detail.get("message", str(exc.detail))
            if isinstance(exc.detail, dict)
            else str(exc.detail)
        )
        append_saga_step(
            db=db,
            transaction_id=tx.id,
            step_order=4,
            step_name="VERIFY_OTP",
            target_service="notification-otp-service",
            step_status="FAILED",
            error_message=err_msg,
        )
        if err_code == "OTP_EXPIRED":
            tx.status = "EXPIRED"
            tx.failure_reason = err_msg
        db.commit()
        raise

    append_saga_step(
        db=db,
        transaction_id=tx.id,
        step_order=4,
        step_name="VERIFY_OTP",
        target_service="notification-otp-service",
        step_status="SUCCESS",
        detail_payload=otp_verify_resp,
    )
    tx.status = "PROCESSING"
    tx.updated_at = now
    db.flush()

    # 3. BƯỚC SAGA 1: Kiểm tra lại số dư khả dụng & Trừ tiền nguyên tử (Pessimistic Lock)
    debit_resp = call_debit_account(
        account_id=tx.payer_account_id,
        transaction_id=tx.id,
        amount=tx.amount,
        idempotency_key=f"debit-{tx.id}",
        description=f"Thanh toán học phí {tx.semester_code} cho MSSV {tx.student_id} ({tx.transaction_code})",
        correlation_id=correlation_id,
    )

    if debit_resp.status_code != 200:
        debit_err = extract_downstream_error(debit_resp, "INSUFFICIENT_BALANCE")
        append_saga_step(
            db=db,
            transaction_id=tx.id,
            step_order=5,
            step_name="DEBIT_ACCOUNT",
            target_service="auth-account-service",
            step_status="FAILED",
            detail_payload=debit_err,
            error_message=debit_err["message"],
        )
        tx.status = "FAILED"
        tx.failure_reason = debit_err["message"]
        tx.completed_at = datetime.now(timezone.utc)
        tx.version = tx.version + 1
        db.commit()
        raise HTTPException(
            status_code=debit_resp.status_code,
            detail=debit_err,
        )

    debit_data = debit_resp.json()
    append_saga_step(
        db=db,
        transaction_id=tx.id,
        step_order=5,
        step_name="DEBIT_ACCOUNT",
        target_service="auth-account-service",
        step_status="SUCCESS",
        detail_payload=debit_data,
    )

    # 4. BƯỚC SAGA 2: Khóa bản ghi Học phí & Cập nhật thành PAID (Pessimistic Lock)
    tuition_resp = call_mark_tuition_paid(
        tuition_bill_id=tx.tuition_bill_id,
        student_id=tx.student_id,
        transaction_id=tx.id,
        payer_account_id=tx.payer_account_id,
        amount=tx.amount,
        correlation_id=correlation_id,
    )

    # XỬ LÝ CONCURRENCY 2: Nếu học phí vừa được tài khoản khác thanh toán trước -> KÍCH HOẠT SAGA COMPENSATION (REFUND)
    if tuition_resp.status_code != 200:
        tuition_err = extract_downstream_error(
            tuition_resp, "TUITION_ALREADY_PAID"
        )
        append_saga_step(
            db=db,
            transaction_id=tx.id,
            step_order=6,
            step_name="MARK_TUITION_PAID",
            target_service="tuition-service",
            step_status="FAILED",
            detail_payload=tuition_err,
            error_message=tuition_err["message"],
        )

        # Gọi bù trừ hoàn tiền ngay lập tức về tài khoản người nộp
        refund_resp = call_refund_account_compensation(
            account_id=tx.payer_account_id,
            transaction_id=tx.id,
            amount=tx.amount,
            idempotency_key=f"refund-{tx.id}",
            reason=f"Saga Compensation: Hoàn tiền giao dịch {tx.transaction_code} do học phí MSSV {tx.student_id} đã được thanh toán bởi giao dịch khác.",
            correlation_id=correlation_id,
        )
        refund_data = (
            refund_resp.json()
            if refund_resp.status_code == 200
            else {"status": "REFUND_ERROR", "code": refund_resp.status_code}
        )

        append_saga_step(
            db=db,
            transaction_id=tx.id,
            step_order=7,
            step_name="COMPENSATE_REFUND",
            target_service="auth-account-service",
            step_status="COMPENSATED",
            detail_payload=refund_data,
            error_message="Đã hoàn trả 100% số tiền về tài khoản người nộp do xung đột thanh toán trùng MSSV.",
        )

        compensated_time = datetime.now(timezone.utc)
        tx.status = "COMPENSATED"
        tx.balance_before = Decimal(str(debit_data["balance_before"]))
        tx.balance_after = Decimal(
            str(refund_data.get("balance_after", debit_data["balance_before"]))
        )
        tx.failure_reason = (
            "Khoản học phí đã được thanh toán bởi một giao dịch khác. "
            "Hệ thống đã tự động hoàn trả 100% số tiền về tài khoản của bạn."
        )
        tx.completed_at = compensated_time
        tx.version = tx.version + 1
        tx.updated_at = compensated_time
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TUITION_ALREADY_PAID_COMPENSATED",
                "message": tx.failure_reason,
                "details": {
                    "transaction_id": str(tx.id),
                    "transaction_code": tx.transaction_code,
                    "status": "COMPENSATED",
                    "student_id": tx.student_id,
                    "refunded_amount": float(tx.amount),
                    "restored_balance": float(tx.balance_after),
                },
            },
        )

    # 5. BƯỚC SAGA 3: Giao dịch thành công trọn vẹn -> Cập nhật COMPLETED & Gửi Email biên lai
    tuition_data = tuition_resp.json()
    append_saga_step(
        db=db,
        transaction_id=tx.id,
        step_order=6,
        step_name="MARK_TUITION_PAID",
        target_service="tuition-service",
        step_status="SUCCESS",
        detail_payload=tuition_data,
    )

    completed_time = datetime.now(timezone.utc)
    tx.status = "COMPLETED"
    tx.balance_before = Decimal(str(debit_data["balance_before"]))
    tx.balance_after = Decimal(str(debit_data["balance_after"]))
    tx.completed_at = completed_time
    tx.version = tx.version + 1
    tx.updated_at = completed_time
    db.flush()

    receipt_resp = call_send_receipt_email(
        payload={
            "transaction_id": str(tx.id),
            "transaction_code": tx.transaction_code,
            "recipient_email": tx.payer_email,
            "payer_name": tx.payer_full_name,
            "payer_phone": tx.payer_phone,
            "student_id": tx.student_id,
            "student_name": tx.student_full_name,
            "semester_name": tx.semester_name,
            "amount": float(tx.amount),
            "balance_before": float(tx.balance_before),
            "balance_after": float(tx.balance_after),
            "paid_at": completed_time.isoformat(),
        },
        correlation_id=correlation_id,
    )

    append_saga_step(
        db=db,
        transaction_id=tx.id,
        step_order=7,
        step_name="SEND_RECEIPT_EMAIL",
        target_service="notification-otp-service",
        step_status="SUCCESS",
        detail_payload=receipt_resp or {"status": "SENT"},
    )

    response_obj = ConfirmOtpResponse(
        transaction_id=tx.id,
        transaction_code=tx.transaction_code,
        status="COMPLETED",
        payer=PayerSummarySchema(
            account_id=tx.payer_account_id,
            full_name=tx.payer_full_name,
            phone_number=tx.payer_phone,
            email=tx.payer_email,
            balance_before=float(tx.balance_before),
            balance_after=float(tx.balance_after),
        ),
        tuition=TuitionSummarySchema(
            tuition_bill_id=tx.tuition_bill_id,
            student_id=tx.student_id,
            student_full_name=tx.student_full_name,
            semester_code=tx.semester_code,
            semester_name=tx.semester_name,
            amount=float(tx.amount),
            tuition_status="PAID",
        ),
        completed_at=completed_time,
        receipt_email_sent=True,
        message="Thanh toán học phí thành công! Biên lai xác nhận đã được gửi tới email của bạn.",
    )

    save_idempotency(
        db=db,
        idempotency_key=clean_idem_key,
        account_id=payer_uuid,
        endpoint=f"POST:/payments/{transaction_id}/confirm-otp",
        payload_dict=payload_dict,
        status_code=status.HTTP_200_OK,
        response_body=response_obj.model_dump(mode="json"),
    )

    return response_obj


@router.get(
    "/payments/history",
    response_model=TransactionHistoryListResponse,
    status_code=status.HTTP_200_OK,
)
def get_payment_history(
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    payer_uuid = uuid.UUID(current_user_id)
    query = db.query(PaymentTransaction).filter(
        PaymentTransaction.payer_account_id == payer_uuid
    )
    if status_filter:
        query = query.filter(
            PaymentTransaction.status == status_filter.strip().upper()
        )

    total = query.count()
    items = (
        query.order_by(PaymentTransaction.created_at.desc())
        .offset(offset)
        .limit(min(limit, 100))
        .all()
    )

    return TransactionHistoryListResponse(
        total=total,
        items=[TransactionHistoryItemSchema.model_validate(tx) for tx in items],
    )


@router.get(
    "/payments/{transaction_id}",
    response_model=TransactionDetailSchema,
    status_code=status.HTTP_200_OK,
)
def get_transaction_detail(
    transaction_id: uuid.UUID,
    current_user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    payer_uuid = uuid.UUID(current_user_id)
    tx = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.id == transaction_id,
            PaymentTransaction.payer_account_id == payer_uuid,
        )
        .first()
    )
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "TRANSACTION_NOT_FOUND",
                "message": "Không tìm thấy thông tin giao dịch.",
            },
        )
    return TransactionDetailSchema.model_validate(tx)


@router.get(
    "/payments/{transaction_id}/demo-otp",
    status_code=status.HTTP_200_OK,
)
def get_demo_otp_for_transaction(
    request: Request,
    transaction_id: uuid.UUID,
    current_user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    API hỗ trợ lấy nhanh mã OTP của giao dịch đang chờ xác thực phục vụ Automated Tests
    và hiển thị gợi ý tiện lợi khi Demo chấm bài (bên cạnh hộp thư Mailpit :8025).
    """
    payer_uuid = uuid.UUID(current_user_id)
    tx = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.id == transaction_id,
            PaymentTransaction.payer_account_id == payer_uuid,
        )
        .first()
    )
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "TRANSACTION_NOT_FOUND",
                "message": "Không tìm thấy giao dịch.",
            },
        )

    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    url = f"{settings.NOTIFICATION_OTP_SERVICE_URL}/internal/otp/debug/{transaction_id}"
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(url, headers={"X-Request-ID": correlation_id})
    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=extract_downstream_error(resp, "OTP_DEBUG_NOT_FOUND"),
        )
    return resp.json()


@router.post("/payments/reset-demo", status_code=status.HTTP_200_OK)
def reset_all_demo_data(request: Request, db: Session = Depends(get_db)):
    """
    Khôi phục toàn bộ dữ liệu mẫu trên cả 4 Microservices về trạng thái ban đầu
    phục vụ chạy Automated Concurrency/E2E Tests và Demo trực tiếp nhiều lần.
    """
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    db.query(SagaStepLog).delete()
    db.query(IdempotencyRecord).delete()
    db.query(PaymentTransaction).delete()
    db.commit()

    with httpx.Client(timeout=10.0) as client:
        client.post(
            f"{settings.AUTH_ACCOUNT_SERVICE_URL}/internal/accounts/reset-demo",
            headers={"X-Request-ID": correlation_id},
        )
        client.post(
            f"{settings.TUITION_SERVICE_URL}/internal/tuitions/reset-demo",
            headers={"X-Request-ID": correlation_id},
        )
        client.post(
            f"{settings.NOTIFICATION_OTP_SERVICE_URL}/internal/otp/reset-demo",
            headers={"X-Request-ID": correlation_id},
        )

    return {
        "status": "ALL_SERVICES_RESET_SUCCESS",
        "message": "Đã khôi phục toàn bộ dữ liệu mẫu trên cả 4 Microservices (Account, Tuition, Payment, OTP).",
    }
