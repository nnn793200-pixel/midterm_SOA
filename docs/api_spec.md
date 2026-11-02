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
| 1 | **`api-gateway`** | `8000` | Stateless | Điểm truy cập duy nhất (Single Entry Point) từ Frontend; cấp phát và truyền dẫn `X-Request-ID` (`Correlation-ID`); xác thực chữ ký JWT tập trung; điều hướng (reverse proxy) tới các microservices nội bộ. |
| 2 | **`auth-account-service`** | `8001` | PostgreSQL (`account_db`) | Xác thực `username`/`password` và phát hành JWT; cung cấp thông tin người nộp tiền (Họ tên, SĐT, Email, Số dư khả dụng); thực thi **trừ tiền nguyên tử (Atomic Debit)** với khóa bi quan (`SELECT ... FOR UPDATE`) và **hoàn tiền bù trừ (Saga Compensating Refund)**; ghi sổ cái biến động số dư (`account_ledger_entries`). |
| 3 | **`tuition-service`** | `8002` | PostgreSQL (`tuition_db`) | Quản lý danh mục sinh viên TDTU (`students`) và công nợ học phí theo học kỳ (`tuition_bills`); hỗ trợ tra cứu học phí theo `MSSV`; thực thi **gạch nợ nguyên tử (Atomic State Transition: `UNPAID` $\rightarrow$ `PAID`)** với khóa bản ghi (`SELECT ... FOR UPDATE`). |
| 4 | **`payment-service`** | `8003` | PostgreSQL (`payment_db`) + Redis (`6379`) | Đóng vai trò **Saga Orchestrator**; kiểm tra điều kiện khởi tạo (Pre-check); kiểm soát `Idempotency-Key` chống double-submit; điều phối vòng đời giao dịch (`PENDING_OTP` $\rightarrow$ `PROCESSING` $\rightarrow$ `COMPLETED` / `COMPENSATED` / `FAILED`); lưu vết từng bước Saga (`saga_step_logs`) và cung cấp lịch sử giao dịch. |
| 5 | **`notification-otp-service`** | `8004` | Redis (`6379`) + PostgreSQL (`notification_db`) | Sinh mã OTP 6 chữ số gắn với `transaction_id`, đảm bảo **không trùng với bất kỳ OTP nào đang có hiệu lực** trên toàn hệ thống; quản lý thời hạn **TTL 300 giây (5 phút)** và cơ chế **chỉ dùng thành công 1 lần** bằng Redis Lua Script nguyên tử; lưu trữ thực thể `otp_tokens` và `notification_logs`; gửi email OTP & email biên lai xác nhận qua **Mailpit SMTP Server (`:1025`)**. |

---

### 1.2. Các Quyết định Thiết kế Cốt lõi (Architectural Decisions)

#### Quyết định 1: Tại sao KHÔNG giữ Database Row Lock trong 5 phút chờ nhập OTP?
- **Vấn đề:** Nếu hệ thống thực hiện `SELECT ... FOR UPDATE` trên bảng `users_accounts` hoặc `tuition_bills` ngay khi người dùng bấm *"Xác nhận giao dịch"* và giữ khóa suốt 5 phút chờ người dùng mở email lấy OTP, kết nối DB sẽ bị treo (connection pool exhaustion) và gây khóa chết (deadlock/starvation) nếu người dùng đóng trình duyệt mà không nhập OTP.
- **Giải pháp chuẩn Production:**
  1. **Tại bước Khởi tạo (`POST /api/v1/payments/initiate`):** Chỉ thực hiện **Pre-check đọc dữ liệu (Read-only validation)**: kiểm tra khoản học phí tồn tại, đang ở trạng thái `UNPAID`, và `available_balance >= amount`. Sau đó tạo bản ghi giao dịch `PENDING_OTP` và gửi OTP. **Tuyệt đối không giữ khóa dòng DB.**
  2. **Tại bước Xác thực OTP (`POST /api/v1/payments/{id}/confirm-otp`):** Ngay khoảnh khắc mã OTP được xác thực hợp lệ, `payment-service` mới kích hoạt luồng Saga khóa dòng tức thời (`SELECT ... FOR UPDATE`) trong vài mili-giây để kiểm tra lại số dư + trạng thái học phí, trừ tiền và gạch nợ.

#### Quyết định 2: Giải quyết Tình huống Concurrency 1 (Nhiều giao dịch đồng thời trên cùng 1 tài khoản)
- **Kịch bản:** Tài khoản người dùng có số dư `15,000,000 VNĐ`. Người dùng mở 2 tab trình duyệt, khởi tạo 2 giao dịch đóng học phí cho 2 MSSV khác nhau (mỗi khoản `12,000,000 VNĐ`). Cả 2 đều vượt qua bước Pre-check và nhận được 2 mã OTP hợp lệ. Người dùng bấm xác nhận cả 2 mã OTP cùng một thời điểm.
- **Cơ chế bảo vệ:**
  Tại `auth-account-service` (`POST /internal/accounts/debit`), giao dịch mở Transaction SQL và thực thi:
  ```sql
  SELECT id, available_balance, version
  FROM users_accounts
  WHERE id = :account_id
  FOR UPDATE;
  ```
  - Request thứ nhất giành được Row Lock, kiểm tra `15,000,000 >= 12,000,000`, trừ tiền còn `3,000,000 VNĐ` và `COMMIT`.
  - Request thứ hai (đang chờ Row Lock) được đánh thức ngay sau khi Request 1 commit, đọc thấy `available_balance = 3,000,000 < 12,000,000`, lập tức `ROLLBACK` và trả về `409 Conflict (INSUFFICIENT_BALANCE)`.
  - Bổ sung lớp bảo vệ thứ 2 ở tầng DDL: `CHECK (available_balance >= 0)` đảm bảo không bao giờ xảy ra thấu chi trong mọi trường hợp.

#### Quyết định 3: Giải quyết Tình huống Concurrency 2 (Nhiều tài khoản cùng thanh toán 1 khoản học phí) bằng Saga Orchestration & Compensating Refund
- **Kịch bản:** Hai người dùng A và B cùng tra cứu MSSV `52200001` (đang `UNPAID`), cùng khởi tạo giao dịch, nhận 2 mã OTP khác nhau và cùng bấm *"Xác nhận OTP"* tại cùng một mili-giây.
- **Cơ chế bảo vệ:**
  1. Cả A và B đều đủ tiền nên đều vượt qua Bước Saga 1 (trừ tiền tài khoản cá nhân của A và B).
  2. Khi bước vào Bước Saga 2 (`POST /internal/tuitions/mark-paid`), `tuition-service` thực thi khóa bi quan kết hợp cập nhật có điều kiện:
     ```sql
     SELECT id, status, version FROM tuition_bills WHERE id = :bill_id FOR UPDATE;
     
     UPDATE tuition_bills
     SET status = 'PAID',
         paid_transaction_id = :transaction_id,
         paid_by_account_id = :payer_account_id,
         paid_at = NOW(),
         version = version + 1
     WHERE id = :bill_id AND status = 'UNPAID';
     ```
  3. Giao dịch của A đến trước 1ms: cập nhật thành công (`rowcount = 1`), học phí chuyển sang `PAID`.
  4. Giao dịch của B đến ngay sau đó: phát hiện `status == 'PAID'`, `tuition-service` trả về `409 Conflict (TUITION_ALREADY_PAID)`.
  5. **Saga Compensation (Hoàn tiền tự động):** Ngay khi nhận mã `409` từ `tuition-service`, `payment-service` lập tức gọi `POST /internal/accounts/refund` tới `auth-account-service` để cộng trả lại nguyên vẹn số tiền vừa trừ của B, ghi nhận bút toán `COMPENSATION_REFUND` vào sổ cái, và cập nhật trạng thái giao dịch của B thành `COMPENSATED`.

#### Quyết định 4: Đảm bảo 4 Ràng buộc của Mã OTP trên Redis + PostgreSQL
1. **Gắn với giao dịch cụ thể:** Lưu tại key `otp:tx:{transaction_id}` và cột `otp_tokens.transaction_id (UNIQUE)`.
2. **Không trùng với OTP đang có hiệu lực của giao dịch khác:** Khi sinh mã 6 chữ số ngẫu nhiên, hệ thống thực thi lệnh Redis nguyên tử `SET otp:active_code:{otp_code} {transaction_id} NX EX 300`. Nếu trả về `nil` (mã này đang được dùng bởi một giao dịch khác chưa hết hạn), vòng lặp tự động sinh mã mới.
3. **Hiệu lực tối đa 5 phút:** Cả 2 key trên Redis đều có `TTL = 300s`, đồng thời cột `expires_at = created_at + INTERVAL '5 minutes'` được kiểm tra nghiêm ngặt.
4. **Chỉ sử dụng thành công 1 lần:** Sử dụng **Redis Lua Script** kiểm tra và đánh dấu `is_used = true` + xóa `otp:active_code:{otp_code}` trong cùng một thao tác nguyên tử đơn luồng trên Redis, kết hợp `UPDATE otp_tokens SET is_used = TRUE WHERE transaction_id = :tx_id AND is_used = FALSE`.

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
| `404 Not Found` | Không tìm thấy sinh viên với `MSSV` tương ứng, hoặc không tìm thấy `transaction_id`. |
| `409 Conflict` | Xung đột trạng thái hoặc Concurrency (VD: Khoản học phí đã được thanh toán `TUITION_ALREADY_PAID`, số dư không đủ `INSUFFICIENT_BALANCE`, OTP đã được sử dụng `OTP_ALREADY_USED`). |
| `422 Unprocessable Entity` | Lỗi định dạng dữ liệu đầu vào (Pydantic Schema Validation: thiếu trường bắt buộc, sai kiểu dữ liệu, thiếu `Idempotency-Key`). |
| `500 Internal Server Error` | Lỗi hệ thống nội bộ hoặc mất kết nối hạ tầng. |

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
  - `TUITION_ALREADY_PAID_COMPENSATED` (**Concurrency 2 + Saga Refund**): Tại thời điểm xác nhận OTP, khoản học phí của MSSV này vừa được một tài khoản khác thanh toán thành công trước. Hệ thống đã tự động **hoàn trả (Refund) 100% số tiền** về tài khoản của bạn. Giao dịch chuyển sang trạng thái `COMPENSATED`.

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

Các API dưới đây chỉ lắng nghe trong mạng nội bộ Docker (`internal_network`), được gọi bởi **Saga Orchestrator (`payment-service`)** và luôn kèm theo header `X-Request-ID` (`Correlation-ID`).

### 4.1. Internal APIs của `auth-account-service (:8001)`

| Method | URI | Mục đích & Cơ chế xử lý Concurrency | Request Body | Response Codes |
| :---: | :--- | :--- | :--- | :---: |
| `GET` | `/internal/accounts/{account_id}` | Lấy thông tin người nộp tiền & kiểm tra số dư ban đầu (Pre-check). | `-` | `200`, `404` |
| `POST` | `/internal/accounts/debit` | **Khóa Pessimistic (`SELECT ... FOR UPDATE`)** trên `users_accounts`, kiểm tra `available_balance >= amount`, trừ tiền nguyên tử và ghi `account_ledger_entries` (`DEBIT`). | `{ "account_id", "transaction_id", "amount", "idempotency_key", "description" }` | `200 OK`, `409 Conflict (INSUFFICIENT_BALANCE)` |
| `POST` | `/internal/accounts/refund` | **Saga Compensating Action:** Khóa bản ghi tài khoản, cộng hoàn trả lại `amount` khi bước gạch nợ học phí bị `409 Conflict`, ghi `account_ledger_entries` (`COMPENSATION_REFUND`). | `{ "account_id", "transaction_id", "amount", "idempotency_key", "reason" }` | `200 OK`, `404 Not Found` |

### 4.2. Internal APIs của `tuition-service (:8002)`

| Method | URI | Mục đích & Cơ chế xử lý Concurrency | Request Body | Response Codes |
| :---: | :--- | :--- | :--- | :---: |
| `GET` | `/internal/tuitions/{student_id}` | Lấy thông tin sinh viên & khoản học phí phục vụ Pre-check. | `-` | `200`, `404` |
| `POST` | `/internal/tuitions/mark-paid` | **Khóa Pessimistic (`SELECT ... FOR UPDATE`)** trên `tuition_bills` + cập nhật nguyên tử `UPDATE ... SET status='PAID' WHERE id=:id AND status='UNPAID'`. Đảm bảo **chỉ duy nhất 1 giao dịch** thành công. | `{ "tuition_bill_id", "student_id", "transaction_id", "payer_account_id", "amount" }` | `200 OK`, `409 Conflict (TUITION_ALREADY_PAID)` |

### 4.3. Internal APIs của `notification-otp-service (:8004)`

| Method | URI | Mục đích & Cơ chế Bảo mật OTP | Request Body | Response Codes |
| :---: | :--- | :--- | :--- | :---: |
| `POST` | `/internal/otp/generate` | Sinh OTP 6 chữ số gắn với `transaction_id`, kiểm tra không trùng với mọi OTP đang active bằng `SET otp:active_code:{code} NX EX 300`, lưu Redis (`TTL=300s`) + bảng `otp_tokens`, gửi email qua Mailpit SMTP và ghi `notification_logs`. | `{ "transaction_id", "recipient_email", "payer_name", "student_id", "student_name", "amount" }` | `201 Created` |
| `POST` | `/internal/otp/verify` | Thực thi **Redis Lua Script** kiểm tra mã OTP khớp với `transaction_id`, còn hạn 5 phút, `is_used == false`, và lập tức đánh dấu `is_used = true` (dùng 1 lần) + cập nhật bảng `otp_tokens`. | `{ "transaction_id", "otp_code" }` | `200 OK`, `400 (INVALID_OTP / OTP_EXPIRED)`, `409 (OTP_ALREADY_USED)` |
| `POST` | `/internal/notifications/payment-receipt` | Gửi email biên lai xác nhận thanh toán học phí thành công đến người nộp tiền và lưu vết vào bảng `notification_logs`. | `{ "transaction_id", "transaction_code", "recipient_email", "payer_name", "student_id", "student_name", "semester_name", "amount", "paid_at" }` | `200 OK` |
