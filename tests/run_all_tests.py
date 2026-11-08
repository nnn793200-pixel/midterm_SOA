"""
TRÌNH CHẠY TOÀN BỘ BỘ KIỂM THỬ TỰ ĐỘNG (E2E WORKFLOW + 2 KỊCH BẢN CONCURRENCY)
Chạy lệnh: python tests/run_all_tests.py
Hoặc:      pytest tests/ -v -s
"""

import sys
import httpx

for _s in (sys.stdout, sys.stderr):
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from test_e2e_workflow import run_e2e_workflow_test
from test_concurrency_same_account import run_concurrency_same_account_test
from test_concurrency_same_tuition import run_concurrency_same_tuition_test
from test_edge_cases_and_security import run_edge_cases_and_security_tests

GATEWAY_URL = "http://localhost:8000/api/v1"


def main():
    print("\n" + "#" * 80)
    print("  TDTU iBANKING - BỘ KIỂM THỬ TỰ ĐỘNG (E2E + CONCURRENCY + EDGE CASES & SECURITY)")
    print("#" * 80)

    run_e2e_workflow_test()
    run_concurrency_same_account_test()
    run_concurrency_same_tuition_test()
    run_edge_cases_and_security_tests()

    # Reset lại dữ liệu mẫu sau khi chạy xong test để sẵn sàng Demo trên Web UI
    with httpx.Client(base_url=GATEWAY_URL, timeout=10.0) as client:
        client.post("/system/reset-demo")

    print("\n" + "#" * 80)
    print("  [PASS 100%] TẤT CẢ CÁC BỘ KIỂM THỬ (E2E, CONCURRENCY 1 & 2, EDGE CASES & SECURITY) ĐỀU THÀNH CÔNG!")
    print("  Dữ liệu mẫu đã được khôi phục sẵn sàng cho việc Demo trên trình duyệt.")
    print("#" * 80 + "\n")


if __name__ == "__main__":
    main()
