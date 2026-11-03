from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, field_serializer


class StudentSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    student_id: str
    full_name: str
    faculty: str
    major: str
    class_code: str
    email: str


class TuitionBillSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: str
    semester_code: str
    semester_name: str
    amount: Decimal
    status: str
    paid_transaction_id: Optional[UUID] = None
    paid_by_account_id: Optional[UUID] = None
    paid_at: Optional[datetime] = None
    version: int

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> float:
        return float(value)


class TuitionLookupResponse(BaseModel):
    student: StudentSchema
    tuition_bill: TuitionBillSchema
    can_pay: bool


class MarkTuitionPaidRequest(BaseModel):
    tuition_bill_id: UUID
    student_id: str = Field(..., min_length=3, max_length=20)
    transaction_id: UUID
    payer_account_id: UUID
    amount: Decimal = Field(..., gt=0)


class MarkTuitionPaidResponse(BaseModel):
    tuition_bill_id: UUID
    student_id: str
    student_full_name: str
    semester_code: str
    semester_name: str
    amount: float
    status: str = "PAID"
    paid_transaction_id: UUID
    paid_by_account_id: UUID
    paid_at: datetime
    version: int
