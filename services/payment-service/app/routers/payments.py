import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import PaymentTransaction, SagaStepLog, IdempotencyRecord
from app.redis_client import acquire_payment_locks, clear_payment_redis_keys
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
    internal_headers,
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

    # 1. Đọc thông tin giao dịch để kiểm tra tồn tại, quyền sở hữu và lấy student_id khóa Redis Lock
    tx_pre = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.id == transaction_id)
        .first()
    )
    if not tx_pre:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "TRANSACTION_NOT_FOUND",
                "message": "Không tìm thấy giao dịch thanh toán.",
            },
        )

    if tx_pre.payer_account_id != payer_uuid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN_TRANSACTION",
                "message": "Bạn không có quyền xác nhận giao dịch của người dùng khác.",
            },
        )

    # 2. Bọc bước xác thực OTP & thực thi Saga bằng Redis Distributed Lock (lock:account & lock:tuition)
    #    kết hợp khóa dòng SELECT ... FOR UPDATE dưới PostgreSQL.
    with acquire_payment_locks(
        account_id=str(payer_uuid),
        student_id=tx_pre.student_id,
    ):
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

        # 3. Xác thực mã OTP (One-Time Use trên Redis Lua Script + PostgreSQL)
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

        # 4. BƯỚC SAGA 1: Kiểm tra lại số dư khả dụng & Trừ tiền nguyên tử (Pessimistic Lock)
        debit_resp = None
        debit_exc: Optional[Exception] = None
        try:
            debit_resp = call_debit_account(
                account_id=tx.payer_account_id,
                transaction_id=tx.id,
                amount=tx.amount,
                idempotency_key=f"debit-{tx.id}",
                description=f"Thanh toán học phí {tx.semester_code} cho MSSV {tx.student_id} ({tx.transaction_code})",
                correlation_id=correlation_id,
            )
        except Exception as exc:
            debit_exc = exc

        if debit_resp is None or debit_resp.status_code != 200:
            if debit_resp is not None:
                debit_err = extract_downstream_error(debit_resp, "INSUFFICIENT_BALANCE")
                err_http_status = debit_resp.status_code
            else:
                debit_err = {
                    "code": "AUTH_ACCOUNT_SERVICE_UNAVAILABLE",
                    "message": f"Không thể kết nối auth-account-service khi trừ tiền: {str(debit_exc)}",
                }
                err_http_status = status.HTTP_503_SERVICE_UNAVAILABLE

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
            tx.failure_reason = debit_err["message"][:255]
            tx.completed_at = datetime.now(timezone.utc)
            tx.version = tx.version + 1
            db.commit()
            raise HTTPException(
                status_code=err_http_status,
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

        # 5. BƯỚC SAGA 2: Khóa bản ghi Học phí & Cập nhật thành PAID (Pessimistic Lock)
        tuition_resp = None
        tuition_exc: Optional[Exception] = None
        try:
            tuition_resp = call_mark_tuition_paid(
                tuition_bill_id=tx.tuition_bill_id,
                student_id=tx.student_id,
                transaction_id=tx.id,
                payer_account_id=tx.payer_account_id,
                amount=tx.amount,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            tuition_exc = exc

        # XỬ LÝ CONCURRENCY 2 / LỖI GẠCH NỢ SAU KHI ĐÃ TRỪ TIỀN -> KÍCH HOẠT SAGA COMPENSATION (REFUND + RETRY)
        if tuition_resp is None or tuition_resp.status_code != 200:
            if tuition_resp is not None:
                tuition_err = extract_downstream_error(
                    tuition_resp, "TUITION_ALREADY_PAID"
                )
            else:
                tuition_err = {
                    "code": "TUITION_SERVICE_UNAVAILABLE",
                    "message": f"Lỗi kết nối tuition-service khi gạch nợ: {str(tuition_exc)}",
                }

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

            # Gọi bù trừ hoàn tiền (có retry tối đa 3 lần) về tài khoản người nộp
            refund_resp = None
            refund_exc: Optional[Exception] = None
            try:
                refund_resp = call_refund_account_compensation(
                    account_id=tx.payer_account_id,
                    transaction_id=tx.id,
                    amount=tx.amount,
                    idempotency_key=f"refund-{tx.id}",
                    reason=f"Saga Compensation: Hoàn tiền giao dịch {tx.transaction_code} do gạch nợ học phí MSSV {tx.student_id} thất bại.",
                    correlation_id=correlation_id,
                )
            except Exception as exc:
                refund_exc = exc

            refund_succeeded = False
            refund_data: Dict[str, Any] = {}
            if refund_resp is not None and refund_resp.status_code == 200:
                try:
                    parsed_refund = refund_resp.json()
                    if (
                        isinstance(parsed_refund, dict)
                        and parsed_refund.get("balance_after") is not None
                    ):
                        refund_succeeded = True
                        refund_data = parsed_refund
                    else:
                        refund_data = {
                            "code": "INVALID_REFUND_PAYLOAD",
                            "message": "Phản hồi hoàn tiền thiếu balance_after thực tế.",
                            "raw": parsed_refund,
                        }
                except Exception as exc:
                    refund_data = {
                        "code": "INVALID_REFUND_JSON",
                        "message": f"Không thể parse phản hồi hoàn tiền: {str(exc)}",
                    }
            elif refund_resp is not None:
                refund_data = extract_downstream_error(refund_resp, "REFUND_FAILED")
                refund_data["http_status"] = refund_resp.status_code
            else:
                refund_data = {
                    "code": "REFUND_REQUEST_EXCEPTION",
                    "message": str(refund_exc)
                    or "Không nhận được phản hồi từ auth-account-service khi hoàn tiền.",
                }

            if refund_succeeded:
                restored_balance = float(refund_data["balance_after"])
                append_saga_step(
                    db=db,
                    transaction_id=tx.id,
                    step_order=7,
                    step_name="COMPENSATE_REFUND",
                    target_service="auth-account-service",
                    step_status="COMPENSATED",
                    detail_payload=refund_data,
                    error_message="Đã hoàn trả 100% số tiền về tài khoản người nộp do gạch nợ học phí không thành công.",
                )

                compensated_time = datetime.now(timezone.utc)
                tx.status = "COMPENSATED"
                tx.balance_before = Decimal(str(debit_data["balance_before"]))
                tx.balance_after = Decimal(str(restored_balance))

                is_already_paid = (
                    tuition_resp is not None
                    and tuition_resp.status_code == 409
                    and tuition_err.get("code") == "TUITION_ALREADY_PAID"
                )
                if is_already_paid:
                    tx.failure_reason = (
                        "Khoản học phí đã được thanh toán bởi một giao dịch khác. "
                        "Hệ thống đã tự động hoàn trả 100% số tiền về tài khoản của bạn."
                    )
                    err_code = "TUITION_ALREADY_PAID_COMPENSATED"
                    http_status = status.HTTP_409_CONFLICT
                else:
                    tx.failure_reason = (
                        f"Gạch nợ học phí không thành công ({tuition_err.get('message', '')}). "
                        "Hệ thống đã tự động hoàn trả 100% số tiền về tài khoản của bạn."
                    )[:255]
                    err_code = "TUITION_PAYMENT_FAILED_COMPENSATED"
                    http_status = (
                        status.HTTP_502_BAD_GATEWAY
                        if (tuition_resp is None or tuition_resp.status_code >= 500)
                        else status.HTTP_409_CONFLICT
                    )

                tx.completed_at = compensated_time
                tx.version = tx.version + 1
                tx.updated_at = compensated_time
                db.commit()

                raise HTTPException(
                    status_code=http_status,
                    detail={
                        "code": err_code,
                        "message": tx.failure_reason,
                        "details": {
                            "transaction_id": str(tx.id),
                            "transaction_code": tx.transaction_code,
                            "status": "COMPENSATED",
                            "student_id": tx.student_id,
                            "refunded_amount": float(tx.amount),
                            "restored_balance": restored_balance,
                        },
                    },
                )

            # Hoàn tiền THẤT BẠI sau các lần retry -> COMPENSATION_FAILED (TUYỆT ĐỐI KHÔNG fake COMPENSATED)
            restored_balance = None
            comp_fail_msg = (
                "Gạch nợ học phí thất bại và hoàn tiền tự động (Saga Compensation) cũng gặp sự cố sau khi retry. "
                "Giao dịch cần được đối soát thủ công bởi bộ phận vận hành."
            )
            append_saga_step(
                db=db,
                transaction_id=tx.id,
                step_order=7,
                step_name="COMPENSATE_REFUND",
                target_service="auth-account-service",
                step_status="COMPENSATION_FAILED",
                detail_payload=refund_data,
                error_message=comp_fail_msg,
            )

            failed_time = datetime.now(timezone.utc)
            tx.status = "COMPENSATION_FAILED"
            tx.balance_before = Decimal(str(debit_data["balance_before"]))
            tx.balance_after = Decimal(str(debit_data["balance_after"]))
            tx.failure_reason = comp_fail_msg[:255]
            tx.completed_at = failed_time
            tx.version = tx.version + 1
            tx.updated_at = failed_time
            db.commit()

            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "COMPENSATION_FAILED",
                    "message": comp_fail_msg,
                    "details": {
                        "transaction_id": str(tx.id),
                        "transaction_code": tx.transaction_code,
                        "status": "COMPENSATION_FAILED",
                        "student_id": tx.student_id,
                        "refund_error": refund_data,
                        "restored_balance": restored_balance,
                        "manual_reconciliation_required": True,
                    },
                },
            )

        # 6. Giao dịch tài chính thành công trọn vẹn -> Commit COMPLETED NGAY LẬP TỨC trước khi gửi Email biên lai
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
        db.commit()
        db.refresh(tx)

    # 7. BƯỚC SAGA 3 (ngoài Distributed Lock): Gửi Email biên lai (không rollback COMPLETED nếu SMTP/service lỗi)
    receipt_sent = False
    receipt_detail: Dict[str, Any] = {"delivery_status": "FAILED"}
    receipt_error: Optional[str] = None
    try:
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
        if isinstance(receipt_resp, dict):
            receipt_detail = receipt_resp
            if receipt_resp.get("delivery_status") == "SENT":
                receipt_sent = True
            else:
                receipt_error = receipt_resp.get("error") or (
                    f"Email delivery_status={receipt_resp.get('delivery_status')}"
                )
        else:
            receipt_error = "Không nhận được phản hồi hợp lệ từ notification-otp-service."
    except Exception as exc:
        receipt_error = str(exc)
        receipt_detail = {"delivery_status": "FAILED", "error": receipt_error}

    if receipt_sent:
        append_saga_step(
            db=db,
            transaction_id=tx.id,
            step_order=7,
            step_name="SEND_RECEIPT_EMAIL",
            target_service="notification-otp-service",
            step_status="SUCCESS",
            detail_payload=receipt_detail,
        )
        final_message = "Thanh toán học phí thành công! Biên lai xác nhận đã được gửi tới email của bạn."
    else:
        append_saga_step(
            db=db,
            transaction_id=tx.id,
            step_order=7,
            step_name="RECEIPT_EMAIL_FAILED",
            target_service="notification-otp-service",
            step_status="FAILED",
            detail_payload=receipt_detail,
            error_message=receipt_error or "Gửi email biên lai thất bại.",
        )
        final_message = (
            "Thanh toán học phí thành công! Tuy nhiên việc gửi email biên lai đang gặp sự cố."
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
        receipt_email_sent=receipt_sent,
        message=final_message,
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
        resp = client.get(url, headers=internal_headers(correlation_id))
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
    clear_payment_redis_keys()

    hdrs = internal_headers(correlation_id)
    with httpx.Client(timeout=10.0) as client:
        r_acc = client.post(
            f"{settings.AUTH_ACCOUNT_SERVICE_URL}/internal/accounts/reset-demo",
            headers=hdrs,
        )
        r_tui = client.post(
            f"{settings.TUITION_SERVICE_URL}/internal/tuitions/reset-demo",
            headers=hdrs,
        )
        r_otp = client.post(
            f"{settings.NOTIFICATION_OTP_SERVICE_URL}/internal/otp/reset-demo",
            headers=hdrs,
        )

    for svc_name, resp in (
        ("auth-account-service", r_acc),
        ("tuition-service", r_tui),
        ("notification-otp-service", r_otp),
    ):
        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "RESET_DEMO_FAILED",
                    "message": f"Khôi phục dữ liệu mẫu thất bại tại {svc_name} (HTTP {resp.status_code}).",
                },
            )

    return {
        "status": "ALL_SERVICES_RESET_SUCCESS",
        "message": "Đã khôi phục toàn bộ dữ liệu mẫu trên cả 4 Microservices (Account, Tuition, Payment, OTP).",
    }
