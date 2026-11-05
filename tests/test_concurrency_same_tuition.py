"""
KIỂM THỬ TÌNH HUỐNG CONCURRENCY 2:
NHIỀU TÀI KHOẢN CÙNG THANH TOÁN MỘT KHOẢN HỌC PHÍ (CHỐNG ĐÓNG TRÙNG + SAGA COMPENSATING REFUND)

Kịch bản:
- Hai người dùng độc lập:
  + Tài khoản A (`nguyenvana` - Số dư: 25,000,000 VNĐ)
  + Tài khoản B (`tranvanb` - Số dư: 30,000,000 VNĐ)
- Cả hai cùng tra cứu và khởi tạo giao dịch đóng học phí cho CÙNG MỘT SINH VIÊN:
  + MSSV `52200001` (Trần Minh Khoa - Số tiền: 14,500,000 VNĐ - Đang `UNPAID`).
- Cả hai đều vượt qua bước Pre-check và nhận 2 mã OTP hợp lệ (`OTP_A != OTP_B`).
- Cả hai cùng nhấn xác nhận OTP tại CÙNG MỘT THỜI ĐIỂM (đồng bộ bằng `threading.Barrier(2)`).
- Kỳ vọng bắt buộc:
  1. Cả hai đều đủ tiền nên đều đi qua bước trừ tiền trên tài khoản cá nhân của mình.
  2. Tại `tuition-service`, khóa Pessimistic (`SELECT ... FOR UPDATE`) và kiểm tra `status == 'UNPAID'`
     chỉ cho phép DUY NHẤT 1 giao dịch cập nhật học phí thành `PAID` (`200 OK`).
  3. Giao dịch đến sau 1ms nhận `409 Conflict (TUITION_ALREADY_PAID)`.
  4. Ngay lập tức, `payment-service` (Saga Orchestrator) kích hoạt **Compensating Transaction**
     (`POST /internal/accounts/refund`) hoàn trả 100% số tiền (14,500,000 VNĐ) về lại tài khoản
     của người đến sau và đánh dấu giao dịch là `COMPENSATED`.
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
import httpx

GATEWAY_URL = "http://localhost:8000/api/v1"


def run_concurrency_same_tuition_test() -> None:
    print("\n" + "=" * 80)
    print("BẮT ĐẦU TEST 3 (CONCURRENCY 2): NHIỀU TÀI KHOẢN CÙNG ĐÓNG 1 MSSV & SAGA REFUND")
    print("=" * 80)

    with httpx.Client(base_url=GATEWAY_URL, timeout=15.0) as client:
        # 1. Reset dữ liệu mẫu
        client.post("/system/reset-demo")

        # 2. Đăng nhập 2 tài khoản độc lập: nguyenvana (25M) và tranvanb (30M)
        login_a = client.post(
            "/auth/login",
            json={"username": "nguyenvana", "password": "Password@123"},
        ).json()
        login_b = client.post(
            "/auth/login",
            json={"username": "tranvanb", "password": "Password@123"},
        ).json()

        headers_a = {"Authorization": f"Bearer {login_a['access_token']}"}
        headers_b = {"Authorization": f"Bearer {login_b['access_token']}"}

        print(
            f"[•] Người nộp A: {login_a['user']['full_name']} | Số dư: {login_a['user']['available_balance']:,.0f} VNĐ\n"
            f"[•] Người nộp B: {login_b['user']['full_name']} | Số dư: {login_b['user']['available_balance']:,.0f} VNĐ"
        )

        # 3. Cả A và B cùng tra cứu MSSV 52200001 (14,500,000 VNĐ - UNPAID)
        tuition_info = client.get("/tuitions/52200001", headers=headers_a).json()
        bill_id = tuition_info["tuition_bill"]["id"]
        bill_amount = tuition_info["tuition_bill"]["amount"]

        # 4. Cả A và B cùng khởi tạo giao dịch cho MSSV 52200001
        init_a = client.post(
            "/payments/initiate",
            headers={**headers_a, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "student_id": "52200001",
                "tuition_bill_id": bill_id,
                "amount": bill_amount,
                "terms_accepted": True,
            },
        )
        init_b = client.post(
            "/payments/initiate",
            headers={**headers_b, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "student_id": "52200001",
                "tuition_bill_id": bill_id,
                "amount": bill_amount,
                "terms_accepted": True,
            },
        )
        assert init_a.status_code == 201
        assert init_b.status_code == 201

        tx_a_id = init_a.json()["transaction_id"]
        tx_b_id = init_b.json()["transaction_id"]

        otp_a = client.get(
            f"/payments/{tx_a_id}/demo-otp", headers=headers_a
        ).json()["otp_code"]
        otp_b = client.get(
            f"/payments/{tx_b_id}/demo-otp", headers=headers_b
        ).json()["otp_code"]

        assert otp_a != otp_b, "Hai mã OTP đang active không được phép trùng nhau!"
        print(
            f"[✓] Cả 2 tài khoản đã khởi tạo giao dịch cho cùng MSSV 52200001 (14,500,000 VNĐ):\n"
            f"    - Tài khoản A (nguyenvana): tx_id={tx_a_id} | OTP={otp_a}\n"
            f"    - Tài khoản B (tranvanb)  : tx_id={tx_b_id} | OTP={otp_b}"
        )

        # 5. Bắn đồng thời confirm-otp từ cả 2 tài khoản tại cùng 1 thời điểm bằng Barrier(2)
        barrier = threading.Barrier(2)

        def confirm_worker(tx_id: str, otp_code: str, user_headers: dict, label: str):
            with httpx.Client(base_url=GATEWAY_URL, timeout=15.0) as worker_client:
                barrier.wait()
                resp = worker_client.post(
                    f"/payments/{tx_id}/confirm-otp",
                    headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
                    json={"otp_code": otp_code},
                )
                return label, resp.status_code, resp.json()

        with ThreadPoolExecutor(max_workers=2) as executor:
            fa = executor.submit(confirm_worker, tx_a_id, otp_a, headers_a, "User_A (nguyenvana)")
            fb = executor.submit(confirm_worker, tx_b_id, otp_b, headers_b, "User_B (tranvanb)")
            results = [fa.result(), fb.result()]

        for label, status_code, body in results:
            print(f"    -> Kết quả {label}: HTTP {status_code} | {body}")

        status_codes = sorted([r[1] for r in results])
        assert status_codes == [200, 409], (
            f"Kỳ vọng 1 giao dịch 200 OK và 1 giao dịch 409 Conflict (Compensated), nhưng nhận được: {status_codes}"
        )

        # Kiểm tra giao dịch bị 409 phải được hoàn tiền tự động (TUITION_ALREADY_PAID_COMPENSATED)
        comp_result = [r for r in results if r[1] == 409][0]
        assert (
            comp_result[2]["error"]["code"] == "TUITION_ALREADY_PAID_COMPENSATED"
        )
        assert comp_result[2]["error"]["details"]["status"] == "COMPENSATED"

        # 6. Kiểm tra trạng thái học phí của MSSV 52200001 và số dư của cả 2 tài khoản
        tuition_after = client.get("/tuitions/52200001", headers=headers_a).json()
        assert tuition_after["tuition_bill"]["status"] == "PAID"

        acc_a_after = client.get("/accounts/me", headers=headers_a).json()
        acc_b_after = client.get("/accounts/me", headers=headers_b).json()

        print(
            f"[✓] Số dư sau giao dịch:\n"
            f"    - nguyenvana (Ban đầu 25,000,000): {acc_a_after['available_balance']:,.0f} VNĐ\n"
            f"    - tranvanb   (Ban đầu 30,000,000): {acc_b_after['available_balance']:,.0f} VNĐ"
        )

        # Tổng số tiền bị trừ trên toàn hệ thống phải đúng bằng 1 lần học phí (14,500,000 VNĐ)
        total_before = 25000000.0 + 30000000.0
        total_after = acc_a_after["available_balance"] + acc_b_after["available_balance"]
        assert total_before - total_after == 14500000.0, (
            "Tổng số tiền trừ trên cả 2 tài khoản phải đúng bằng 1 lần học phí (14,500,000 VNĐ)!"
        )
        print(
            "[✓] KẾT LUẬN CONCURRENCY 2: Khoản học phí MSSV 52200001 chỉ được thanh toán ĐÚNG 1 LẦN.\n"
            "    Giao dịch đến sau đã được Saga Orchestrator hoàn tiền (COMPENSATION_REFUND) 100%!"
        )


def test_concurrency_same_tuition():
    run_concurrency_same_tuition_test()


if __name__ == "__main__":
    run_concurrency_same_tuition_test()
