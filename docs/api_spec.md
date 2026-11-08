# ĐẶC TẢ KIẾN TRÚC MICROSERVICES & THIẾT KẾ REST API
**Dự án Giữa kỳ:** Phân hệ đóng học phí của ứng dụng iBanking (TDTU)  
**Môn học:** Kiến Trúc Hướng Dịch Vụ (504070) – HK1/2026-2027  
**Trường Đại học Tôn Đức Thắng – Khoa Công nghệ Thông tin**

### Thông tin Thành viên Nhóm Thực hiện:
| STT | Họ và tên Sinh viên | Mã số Sinh viên (MSSV) | Email Sinh viên |
| :---: | :--- | :---: | :--- |
| 1 | **Trần Minh Nghĩa** | `524K0032` | `524k0032@student.tdtu.edu.vn` |
| 2 | **Huỳnh Trung Tín** | `524K0033` | `524k0033@student.tdtu.edu.vn` |
| 3 | **Phan Nguyễn Thảo Như** | `524V0007` | `524v0007@student.tdtu.edu.vn` |

---

## PHẦN 1: GIẢI THÍCH KIẾN TRÚC MICROSERVICES & QUYẾT ĐỊNH THIẾT KẾ

### 1.1. Phân rã Dịch vụ & Trách nhiệm (Service Decomposition & Data Ownership)
Hệ thống tuân thủ nghiêm ngặt mẫu thiết kế **Database-per-Service** (mỗi microservice sở hữu độc quyền phân vùng cơ sở dữ liệu riêng, không truy cập chéo bảng ở tầng SQL):

| STT | Tên Service | Cổng (Port) | Data Store Sở hữu | Trách nhiệm Nghiệp vụ Chính |
| :--- | :--- | :---: | :--- | :--- |
| 1 | **`api-gateway`** | `8000` *(Public)* | Stateless | Điểm truy cập duy nhất (Single Entry Point) từ Frontend qua `public_network`; kiểm soát `CORS_ORIGINS`; cấp phát và truyền dẫn `X-Request-ID` (`Correlation-ID`); xác thực JWT tập trung; đính kèm `X-Internal-Service-Token` và điều hướng qua `internal_network`. |
| 2 | **`auth-account-service`** | `8001` *(Expose)* | PostgreSQL (`account_db`) | Xác thực `username`/`password` và phát hành JWT; cung cấp thông tin người nộp tiền; thực thi **trừ tiền nguyên tử (`SELECT ... FOR UPDATE`)** và **hoàn tiền bù trừ (Saga Refund)**; ghi sổ cái `account_ledger_entries`; bảo vệ `/internal/*` bằng `X-Internal-Service-Token`. |
| 3 | **`tuition-service`** | `8002` *(Expose)* | PostgreSQL (`tuition_db`) | Quản lý danh mục sinh viên TDTU (`students`) và công nợ học phí (`tuition_bills`); tra cứu học phí theo `MSSV`; thực thi **gạch nợ nguyên tử (`SELECT ... FOR UPDATE` + kiểm tra `status == 'UNPAID'`)**; bảo vệ `/internal/*` bằng `X-Internal-Service-Token`. |
| 4 | **`payment-service`** | `8003` *(Expose)* | PostgreSQL (`payment_db`) + Redis (`6379`) | **Saga Orchestrator**; Pre-check không giữ Row Lock; kiểm soát `Idempotency-Key` trên **Redis cache (`idempotency:{key}`) + PostgreSQL (`idempotency_records`)**; bọc bước `confirm-otp` bằng **Redis Distributed Lock (`lock:account:{user_id}`, `lock:tuition:{student_id}`)**; điều phối Saga, retry refund tối đa 3 lần (`COMPENSATED` / `COMPENSATION_FAILED`), và commit `COMPLETED` ngay trước khi gửi email biên lai. |
| 5 | **`notification-otp-service`** | `8004` *(Expose)* | Redis (`6379`) + PostgreSQL (`notification_db`) | Sinh OTP 6 chữ số gắn với `transaction_id`, chống trùng qua Redis `SET NX` (`otp:active_code:{code}`), TTL 300s (`otp:tx:{tx_id}`), xác thực & tiêu hủy 1 lần bằng **Redis Lua Script**; lưu `otp_tokens` & `notification_logs` (ghi nhận trung thực `SENT` hoặc `FAILED` khi SMTP lỗi); bảo vệ `/internal/*` bằng `X-Internal-Service-Token`. |

---

### 1.2. Các Quyết định Thiết kế Cốt lõi (Architectural Decisions)

#### Quyết định 1: Tại sao KHÔNG giữ Database Row Lock trong 5 phút chờ nhập OTP?
- **Vấn đề:** Nếu hệ thống thực hiện `SELECT ... FOR UPDATE` trên bảng `users_accounts` hoặc `tuition_bills` ngay khi người dùng bấm *"Xác nhận giao dịch"* và giữ khóa suốt 5 phút chờ người dùng mở email lấy OTP, kết nối DB sẽ bị treo (connection pool exhaustion) và gây khóa chết (deadlock/starvation) nếu người dùng đóng trình duyệt mà không nhập OTP.
- **Giải pháp chuẩn Production:**
  1. **Tại bước Khởi tạo (`POST /api/v1/payments/initiate`):** Chỉ thực hiện **Pre-check đọc dữ liệu (Read-only validation)**: kiểm tra khoản học phí tồn tại, đang ở trạng thái `UNPAID`, và `available_balance >= amount`. Sau đó tạo bản ghi giao dịch `PENDING_OTP` và gửi OTP. **Tuyệt đối không giữ khóa dòng DB.**
  2. **Tại bước Xác thực OTP (`POST /api/v1/payments/{id}/confirm-otp`):** Ngay khoảnh khắc mã OTP được xác thực hợp lệ, `payment-service` mới kích hoạt luồng Saga khóa dòng tức thời (`SELECT ... FOR UPDATE`) trong vài mili-giây để kiểm tra lại số dư + trạng thái học phí, trừ tiền và gạch nợ.

#### Quyết định 2: Giải quyết Tình huống Concurrency 1 (Nhiều giao dịch đồng thời trên cùng 1 tài khoản)
- **Kịch bản:** Tài khoản người dùng có số dư `25,000,000 VNĐ`. Người dùng mở 2 tab trình duyệt, khởi tạo 2 giao dịch đóng học phí cho 2 MSSV khác nhau (mỗi khoản `14,500,000 VNĐ`). Cả 2 đều vượt qua bước Pre-check và nhận được 2 mã OTP hợp lệ. Người dùng bấm xác nhận cả 2 mã OTP cùng một thời điểm.
- **Cơ chế bảo vệ đa tầng (Redis Distributed Lock + PostgreSQL Row Lock):**
  1. Tại `payment-service`, `POST /payments/{id}/confirm-otp` giành **Redis Distributed Lock** `lock:account:{user_id}` (`SET ... NX PX`, giải phóng bằng **Lua script**) trước khi vào luồng Saga.
  2. Tại `auth-account-service` (`POST /internal/accounts/debit`), giao dịch mở Transaction SQL và khóa dòng tài khoản:
     ```sql
     SELECT * FROM users_accounts WHERE id = :account_id FOR UPDATE;
     ```
  3. Request thứ nhất kiểm tra `available_balance >= debit_amount`, trừ số dư (`available_balance = current_balance - debit_amount`), tăng `version = version + 1`, ghi sổ cái `DEBIT` và `COMMIT`.
  4. Request thứ hai đọc thấy số dư mới không đủ (`available_balance < debit_amount`), lập tức `ROLLBACK` và trả về `409 Conflict (INSUFFICIENT_BALANCE)`.
  5. Lớp bảo vệ DDL `CHECK (available_balance >= 0)` đảm bảo tuyệt đối không xảy ra thấu chi.

#### Quyết định 3: Giải quyết Tình huống Concurrency 2 (Nhiều tài khoản cùng thanh toán 1 khoản học phí) bằng Saga Orchestration & Compensating Refund
- **Kịch bản:** Hai người dùng A và B cùng tra cứu MSSV `52200001` (đang `UNPAID`), cùng khởi tạo giao dịch, nhận 2 mã OTP khác nhau và cùng bấm *"Xác nhận OTP"* tại cùng một mili-giây.
- **Cơ chế bảo vệ đa tầng (Redis Distributed Lock + PostgreSQL Row Lock + Saga Retry):**
  1. Tại `payment-service`, mỗi request giành khóa phân tán theo thứ tự cố định `lock:account:{user_id}` $\rightarrow$ `lock:tuition:{student_id}` (`SET ... NX PX` + Lua unlock) để serialize thực thi mà không gây deadlock.
  2. Khi bước vào Bước Saga 2 (`POST /internal/tuitions/mark-paid`), `tuition-service` mở Transaction SQL, khóa dòng học phí bằng `SELECT ... FOR UPDATE`, sau đó kiểm tra trạng thái ở tầng ứng dụng trước khi gán `PAID`:
     ```sql
     SELECT * FROM tuition_bills
     WHERE id = :bill_id AND student_id = :student_id
     FOR UPDATE;
     -- Kiểm tra trong transaction: nếu bill.status != 'UNPAID' -> ROLLBACK & 409 TUITION_ALREADY_PAID
     -- Kiểm tra bill.amount == payload.amount (chống thanh toán một phần)
     -- Gán bill.status = 'PAID', paid_transaction_id, paid_by_account_id, paid_at, version = version + 1 -> COMMIT
     ```
  3. Giao dịch của A đến trước: cập nhật thành công (`PAID`). `payment-service` cập nhật `tx.status = 'COMPLETED'`, ghi `MARK_TUITION_PAID` (`SUCCESS`) và **`db.commit()` ngay lập tức** trước khi gọi `notification-otp-service` gửi email biên lai (tránh việc lỗi SMTP làm rollback giao dịch đã hoàn tất về `PROCESSING`). Nếu email biên lai thất bại, `payment-service` ghi bước `RECEIPT_EMAIL_FAILED` và trả `200 OK` kèm `receipt_email_sent: false`.
  4. Giao dịch của B đến sau hoặc gặp lỗi gạch nợ sau khi đã trừ tiền: `tuition-service` trả về `409 Conflict (TUITION_ALREADY_PAID)`.
  5. **Saga Compensation (Hoàn tiền tự động có Retry):** `payment-service` gọi `POST /internal/accounts/refund` với cơ chế **retry tối đa 3 lần (backoff ngắn)**:
     - Nếu `refund` thành công (`HTTP 200`): lấy `balance_after` thực tế từ response làm `restored_balance`, ghi trạng thái `COMPENSATED` và trả `409 (TUITION_ALREADY_PAID_COMPENSATED)`.
     - Nếu `refund` thất bại sau 3 lần thử: **không** báo `COMPENSATED` giả và đặt `restored_balance = null`, lưu `COMPENSATION_FAILED` vào `payment_transactions` & `saga_step_logs` trong DB, và trả về `502 Bad Gateway (COMPENSATION_FAILED)` yêu cầu đối soát thủ công.

#### Quyết định 4: Đảm bảo 4 Ràng buộc của Mã OTP trên Redis + PostgreSQL & Báo cáo Trạng thái Email Trung thực
1. **Gắn với giao dịch cụ thể:** Lưu tại key `otp:tx:{transaction_id}` và cột `otp_tokens.transaction_id (UNIQUE)`.
2. **Không trùng với OTP đang có hiệu lực của giao dịch khác:** Thực thi lệnh Redis nguyên tử `SET otp:active_code:{otp_code} {transaction_id} NX EX 300`.
3. **Hiệu lực tối đa 5 phút:** `TTL = 300s` trên Redis và `expires_at` trong PostgreSQL.
4. **Chỉ sử dụng thành công 1 lần:** **Redis Lua Script** kiểm tra và đánh dấu `is_used = true` + xóa `otp:active_code:{otp_code}` nguyên tử, kết hợp khóa dòng `otp_tokens` trên PostgreSQL.
5. **Báo cáo lỗi SMTP trung thực (`FAILED`):** Khi gửi email qua SMTP gặp exception, `mailer.py` trả về `("FAILED", "SMTP_ERROR: ...")` và lưu `delivery_status = 'FAILED'` vào `notification_logs`. Riêng `/internal/otp/generate` sẽ thu hồi OTP tạm trên Redis và trả về `502 Bad Gateway (OTP_EMAIL_DELIVERY_FAILED)` để báo lỗi rõ ràng.

#### Quyết định 5: Phân tách Mạng Docker (`public_network` vs `internal_network`), Bảo mật Internal API, CORS & Demo Endpoints
- **Mạng Docker cách ly:** `docker-compose.yml` cấu hình hai mạng:
  - `public_network` (`driver: bridge`): kết nối `frontend` (`:5173`), `api-gateway` (`:8000`) và Web UI của `mailpit` (`:8025`).
  - `internal_network` (`driver: bridge`, **`internal: true`**): cô lập hoàn toàn `postgres`, `redis`, `auth-account-service`, `tuition-service`, `payment-service`, `notification-otp-service` (tất cả đều dùng `expose:`, không mở port trực tiếp ra host hay internet). `api-gateway` và `mailpit` gắn với cả hai mạng để làm cầu nối kiểm soát.
- **Bảo mật Internal Endpoints (`X-Internal-Service-Token`):** Mọi route `/internal/*` trên `auth-account-service`, `tuition-service` và `notification-otp-service` đều bắt buộc xác thực header `X-Internal-Service-Token` khớp với biến môi trường `INTERNAL_SERVICE_SECRET` (trả về `403 Forbidden - FORBIDDEN_INTERNAL_API` nếu thiếu hoặc sai token). Chỉ `payment-service` và `api-gateway` đính kèm token này khi giao tiếp nội bộ.
- **CORS (`CORS_ORIGINS`):** Cả 5 service đều đọc danh sách origin được phép từ biến môi trường `CORS_ORIGINS` (mặc định: `http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000`) đi kèm `allow_credentials=True`, thay cho `["*"]`.
- **Ghi chú về Endpoint Demo & Tài khoản mẫu:** Các endpoint `GET /api/v1/accounts/demo-users` và `POST /api/v1/system/reset-demo` cùng danh sách tài khoản mẫu (`nguyenvana`, `tranvanb`, ... với mật khẩu phát triển `Password@123`) được mở có chủ đích trong phạm vi bài đồ án để phục vụ **giảng viên chấm điểm trực tiếp trên lớp và bộ kiểm thử tự động (E2E & Concurrency Tests)**; các thông tin này chỉ là dữ liệu giả lập phát triển, không dùng cho môi trường production.

---

## PHẦN 2: QUY ƯỚC CHUNG CHO REST API

### 2.1. Headers Chuẩn Xuyên Suốt Hệ Thống
| Header | Bắt buộc | Mô tả |
| :--- | :---: | :--- |
| `Content-Type` | Có | `application/json` |
| `Authorization` | Tùy API | `Bearer <jwt_access_token>` (Bắt buộc cho mọi Public API trừ `/api/v1/auth/login`) |
| `X-Request-ID` | Tự động | UUIDv4 định danh duy nhất cho mỗi HTTP Request (`Correlation-ID`). Nếu Client không gửi, `api-gateway` tự sinh và truyền tới mọi Microservices + trả về trong Response Header. |
| `Idempotency-Key` | Có (POST) | UUIDv4 bắt buộc cho `POST /api/v1/payments/initiate` và `POST /api/v1/payments/{id}/confirm-otp` để chống gửi trùng request (double-click / network retry). |

### 2.2. Cấu trúc JSON Chuẩn hóa khi Thành công và Lỗi
- **Cấu trúc Error Response chuẩn (cho mọi mã 4xx, 5xx):**
```json
{
  "error": {
    "code": "INSUFFICIENT_BALANCE",
    "message": "Số dư khả dụng không đủ để thực hiện giao dịch thanh toán học phí.",
    "details": {
      "available_balance": 5000000.00,
      "required_amount": 14500000.00
    },
    "correlation_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "timestamp": "2026-10-27T23:00:00Z"
  }
}
```

### 2.3. Bảng Mã Trạng thái HTTP (HTTP Status Codes)
| Status Code | Ý nghĩa trong Phân hệ Đóng học phí |
| :---: | :--- |
| `200 OK` | Truy vấn thành công, đăng nhập thành công, hoặc hoàn tất xác nhận OTP & thanh toán thành công. |
| `201 Created` | Khởi tạo giao dịch thanh toán thành công (`PENDING_OTP`) và đã gửi mã OTP qua email. |
| `400 Bad Request` | Dữ liệu nghiệp vụ không hợp lệ (VD: mã OTP sai, mã OTP đã hết hạn 5 phút, chưa đồng ý điều khoản). |
| `401 Unauthorized` | Sai `username`/`password`, thiếu JWT Token hoặc JWT Token đã hết hạn/không hợp lệ. |
| `403 Forbidden` | Không có quyền truy cập giao dịch của người khác hoặc gọi Internal API thiếu/sai header `X-Internal-Service-Token` (`FORBIDDEN_INTERNAL_API`). |
| `404 Not Found` | Không tìm thấy sinh viên với `MSSV` tương ứng, hoặc không tìm thấy `transaction_id`. |
| `409 Conflict` | Xung đột trạng thái hoặc Concurrency (VD: Khoản học phí đã được thanh toán `TUITION_ALREADY_PAID`, số dư không đủ `INSUFFICIENT_BALANCE`, OTP đã được sử dụng `OTP_ALREADY_USED`). |
| `422 Unprocessable Entity` | Lỗi định dạng dữ liệu đầu vào (Pydantic Schema Validation: thiếu trường bắt buộc, sai kiểu dữ liệu, thiếu `Idempotency-Key`). |
| `500 Internal Server Error` | Lỗi hệ thống nội bộ hoặc mất kết nối hạ tầng. |
| `502 Bad Gateway` | Service hạ tầng/bên ngoài lỗi (VD: gửi Email OTP qua SMTP thất bại `OTP_EMAIL_DELIVERY_FAILED` hoặc Saga hoàn tiền tự động thất bại `COMPENSATION_FAILED`). |

---

## PHẦN 3: ĐẶC TẢ CHI TIẾT PUBLIC REST APIs (QUA API GATEWAY `:8000`)

---

### 3.1. Đăng nhập hệ thống
- **URI:** `/api/v1/auth/login`
- **Method:** `POST`
- **Service đích:** `auth-account-service (:8001)`
- **Authentication:** Public (Không yêu cầu JWT)

#### Request Body:
```json
{
  "username": "nguyenvana",
  "password": "Password@123"
}
```

#### Response `200 OK`:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "id": "11111111-1111-1111-1111-111111111101",
    "username": "nguyenvana",
    "full_name": "Nguyễn Văn A",
    "phone_number": "0901234567",
    "email": "nguyenvana@tdtu.edu.vn",
    "available_balance": 25000000.00,
    "status": "ACTIVE"
  }
}
```

#### Các mã lỗi có thể trả về:
- `401 Unauthorized`: `INVALID_CREDENTIALS` — Sai tên đăng nhập hoặc mật khẩu.
- `422 Unprocessable Entity`: Thiếu trường `username` hoặc `password`.

---

### 3.2. Lấy thông tin người nộp tiền & Số dư khả dụng hiện tại
- **URI:** `/api/v1/accounts/me`
- **Method:** `GET`
- **Service đích:** `auth-account-service (:8001)`
- **Headers:** `Authorization: Bearer <token>`

#### Response `200 OK`:
```json
{
  "id": "11111111-1111-1111-1111-111111111101",
  "username": "nguyenvana",
  "full_name": "Nguyễn Văn A",
  "phone_number": "0901234567",
  "email": "nguyenvana@tdtu.edu.vn",
  "available_balance": 25000000.00,
  "status": "ACTIVE",
  "updated_at": "2026-10-27T23:00:00Z"
}
```
> **Quy tắc nghiệp vụ:** Các trường `full_name`, `phone_number`, `email` từ API này được tự động điền vào nhóm **"a. Người nộp tiền"** trên giao diện và khóa `read-only` (người dùng không được phép chỉnh sửa).

---

### 3.3. Tra cứu thông tin sinh viên & Khoản học phí theo MSSV
- **URI:** `/api/v1/tuitions/{student_id}`
- **Method:** `GET`
- **Service đích:** `tuition-service (:8002)`
- **Headers:** `Authorization: Bearer <token>`
- **Path Parameter:** `student_id` (Mã số sinh viên TDTU, ví dụ: `52200001`)

#### Response `200 OK`:
```json
{
  "student": {
    "student_id": "52200001",
    "full_name": "Trần Minh Khoa",
    "faculty": "Khoa Công nghệ Thông tin",
    "major": "Kỹ thuật Phần mềm",
    "class_code": "22050301",
    "email": "52200001@student.tdtu.edu.vn"
  },
  "tuition_bill": {
    "id": "22222222-2222-2222-2222-222222222201",
    "student_id": "52200001",
    "semester_code": "HK1_2026_2027",
    "semester_name": "Học kỳ 1 - Năm học 2026-2027",
    "amount": 14500000.00,
    "status": "UNPAID",
    "paid_transaction_id": null,
    "paid_at": null
  },
  "can_pay": true
}
```

#### Các mã lỗi có thể trả về:
- `404 Not Found`: `STUDENT_OR_TUITION_NOT_FOUND` — Không tìm thấy sinh viên hoặc khoản học phí tương ứng với MSSV đã nhập.
- `401 Unauthorized`: Token không hợp lệ.

---

### 3.4. Khởi tạo giao dịch thanh toán học phí & Yêu cầu gửi OTP
- **URI:** `/api/v1/payments/initiate`
- **Method:** `POST`
- **Service đích:** `payment-service (:8003)` (Phối hợp `auth-account-service`, `tuition-service`, `notification-otp-service`)
- **Headers:**
  - `Authorization: Bearer <token>`
  - `Idempotency-Key: <uuid_v4>` *(Bắt buộc)*
  - `X-Request-ID: <uuid_v4>` *(Tùy chọn, Gateway tự cấp nếu thiếu)*

#### Request Body:
```json
{
  "student_id": "52200001",
  "tuition_bill_id": "22222222-2222-2222-2222-222222222201",
  "amount": 14500000.00,
  "terms_accepted": true
}
```
> **Quy tắc kiểm tra (Pre-check, không khóa DB Row Lock):**
> 1. `terms_accepted` bắt buộc là `true`.
> 2. `amount` gửi lên phải bằng **100% số tiền khoản học phí** (`tuition_bill.amount`). Tuyệt đối từ chối nếu thanh toán một phần (`PARTIAL_PAYMENT_NOT_ALLOWED`).
> 3. Khoản học phí phải tồn tại và đang có trạng thái `UNPAID`.
> 4. Số dư khả dụng hiện tại của người nộp phải `>= tuition_bill.amount`.

#### Response `201 Created`:
```json
{
  "transaction_id": "33333333-3333-3333-3333-333333333301",
  "transaction_code": "TXN-20261027-894120",
  "status": "PENDING_OTP",
  "payer": {
    "account_id": "11111111-1111-1111-1111-111111111101",
    "full_name": "Nguyễn Văn A",
    "phone_number": "0901234567",
    "email": "nguyenvana@tdtu.edu.vn"
  },
  "tuition": {
    "tuition_bill_id": "22222222-2222-2222-2222-222222222201",
    "student_id": "52200001",
    "student_full_name": "Trần Minh Khoa",
    "semester_code": "HK1_2026_2027",
    "amount": 14500000.00
  },
  "otp_info": {
    "sent_to_email": "nguyenvana@tdtu.edu.vn",
    "expires_in_seconds": 300,
    "expires_at": "2026-10-27T23:05:00Z"
  },
  "message": "Mã OTP đã được gửi đến địa chỉ email của bạn. Mã có hiệu lực trong 5 phút."
}
```

#### Các mã lỗi có thể trả về:
- `400 Bad Request`:
  - `TERMS_NOT_ACCEPTED`: Chưa đồng ý điều khoản và thỏa thuận của hệ thống.
  - `PARTIAL_PAYMENT_NOT_ALLOWED`: Số tiền thanh toán không khớp toàn bộ khoản học phí.
- `404 Not Found`: `TUITION_NOT_FOUND` — Không tìm thấy khoản học phí.
- `409 Conflict`:
  - `TUITION_ALREADY_PAID`: Khoản học phí này đã được thanh toán.
  - `INSUFFICIENT_BALANCE`: Số dư khả dụng không đủ để thanh toán khoản học phí.
- `422 Unprocessable Entity`: Thiếu header `Idempotency-Key` hoặc body sai định dạng.

---

### 3.5. Xác thực OTP & Hoàn tất giao dịch thanh toán (Saga Execution)
- **URI:** `/api/v1/payments/{transaction_id}/confirm-otp`
- **Method:** `POST`
- **Service đích:** `payment-service (:8003)` (Thực thi Saga qua `notification-otp-service`, `auth-account-service`, `tuition-service`)
- **Headers:**
  - `Authorization: Bearer <token>`
  - `Idempotency-Key: <uuid_v4>` *(Bắt buộc)*

#### Request Body:
```json
{
  "otp_code": "482910"
}
```

#### Response `200 OK` (Khi giao dịch thành công trọn vẹn):
```json
{
  "transaction_id": "33333333-3333-3333-3333-333333333301",
  "transaction_code": "TXN-20261027-894120",
  "status": "COMPLETED",
  "payer": {
    "account_id": "11111111-1111-1111-1111-111111111101",
    "full_name": "Nguyễn Văn A",
    "phone_number": "0901234567",
    "email": "nguyenvana@tdtu.edu.vn",
    "balance_before": 25000000.00,
    "balance_after": 10500000.00
  },
  "tuition": {
    "tuition_bill_id": "22222222-2222-2222-2222-222222222201",
    "student_id": "52200001",
    "student_full_name": "Trần Minh Khoa",
    "semester_code": "HK1_2026_2027",
    "amount": 14500000.00,
    "tuition_status": "PAID"
  },
  "completed_at": "2026-10-27T23:01:15Z",
  "receipt_email_sent": true,
  "message": "Thanh toán học phí thành công. Email xác nhận đã được gửi tới hộp thư của bạn."
}
```

#### Các mã lỗi có thể trả về:
- `400 Bad Request`:
  - `INVALID_OTP`: Mã OTP không chính xác.
  - `OTP_EXPIRED`: Mã OTP đã quá thời hạn hiệu lực 5 phút (`status` giao dịch chuyển thành `EXPIRED`).
- `404 Not Found`: `TRANSACTION_NOT_FOUND` — Không tìm thấy giao dịch hoặc giao dịch không thuộc về người dùng đang đăng nhập.
- `409 Conflict`:
  - `OTP_ALREADY_USED`: Mã OTP này đã được sử dụng trước đó (chỉ dùng thành công 1 lần).
  - `INSUFFICIENT_BALANCE` (**Concurrency 1**): Tại thời điểm xác nhận OTP, một giao dịch đồng thời khác trên cùng tài khoản vừa trừ tiền khiến số dư khả dụng còn lại không đủ. Giao dịch chuyển sang `FAILED`, số dư không bị âm.
  - `TUITION_ALREADY_PAID_COMPENSATED` (**Concurrency 2 + Saga Refund**): Tại thời điểm xác nhận OTP, khoản học phí của MSSV này vừa được một tài khoản khác thanh toán thành công trước. Hệ thống đã tự động **hoàn trả (Refund) 100% số tiền** về tài khoản của bạn (`restored_balance` lấy theo `balance_after` thực tế từ `auth-account-service`). Giao dịch chuyển sang trạng thái `COMPENSATED`.
- `502 Bad Gateway`:
  - `COMPENSATION_FAILED`: Bước gạch nợ học phí thất bại và lời gọi hoàn tiền tự động (`/internal/accounts/refund`) cũng thất bại sau tối đa 3 lần retry. Giao dịch và Saga step được lưu `COMPENSATION_FAILED`, `restored_balance = null`, cần đối soát thủ công (không bao giờ báo `COMPENSATED` giả).
- **Lưu ý trạng thái Email biên lai:** Trường `receipt_email_sent` trong response `200 OK` chỉ mang giá trị `true` khi `notification-otp-service` trả về HTTP `200` và `delivery_status == "SENT"`. Nếu gửi email biên lai thất bại, giao dịch vẫn giữ nguyên `status = "COMPLETED"` (đã commit trước bước email) và trả về `receipt_email_sent: false` kèm log Saga `RECEIPT_EMAIL_FAILED`.

---

### 3.6. Xem danh sách lịch sử giao dịch của người dùng
- **URI:** `/api/v1/payments/history`
- **Method:** `GET`
- **Service đích:** `payment-service (:8003)`
- **Headers:** `Authorization: Bearer <token>`
- **Query Parameters:** `limit=20&offset=0&status=COMPLETED` *(Tùy chọn)*

#### Response `200 OK`:
```json
{
  "total": 2,
  "items": [
    {
      "transaction_id": "33333333-3333-3333-3333-333333333301",
      "transaction_code": "TXN-20261027-894120",
      "student_id": "52200001",
      "student_full_name": "Trần Minh Khoa",
      "semester_code": "HK1_2026_2027",
      "amount": 14500000.00,
      "status": "COMPLETED",
      "failure_reason": null,
      "created_at": "2026-10-27T23:00:00Z",
      "completed_at": "2026-10-27T23:01:15Z"
    },
    {
      "transaction_id": "33333333-3333-3333-3333-333333333302",
      "transaction_code": "TXN-20261027-901452",
      "student_id": "52200001",
      "student_full_name": "Trần Minh Khoa",
      "semester_code": "HK1_2026_2027",
      "amount": 14500000.00,
      "status": "COMPENSATED",
      "failure_reason": "Khoản học phí đã được thanh toán bởi một giao dịch khác. Đã hoàn tiền tự động.",
      "created_at": "2026-10-27T23:00:02Z",
      "completed_at": "2026-10-27T23:01:15Z"
    }
  ]
}
```

---

### 3.7. Xem chi tiết một giao dịch theo ID
- **URI:** `/api/v1/payments/{transaction_id}`
- **Method:** `GET`
- **Service đích:** `payment-service (:8003)`
- **Headers:** `Authorization: Bearer <token>`

#### Response `200 OK`:
Trả về thông tin chi tiết của giao dịch kèm danh sách `saga_step_logs` phục vụ đối soát và minh chứng luồng Saga khi bảo vệ đồ án.

---

## PHẦN 4: ĐẶC TẢ INTERNAL REST APIs (GIAO TIẾP NỘI BỘ SERVICE-TO-SERVICE)

Các API dưới đây chỉ được `expose:` trong mạng nội bộ cách ly **`internal_network` (`internal: true`)**, **không công bố ra host**, và **mọi request bắt buộc phải đính kèm header `X-Internal-Service-Token`** khớp với `INTERNAL_SERVICE_SECRET` (trả về **`403 Forbidden - FORBIDDEN_INTERNAL_API`** nếu thiếu hoặc sai token) cùng header `X-Request-ID` (`Correlation-ID`).

### 4.1. Internal APIs của `auth-account-service (:8001)`

| Method | URI | Mục đích & Cơ chế xử lý Concurrency | Request Body | Response Codes |
| :---: | :--- | :--- | :--- | :---: |
| `GET` | `/internal/accounts/{account_id}` | Lấy thông tin người nộp tiền & kiểm tra số dư ban đầu (Pre-check). | `-` | `200`, `403`, `404` |
| `POST` | `/internal/accounts/debit` | **Khóa Pessimistic (`SELECT ... FOR UPDATE`)** trên `users_accounts`, kiểm tra `available_balance >= debit_amount`, trừ tiền nguyên tử và ghi `account_ledger_entries` (`DEBIT`). | `{ "account_id", "transaction_id", "amount", "idempotency_key", "description" }` | `200 OK`, `403`, `409 Conflict (INSUFFICIENT_BALANCE)` |
| `POST` | `/internal/accounts/refund` | **Saga Compensating Action:** Khóa bản ghi tài khoản, cộng hoàn trả lại `amount` khi bước gạch nợ học phí thất bại, ghi `account_ledger_entries` (`COMPENSATION_REFUND`). | `{ "account_id", "transaction_id", "amount", "idempotency_key", "reason" }` | `200 OK`, `403`, `404 Not Found` |
| `POST` | `/internal/accounts/reset-demo` | Khôi phục số dư mặc định cho các tài khoản mẫu (chỉ gọi nội bộ từ `payment-service`). | `-` | `200 OK`, `403` |

### 4.2. Internal APIs của `tuition-service (:8002)`

| Method | URI | Mục đích & Cơ chế xử lý Concurrency | Request Body | Response Codes |
| :---: | :--- | :--- | :--- | :---: |
| `GET` | `/internal/tuitions/{student_id}` | Lấy thông tin sinh viên & khoản học phí phục vụ Pre-check. | `-` | `200`, `403`, `404` |
| `POST` | `/internal/tuitions/mark-paid` | **Khóa Pessimistic (`SELECT ... FOR UPDATE`)** trên `tuition_bills`, kiểm tra `bill.status == 'UNPAID'` và `bill.amount == payload.amount` rồi cập nhật sang `PAID`, tăng `version` và `COMMIT`. Đảm bảo **chỉ duy nhất 1 giao dịch** thành công. | `{ "tuition_bill_id", "student_id", "transaction_id", "payer_account_id", "amount" }` | `200 OK`, `403`, `409 Conflict (TUITION_ALREADY_PAID)` |
| `POST` | `/internal/tuitions/reset-demo` | Khôi phục trạng thái học phí mặc định cho sinh viên mẫu. | `-` | `200 OK`, `403` |

### 4.3. Internal APIs của `notification-otp-service (:8004)`

| Method | URI | Mục đích & Cơ chế Bảo mật OTP | Request Body | Response Codes |
| :---: | :--- | :--- | :--- | :---: |
| `POST` | `/internal/otp/generate` | Sinh OTP 6 chữ số gắn với `transaction_id`, chống trùng bằng `SET otp:active_code:{code} NX EX 300`, lưu Redis (`TTL=300s`) + `otp_tokens`, gửi email qua SMTP và lưu `notification_logs` (`SENT` hoặc `FAILED`). Trả `502 OTP_EMAIL_DELIVERY_FAILED` nếu SMTP thất bại. | `{ "transaction_id", "recipient_email", "payer_name", "student_id", "student_name", "amount" }` | `201 Created`, `403`, `502 (OTP_EMAIL_DELIVERY_FAILED)` |
| `POST` | `/internal/otp/verify` | Thực thi **Redis Lua Script** kiểm tra mã OTP khớp với `transaction_id`, còn hạn 5 phút, `is_used == false`, và lập tức đánh dấu `is_used = true` (dùng 1 lần) + cập nhật bảng `otp_tokens`. | `{ "transaction_id", "otp_code" }` | `200 OK`, `400 (INVALID_OTP / OTP_EXPIRED)`, `403`, `409 (OTP_ALREADY_USED)` |
| `POST` | `/internal/notifications/payment-receipt` | Gửi email biên lai xác nhận thanh toán học phí thành công qua SMTP và lưu vết `notification_logs` với trạng thái trung thực (`SENT` hoặc `FAILED`). | `{ "transaction_id", "transaction_code", "recipient_email", "payer_name", "student_id", "student_name", "semester_name", "amount", "paid_at" }` | `200 OK`, `403` |
| `GET` | `/internal/otp/debug/{transaction_id}` | Tra cứu nhanh OTP phục vụ Automated Tests / Demo qua `payment-service`. | `-` | `200 OK`, `403`, `404` |
| `POST` | `/internal/otp/reset-demo` | Xóa sạch OTP & notification logs khi reset dữ liệu demo. | `-` | `200 OK`, `403` |
