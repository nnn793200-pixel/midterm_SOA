import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Numeric,
    Boolean,
    Integer,
    DateTime,
    Text,
    ForeignKey,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_code = Column(String(32), unique=True, nullable=False, index=True)
    payer_account_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    payer_full_name = Column(String(100), nullable=False)
    payer_phone = Column(String(20), nullable=False)
    payer_email = Column(String(120), nullable=False)
    student_id = Column(String(20), nullable=False, index=True)
    student_full_name = Column(String(100), nullable=False)
    tuition_bill_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    semester_code = Column(String(20), nullable=False)
    semester_name = Column(
        String(100), nullable=False, default="Học kỳ 1 - Năm học 2026-2027"
    )
    amount = Column(Numeric(15, 2), nullable=False)
    balance_before = Column(Numeric(15, 2), nullable=True)
    balance_after = Column(Numeric(15, 2), nullable=True)
    terms_accepted = Column(Boolean, nullable=False, default=True)
    status = Column(String(30), nullable=False, default="PENDING_OTP", index=True)
    failure_reason = Column(String(255), nullable=True)
    idempotency_key = Column(String(100), unique=True, nullable=False, index=True)
    correlation_id = Column(String(64), nullable=False, index=True)
    otp_expires_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    saga_steps = relationship(
        "SagaStepLog",
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="asc(SagaStepLog.step_order)",
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_payment_tx_amount_positive"),
        CheckConstraint(
            "terms_accepted = TRUE", name="chk_payment_tx_terms_accepted"
        ),
        CheckConstraint(
            "status IN ('PENDING_OTP', 'PROCESSING', 'COMPLETED', 'FAILED', 'COMPENSATED', 'EXPIRED')",
            name="chk_payment_tx_status",
        ),
    )


class SagaStepLog(Base):
    __tablename__ = "saga_step_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id = Column(
        UUID(as_uuid=True),
        ForeignKey("payment_transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_order = Column(Integer, nullable=False)
    step_name = Column(String(50), nullable=False)
    target_service = Column(String(50), nullable=False)
    step_status = Column(String(20), nullable=False)
    detail_payload = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    transaction = relationship("PaymentTransaction", back_populates="saga_steps")

    __table_args__ = (
        CheckConstraint(
            "step_status IN ('SUCCESS', 'FAILED', 'COMPENSATED')",
            name="chk_saga_step_status",
        ),
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    idempotency_key = Column(String(100), primary_key=True)
    account_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    endpoint = Column(String(100), nullable=False)
    request_hash = Column(String(64), nullable=False)
    response_status_code = Column(Integer, nullable=True)
    response_body = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
