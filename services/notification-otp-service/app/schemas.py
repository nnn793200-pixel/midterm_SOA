from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field


class GenerateOtpRequest(BaseModel):
    transaction_id: UUID
    transaction_code: str
    recipient_email: str
    payer_name: str
    student_id: str
    student_name: str
    semester_name: str = "Học kỳ 1 - Năm học 2026-2027"
    amount: Decimal = Field(..., gt=0)


class GenerateOtpResponse(BaseModel):
    otp_token_id: UUID
    transaction_id: UUID
    recipient_email: str
    expires_in_seconds: int
    expires_at: datetime
    email_delivery_status: str


class VerifyOtpRequest(BaseModel):
    transaction_id: UUID
    otp_code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class VerifyOtpResponse(BaseModel):
    transaction_id: UUID
    verified: bool
    used_at: datetime
    message: str


class SendPaymentReceiptRequest(BaseModel):
    transaction_id: UUID
    transaction_code: str
    recipient_email: str
    payer_name: str
    payer_phone: str
    student_id: str
    student_name: str
    semester_name: str
    amount: Decimal = Field(..., gt=0)
    balance_before: Decimal
    balance_after: Decimal
    paid_at: datetime


class SendPaymentReceiptResponse(BaseModel):
    notification_log_id: UUID
    transaction_id: UUID
    recipient_email: str
    delivery_status: str
    sent_at: datetime
