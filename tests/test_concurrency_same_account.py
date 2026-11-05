"""
KIỂM THỬ TÌNH HUỐNG CONCURRENCY 1:
NHIỀU GIAO DỊCH ĐỒNG THỜI TRÊN CÙNG MỘT TÀI KHOẢN (CHỐNG CHI TIÊU VƯỢT SỐ DƯ)

Kịch bản:
- Tài khoản `nguyenvana` có số dư khả dụng = 25,000,000 VNĐ.
- Người dùng mở 2 phiên giao dịch cùng lúc để đóng học phí cho:
  + Giao dịch 1: MSSV 52200001 (Số tiền: 14,500,000 VNĐ)
  + Giao dịch 2: MSSV 52200002 (Số tiền: 14,500,000 VNĐ)
- Vì bước khởi tạo chỉ thực hiện Pre-check đọc dữ liệu (không giữ DB Row Lock trong 5 phút chờ OTP),
  cả 2 giao dịch đều được tạo ở trạng thái PENDING_OTP và nhận 2 mã OTP khác nhau (OTP_1 != OTP_2).
- Tại thời điểm xác nhận, cả 2 luồng (threads) cùng bắn `POST /confirm-otp` đồng thời ở cùng 1 mili-giây
  (đồng bộ bằng `threading.Barrier(2)`).
- Tổng 2 khoản là 29,000,000 VNĐ > 25,000,000 VNĐ.
- Kỳ vọng bắt buộc:
  1. Khóa Pessimistic (`SELECT ... FOR UPDATE`) trên bảng `users_accounts` tuần tự hóa 2 giao dịch.
  2. Chỉ DUY NHẤT 1 giao dịch thành công (`200 OK`, `COMPLETED`).
  3. Giao dịch còn lại bị từ chối tức khắc (`409 Conflict`, `INSUFFICIENT_BALANCE`).
  4. Số dư cuối cùng của `nguyenvana` là 10,500,000 VNĐ (Tuyệt đối không bị âm tiền!).
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
import httpx

GATEWAY_URL = "http://localhost:8000/api/v1"


def run_concurrency_same_account_test() -> None:
    print("\n" + "=" * 80)
    print("BẮT ĐẦU TEST 2 (CONCURRENCY 1): NHIỀU GIAO DỊCH ĐỒNG THỜI TRÊN CÙNG 1 TÀI KHOẢN")
    print("=" * 80)

    with httpx.Client(base_url=GATEWAY_URL, timeout=15.0) as client:
        # 1. Reset dữ liệu mẫu
        client.post("/system/reset-demo")

        # 2. Đăng nhập tài khoản nguyenvana (Số dư = 25,000,000 VNĐ)
        login_resp = client.post(
            "/auth/login",
            json={"username": "nguyenvana", "password": "Password@123"},
        ).json()
        token = login_resp["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        initial_balance = login_resp["user"]["available_balance"]
        print(
            f"[•] Tài khoản: nguyenvana | Số dư ban đầu: {initial_balance:,.0f} VNĐ"
        )

        # 3. Tra cứu 2 khoản học phí của 2 MSSV khác nhau (mỗi khoản 14,500,000 VNĐ)
        t1_info = client.get("/tuitions/52200001", headers=headers).json()
        t2_info = client.get("/tuitions/52200002", headers=headers).json()

        # 4. Khởi tạo đồng thời 2 giao dịch (Cả 2 đều vượt qua Pre-check 14.5M <= 25M)
        tx1_init = client.post(
            "/payments/initiate",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "student_id": "52200001",
                "tuition_bill_id": t1_info["tuition_bill"]["id"],
                "amount": t1_info["tuition_bill"]["amount"],
                "terms_accepted": True,
            },
        )
        tx2_init = client.post(
            "/payments/initiate",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "student_id": "52200002",
                "tuition_bill_id": t2_info["tuition_bill"]["id"],
                "amount": t2_info["tuition_bill"]["amount"],
                "terms_accepted": True,
            },
        )
        assert tx1_init.status_code == 201
        assert tx2_init.status_code == 201

        tx1_id = tx1_init.json()["transaction_id"]
        tx2_id = tx2_init.json()["transaction_id"]

        otp1 = client.get(
            f"/payments/{tx1_id}/demo-otp", headers=headers
        ).json()["otp_code"]
        otp2 = client.get(
            f"/payments/{tx2_id}/demo-otp", headers=headers
        ).json()["otp_code"]

        # Chứng minh 2 OTP đang active không bao giờ trùng nhau
        assert otp1 != otp2, "Hai mã OTP đang active không được phép trùng nhau!"
        print(
            f"[✓] Đã khởi tạo 2 giao dịch chờ OTP trên cùng tài khoản:\n"
            f"    - GD 1 (MSSV 52200001 - 14,500,000 VNĐ): tx_id={tx1_id} | OTP={otp1}\n"
            f"    - GD 2 (MSSV 52200002 - 14,500,000 VNĐ): tx_id={tx2_id} | OTP={otp2}"
        )

        # 5. Bắn đồng thời 2 request confirm-otp tại cùng 1 thời điểm bằng Barrier(2)
        barrier = threading.Barrier(2)

        def confirm_worker(tx_id: str, otp_code: str, label: str):
            with httpx.Client(base_url=GATEWAY_URL, timeout=15.0) as worker_client:
                barrier.wait()  # Đợi cả 2 luồng sẵn sàng rồi bắn cùng lúc
                resp = worker_client.post(
                    f"/payments/{tx_id}/confirm-otp",
                    headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
                    json={"otp_code": otp_code},
                )
                return label, resp.status_code, resp.json()

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(confirm_worker, tx1_id, otp1, "GD_1 (52200001)")
            f2 = executor.submit(confirm_worker, tx2_id, otp2, "GD_2 (52200002)")
            results = [f1.result(), f2.result()]

        for label, status_code, body in results:
            print(f"    -> Kết quả {label}: HTTP {status_code} | {body}")

        status_codes = sorted([r[1] for r in results])
        assert status_codes == [200, 409], (
            f"Kỳ vọng 1 giao dịch 200 OK và 1 giao dịch 409 Conflict, nhưng nhận được: {status_codes}"
        )

        # Kiểm tra mã lỗi của giao dịch bị từ chối phải là INSUFFICIENT_BALANCE
        failed_result = [r for r in results if r[1] == 409][0]
        assert failed_result[2]["error"]["code"] == "INSUFFICIENT_BALANCE"

        # 6. Kiểm tra số dư cuối cùng của tài khoản nguyenvana
        me_after = client.get("/accounts/me", headers=headers).json()
        final_balance = me_after["available_balance"]
        assert final_balance == 10500000.0, (
            f"Số dư cuối cùng phải là 10,500,000 VNĐ, nhưng thực tế là {final_balance}"
        )
        print(
            f"[✓] KẾT LUẬN CONCURRENCY 1: Chính xác 1 GD thành công (200), 1 GD bị chặn (409 INSUFFICIENT_BALANCE).\n"
            f"    Số dư cuối cùng: {final_balance:,.0f} VNĐ (Đảm bảo tuyệt đối không chi tiêu vượt số dư!)."
        )


def test_concurrency_same_account():
    run_concurrency_same_account_test()


if __name__ == "__main__":
    run_concurrency_same_account_test()
