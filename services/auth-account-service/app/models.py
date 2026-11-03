import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Numeric,
    Integer,
    DateTime,
    ForeignKey,
    CheckConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class UserAccount(Base):
    __tablename__ = "users_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=False)
    phone_number = Column(String(20), nullable=False)
    email = Column(String(120), nullable=False, index=True)
    available_balance = Column(Numeric(15, 2), nullable=False, default=0.00)
    status = Column(String(20), nullable=False, default="ACTIVE")
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    ledger_entries = relationship(
        "AccountLedgerEntry",
        back_populates="account",
        cascade="all, delete-orphan",
        order_by="desc(AccountLedgerEntry.created_at)",
    )

    __table_args__ = (
        CheckConstraint(
            "available_balance >= 0", name="chk_users_accounts_balance_non_negative"
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'LOCKED')", name="chk_users_accounts_status"
        ),
    )


class AccountLedgerEntry(Base):
    __tablename__ = "account_ledger_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    transaction_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    entry_type = Column(String(30), nullable=False)
    amount = Column(Numeric(15, 2), nullable=False)
    balance_before = Column(Numeric(15, 2), nullable=False)
    balance_after = Column(Numeric(15, 2), nullable=False)
    idempotency_key = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    account = relationship("UserAccount", back_populates="ledger_entries")

    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_ledger_amount_positive"),
        CheckConstraint(
            "balance_before >= 0", name="chk_ledger_balance_before_non_negative"
        ),
        CheckConstraint(
            "balance_after >= 0", name="chk_ledger_balance_after_non_negative"
        ),
        CheckConstraint(
            "entry_type IN ('DEBIT', 'COMPENSATION_REFUND')",
            name="chk_ledger_entry_type",
        ),
        Index("idx_ledger_tx_entry_type", "transaction_id", "entry_type"),
    )
