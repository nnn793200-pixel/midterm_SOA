from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models import Student, TuitionBill
from app.schemas import (
    TuitionLookupResponse,
    StudentSchema,
    TuitionBillSchema,
    MarkTuitionPaidRequest,
    MarkTuitionPaidResponse,
)
from app.seed import seed_tuitions
from app.security import verify_internal_service_token

router = APIRouter(
    prefix="/internal/tuitions",
    tags=["Internal Tuition Operations"],
    dependencies=[Depends(verify_internal_service_token)],
)


@router.get(
    "/{student_id}",
    response_model=TuitionLookupResponse,
    status_code=status.HTTP_200_OK,
)
def get_tuition_internal_precheck(student_id: str, db: Session = Depends(get_db)):
    """
    API đọc thông tin sinh viên & khoản học phí ở bước Pre-check khi khởi tạo giao dịch.
    TUYỆT ĐỐI KHÔNG giữ DB Row Lock (SELECT FOR UPDATE) trong suốt 5 phút chờ nhập OTP.
    """
    clean_mssv = student_id.strip().upper()
    student = db.query(Student).filter(Student.student_id == clean_mssv).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "STUDENT_NOT_FOUND",
                "message": f"Không tìm thấy sinh viên với MSSV '{clean_mssv}'.",
            },
        )

    bill = (
        db.query(TuitionBill)
        .filter(TuitionBill.student_id == clean_mssv)
        .order_by(TuitionBill.created_at.desc())
        .first()
    )
    if not bill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "TUITION_NOT_FOUND",
                "message": f"Không tìm thấy khoản học phí cho sinh viên '{clean_mssv}'.",
            },
        )

    return TuitionLookupResponse(
        student=StudentSchema.model_validate(student),
        tuition_bill=TuitionBillSchema.model_validate(bill),
        can_pay=(bill.status == "UNPAID"),
    )


@router.post(
    "/mark-paid",
    response_model=MarkTuitionPaidResponse,
    status_code=status.HTTP_200_OK,
)
def mark_tuition_paid_atomic(
    payload: MarkTuitionPaidRequest, db: Session = Depends(get_db)
):
    """
    Thực thi gạch nợ học phí nguyên tử ngay tại thời điểm OTP được xác thực thành công.
    Sử dụng Pessimistic Locking (SELECT ... FOR UPDATE) + kiểm tra trạng thái UNPAID
    để giải quyết triệt để Concurrency 2 (Nhiều tài khoản cùng thanh toán 1 MSSV).
    """
    try:
        # 1. Khóa Pessimistic (SELECT ... FOR UPDATE) trên bản ghi học phí
        bill = (
            db.query(TuitionBill)
            .filter(
                TuitionBill.id == payload.tuition_bill_id,
                TuitionBill.student_id == payload.student_id.strip().upper(),
            )
            .with_for_update()
            .first()
        )

        if not bill:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "TUITION_NOT_FOUND",
                    "message": "Không tìm thấy khoản học phí tương ứng để gạch nợ.",
                },
            )

        student = (
            db.query(Student)
            .filter(Student.student_id == bill.student_id)
            .first()
        )
        student_name = student.full_name if student else bill.student_id

        # 2. Hỗ trợ Idempotent retry cho cùng 1 transaction_id
        if bill.status == "PAID" and bill.paid_transaction_id == payload.transaction_id:
            return MarkTuitionPaidResponse(
                tuition_bill_id=bill.id,
                student_id=bill.student_id,
                student_full_name=student_name,
                semester_code=bill.semester_code,
                semester_name=bill.semester_name,
                amount=float(bill.amount),
                status="PAID",
                paid_transaction_id=bill.paid_transaction_id,
                paid_by_account_id=bill.paid_by_account_id,
                paid_at=bill.paid_at,
                version=bill.version,
            )

        # 3. Kiểm tra Concurrency 2: Nếu đã PAID bởi một giao dịch khác -> Từ chối ngay (409 Conflict)
        if bill.status != "UNPAID":
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "TUITION_ALREADY_PAID",
                    "message": f"Khoản học phí của MSSV {bill.student_id} đã được thanh toán bởi một giao dịch khác.",
                    "details": {
                        "student_id": bill.student_id,
                        "paid_transaction_id": str(bill.paid_transaction_id),
                        "paid_at": bill.paid_at.isoformat() if bill.paid_at else None,
                    },
                },
            )

        # 4. Kiểm tra bắt buộc thanh toán TOÀN BỘ khoản học phí
        bill_amount = Decimal(str(bill.amount))
        req_amount = Decimal(str(payload.amount))
        if bill_amount != req_amount:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "PARTIAL_PAYMENT_NOT_ALLOWED",
                    "message": "Hệ thống chỉ cho phép thanh toán toàn bộ khoản học phí, không thanh toán một phần.",
                    "details": {
                        "required_amount": float(bill_amount),
                        "submitted_amount": float(req_amount),
                    },
                },
            )

        # 5. Chuyển trạng thái nguyên tử sang PAID và tăng version
        now = datetime.now(timezone.utc)
        bill.status = "PAID"
        bill.paid_transaction_id = payload.transaction_id
        bill.paid_by_account_id = payload.payer_account_id
        bill.paid_at = now
        bill.version = bill.version + 1
        bill.updated_at = now

        db.commit()
        db.refresh(bill)

        return MarkTuitionPaidResponse(
            tuition_bill_id=bill.id,
            student_id=bill.student_id,
            student_full_name=student_name,
            semester_code=bill.semester_code,
            semester_name=bill.semester_name,
            amount=float(bill.amount),
            status=bill.status,
            paid_transaction_id=bill.paid_transaction_id,
            paid_by_account_id=bill.paid_by_account_id,
            paid_at=bill.paid_at,
            version=bill.version,
        )

    except HTTPException:
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TUITION_ALREADY_PAID",
                "message": f"Khoản học phí đã được thanh toán bởi giao dịch khác: {str(exc.orig)}",
            },
        )


@router.post("/reset-demo", status_code=status.HTTP_200_OK)
def reset_demo_tuitions(db: Session = Depends(get_db)):
    """
    Khôi phục trạng thái UNPAID cho các khoản học phí mẫu phục vụ kiểm thử tự động & demo.
    """
    seed_tuitions(db, force_reset=True)
    return {
        "status": "RESET_SUCCESS",
        "message": "Đã khôi phục trạng thái học phí mặc định cho toàn bộ sinh viên mẫu.",
    }
