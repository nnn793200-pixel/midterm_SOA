import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models import Student, TuitionBill

SEED_TUITIONS = [
    {
        "student_id": "524K0032",
        "full_name": "Trần Minh Nghĩa",
        "faculty": "Khoa Công nghệ Thông tin",
        "major": "Kỹ thuật Phần mềm",
        "class_code": "24K50301",
        "email": "524k0032@student.tdtu.edu.vn",
        "bill_id": uuid.UUID("22222222-2222-2222-2222-222222222206"),
        "semester_code": "HK1_2026_2027",
        "semester_name": "Học kỳ 1 - Năm học 2026-2027",
        "amount": Decimal("15000000.00"),
        "status": "UNPAID",
    },
    {
        "student_id": "524K0033",
        "full_name": "Huỳnh Trung Tín",
        "faculty": "Khoa Công nghệ Thông tin",
        "major": "Khoa học Máy tính",
        "class_code": "24K50101",
        "email": "524k0033@student.tdtu.edu.vn",
        "bill_id": uuid.UUID("22222222-2222-2222-2222-222222222207"),
        "semester_code": "HK1_2026_2027",
        "semester_name": "Học kỳ 1 - Năm học 2026-2027",
        "amount": Decimal("15000000.00"),
        "status": "UNPAID",
    },
    {
        "student_id": "524V0007",
        "full_name": "Phan Nguyễn Thảo Như",
        "faculty": "Khoa Công nghệ Thông tin",
        "major": "Hệ thống Thông tin",
        "class_code": "24V50201",
        "email": "524v0007@student.tdtu.edu.vn",
        "bill_id": uuid.UUID("22222222-2222-2222-2222-222222222208"),
        "semester_code": "HK1_2026_2027",
        "semester_name": "Học kỳ 1 - Năm học 2026-2027",
        "amount": Decimal("14000000.00"),
        "status": "UNPAID",
    },
    {
        "student_id": "52200001",
        "full_name": "Trần Minh Khoa",
        "faculty": "Khoa Công nghệ Thông tin",
        "major": "Kỹ thuật Phần mềm",
        "class_code": "22050301",
        "email": "52200001@student.tdtu.edu.vn",
        "bill_id": uuid.UUID("22222222-2222-2222-2222-222222222201"),
        "semester_code": "HK1_2026_2027",
        "semester_name": "Học kỳ 1 - Năm học 2026-2027",
        "amount": Decimal("14500000.00"),
        "status": "UNPAID",
    },
    {
        "student_id": "52200002",
        "full_name": "Lê Hoàng Nam",
        "faculty": "Khoa Công nghệ Thông tin",
        "major": "Khoa học Máy tính",
        "class_code": "22050102",
        "email": "52200002@student.tdtu.edu.vn",
        "bill_id": uuid.UUID("22222222-2222-2222-2222-222222222202"),
        "semester_code": "HK1_2026_2027",
        "semester_name": "Học kỳ 1 - Năm học 2026-2027",
        "amount": Decimal("14500000.00"),
        "status": "UNPAID",
    },
    {
        "student_id": "52200003",
        "full_name": "Nguyễn Ngọc Mai",
        "faculty": "Khoa Quản trị Kinh doanh",
        "major": "Marketing",
        "class_code": "22070201",
        "email": "52200003@student.tdtu.edu.vn",
        "bill_id": uuid.UUID("22222222-2222-2222-2222-222222222203"),
        "semester_code": "HK1_2026_2027",
        "semester_name": "Học kỳ 1 - Năm học 2026-2027",
        "amount": Decimal("12000000.00"),
        "status": "UNPAID",
    },
    {
        "student_id": "52200004",
        "full_name": "Phạm Quốc Bảo",
        "faculty": "Khoa Điện - Điện tử",
        "major": "Kỹ thuật Điều khiển và Tự động hóa",
        "class_code": "22040301",
        "email": "52200004@student.tdtu.edu.vn",
        "bill_id": uuid.UUID("22222222-2222-2222-2222-222222222204"),
        "semester_code": "HK1_2026_2027",
        "semester_name": "Học kỳ 1 - Năm học 2026-2027",
        "amount": Decimal("16000000.00"),
        "status": "UNPAID",
    },
    {
        "student_id": "52200005",
        "full_name": "Võ Thị Thanh Tâm",
        "faculty": "Khoa Kế toán",
        "major": "Kế toán - Kiểm toán",
        "class_code": "22020101",
        "email": "52200005@student.tdtu.edu.vn",
        "bill_id": uuid.UUID("22222222-2222-2222-2222-222222222205"),
        "semester_code": "HK1_2026_2027",
        "semester_name": "Học kỳ 1 - Năm học 2026-2027",
        "amount": Decimal("13500000.00"),
        "status": "PAID",
    },
]


def seed_tuitions(db: Session, force_reset: bool = False) -> None:
    now = datetime.now(timezone.utc)
    for item in SEED_TUITIONS:
        student = (
            db.query(Student)
            .filter(Student.student_id == item["student_id"])
            .first()
        )
        if not student:
            student = Student(
                student_id=item["student_id"],
                full_name=item["full_name"],
                faculty=item["faculty"],
                major=item["major"],
                class_code=item["class_code"],
                email=item["email"],
            )
            db.add(student)
            db.flush()

        bill = (
            db.query(TuitionBill)
            .filter(
                TuitionBill.student_id == item["student_id"],
                TuitionBill.semester_code == item["semester_code"],
            )
            .first()
        )
        if not bill:
            is_pre_paid = item["status"] == "PAID"
            bill = TuitionBill(
                id=item["bill_id"],
                student_id=item["student_id"],
                semester_code=item["semester_code"],
                semester_name=item["semester_name"],
                amount=item["amount"],
                status=item["status"],
                paid_transaction_id=uuid.UUID("99999999-9999-9999-9999-999999999905")
                if is_pre_paid
                else None,
                paid_by_account_id=uuid.UUID("11111111-1111-1111-1111-111111111104")
                if is_pre_paid
                else None,
                paid_at=now if is_pre_paid else None,
                version=1,
            )
            db.add(bill)
        elif force_reset:
            is_pre_paid = item["status"] == "PAID"
            bill.amount = item["amount"]
            bill.status = item["status"]
            bill.paid_transaction_id = (
                uuid.UUID("99999999-9999-9999-9999-999999999905")
                if is_pre_paid
                else None
            )
            bill.paid_by_account_id = (
                uuid.UUID("11111111-1111-1111-1111-111111111104")
                if is_pre_paid
                else None
            )
            bill.paid_at = now if is_pre_paid else None
            bill.version = 1
            bill.updated_at = now

    db.commit()
