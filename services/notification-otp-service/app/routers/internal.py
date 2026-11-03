from datetime import datetime, timedelta, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import OtpToken, NotificationLog
from app.schemas import (
    GenerateOtpRequest,
    GenerateOtpResponse,
    VerifyOtpRequest,
    VerifyOtpResponse,
    SendPaymentReceiptRequest,
    SendPaymentReceiptResponse,
)
from app.redis_client import (
    generate_unique_otp_in_redis,
    verify_and_consume_otp_in_redis,
    get_redis,
)
from app.mailer import (
    build_otp_email_html,
    build_receipt_email_html,
    send_html_email,
)

router = APIRouter(prefix="/internal", tags=["Internal OTP & Notification Operations"])


@router.post(
    "/otp/generate",
    response_model=GenerateOtpResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_and_send_otp(
    payload: GenerateOtpRequest, db: Session = Depends(get_db)
):
    """
    Sinh mã OTP 6 chữ số gắn với transaction_id:
    - Không trùng với bất kỳ OTP nào đang có hiệu lực (trên Redis & DB)
    - Thời hạn hiệu lực tối đa 5 phút (TTL = 300s)
    - Chỉ được sử dụng thành công 1 lần (is_used = False)
    - Gửi qua email người nộp tiền (Mailpit SMTP) & lưu vết vào notification_logs
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.OTP_TTL_SECONDS)

    # 1. Lấy danh sách các mã OTP đang active trong DB để đảm bảo không trùng lặp
    active_tokens = (
        db.query(OtpToken.otp_code)
        .filter(OtpToken.is_used.is_(False), OtpToken.expires_at > now)
        .all()
    )
    active_db_codes = {row[0] for row in active_tokens}

    # 2. Sinh OTP duy nhất trên Redis với SET NX EX 300
    otp_code = generate_unique_otp_in_redis(
        transaction_id=str(payload.transaction_id),
        recipient_email=payload.recipient_email,
        expires_at=expires_at,
        active_db_codes=active_db_codes,
    )

    # 3. Lưu hoặc cập nhật thực thể OtpToken trong PostgreSQL notification_db
    otp_record = (
        db.query(OtpToken)
        .filter(OtpToken.transaction_id == payload.transaction_id)
        .first()
    )
    if otp_record:
        otp_record.otp_code = otp_code
        otp_record.recipient_email = payload.recipient_email
        otp_record.is_used = False
        otp_record.attempt_count = 0
        otp_record.created_at = now
        otp_record.expires_at = expires_at
        otp_record.used_at = None
    else:
        otp_record = OtpToken(
            transaction_id=payload.transaction_id,
            otp_code=otp_code,
            recipient_email=payload.recipient_email,
            is_used=False,
            attempt_count=0,
            created_at=now,
            expires_at=expires_at,
        )
        db.add(otp_record)
    db.flush()

    # 4. Soạn và gửi Email chứa mã OTP qua Mailpit SMTP
    subject, html_body = build_otp_email_html(
        payer_name=payload.payer_name,
        otp_code=otp_code,
        transaction_code=payload.transaction_code,
        student_id=payload.student_id,
        student_name=payload.student_name,
        semester_name=payload.semester_name,
        amount=float(payload.amount),
        ttl_minutes=settings.OTP_TTL_SECONDS // 60,
    )
    delivery_status, smtp_resp = send_html_email(
        recipient_email=payload.recipient_email,
        subject=subject,
        html_body=html_body,
    )

    # 5. Lưu bản ghi NotificationLog
    notif_log = NotificationLog(
        transaction_id=payload.transaction_id,
        otp_token_id=otp_record.id,
        recipient_email=payload.recipient_email,
        notification_type="OTP_EMAIL",
        email_subject=subject,
        email_body_snapshot=html_body,
        delivery_status=delivery_status,
        smtp_response=smtp_resp,
        sent_at=now,
    )
    db.add(notif_log)
    db.commit()
    db.refresh(otp_record)

    return GenerateOtpResponse(
        otp_token_id=otp_record.id,
        transaction_id=otp_record.transaction_id,
        recipient_email=otp_record.recipient_email,
        expires_in_seconds=settings.OTP_TTL_SECONDS,
        expires_at=otp_record.expires_at,
        email_delivery_status=delivery_status,
    )


@router.post(
    "/otp/verify",
    response_model=VerifyOtpResponse,
    status_code=status.HTTP_200_OK,
)
def verify_otp_one_time(
    payload: VerifyOtpRequest, db: Session = Depends(get_db)
):
    """
    Xác thực mã OTP nguyên tử bằng Redis Lua Script + PostgreSQL Lock:
    - Kiểm tra gắn đúng với transaction_id
    - Kiểm tra còn trong thời hạn 5 phút
    - Chỉ cho phép sử dụng thành công duy nhất 01 lần
    """
    now = datetime.now(timezone.utc)
    tx_str = str(payload.transaction_id)
    submitted_code = payload.otp_code.strip()

    lua_status = verify_and_consume_otp_in_redis(tx_str, submitted_code)

    otp_record = (
        db.query(OtpToken)
        .filter(OtpToken.transaction_id == payload.transaction_id)
        .with_for_update()
        .first()
    )

    if lua_status == "VERIFIED":
        if otp_record:
            if otp_record.is_used:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "OTP_ALREADY_USED",
                        "message": "Mã OTP này đã được sử dụng trước đó. Mỗi mã OTP chỉ có giá trị sử dụng 1 lần.",
                    },
                )
            otp_record.is_used = True
            otp_record.used_at = now
            db.commit()

        return VerifyOtpResponse(
            transaction_id=payload.transaction_id,
            verified=True,
            used_at=now,
            message="Xác thực mã OTP thành công.",
        )

    if lua_status == "ALREADY_USED":
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "OTP_ALREADY_USED",
                "message": "Mã OTP này đã được sử dụng trước đó. Mỗi mã OTP chỉ có giá trị sử dụng 1 lần.",
            },
        )

    if lua_status in ("INVALID_CODE", "MAX_ATTEMPTS_EXCEEDED"):
        if otp_record and otp_record.attempt_count < 5:
            otp_record.attempt_count = otp_record.attempt_count + 1
            if lua_status == "MAX_ATTEMPTS_EXCEEDED":
                otp_record.is_used = True
            db.commit()
        else:
            db.rollback()

        msg = (
            "Mã OTP đã bị vô hiệu hóa do nhập sai quá 5 lần."
            if lua_status == "MAX_ATTEMPTS_EXCEEDED"
            else "Mã xác thực OTP không chính xác. Vui lòng kiểm tra lại email."
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_OTP",
                "message": msg,
            },
        )

    # Trường hợp EXPIRED_OR_MISSING trên Redis -> Đối chiếu DB để trả về đúng mã lỗi
    if otp_record:
        if otp_record.is_used:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "OTP_ALREADY_USED",
                    "message": "Mã OTP này đã được sử dụng trước đó.",
                },
            )
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "OTP_EXPIRED",
                "message": "Mã OTP đã hết thời hạn hiệu lực 5 phút. Vui lòng khởi tạo lại giao dịch mới.",
            },
        )

    db.rollback()
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "OTP_NOT_FOUND",
            "message": "Không tìm thấy mã OTP gắn với giao dịch này.",
        },
    )


@router.post(
    "/notifications/payment-receipt",
    response_model=SendPaymentReceiptResponse,
    status_code=status.HTTP_200_OK,
)
def send_payment_receipt_email(
    payload: SendPaymentReceiptRequest, db: Session = Depends(get_db)
):
    """
    Gửi email xác nhận giao dịch thanh toán học phí thành công đến người nộp tiền
    và lưu vết vào bảng notification_logs.
    """
    now = datetime.now(timezone.utc)
    paid_at_str = payload.paid_at.strftime("%H:%M:%S - %d/%m/%Y (UTC)")

    subject, html_body = build_receipt_email_html(
        payer_name=payload.payer_name,
        payer_phone=payload.payer_phone,
        transaction_code=payload.transaction_code,
        student_id=payload.student_id,
        student_name=payload.student_name,
        semester_name=payload.semester_name,
        amount=float(payload.amount),
        balance_before=float(payload.balance_before),
        balance_after=float(payload.balance_after),
        paid_at_str=paid_at_str,
    )

    delivery_status, smtp_resp = send_html_email(
        recipient_email=payload.recipient_email,
        subject=subject,
        html_body=html_body,
    )

    otp_record = (
        db.query(OtpToken)
        .filter(OtpToken.transaction_id == payload.transaction_id)
        .first()
    )

    notif_log = NotificationLog(
        transaction_id=payload.transaction_id,
        otp_token_id=otp_record.id if otp_record else None,
        recipient_email=payload.recipient_email,
        notification_type="PAYMENT_RECEIPT_EMAIL",
        email_subject=subject,
        email_body_snapshot=html_body,
        delivery_status=delivery_status,
        smtp_response=smtp_resp,
        sent_at=now,
    )
    db.add(notif_log)
    db.commit()
    db.refresh(notif_log)

    return SendPaymentReceiptResponse(
        notification_log_id=notif_log.id,
        transaction_id=notif_log.transaction_id,
        recipient_email=notif_log.recipient_email,
        delivery_status=notif_log.delivery_status,
        sent_at=notif_log.sent_at,
    )


@router.get("/otp/debug/{transaction_id}", status_code=status.HTTP_200_OK)
def get_otp_for_testing_and_demo(
    transaction_id: UUID, db: Session = Depends(get_db)
):
    """
    Endpoint hỗ trợ Automated Integration/Concurrency Tests và Demo nhanh
    lấy mã OTP của transaction_id (song song với việc xem trực tiếp trên Mailpit Web UI :8025).
    """
    otp_record = (
        db.query(OtpToken)
        .filter(OtpToken.transaction_id == transaction_id)
        .first()
    )
    if not otp_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "OTP_NOT_FOUND",
                "message": "Không tìm thấy bản ghi OTP cho giao dịch này.",
            },
        )

    r = get_redis()
    ttl_remaining = r.ttl(f"otp:tx:{transaction_id}")
    return {
        "transaction_id": str(otp_record.transaction_id),
        "otp_code": otp_record.otp_code,
        "recipient_email": otp_record.recipient_email,
        "is_used": otp_record.is_used,
        "attempt_count": otp_record.attempt_count,
        "expires_at": otp_record.expires_at.isoformat(),
        "redis_ttl_remaining_seconds": max(ttl_remaining, 0),
    }


@router.post("/otp/reset-demo", status_code=status.HTTP_200_OK)
def reset_demo_otp_and_notifications(db: Session = Depends(get_db)):
    db.query(NotificationLog).delete()
    db.query(OtpToken).delete()
    db.commit()
    r = get_redis()
    for key in r.scan_iter("otp:*"):
        r.delete(key)
    return {
        "status": "RESET_SUCCESS",
        "message": "Đã làm sạch dữ liệu OTP và Notification Logs.",
    }
