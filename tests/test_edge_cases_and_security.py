"""
KIỂM THỬ BỔ SUNG CHO CÁC TRƯỜNG HỢP BIÊN & BẢO MẬT (EDGE CASES & SECURITY TESTS)
Kiểm chứng đầy đủ các kịch bản trọng yếu:
1. Gọi trực tiếp /internal/* không có hoặc sai X-Internal-Service-Token -> 403 Forbidden.
2. Khi mailer.py gặp lỗi SMTP -> trả về "FAILED" (không trả về "SENT" giả), /internal/otp/generate
   trả 502 và vô hiệu hóa OtpToken trong DB (is_used=True) đồng bộ với xóa Redis.
3. Khi bước refund trong Saga thất bại -> retry tối đa 3 lần rồi chuyển sang COMPENSATION_FAILED,
   restored_balance = None (không báo COMPENSATED giả).
4. Khi gửi email biên lai thất bại sau khi đã trừ tiền và gạch nợ -> DB vẫn commit COMPLETED
   trước khi gửi email, HTTP trả 200 với status="COMPLETED", receipt_email_sent=False và log RECEIPT_EMAIL_FAILED.
5. Xác minh Redis Distributed Lock & Redis Idempotency Cache trong payment-service.
6. Công tắc ENABLE_DEMO_ENDPOINTS tại API Gateway (tắt trả 403 DEMO_ENDPOINTS_DISABLED, bật cho đi qua).
7. Query param ?status= trên /payments/history, save_idempotency cho nhánh lỗi (409/502),
   IntegrityError fallback trên /payments/initiate và httpx.RequestError -> 503 trên demo-otp/reset-demo.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import smtplib
import subprocess
import sys
import types

for _s in (sys.stdout, sys.stderr):
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError


ROOT_DIR = Path(__file__).resolve().parents[1]
SERVICES_DIR = ROOT_DIR / "services"
TEST_JWT_SECRET = "tdtu-soa-2026-super-secret-jwt-key-9999"
TEST_INTERNAL_SECRET = "tdtu-soa-2026-internal-service-secret-9999"


def _ensure_psycopg2_stub() -> None:
    """
    Cho phép import SQLAlchemy create_engine("postgresql+psycopg2://...") trên host
    khi chỉ test bằng FastAPI TestClient & Fake DB Session mà không cần psycopg2 native.
    """
    if "psycopg2" in sys.modules:
        return
    try:
        import psycopg2  # noqa: F401
        return
    except ImportError:
        pass

    stub = types.ModuleType("psycopg2")
    stub.__version__ = "2.9.9"
    stub.apilevel = "2.0"
    stub.threadsafety = 2
    stub.paramstyle = "pyformat"

    class _DummyError(Exception):
        pass

    for err_name in (
        "Warning",
        "Error",
        "InterfaceError",
        "DatabaseError",
        "DataError",
        "OperationalError",
        "IntegrityError",
        "InternalError",
        "ProgrammingError",
        "NotSupportedError",
    ):
        setattr(stub, err_name, _DummyError)

    extras = types.ModuleType("psycopg2.extras")
    extensions = types.ModuleType("psycopg2.extensions")
    stub.extras = extras
    stub.extensions = extensions
    sys.modules["psycopg2"] = stub
    sys.modules["psycopg2.extras"] = extras
    sys.modules["psycopg2.extensions"] = extensions


@contextmanager
def _service_import_context(service_name: str):
    """
    Cô lập namespace `app.*` khi nạp từng microservice trong cùng tiến trình Python.
    """
    _ensure_psycopg2_stub()
    svc_path = str(SERVICES_DIR / service_name)
    saved_modules = {
        k: sys.modules.pop(k)
        for k in list(sys.modules.keys())
        if k == "app" or k.startswith("app.")
    }
    sys.path.insert(0, svc_path)
    try:
        yield
    finally:
        for k in list(sys.modules.keys()):
            if k == "app" or k.startswith("app."):
                sys.modules.pop(k, None)
        if sys.path and sys.path[0] == svc_path:
            sys.path.pop(0)
        sys.modules.update(saved_modules)


def _make_jwt(account_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": account_id,
            "username": "nguyenvana",
            "exp": now + timedelta(minutes=30),
            "iat": now,
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


class _FakeQuery:
    def __init__(self, first_obj=None, all_objs=None):
        self._first_obj = first_obj
        self._all_objs = list(all_objs) if all_objs is not None else ([] if first_obj is None else [first_obj])
        self._offset = 0
        self._limit = None

    def filter(self, *args, **kwargs):
        filtered = []
        for obj in self._all_objs:
            matched = True
            for crit in args:
                left = getattr(crit, "left", None)
                right = getattr(crit, "right", None)
                attr_name = getattr(left, "key", None)
                expected_val = getattr(right, "value", None)
                if attr_name and expected_val is not None and hasattr(obj, attr_name):
                    if getattr(obj, attr_name) != expected_val:
                        matched = False
                        break
            if matched:
                filtered.append(obj)
        self._all_objs = filtered
        self._first_obj = filtered[0] if filtered else None
        return self

    def with_for_update(self):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def offset(self, n):
        self._offset = n or 0
        return self

    def limit(self, n):
        self._limit = n
        return self

    def count(self):
        return len(self._all_objs)

    def delete(self):
        count = len(self._all_objs)
        self._all_objs.clear()
        self._first_obj = None
        return count

    def first(self):
        return self._first_obj

    def all(self):
        end = None if self._limit is None else self._offset + self._limit
        return list(self._all_objs[self._offset:end])


class _FakePaymentDbSession:
    """
    Mock SQLAlchemy Session cho payment-service để ghi nhận chính xác
    trình tự db.commit(), trạng thái PaymentTransaction và các SagaStepLog được lưu.
    """

    def __init__(self, tx_obj, extra_txs=None):
        self.tx = tx_obj
        self.txs = list(extra_txs) if extra_txs is not None else ([tx_obj] if tx_obj is not None else [])
        self.steps = []
        self.idempotency_records = []
        self.commit_snapshots = []
        self.commit_count = 0
        self.rollback_count = 0

    def query(self, model):
        model_name = getattr(model, "__name__", "")
        if model_name == "PaymentTransaction":
            return _FakeQuery(all_objs=self.txs)
        if model_name == "IdempotencyRecord":
            return _FakeQuery(all_objs=self.idempotency_records)
        if model_name == "SagaStepLog":
            return _FakeQuery(all_objs=self.steps)
        return _FakeQuery(first_obj=None)

    def add(self, obj):
        cls_name = obj.__class__.__name__
        if cls_name == "PaymentTransaction":
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            self.tx = obj
            if obj not in self.txs:
                self.txs.append(obj)
        elif cls_name == "SagaStepLog":
            self.steps.append(obj)
        elif cls_name == "IdempotencyRecord":
            self.idempotency_records.append(obj)

    def flush(self):
        return None

    def commit(self):
        self.commit_count += 1
        self.commit_snapshots.append(
            {
                "commit_number": self.commit_count,
                "tx_status": self.tx.status,
                "step_names": [s.step_name for s in self.steps],
                "step_statuses": [s.step_status for s in self.steps],
            }
        )

    def rollback(self):
        self.rollback_count += 1

    def refresh(self, obj):
        return None

    def delete(self, obj):
        return None

    def close(self):
        return None


def test_internal_endpoints_require_token() -> None:
    """
    Kiểm thử 1: Gọi trực tiếp /internal/* không có hoặc sai X-Internal-Service-Token
    bắt buộc trả về 403 Forbidden trên cả auth-account, tuition và notification-otp.
    Đồng thời kiểm tra container thực tế nếu cụm Docker đang chạy.
    """
    print("\n" + "=" * 80)
    print("TEST BIÊN 1: BẢO MẬT INTERNAL APIs (X-Internal-Service-Token -> 403 Forbidden)")
    print("=" * 80)

    sample_uuid = "11111111-1111-1111-1111-111111111101"
    service_cases = [
        (
            "auth-account-service",
            [
                ("GET", f"/internal/accounts/{sample_uuid}", None),
                (
                    "POST",
                    "/internal/accounts/debit",
                    {
                        "account_id": sample_uuid,
                        "transaction_id": str(uuid.uuid4()),
                        "amount": 1000000,
                        "idempotency_key": "test-idem-1",
                        "description": "test",
                    },
                ),
                (
                    "POST",
                    "/internal/accounts/refund",
                    {
                        "account_id": sample_uuid,
                        "transaction_id": str(uuid.uuid4()),
                        "amount": 1000000,
                        "idempotency_key": "test-idem-refund-1",
                        "reason": "test",
                    },
                ),
                ("POST", "/internal/accounts/reset-demo", None),
            ],
        ),
        (
            "tuition-service",
            [
                ("GET", "/internal/tuitions/52200001", None),
                (
                    "POST",
                    "/internal/tuitions/mark-paid",
                    {
                        "tuition_bill_id": str(uuid.uuid4()),
                        "student_id": "52200001",
                        "transaction_id": str(uuid.uuid4()),
                        "payer_account_id": sample_uuid,
                        "amount": 14500000,
                    },
                ),
                ("POST", "/internal/tuitions/reset-demo", None),
            ],
        ),
        (
            "notification-otp-service",
            [
                (
                    "POST",
                    "/internal/otp/generate",
                    {
                        "transaction_id": str(uuid.uuid4()),
                        "transaction_code": "TXN-TEST-001",
                        "recipient_email": "test@tdtu.edu.vn",
                        "payer_name": "Tester",
                        "student_id": "52200001",
                        "student_name": "Sinh Vien",
                        "amount": 14500000,
                    },
                ),
                (
                    "POST",
                    "/internal/otp/verify",
                    {"transaction_id": str(uuid.uuid4()), "otp_code": "123456"},
                ),
                (
                    "POST",
                    "/internal/notifications/payment-receipt",
                    {
                        "transaction_id": str(uuid.uuid4()),
                        "transaction_code": "TXN-TEST-001",
                        "recipient_email": "test@tdtu.edu.vn",
                        "payer_name": "Tester",
                        "payer_phone": "0900000000",
                        "student_id": "52200001",
                        "student_name": "Sinh Vien",
                        "semester_name": "HK1",
                        "amount": 14500000,
                        "balance_before": 25000000,
                        "balance_after": 10500000,
                        "paid_at": datetime.now(timezone.utc).isoformat(),
                    },
                ),
                ("GET", f"/internal/otp/debug/{uuid.uuid4()}", None),
                ("POST", "/internal/otp/reset-demo", None),
            ],
        ),
    ]

    for service_name, endpoints in service_cases:
        with _service_import_context(service_name):
            from app.main import app
            from app.database import get_db

            app.dependency_overrides[get_db] = lambda: _FakePaymentDbSession(None)
            client = TestClient(app)

            for method, path, body in endpoints:
                # 1. Thiếu header X-Internal-Service-Token
                resp_missing = client.request(method, path, json=body)
                assert resp_missing.status_code == 403, (
                    f"[{service_name}] {method} {path} thiếu token phải trả 403, thực tế: {resp_missing.status_code}"
                )
                assert resp_missing.json()["error"]["code"] == "FORBIDDEN_INTERNAL_API"

                # 2. Sai header X-Internal-Service-Token
                resp_wrong = client.request(
                    method,
                    path,
                    json=body,
                    headers={"X-Internal-Service-Token": "invalid-secret-token"},
                )
                assert resp_wrong.status_code == 403, (
                    f"[{service_name}] {method} {path} sai token phải trả 403, thực tế: {resp_wrong.status_code}"
                )

            app.dependency_overrides.clear()
        print(f"[✓] {service_name}: Tất cả {len(endpoints)} routes /internal/* chặn 403 khi thiếu/sai token.")

    # Kiểm chứng thêm trên cụm Docker nếu đang chạy:
    # 1) Port nội bộ 8001-8004 không mở công khai ra host (internal_network isolation)
    # 2) Gọi bên trong mạng Docker thiếu X-Internal-Service-Token trả về 403
    try:
        docker_ps = subprocess.run(
            ["docker", "compose", "ps", "--services", "--status", "running"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=5,
        )
        running = set(docker_ps.stdout.strip().splitlines()) if docker_ps.returncode == 0 else set()
        if {"api-gateway", "auth-account-service", "tuition-service", "notification-otp-service"}.issubset(running):
            for internal_port in (8001, 8002, 8003, 8004):
                try:
                    httpx.get(f"http://127.0.0.1:{internal_port}/health", timeout=0.5)
                    raise AssertionError(
                        f"Port nội bộ {internal_port} không được phép mở trực tiếp ra host!"
                    )
                except httpx.RequestError:
                    pass

            probe_code = (
                "import urllib.request, urllib.error, json; "
                "targets=['http://auth-account-service:8001/internal/accounts/reset-demo',"
                "'http://tuition-service:8002/internal/tuitions/reset-demo',"
                "'http://notification-otp-service:8004/internal/otp/reset-demo']; "
                "codes=[]; "
                "\nfor u in targets:\n"
                "  req=urllib.request.Request(u, method='POST', data=b'{}', headers={'Content-Type':'application/json'});\n"
                "  try:\n    urllib.request.urlopen(req, timeout=3); codes.append(200)\n"
                "  except urllib.error.HTTPError as e:\n    codes.append(e.code)\n"
                "print(json.dumps(codes))"
            )
            exec_res = subprocess.run(
                ["docker", "compose", "exec", "-T", "api-gateway", "python", "-c", probe_code],
                cwd=str(ROOT_DIR),
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert exec_res.returncode == 0, f"Docker internal probe lỗi: {exec_res.stderr}"
            live_codes = json.loads(exec_res.stdout.strip())
            assert live_codes == [403, 403, 403], (
                f"Kỳ vọng [403, 403, 403] khi gọi trực tiếp internal container, thực tế: {live_codes}"
            )
            print("[✓] Live Docker internal_network: port 8001-8004 cô lập khỏi host & internal call thiếu token trả [403, 403, 403].")
    except FileNotFoundError:
        pass


def test_mailer_returns_failed_on_smtp_error() -> None:
    """
    Kiểm thử 2:
    - mailer.send_html_email khi SMTP exception trả về ("FAILED", "SMTP_ERROR: ..."), KHÔNG trả về "SENT".
    - POST /internal/otp/generate khi gửi mail thất bại phải lưu NotificationLog FAILED và trả HTTP 502.
    """
    print("\n" + "=" * 80)
    print("TEST BIÊN 2: MAILER TRẢ VỀ 'FAILED' KHI LỖI SMTP & /internal/otp/generate TRẢ 502")
    print("=" * 80)

    with _service_import_context("notification-otp-service"):
        from app import mailer
        from app.main import app
        from app.database import get_db
        from app.routers import internal as otp_internal_router

        with patch.object(
            smtplib, "SMTP", side_effect=ConnectionRefusedError("Mailpit connection refused")
        ):
            delivery_status, smtp_resp = mailer.send_html_email(
                recipient_email="student@tdtu.edu.vn",
                subject="[TDTU iBanking] OTP Test",
                html_body="<p>123456</p>",
            )

        assert delivery_status == "FAILED", f"Phải trả về FAILED nhưng nhận được: {delivery_status}"
        assert smtp_resp.startswith("SMTP_ERROR:")
        print(f"[✓] mailer.send_html_email trả về đúng trạng thái '{delivery_status}' ({smtp_resp}).")

        # Kiểm chứng tiếp /internal/otp/generate ghi FAILED vào DB và trả HTTP 502
        added_objects = []

        class _FakeNotifSession:
            def query(self, model):
                return _FakeQuery(first_obj=None, all_objs=[])

            def add(self, obj):
                if getattr(obj, "id", None) is None:
                    obj.id = uuid.uuid4()
                added_objects.append(obj)

            def flush(self):
                return None

            def commit(self):
                return None

            def refresh(self, obj):
                return None

            def close(self):
                return None

        fake_redis = MagicMock()
        app.dependency_overrides[get_db] = lambda: _FakeNotifSession()
        client = TestClient(app)

        with (
            patch.object(otp_internal_router, "generate_unique_otp_in_redis", return_value="654321"),
            patch.object(otp_internal_router, "get_redis", return_value=fake_redis),
            patch.object(smtplib, "SMTP", side_effect=smtplib.SMTPException("SMTP down")),
        ):
            resp = client.post(
                "/internal/otp/generate",
                headers={"X-Internal-Service-Token": TEST_INTERNAL_SECRET},
                json={
                    "transaction_id": str(uuid.uuid4()),
                    "transaction_code": "TXN-20261108-999001",
                    "recipient_email": "fail@tdtu.edu.vn",
                    "payer_name": "Nguyen Van A",
                    "student_id": "52200001",
                    "student_name": "Tran Minh Khoa",
                    "semester_name": "HK1 2026-2027",
                    "amount": 14500000,
                },
            )

        app.dependency_overrides.clear()

        assert resp.status_code == 502, f"Kỳ vọng 502 khi SMTP OTP thất bại, nhận: {resp.status_code}"
        assert resp.json()["error"]["code"] == "OTP_EMAIL_DELIVERY_FAILED"

        notif_logs = [o for o in added_objects if o.__class__.__name__ == "NotificationLog"]
        assert len(notif_logs) == 1
        assert notif_logs[0].delivery_status == "FAILED", (
            f"NotificationLog phải lưu FAILED nhưng thực tế: {notif_logs[0].delivery_status}"
        )
        otp_tokens = [o for o in added_objects if o.__class__.__name__ == "OtpToken"]
        assert len(otp_tokens) == 1
        assert otp_tokens[0].is_used is True, (
            "OtpToken phải bị đánh dấu is_used=True khi gửi SMTP thất bại (không để OTP sống trong DB)!"
        )
        assert otp_tokens[0].used_at is not None
        assert fake_redis.delete.call_count >= 2
        print("[✓] /internal/otp/generate lưu NotificationLog(FAILED), vô hiệu hóa OtpToken (is_used=True), xóa Redis và trả HTTP 502.")


def test_saga_compensation_failed_when_refund_fails() -> None:
    """
    Kiểm thử 3: Khi mark-paid thất bại sau khi đã trừ tiền, và bước refund thất bại
    sau khi retry tối đa 3 lần -> giao dịch & step chuyển sang COMPENSATION_FAILED,
    restored_balance = None, HTTP 502 (KHÔNG báo COMPENSATED giả).
    """
    print("\n" + "=" * 80)
    print("TEST BIÊN 3: REFUND THẤT BẠI SAU 3 LẦN RETRY -> COMPENSATION_FAILED (KHÔNG GIẢ COMPENSATED)")
    print("=" * 80)

    with _service_import_context("payment-service"):
        from app.main import app
        from app.database import get_db
        from app.models import PaymentTransaction
        from app import saga as payment_saga
        from app.routers import payments as payments_router

        payer_id = uuid.uuid4()
        tx_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        tx = PaymentTransaction(
            id=tx_id,
            transaction_code="TXN-20261108-777001",
            payer_account_id=payer_id,
            payer_full_name="Nguyễn Văn A",
            payer_phone="0901234567",
            payer_email="nguyenvana@tdtu.edu.vn",
            student_id="52200001",
            student_full_name="Trần Minh Khoa",
            tuition_bill_id=uuid.uuid4(),
            semester_code="HK1_2026_2027",
            semester_name="Học kỳ 1 - Năm học 2026-2027",
            amount=Decimal("14500000.00"),
            terms_accepted=True,
            status="PENDING_OTP",
            idempotency_key=f"init-{tx_id}",
            correlation_id=str(uuid.uuid4()),
            otp_expires_at=now + timedelta(minutes=5),
            version=1,
            created_at=now,
            updated_at=now,
        )
        fake_db = _FakePaymentDbSession(tx)

        @contextmanager
        def _noop_locks(**kwargs):
            yield

        refund_attempts = {"count": 0}

        class _FakeHttpClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, **kwargs):
                refund_attempts["count"] += 1
                return httpx.Response(
                    status_code=500,
                    json={"error": {"code": "REFUND_DB_ERROR", "message": "Account DB locked"}},
                )

        debit_resp = httpx.Response(
            200,
            json={"balance_before": 25000000.0, "balance_after": 10500000.0},
        )
        tuition_409_resp = httpx.Response(
            409,
            json={"error": {"code": "TUITION_ALREADY_PAID", "message": "Đã đóng bởi người khác"}},
        )

        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        with (
            patch.object(payments_router, "acquire_payment_locks", _noop_locks),
            patch.object(payments_router, "check_idempotency", return_value=None),
            patch.object(payments_router, "call_verify_otp", return_value={"verified": True}),
            patch.object(payments_router, "call_debit_account", return_value=debit_resp),
            patch.object(payments_router, "call_mark_tuition_paid", return_value=tuition_409_resp),
            patch.object(payment_saga.httpx, "Client", _FakeHttpClient),
            patch.object(payment_saga.time, "sleep", return_value=None),
        ):
            resp = client.post(
                f"/payments/{tx_id}/confirm-otp",
                headers={
                    "Authorization": f"Bearer {_make_jwt(str(payer_id))}",
                    "Idempotency-Key": str(uuid.uuid4()),
                },
                json={"otp_code": "123456"},
            )

        app.dependency_overrides.clear()

        assert refund_attempts["count"] == 3, (
            f"Refund phải retry đúng 3 lần, thực tế: {refund_attempts['count']}"
        )
        assert resp.status_code == 502, f"Kỳ vọng HTTP 502 khi refund thất bại, nhận: {resp.status_code}"
        err = resp.json()["error"]
        assert err["code"] == "COMPENSATION_FAILED"
        assert err["details"]["status"] == "COMPENSATION_FAILED"
        assert err["details"]["restored_balance"] is None, (
            f"TUYỆT ĐỐI không được giả mạo restored_balance! Thực tế: {err['details']['restored_balance']}"
        )
        assert err["details"]["manual_reconciliation_required"] is True

        assert tx.status == "COMPENSATION_FAILED"
        assert tx.balance_after == Decimal("10500000.0")
        refund_steps = [s for s in fake_db.steps if s.step_name == "COMPENSATE_REFUND"]
        assert len(refund_steps) == 1
        assert refund_steps[0].step_status == "COMPENSATION_FAILED"
        assert fake_db.commit_count >= 1
        print("[✓] Refund thất bại sau 3 lần retry: tx & step = COMPENSATION_FAILED, restored_balance=None, HTTP 502.")


def test_receipt_email_failure_preserves_completed_status() -> None:
    """
    Kiểm thử 4: Khi debit và mark-paid thành công, payment-service phải db.commit() COMPLETED
    NGAY TRƯỚC khi gửi email biên lai; nếu gửi email biên lai thất bại (delivery_status != 'SENT'
    hoặc exception), giao dịch vẫn COMPLETED và HTTP 200 trả receipt_email_sent = False.
    """
    print("\n" + "=" * 80)
    print("TEST BIÊN 4: LỖI EMAIL BIÊN LAI KHÔNG ROLLBACK COMPLETED & TRẢ receipt_email_sent=False")
    print("=" * 80)

    with _service_import_context("payment-service"):
        from app.main import app
        from app.database import get_db
        from app.models import PaymentTransaction
        from app.routers import payments as payments_router

        for case_label, receipt_side_effect in (
            ("delivery_status == FAILED", {"delivery_status": "FAILED", "error": "SMTP timeout"}),
            ("exception từ notification-otp-service", RuntimeError("Notification service down")),
        ):
            payer_id = uuid.uuid4()
            tx_id = uuid.uuid4()
            now = datetime.now(timezone.utc)
            tx = PaymentTransaction(
                id=tx_id,
                transaction_code=f"TXN-20261108-{uuid.uuid4().hex[:6].upper()}",
                payer_account_id=payer_id,
                payer_full_name="Nguyễn Văn A",
                payer_phone="0901234567",
                payer_email="nguyenvana@tdtu.edu.vn",
                student_id="52200001",
                student_full_name="Trần Minh Khoa",
                tuition_bill_id=uuid.uuid4(),
                semester_code="HK1_2026_2027",
                semester_name="Học kỳ 1 - Năm học 2026-2027",
                amount=Decimal("14500000.00"),
                terms_accepted=True,
                status="PENDING_OTP",
                idempotency_key=f"init-{tx_id}",
                correlation_id=str(uuid.uuid4()),
                otp_expires_at=now + timedelta(minutes=5),
                version=1,
                created_at=now,
                updated_at=now,
            )
            fake_db = _FakePaymentDbSession(tx)
            commit_count_when_receipt_called = {}

            @contextmanager
            def _noop_locks(**kwargs):
                yield

            def _mock_receipt_call(payload, correlation_id):
                commit_count_when_receipt_called["commits_before_email"] = fake_db.commit_count
                commit_count_when_receipt_called["status_before_email"] = tx.status
                if isinstance(receipt_side_effect, Exception):
                    raise receipt_side_effect
                return receipt_side_effect

            debit_resp = httpx.Response(
                200,
                json={"balance_before": 25000000.0, "balance_after": 10500000.0},
            )
            tuition_200_resp = httpx.Response(
                200,
                json={"status": "PAID", "student_id": "52200001"},
            )

            app.dependency_overrides[get_db] = lambda: fake_db
            client = TestClient(app)

            with (
                patch.object(payments_router, "acquire_payment_locks", _noop_locks),
                patch.object(payments_router, "check_idempotency", return_value=None),
                patch.object(payments_router, "save_idempotency", side_effect=lambda **kw: fake_db.commit()),
                patch.object(payments_router, "call_verify_otp", return_value={"verified": True}),
                patch.object(payments_router, "call_debit_account", return_value=debit_resp),
                patch.object(payments_router, "call_mark_tuition_paid", return_value=tuition_200_resp),
                patch.object(payments_router, "call_send_receipt_email", side_effect=_mock_receipt_call),
            ):
                resp = client.post(
                    f"/payments/{tx_id}/confirm-otp",
                    headers={
                        "Authorization": f"Bearer {_make_jwt(str(payer_id))}",
                        "Idempotency-Key": str(uuid.uuid4()),
                    },
                    json={"otp_code": "123456"},
                )

            app.dependency_overrides.clear()

            assert resp.status_code == 200, f"({case_label}) Phải trả HTTP 200, nhận: {resp.status_code}"
            body = resp.json()
            assert body["status"] == "COMPLETED"
            assert body["receipt_email_sent"] is False, (
                f"({case_label}) receipt_email_sent phải là False!"
            )
            assert commit_count_when_receipt_called["commits_before_email"] >= 1, (
                "Phải db.commit() COMPLETED NGAY TRƯỚC khi gọi service gửi email biên lai!"
            )
            assert commit_count_when_receipt_called["status_before_email"] == "COMPLETED"
            assert tx.status == "COMPLETED"

            receipt_steps = [s for s in fake_db.steps if s.step_name == "RECEIPT_EMAIL_FAILED"]
            assert len(receipt_steps) == 1
            assert receipt_steps[0].step_status == "FAILED"
            print(f"[✓] Trường hợp '{case_label}': Đã commit COMPLETED trước email, HTTP 200, receipt_email_sent=False, step=RECEIPT_EMAIL_FAILED.")


def test_payment_redis_locks_and_idempotency() -> None:
    """
    Kiểm thử 5: Xác minh payment-service thực sự sử dụng Redis Distributed Lock
    (lock:account:{user_id}, lock:tuition:{student_id} qua SET NX PX + Lua unlock)
    và Redis Idempotency Cache (idempotency:{key}).
    """
    print("\n" + "=" * 80)
    print("TEST BIÊN 5: REDIS DISTRIBUTED LOCKS & REDIS IDEMPOTENCY CACHE TRONG payment-service")
    print("=" * 80)

    with _service_import_context("payment-service"):
        from app import redis_client as pay_redis
        from app import saga as payment_saga

        store = {}
        eval_calls = []

        class _InMemoryRedis:
            def set(self, key, value, nx=False, px=None, ex=None):
                if nx and key in store:
                    return False
                store[key] = value
                return True

            def get(self, key):
                return store.get(key)

            def eval(self, script, numkeys, key, token):
                eval_calls.append((key, token))
                if store.get(key) == token:
                    del store[key]
                    return 1
                return 0

        fake_r = _InMemoryRedis()
        uid = "11111111-1111-1111-1111-111111111101"

        with patch.object(pay_redis, "get_redis", return_value=fake_r):
            with pay_redis.acquire_payment_locks(account_id=uid, student_id="52200001"):
                assert f"lock:account:{uid}" in store
                assert "lock:tuition:52200001" in store

            # Sau khi thoát context manager, cả 2 lock phải được giải phóng qua Lua script
            assert f"lock:account:{uid}" not in store
            assert "lock:tuition:52200001" not in store
            assert len(eval_calls) == 2

            # Kiểm chứng Redis Idempotency Cache fast-path
            dummy_db = MagicMock()
            payload = {"student_id": "52200001", "amount": 14500000}
            resp_body = {"transaction_id": "tx-1", "status": "PENDING_OTP"}
            payment_saga.save_idempotency(
                db=dummy_db,
                idempotency_key="idem-redis-001",
                account_id=uuid.UUID(uid),
                endpoint="POST:/payments/initiate",
                payload_dict=payload,
                status_code=201,
                response_body=resp_body,
            )
            assert "idempotency:idem-redis-001" in store
            # Trả kết quả ngay từ Redis Cache mà không cần query PostgreSQL
            dummy_db.query.reset_mock()
            hit = payment_saga.check_idempotency(
                db=dummy_db,
                idempotency_key="idem-redis-001",
                account_id=uuid.UUID(uid),
                endpoint="POST:/payments/initiate",
                payload_dict=payload,
            )
            assert hit == (201, resp_body)
            assert dummy_db.query.call_count == 0
            print("[✓] Redis lock:account, lock:tuition (SET NX PX + Lua unlock) và idempotency:{key} fast-path hoạt động chính xác.")


def test_demo_endpoints_toggle_on_api_gateway() -> None:
    """
    Kiểm thử 6: Khi ENABLE_DEMO_ENDPOINTS=False trên API Gateway, cả 3 endpoint demo
    (/accounts/demo-users, /payments/{id}/demo-otp, /system/reset-demo) phải trả 403 DEMO_ENDPOINTS_DISABLED;
    khi bật True, yêu cầu được forward bình thường.
    """
    print("\n" + "=" * 80)
    print("TEST BIÊN 6: CÔNG TẮC ENABLE_DEMO_ENDPOINTS TRÊN API GATEWAY")
    print("=" * 80)

    with _service_import_context("api-gateway"):
        from app import main as gw_main
        from app.config import settings as gw_settings

        client = TestClient(gw_main.app)
        payer_jwt = _make_jwt("11111111-1111-1111-1111-111111111101")
        tx_id = str(uuid.uuid4())

        # 1. Tắt ENABLE_DEMO_ENDPOINTS -> 403 DEMO_ENDPOINTS_DISABLED
        with patch.object(gw_settings, "ENABLE_DEMO_ENDPOINTS", False):
            r_demo_users = client.get("/api/v1/accounts/demo-users")
            r_demo_otp = client.get(
                f"/api/v1/payments/{tx_id}/demo-otp",
                headers={"Authorization": f"Bearer {payer_jwt}"},
            )
            r_reset = client.post("/api/v1/system/reset-demo")

            for label, resp in (
                ("GET /api/v1/accounts/demo-users", r_demo_users),
                ("GET /api/v1/payments/{id}/demo-otp", r_demo_otp),
                ("POST /api/v1/system/reset-demo", r_reset),
            ):
                assert resp.status_code == 403, f"{label} khi tắt phải trả 403, nhận: {resp.status_code}"
                assert resp.json()["error"]["code"] == "DEMO_ENDPOINTS_DISABLED"

        # 2. Bật ENABLE_DEMO_ENDPOINTS -> forward_request được gọi
        mock_forward = AsyncMock(
            side_effect=lambda *args, **kwargs: JSONResponse(status_code=200, content={"ok": True})
        )
        with (
            patch.object(gw_settings, "ENABLE_DEMO_ENDPOINTS", True),
            patch.object(gw_main, "forward_request", mock_forward),
        ):
            r1 = client.get("/api/v1/accounts/demo-users")
            r2 = client.get(
                f"/api/v1/payments/{tx_id}/demo-otp",
                headers={"Authorization": f"Bearer {payer_jwt}"},
            )
            r3 = client.post("/api/v1/system/reset-demo")
            assert (r1.status_code, r2.status_code, r3.status_code) == (200, 200, 200)
            assert mock_forward.await_count == 3

        print("[✓] Công tắc ENABLE_DEMO_ENDPOINTS chặn 403 khi False và forward bình thường khi True.")


def test_payment_history_status_error_idempotency_and_request_errors() -> None:
    """
    Kiểm thử 7:
    - GET /payments/history hỗ trợ cả ?status= (đúng api_spec.md) lẫn ?status_filter=.
    - confirm-otp lưu Idempotency cache cho cả nhánh lỗi (INSUFFICIENT_BALANCE, COMPENSATED, COMPENSATION_FAILED)
      và replay lại đúng status/envelope ở lần gửi trùng.
    - /payments/initiate bắt IntegrityError khi 2 request trùng Idempotency-Key đồng thời và replay cache thay vì 500.
    - /payments/{id}/demo-otp và /payments/reset-demo trả 503 gọn gàng khi httpx.RequestError.
    """
    print("\n" + "=" * 80)
    print("TEST BIÊN 7: ?status= FILTER, ERROR IDEMPOTENCY, RACE INTEGRITY ERROR & 503 REQUEST ERROR")
    print("=" * 80)

    with _service_import_context("payment-service"):
        from app.main import app
        from app.database import get_db
        from app.models import PaymentTransaction
        from app import saga as payment_saga
        from app.routers import payments as payments_router

        payer_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        def _make_tx(tx_status: str, student_id: str) -> PaymentTransaction:
            return PaymentTransaction(
                id=uuid.uuid4(),
                transaction_code=f"TXN-20261108-{uuid.uuid4().hex[:6].upper()}",
                payer_account_id=payer_id,
                payer_full_name="Nguyễn Văn A",
                payer_phone="0901234567",
                payer_email="nguyenvana@tdtu.edu.vn",
                student_id=student_id,
                student_full_name="Sinh Viên Test",
                tuition_bill_id=uuid.uuid4(),
                semester_code="HK1_2026_2027",
                semester_name="Học kỳ 1 - Năm học 2026-2027",
                amount=Decimal("14500000.00"),
                terms_accepted=True,
                status=tx_status,
                idempotency_key=f"init-{uuid.uuid4().hex}",
                correlation_id=str(uuid.uuid4()),
                otp_expires_at=now + timedelta(minutes=5),
                version=1,
                created_at=now,
                updated_at=now,
            )

        # Part A: GET /payments/history?status=COMPLETED & ?status_filter=FAILED
        tx_completed = _make_tx("COMPLETED", "52200001")
        tx_failed = _make_tx("FAILED", "524K0032")
        hist_db = _FakePaymentDbSession(tx_completed, extra_txs=[tx_completed, tx_failed])
        app.dependency_overrides[get_db] = lambda: hist_db
        client = TestClient(app)

        auth_headers = {"Authorization": f"Bearer {_make_jwt(str(payer_id))}"}
        r_status = client.get("/payments/history?status=COMPLETED", headers=auth_headers)
        r_legacy = client.get("/payments/history?status_filter=FAILED", headers=auth_headers)
        app.dependency_overrides.clear()

        assert r_status.status_code == 200
        assert r_status.json()["total"] == 1
        assert r_status.json()["items"][0]["status"] == "COMPLETED"
        assert r_legacy.status_code == 200
        assert r_legacy.json()["total"] == 1
        assert r_legacy.json()["items"][0]["status"] == "FAILED"
        print("[✓] GET /payments/history lọc chính xác theo cả ?status= lẫn ?status_filter=.")

        # Part B: Error branch save_idempotency + replay cho INSUFFICIENT_BALANCE (409),
        # COMPENSATED (409), COMPENSATION_FAILED (502)
        @contextmanager
        def _noop_locks(**kwargs):
            yield

        class _StaticPostClient:
            def __init__(self, status_code, body):
                self._status = status_code
                self._body = body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, **kwargs):
                return httpx.Response(self._status, json=self._body)

        scenarios = [
            (
                "INSUFFICIENT_BALANCE",
                409,
                "INSUFFICIENT_BALANCE",
                httpx.Response(409, json={"error": {"code": "INSUFFICIENT_BALANCE", "message": "Số dư không đủ"}}),
                None,
                None,
            ),
            (
                "TUITION_ALREADY_PAID_COMPENSATED",
                409,
                "TUITION_ALREADY_PAID_COMPENSATED",
                httpx.Response(200, json={"balance_before": 25000000.0, "balance_after": 10500000.0}),
                httpx.Response(409, json={"error": {"code": "TUITION_ALREADY_PAID", "message": "Đã thanh toán"}}),
                lambda *a, **kw: _StaticPostClient(200, {"balance_after": 25000000.0}),
            ),
            (
                "COMPENSATION_FAILED",
                502,
                "COMPENSATION_FAILED",
                httpx.Response(200, json={"balance_before": 25000000.0, "balance_after": 10500000.0}),
                httpx.Response(409, json={"error": {"code": "TUITION_ALREADY_PAID", "message": "Đã thanh toán"}}),
                lambda *a, **kw: _StaticPostClient(500, {"error": {"code": "REFUND_ERROR", "message": "Lỗi DB"}}),
            ),
        ]

        for label, expected_http, expected_code, debit_resp, tuition_resp, refund_client_factory in scenarios:
            tx_case = _make_tx("PENDING_OTP", "52200001")
            case_db = _FakePaymentDbSession(tx_case)
            idem_cache = {}

            def _fake_check(db, idempotency_key, account_id, endpoint, payload_dict):
                return idem_cache.get(idempotency_key)

            def _fake_save(db, idempotency_key, account_id, endpoint, payload_dict, status_code, response_body):
                idem_cache[idempotency_key] = (status_code, response_body)

            app.dependency_overrides[get_db] = lambda d=case_db: d
            idem_key = f"idem-{label}-{uuid.uuid4().hex[:8]}"

            patches = [
                patch.object(payments_router, "acquire_payment_locks", _noop_locks),
                patch.object(payments_router, "check_idempotency", side_effect=_fake_check),
                patch.object(payments_router, "save_idempotency", side_effect=_fake_save),
                patch.object(payments_router, "call_verify_otp", return_value={"verified": True}),
                patch.object(payments_router, "call_debit_account", return_value=debit_resp),
            ]
            if tuition_resp is not None:
                patches.append(patch.object(payments_router, "call_mark_tuition_paid", return_value=tuition_resp))
            if refund_client_factory is not None:
                patches.append(patch.object(payment_saga.httpx, "Client", refund_client_factory))
                patches.append(patch.object(payment_saga.time, "sleep", return_value=None))

            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                if len(patches) == 5:
                    r_first = client.post(
                        f"/payments/{tx_case.id}/confirm-otp",
                        headers={**auth_headers, "Idempotency-Key": idem_key},
                        json={"otp_code": "123456"},
                    )
                    assert idem_key in idem_cache
                    # Gửi lại đúng Idempotency-Key -> replay ngay từ cache dù tx đã đổi trạng thái!
                    r_replay = client.post(
                        f"/payments/{tx_case.id}/confirm-otp",
                        headers={**auth_headers, "Idempotency-Key": idem_key},
                        json={"otp_code": "123456"},
                    )
                else:
                    with patches[5], patches[6], patches[7]:
                        r_first = client.post(
                            f"/payments/{tx_case.id}/confirm-otp",
                            headers={**auth_headers, "Idempotency-Key": idem_key},
                            json={"otp_code": "123456"},
                        )
                        assert idem_key in idem_cache
                        r_replay = client.post(
                            f"/payments/{tx_case.id}/confirm-otp",
                            headers={**auth_headers, "Idempotency-Key": idem_key},
                            json={"otp_code": "123456"},
                        )

            app.dependency_overrides.clear()
            assert r_first.status_code == expected_http
            assert r_first.json()["error"]["code"] == expected_code
            assert r_replay.status_code == expected_http
            assert r_replay.json() == r_first.json()

        print("[✓] Idempotency lưu và replay chuẩn cho cả nhánh INSUFFICIENT_BALANCE (409), COMPENSATED (409) và COMPENSATION_FAILED (502).")

        # Part C: /payments/initiate IntegrityError fallback khi 2 request trùng Idempotency-Key đồng thời
        bill_id = uuid.uuid4()
        race_db = _FakePaymentDbSession(None)
        cached_payload = {"transaction_id": str(uuid.uuid4()), "status": "PENDING_OTP", "from_race_cache": True}
        check_calls = {"n": 0}

        def _race_check(db, idempotency_key, account_id, endpoint, payload_dict):
            check_calls["n"] += 1
            if check_calls["n"] == 1:
                return None
            return (201, cached_payload)

        app.dependency_overrides[get_db] = lambda: race_db
        with (
            patch.object(payments_router, "check_idempotency", side_effect=_race_check),
            patch.object(
                payments_router,
                "call_precheck_account",
                return_value={
                    "full_name": "Nguyễn Văn A",
                    "phone_number": "0901234567",
                    "email": "nguyenvana@tdtu.edu.vn",
                    "available_balance": 25000000,
                },
            ),
            patch.object(
                payments_router,
                "call_precheck_tuition",
                return_value={
                    "student": {"student_id": "52200001", "full_name": "Trần Minh Khoa"},
                    "tuition_bill": {
                        "id": str(bill_id),
                        "semester_code": "HK1_2026_2027",
                        "semester_name": "Học kỳ 1",
                        "amount": 14500000,
                        "status": "UNPAID",
                    },
                },
            ),
            patch.object(
                payments_router,
                "call_generate_otp",
                return_value={"expires_in_seconds": 300},
            ),
            patch.object(
                payments_router,
                "save_idempotency",
                side_effect=IntegrityError("dup", {}, Exception("unique violation")),
            ),
        ):
            r_race = client.post(
                "/payments/initiate",
                headers={**auth_headers, "Idempotency-Key": "concurrent-key-001"},
                json={
                    "student_id": "52200001",
                    "tuition_bill_id": str(bill_id),
                    "amount": 14500000,
                    "terms_accepted": True,
                },
            )
        app.dependency_overrides.clear()
        assert r_race.status_code == 201
        assert r_race.json()["from_race_cache"] is True
        assert race_db.rollback_count >= 1

        # Part D: httpx.RequestError trên /demo-otp và /reset-demo trả HTTP 503 gọn gàng
        tx_demo = _make_tx("PENDING_OTP", "52200001")
        err_db = _FakePaymentDbSession(tx_demo)

        class _BrokenHttpClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url, **kwargs):
                raise httpx.ConnectError("Connection refused")

            def post(self, url, **kwargs):
                raise httpx.ConnectError("Connection refused")

        app.dependency_overrides[get_db] = lambda: err_db
        with (
            patch.object(payments_router, "clear_payment_redis_keys", return_value=None),
            patch.object(payments_router.httpx, "Client", _BrokenHttpClient),
        ):
            r_demo_err = client.get(f"/payments/{tx_demo.id}/demo-otp", headers=auth_headers)
            r_reset_err = client.post("/payments/reset-demo")
        app.dependency_overrides.clear()

        assert r_demo_err.status_code == 503
        assert r_demo_err.json()["error"]["code"] == "NOTIFICATION_SERVICE_UNAVAILABLE"
        assert r_reset_err.status_code == 503
        assert r_reset_err.json()["error"]["code"] == "DOWNSTREAM_SERVICE_UNAVAILABLE"
        print("[✓] IntegrityError fallback trên /payments/initiate và 503 RequestError trên /demo-otp, /reset-demo hoạt động chính xác.")


def run_edge_cases_and_security_tests() -> None:
    test_internal_endpoints_require_token()
    test_mailer_returns_failed_on_smtp_error()
    test_saga_compensation_failed_when_refund_fails()
    test_receipt_email_failure_preserves_completed_status()
    test_payment_redis_locks_and_idempotency()
    test_demo_endpoints_toggle_on_api_gateway()
    test_payment_history_status_error_idempotency_and_request_errors()


if __name__ == "__main__":
    run_edge_cases_and_security_tests()
