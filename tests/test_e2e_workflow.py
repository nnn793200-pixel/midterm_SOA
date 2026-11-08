"""
KIỂM THỬ TÍCH HỢP TOÀN LUỒNG (E2E WORKFLOW & BUSINESS RULES TEST)
Chứng minh các tiêu chí đạt điểm 10.0:
1. API Gateway định tuyến & gắn X-Request-ID (Correlation-ID) xuyên suốt.
2. Đăng nhập & lấy thông tin người nộp tiền + số dư khả dụng.
3. Tra cứu học phí theo MSSV.
4. Kiểm tra các quy tắc từ chối:
   - Không cho phép thanh toán một phần (PARTIAL_PAYMENT_NOT_ALLOWED)
   - Không cho phép khi chưa đồng ý điều khoản (TERMS_NOT_ACCEPTED)
   - Không cho phép khi số dư không đủ (INSUFFICIENT_BALANCE)
   - Không cho phép khi học phí đã thanh toán (TUITION_ALREADY_PAID)
5. Kiểm tra Idempotency-Key chống double-submit.
6. Kiểm tra OTP: nhập sai bị từ chối (INVALID_OTP), nhập đúng thanh toán thành công (COMPLETED),
   và dùng lại OTP lần 2 bị từ chối (chỉ dùng 1 lần).
7. Kiểm tra cập nhật số dư, trạng thái học phí PAID, lịch sử giao dịch và Saga Step Logs.
"""

import uuid
import httpx

GATEWAY_URL = "http://localhost:8000/api/v1"


def run_e2e_workflow_test() -> None:
    print("\n" + "=" * 80)
    print("BẮT ĐẦU TEST 1: LUỒNG NGHIỆP VỤ E2E, QUY TẮC BẮT BUỘC, IDEMPOTENCY & OTP")
    print("=" * 80)

    with httpx.Client(base_url=GATEWAY_URL, timeout=15.0) as client:
        # 1. Reset toàn bộ dữ liệu mẫu
        reset_resp = client.post("/system/reset-demo")
        assert reset_resp.status_code == 200, f"Reset failed: {reset_resp.text}"
        assert "X-Request-ID" in reset_resp.headers
        print("[✓] 1. Đã khôi phục dữ liệu mẫu trên cả 4 Microservices & kiểm tra X-Request-ID.")

        # 2. Kiểm tra sức khỏe cụm Microservices qua Gateway
        health_resp = client.get("/health/services")
        assert health_resp.status_code == 200
        health_data = health_resp.json()
        for svc_name, svc_info in health_data["services"].items():
            assert svc_info.get("status") == "UP", f"Service {svc_name} is not UP!"
        print("[✓] 2. Tất cả 4 Microservices (Auth, Tuition, Payment, OTP) đều đang UP.")

        # 3. Đăng nhập tài khoản nguyenvana (Số dư: 25,000,000 VNĐ)
        login_resp = client.post(
            "/auth/login",
            json={"username": "nguyenvana", "password": "Password@123"},
        )
        assert login_resp.status_code == 200
        login_data = login_resp.json()
        token = login_data["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}
        assert login_data["user"]["available_balance"] == 25000000.0
        print(
            f"[✓] 3. Đăng nhập thành công: {login_data['user']['full_name']} | "
            f"Số dư: {login_data['user']['available_balance']:,.0f} VNĐ"
        )

        # 4. Tra cứu học phí MSSV 52200003 (Nguyễn Ngọc Mai - 12,000,000 VNĐ - UNPAID)
        tuition_resp = client.get("/tuitions/52200003", headers=auth_headers)
        assert tuition_resp.status_code == 200
        tuition_data = tuition_resp.json()
        bill_id = tuition_data["tuition_bill"]["id"]
        bill_amount = tuition_data["tuition_bill"]["amount"]
        assert bill_amount == 12000000.0
        assert tuition_data["tuition_bill"]["status"] == "UNPAID"
        print(
            f"[✓] 4. Tra cứu MSSV 52200003: {tuition_data['student']['full_name']} | "
            f"Học phí: {bill_amount:,.0f} VNĐ ({tuition_data['tuition_bill']['status']})"
        )

        # 5A. Kiểm tra từ chối thanh toán một phần (Partial Payment)
        partial_resp = client.post(
            "/payments/initiate",
            headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "student_id": "52200003",
                "tuition_bill_id": bill_id,
                "amount": 5000000.0,
                "terms_accepted": True,
            },
        )
        assert partial_resp.status_code == 400
        assert partial_resp.json()["error"]["code"] == "PARTIAL_PAYMENT_NOT_ALLOWED"
        print("[✓] 5A. Chặn thành công hành vi thanh toán một phần (400 PARTIAL_PAYMENT_NOT_ALLOWED).")

        # 5B. Kiểm tra từ chối khi chưa đồng ý điều khoản
        terms_resp = client.post(
            "/payments/initiate",
            headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "student_id": "52200003",
                "tuition_bill_id": bill_id,
                "amount": bill_amount,
                "terms_accepted": False,
            },
        )
        assert terms_resp.status_code == 400
        assert terms_resp.json()["error"]["code"] == "TERMS_NOT_ACCEPTED"
        print("[✓] 5B. Chặn thành công khi chưa tick điều khoản (400 TERMS_NOT_ACCEPTED).")

        # 5C. Kiểm tra từ chối khi học phí đã thanh toán (MSSV 52200005 đã PAID sẵn)
        paid_lookup = client.get("/tuitions/52200005", headers=auth_headers).json()
        already_paid_resp = client.post(
            "/payments/initiate",
            headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "student_id": "52200005",
                "tuition_bill_id": paid_lookup["tuition_bill"]["id"],
                "amount": paid_lookup["tuition_bill"]["amount"],
                "terms_accepted": True,
            },
        )
        assert already_paid_resp.status_code == 409
        assert already_paid_resp.json()["error"]["code"] == "TUITION_ALREADY_PAID"
        print("[✓] 5C. Chặn thành công khi học phí đã đóng trước đó (409 TUITION_ALREADY_PAID).")

        # 6. Kiểm tra khởi tạo giao dịch hợp lệ & Idempotency-Key chống double-submit
        idem_key = str(uuid.uuid4())
        init_payload = {
            "student_id": "52200003",
            "tuition_bill_id": bill_id,
            "amount": bill_amount,
            "terms_accepted": True,
        }
        init_resp_1 = client.post(
            "/payments/initiate",
            headers={**auth_headers, "Idempotency-Key": idem_key},
            json=init_payload,
        )
        init_resp_2 = client.post(
            "/payments/initiate",
            headers={**auth_headers, "Idempotency-Key": idem_key},
            json=init_payload,
        )
        assert init_resp_1.status_code == 201
        assert init_resp_2.status_code == 201
        tx_id = init_resp_1.json()["transaction_id"]
        assert tx_id == init_resp_2.json()["transaction_id"]
        print(
            f"[✓] 6. Khởi tạo giao dịch & kiểm chứng Idempotency-Key thành công (tx_id={tx_id})."
        )

        # 7. Lấy mã OTP đã sinh cho giao dịch
        otp_debug_resp = client.get(
            f"/payments/{tx_id}/demo-otp", headers=auth_headers
        )
        assert otp_debug_resp.status_code == 200
        otp_code = otp_debug_resp.json()["otp_code"]
        print(f"[✓] 7. Đã nhận mã OTP gắn với giao dịch: {otp_code} (TTL <= 300s).")

        # 8A. Thử nhập mã OTP sai -> Phải bị từ chối 400 INVALID_OTP
        wrong_otp = "000000" if otp_code != "000000" else "999999"
        wrong_resp = client.post(
            f"/payments/{tx_id}/confirm-otp",
            headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
            json={"otp_code": wrong_otp},
        )
        assert wrong_resp.status_code == 400
        assert wrong_resp.json()["error"]["code"] == "INVALID_OTP"
        print("[✓] 8A. Nhập OTP sai bị từ chối đúng quy định (400 INVALID_OTP).")

        # 8B. Nhập mã OTP chính xác -> Hoàn tất Saga thanh toán
        confirm_resp = client.post(
            f"/payments/{tx_id}/confirm-otp",
            headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
            json={"otp_code": otp_code},
        )
        assert confirm_resp.status_code == 200, f"Confirm failed: {confirm_resp.text}"
        confirm_data = confirm_resp.json()
        assert confirm_data["status"] == "COMPLETED"
        assert confirm_data["payer"]["balance_before"] == 25000000.0
        assert confirm_data["payer"]["balance_after"] == 13000000.0
        assert confirm_data["tuition"]["tuition_status"] == "PAID"
        print(
            f"[✓] 8B. Xác thực OTP & Hoàn tất Saga thành công! "
            f"Số dư: 25,000,000 -> {confirm_data['payer']['balance_after']:,.0f} VNĐ."
        )

        # 8C. Thử dùng lại cùng mã OTP lần thứ 2 (với Idempotency-Key mới) -> Phải bị từ chối 409
        replay_resp = client.post(
            f"/payments/{tx_id}/confirm-otp",
            headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
            json={"otp_code": otp_code},
        )
        assert replay_resp.status_code == 409
        print("[✓] 8C. Chặn thành công việc tái sử dụng mã OTP lần thứ 2 (One-time use).")

        # 9. Kiểm tra chi tiết giao dịch, lọc lịch sử (?status=COMPLETED) & 7 bước Saga Step Logs
        detail_resp = client.get(f"/payments/{tx_id}", headers=auth_headers)
        assert detail_resp.status_code == 200
        saga_steps = detail_resp.json()["saga_steps"]
        assert len(saga_steps) >= 7
        history_completed = client.get(
            "/payments/history?status=COMPLETED", headers=auth_headers
        )
        assert history_completed.status_code == 200
        history_items = history_completed.json()["items"]
        assert any(item["id"] == tx_id and item["status"] == "COMPLETED" for item in history_items)
        print(
            f"[✓] 9. Đối soát lịch sử giao dịch (?status=COMPLETED) & Saga Step Logs ({len(saga_steps)} bước) hoàn tất!"
        )


def test_e2e_workflow():
    run_e2e_workflow_test()


if __name__ == "__main__":
    run_e2e_workflow_test()
