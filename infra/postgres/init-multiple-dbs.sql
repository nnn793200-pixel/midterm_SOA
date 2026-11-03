-- ============================================================================
-- KHỞI TẠO 4 CƠ SỞ DỮ LIỆU ĐỘC LẬP (DATABASE-PER-SERVICE PATTERN)
-- Chạy tự động khi container PostgreSQL khởi tạo lần đầu
-- ============================================================================

CREATE DATABASE account_db;
CREATE DATABASE tuition_db;
CREATE DATABASE payment_db;
CREATE DATABASE notification_db;

GRANT ALL PRIVILEGES ON DATABASE account_db TO postgres;
GRANT ALL PRIVILEGES ON DATABASE tuition_db TO postgres;
GRANT ALL PRIVILEGES ON DATABASE payment_db TO postgres;
GRANT ALL PRIVILEGES ON DATABASE notification_db TO postgres;
