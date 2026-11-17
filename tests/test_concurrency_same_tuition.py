"""
KIỂM THỬ TÌNH HUỐNG CONCURRENCY 2: HAI NGƯỜI CÙNG THANH TOÁN CHO 1 SINH VIÊN (HÀNG ĐỢI CHỜ)

Kịch bản (MSSV 524K0033 - Huỳnh Trung Tín, học phí 15,000,000 VNĐ):
- User A (phuhuynh1) bấm thanh toán trước -> nhận OTP, giữ khoá `checkout_lock:524K0033`.
- User B (phuhuynh2) bấm thanh toán sau -> API trả `202 WAITING_FOR_OTHER_PAYMENT`, KHÔNG gửi OTP.
- `GET /payments/tuition-status/524K0033` báo `LOCKED` cho B.

Trường hợp 1: User A hủy khung nhập OTP (`POST /payments/{id}/cancel`)
  -> khoá được giải phóng (`AVAILABLE`) -> B khởi tạo lại thành công (201), nhận OTP, thanh toán thành công.
Trường hợp 2: User A thanh toán THÀNH CÔNG
  -> trạng thái `PAID` -> B khởi tạo lại bị chặn (409 TUITION_ALREADY_PAID) và tổng tiền chỉ bị trừ đúng 1 lần.
"""

import uuid
import httpx

GATEWAY_URL = "http://localhost:8000/api/v1"
MSSV = "524K0033"


def _login(client: httpx.Client, username: str) -> dict:
    resp = client.post(
        "/auth/login", json={"username": username, "password": "Password@123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _initiate(client: httpx.Client, headers: dict, bill: dict) -> httpx.Response:
    return client.post(
        "/payments/initiate",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "student_id": MSSV,
            "tuition_bill_id": bill["id"],
            "amount": bill["amount"],
            "terms_accepted": True,
        },
    )


def _otp(client: httpx.Client, headers: dict, tx_id: str) -> str:
    return client.get(f"/payments/{tx_id}/demo-otp", headers=headers).json()["otp_code"]


def run_concurrency_same_tuition_test() -> None:
    print("\n" + "=" * 80)
    print("BẮT ĐẦU TEST 3 (CONCURRENCY 2): 2 NGƯỜI CÙNG ĐÓNG 1 MSSV -> MÀN HÌNH CHỜ (WAITING)")
    print("=" * 80)

    with httpx.Client(base_url=GATEWAY_URL, timeout=30.0) as client:
        client.post("/system/reset-demo")
        headers_a = _login(client, "phuhuynh1")
        headers_b = _login(client, "phuhuynh2")
        bill = client.get(f"/tuitions/{MSSV}", headers=headers_a).json()["tuition_bill"]

        # ---------- Trường hợp 1: User A hủy -> User B nhận OTP ----------
        init_a = _initiate(client, headers_a, bill)
        assert init_a.status_code == 201, init_a.text
        tx_a = init_a.json()["transaction_id"]

        init_b = _initiate(client, headers_b, bill)
        assert init_b.status_code == 202, init_b.text
        assert init_b.json()["status"] == "WAITING_FOR_OTHER_PAYMENT"
        assert init_b.json()["student_id"] == MSSV
        status_b = client.get(f"/payments/tuition-status/{MSSV}", headers=headers_b).json()
        assert status_b["state"] == "LOCKED" and status_b["locked_by_me"] is False
        print("[✓] 1a. User A giữ khoá; User B nhận 202 WAITING_FOR_OTHER_PAYMENT (chưa gửi OTP), MSSV = LOCKED.")

        # User B không thể xác nhận đè lên giao dịch của A
        cancel_resp = client.post(f"/payments/{tx_a}/cancel", headers=headers_a)
        assert cancel_resp.status_code == 200 and cancel_resp.json()["cancelled"] is True
        status_after = client.get(f"/payments/tuition-status/{MSSV}", headers=headers_b).json()
        assert status_after["state"] == "AVAILABLE"
        print("[✓] 1b. User A đóng khung OTP (cancel) -> khoá giải phóng ngay, MSSV = AVAILABLE.")

        init_b2 = _initiate(client, headers_b, bill)
        assert init_b2.status_code == 201, init_b2.text
        tx_b = init_b2.json()["transaction_id"]
        confirm_b = client.post(
            f"/payments/{tx_b}/confirm-otp",
            headers={**headers_b, "Idempotency-Key": str(uuid.uuid4())},
            json={"otp_code": _otp(client, headers_b, tx_b)},
        )
        assert confirm_b.status_code == 200, confirm_b.text
        assert confirm_b.json()["status"] == "COMPLETED"
        print("[✓] 1c. User B tự khởi tạo lại, nhận OTP và thanh toán thành công.")

        # ---------- Trường hợp 2: User A thanh toán thành công -> User B thấy PAID ----------
        client.post("/system/reset-demo")
        headers_a = _login(client, "phuhuynh1")
        headers_b = _login(client, "phuhuynh2")
        bill = client.get(f"/tuitions/{MSSV}", headers=headers_a).json()["tuition_bill"]

        init_a = _initiate(client, headers_a, bill)
        assert init_a.status_code == 201, init_a.text
        tx_a = init_a.json()["transaction_id"]
        assert _initiate(client, headers_b, bill).status_code == 202

        confirm_a = client.post(
            f"/payments/{tx_a}/confirm-otp",
            headers={**headers_a, "Idempotency-Key": str(uuid.uuid4())},
            json={"otp_code": _otp(client, headers_a, tx_a)},
        )
        assert confirm_a.status_code == 200, confirm_a.text

        status_paid = client.get(f"/payments/tuition-status/{MSSV}", headers=headers_b).json()
        assert status_paid["state"] == "PAID" and status_paid["tuition_status"] == "PAID"
        blocked = _initiate(client, headers_b, bill)
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "TUITION_ALREADY_PAID"

        acc_a = client.get("/accounts/me", headers=headers_a).json()
        acc_b = client.get("/accounts/me", headers=headers_b).json()
        assert acc_a["available_balance"] + acc_b["available_balance"] == 55000000.0 - 15000000.0
        print("[✓] 2.  User A thanh toán thành công -> MSSV = PAID; User B bị chặn 409, tổng tiền chỉ bị trừ 1 lần.")


def test_concurrency_same_tuition():
    run_concurrency_same_tuition_test()


if __name__ == "__main__":
    run_concurrency_same_tuition_test()
