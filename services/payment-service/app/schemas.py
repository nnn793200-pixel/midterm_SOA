from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Any, Dict
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, field_serializer


class InitiatePaymentRequest(BaseModel):
    student_id: str = Field(..., min_length=3, max_length=20)
    tuition_bill_id: UUID
    amount: Decimal = Field(..., gt=0)
    terms_accepted: bool = Field(...)


class PayerSummarySchema(BaseModel):
    account_id: UUID
    full_name: str
    phone_number: str
    email: str
    balance_before: Optional[float] = None
    balance_after: Optional[float] = None


class TuitionSummarySchema(BaseModel):
    tuition_bill_id: UUID
    student_id: str
    student_full_name: str
    semester_code: str
    semester_name: str
    amount: float
    tuition_status: Optional[str] = None


class OtpInfoSchema(BaseModel):
    sent_to_email: str
    expires_in_seconds: int
    expires_at: datetime


class InitiatePaymentResponse(BaseModel):
    transaction_id: UUID
    transaction_code: str
    status: str
    payer: PayerSummarySchema
    tuition: TuitionSummarySchema
    otp_info: OtpInfoSchema
    message: str


class ConfirmOtpRequest(BaseModel):
    otp_code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class ConfirmOtpResponse(BaseModel):
    transaction_id: UUID
    transaction_code: str
    status: str
    payer: PayerSummarySchema
    tuition: TuitionSummarySchema
    completed_at: datetime
    receipt_email_sent: bool
    message: str


class SagaStepLogSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    step_order: int
    step_name: str
    target_service: str
    step_status: str
    detail_payload: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: datetime


class TransactionHistoryItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transaction_code: str
    payer_account_id: UUID
    payer_full_name: str
    payer_phone: str
    payer_email: str
    student_id: str
    student_full_name: str
    tuition_bill_id: UUID
    semester_code: str
    semester_name: str
    amount: Decimal
    balance_before: Optional[Decimal] = None
    balance_after: Optional[Decimal] = None
    status: str
    failure_reason: Optional[str] = None
    correlation_id: str
    otp_expires_at: datetime
    completed_at: Optional[datetime] = None
    created_at: datetime

    @field_serializer("amount", "balance_before", "balance_after")
    def serialize_decimals(self, value: Optional[Decimal]) -> Optional[float]:
        if value is None:
            return None
        return float(value)


class TransactionDetailSchema(TransactionHistoryItemSchema):
    saga_steps: List[SagaStepLogSchema] = []


class TransactionHistoryListResponse(BaseModel):
    total: int
    items: List[TransactionHistoryItemSchema]
