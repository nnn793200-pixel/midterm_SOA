from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Student, TuitionBill
from app.schemas import TuitionLookupResponse, StudentSchema, TuitionBillSchema

router = APIRouter(tags=["Tuition Lookup"])


@router.get(
    "/tuitions/{student_id}",
    response_model=TuitionLookupResponse,
    status_code=status.HTTP_200_OK,
)
def lookup_tuition_by_mssv(student_id: str, db: Session = Depends(get_db)):
    clean_mssv = student_id.strip().upper()
    student = db.query(Student).filter(Student.student_id == clean_mssv).first()

    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "STUDENT_OR_TUITION_NOT_FOUND",
                "message": f"Không tìm thấy sinh viên TDTU với MSSV '{clean_mssv}'.",
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
                "code": "TUITION_BILL_NOT_FOUND",
                "message": f"Sinh viên '{clean_mssv}' hiện không có khoản học phí nào.",
            },
        )

    return TuitionLookupResponse(
        student=StudentSchema.model_validate(student),
        tuition_bill=TuitionBillSchema.model_validate(bill),
        can_pay=(bill.status == "UNPAID"),
    )


@router.get(
    "/tuitions",
    response_model=List[TuitionLookupResponse],
    status_code=status.HTTP_200_OK,
)
def list_all_tuitions(db: Session = Depends(get_db)):
    """
    Liệt kê danh sách toàn bộ sinh viên & học phí mẫu phục vụ tra cứu nhanh khi Demo.
    """
    students = db.query(Student).order_by(Student.student_id.asc()).all()
    results: List[TuitionLookupResponse] = []
    for st in students:
        bill = (
            db.query(TuitionBill)
            .filter(TuitionBill.student_id == st.student_id)
            .order_by(TuitionBill.created_at.desc())
            .first()
        )
        if bill:
            results.append(
                TuitionLookupResponse(
                    student=StudentSchema.model_validate(st),
                    tuition_bill=TuitionBillSchema.model_validate(bill),
                    can_pay=(bill.status == "UNPAID"),
                )
            )
    return results
