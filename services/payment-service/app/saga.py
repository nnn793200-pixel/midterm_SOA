import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Any, Optional, Tuple
from uuid import UUID
import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.config import settings
from app.models import PaymentTransaction, SagaStepLog, IdempotencyRecord

logger = logging.getLogger(settings.SERVICE_NAME)


def compute_request_hash(payload_dict: Dict[str, Any]) -> str:
    serialized = json.dumps(payload_dict, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def check_idempotency(
    db: Session,
    idempotency_key: str,
    account_id: UUID,
    endpoint: str,
    payload_dict: Dict[str, Any],
) -> Optional[Tuple[int, Dict[str, Any]]]:
    now = datetime.now(timezone.utc)
    record = (
        db.query(IdempotencyRecord)
        .filter(IdempotencyRecord.idempotency_key == idempotency_key)
        .first()
    )
    if not record:
        return None

    if record.expires_at < now:
        db.delete(record)
        db.commit()
        return None

    req_hash = compute_request_hash(payload_dict)
    if record.account_id != account_id or record.endpoint != endpoint or record.request_hash != req_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "IDEMPOTENCY_KEY_REUSED_MISMATCH",
                "message": "Idempotency-Key đã được sử dụng cho một yêu cầu khác.",
            },
        )

    if record.response_status_code and record.response_body:
        return record.response_status_code, record.response_body

    return None


def save_idempotency(
    db: Session,
    idempotency_key: str,
    account_id: UUID,
    endpoint: str,
    payload_dict: Dict[str, Any],
    status_code: int,
    response_body: Dict[str, Any],
) -> None:
    now = datetime.now(timezone.utc)
    req_hash = compute_request_hash(payload_dict)
    existing = (
        db.query(IdempotencyRecord)
        .filter(IdempotencyRecord.idempotency_key == idempotency_key)
        .first()
    )
    if existing:
        existing.response_status_code = status_code
        existing.response_body = response_body
    else:
        record = IdempotencyRecord(
            idempotency_key=idempotency_key,
            account_id=account_id,
            endpoint=endpoint,
            request_hash=req_hash,
            response_status_code=status_code,
            response_body=response_body,
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
        db.add(record)
    db.commit()


def append_saga_step(
    db: Session,
    transaction_id: UUID,
    step_order: int,
    step_name: str,
    target_service: str,
    step_status: str,
    detail_payload: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> SagaStepLog:
    step = SagaStepLog(
        transaction_id=transaction_id,
        step_order=step_order,
        step_name=step_name,
        target_service=target_service,
        step_status=step_status,
        detail_payload=detail_payload,
        error_message=error_message,
        created_at=datetime.now(timezone.utc),
    )
    db.add(step)
    db.flush()
    return step


def extract_downstream_error(resp: httpx.Response, default_code: str) -> Dict[str, Any]:
    try:
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            return {
                "code": data["error"].get("code", default_code),
                "message": data["error"].get("message", resp.text),
                "details": data["error"].get("details"),
            }
    except Exception:
        pass
    return {
        "code": default_code,
        "message": f"Lỗi từ service nội bộ ({resp.status_code}): {resp.text[:200]}",
    }


def call_precheck_account(account_id: UUID, correlation_id: str) -> Dict[str, Any]:
    url = f"{settings.AUTH_ACCOUNT_SERVICE_URL}/internal/accounts/{account_id}"
    with httpx.Client(timeout=8.0) as client:
        resp = client.get(url, headers={"X-Request-ID": correlation_id})
    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=extract_downstream_error(resp, "ACCOUNT_PRECHECK_FAILED"),
        )
    return resp.json()


def call_precheck_tuition(student_id: str, correlation_id: str) -> Dict[str, Any]:
    url = f"{settings.TUITION_SERVICE_URL}/internal/tuitions/{student_id}"
    with httpx.Client(timeout=8.0) as client:
        resp = client.get(url, headers={"X-Request-ID": correlation_id})
    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=extract_downstream_error(resp, "TUITION_PRECHECK_FAILED"),
        )
    return resp.json()


def call_generate_otp(
    payload: Dict[str, Any], correlation_id: str
) -> Dict[str, Any]:
    url = f"{settings.NOTIFICATION_OTP_SERVICE_URL}/internal/otp/generate"
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            url, json=payload, headers={"X-Request-ID": correlation_id}
        )
    if resp.status_code not in (200, 201):
        raise HTTPException(
            status_code=resp.status_code,
            detail=extract_downstream_error(resp, "OTP_GENERATION_FAILED"),
        )
    return resp.json()


def call_verify_otp(
    transaction_id: UUID, otp_code: str, correlation_id: str
) -> Dict[str, Any]:
    url = f"{settings.NOTIFICATION_OTP_SERVICE_URL}/internal/otp/verify"
    with httpx.Client(timeout=8.0) as client:
        resp = client.post(
            url,
            json={"transaction_id": str(transaction_id), "otp_code": otp_code},
            headers={"X-Request-ID": correlation_id},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=extract_downstream_error(resp, "OTP_VERIFICATION_FAILED"),
        )
    return resp.json()


def call_debit_account(
    account_id: UUID,
    transaction_id: UUID,
    amount: Decimal,
    idempotency_key: str,
    description: str,
    correlation_id: str,
) -> httpx.Response:
    url = f"{settings.AUTH_ACCOUNT_SERVICE_URL}/internal/accounts/debit"
    with httpx.Client(timeout=10.0) as client:
        return client.post(
            url,
            json={
                "account_id": str(account_id),
                "transaction_id": str(transaction_id),
                "amount": float(amount),
                "idempotency_key": idempotency_key,
                "description": description,
            },
            headers={"X-Request-ID": correlation_id},
        )


def call_mark_tuition_paid(
    tuition_bill_id: UUID,
    student_id: str,
    transaction_id: UUID,
    payer_account_id: UUID,
    amount: Decimal,
    correlation_id: str,
) -> httpx.Response:
    url = f"{settings.TUITION_SERVICE_URL}/internal/tuitions/mark-paid"
    with httpx.Client(timeout=10.0) as client:
        return client.post(
            url,
            json={
                "tuition_bill_id": str(tuition_bill_id),
                "student_id": student_id,
                "transaction_id": str(transaction_id),
                "payer_account_id": str(payer_account_id),
                "amount": float(amount),
            },
            headers={"X-Request-ID": correlation_id},
        )


def call_refund_account_compensation(
    account_id: UUID,
    transaction_id: UUID,
    amount: Decimal,
    idempotency_key: str,
    reason: str,
    correlation_id: str,
) -> httpx.Response:
    url = f"{settings.AUTH_ACCOUNT_SERVICE_URL}/internal/accounts/refund"
    with httpx.Client(timeout=10.0) as client:
        return client.post(
            url,
            json={
                "account_id": str(account_id),
                "transaction_id": str(transaction_id),
                "amount": float(amount),
                "idempotency_key": idempotency_key,
                "reason": reason,
            },
            headers={"X-Request-ID": correlation_id},
        )


def call_send_receipt_email(
    payload: Dict[str, Any], correlation_id: str
) -> Optional[Dict[str, Any]]:
    url = f"{settings.NOTIFICATION_OTP_SERVICE_URL}/internal/notifications/payment-receipt"
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(
                url, json=payload, headers={"X-Request-ID": correlation_id}
            )
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:
        logger.warning("Receipt email notification warning: %s", str(exc))
    return None
