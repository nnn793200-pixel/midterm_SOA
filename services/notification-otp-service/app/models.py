import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Boolean,
    Integer,
    DateTime,
    Text,
    ForeignKey,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class OtpToken(Base):
    __tablename__ = "otp_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id = Column(
        UUID(as_uuid=True), unique=True, nullable=False, index=True
    )
    otp_code = Column(String(6), nullable=False, index=True)
    recipient_email = Column(String(120), nullable=False)
    is_used = Column(Boolean, nullable=False, default=False)
    attempt_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    notification_logs = relationship(
        "NotificationLog",
        back_populates="otp_token",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 5",
            name="chk_otp_tokens_attempt_count",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="chk_otp_tokens_expires_after_created",
        ),
    )


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    otp_token_id = Column(
        UUID(as_uuid=True),
        ForeignKey("otp_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    recipient_email = Column(String(120), nullable=False)
    notification_type = Column(String(30), nullable=False)
    email_subject = Column(String(255), nullable=False)
    email_body_snapshot = Column(Text, nullable=False)
    delivery_status = Column(String(20), nullable=False, default="SENT")
    smtp_response = Column(String(255), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    otp_token = relationship("OtpToken", back_populates="notification_logs")

    __table_args__ = (
        CheckConstraint(
            "notification_type IN ('OTP_EMAIL', 'PAYMENT_RECEIPT_EMAIL')",
            name="chk_notification_logs_type",
        ),
        CheckConstraint(
            "delivery_status IN ('SENT', 'FAILED')",
            name="chk_notification_logs_status",
        ),
    )
