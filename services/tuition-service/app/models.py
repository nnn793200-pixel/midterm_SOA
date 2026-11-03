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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class Student(Base):
    __tablename__ = "students"

    student_id = Column(String(20), primary_key=True, index=True)
    full_name = Column(String(100), nullable=False)
    faculty = Column(String(100), nullable=False)
    major = Column(String(100), nullable=False)
    class_code = Column(String(30), nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    tuition_bills = relationship(
        "TuitionBill",
        back_populates="student",
        cascade="all, delete-orphan",
        order_by="desc(TuitionBill.created_at)",
    )


class TuitionBill(Base):
    __tablename__ = "tuition_bills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(
        String(20),
        ForeignKey("students.student_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    semester_code = Column(String(20), nullable=False, default="HK1_2026_2027")
    semester_name = Column(
        String(100), nullable=False, default="Học kỳ 1 - Năm học 2026-2027"
    )
    amount = Column(Numeric(15, 2), nullable=False)
    status = Column(String(20), nullable=False, default="UNPAID")
    paid_transaction_id = Column(UUID(as_uuid=True), unique=True, nullable=True)
    paid_by_account_id = Column(UUID(as_uuid=True), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    student = relationship("Student", back_populates="tuition_bills")

    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_tuition_bills_amount_positive"),
        CheckConstraint(
            "status IN ('UNPAID', 'PAID')", name="chk_tuition_bills_status"
        ),
        UniqueConstraint(
            "student_id", "semester_code", name="uq_tuition_student_semester"
        ),
    )
