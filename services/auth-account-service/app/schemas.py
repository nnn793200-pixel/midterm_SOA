from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, field_serializer


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="Tên đăng nhập")
    password: str = Field(..., min_length=3, max_length=100, description="Mật khẩu")


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    full_name: str
    phone_number: str
    email: str
    available_balance: Decimal
    status: str
    version: int
    updated_at: datetime

    @field_serializer("available_balance")
    def serialize_balance(self, value: Decimal) -> float:
        return float(value)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserProfileResponse


class LedgerEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    transaction_id: UUID
    entry_type: str
    amount: Decimal
    balance_before: Decimal
    balance_after: Decimal
    idempotency_key: str
    description: str
    created_at: datetime

    @field_serializer("amount", "balance_before", "balance_after")
    def serialize_amounts(self, value: Decimal) -> float:
        return float(value)


class AccountMeDetailResponse(UserProfileResponse):
    recent_ledger_entries: List[LedgerEntryResponse] = []


class DebitAccountRequest(BaseModel):
    account_id: UUID
    transaction_id: UUID
    amount: Decimal = Field(..., gt=0, description="Số tiền cần trừ (> 0)")
    idempotency_key: str = Field(..., min_length=5, max_length=100)
    description: str = Field(
        default="Thanh toán học phí TDTU", min_length=3, max_length=255
    )


class DebitAccountResponse(BaseModel):
    account_id: UUID
    transaction_id: UUID
    ledger_entry_id: UUID
    entry_type: str = "DEBIT"
    amount: float
    balance_before: float
    balance_after: float
    version: int
    processed_at: datetime


class RefundAccountRequest(BaseModel):
    account_id: UUID
    transaction_id: UUID
    amount: Decimal = Field(..., gt=0, description="Số tiền hoàn trả (> 0)")
    idempotency_key: str = Field(..., min_length=5, max_length=100)
    reason: str = Field(
        default="Saga Compensation: Hoàn tiền do khoản học phí đã được thanh toán bởi giao dịch khác",
        min_length=3,
        max_length=255,
    )


class RefundAccountResponse(BaseModel):
    account_id: UUID
    transaction_id: UUID
    ledger_entry_id: UUID
    entry_type: str = "COMPENSATION_REFUND"
    amount: float
    balance_before: float
    balance_after: float
    version: int
    processed_at: datetime
