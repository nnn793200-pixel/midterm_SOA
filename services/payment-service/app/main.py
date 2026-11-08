import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from app.config import settings
from app.database import engine, Base
from app.routers import payments

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | [%(name)s] | %(message)s",
)
logger = logging.getLogger(settings.SERVICE_NAME)


def sync_enum_check_constraints() -> None:
    """
    Cập nhật CHECK constraints trên PostgreSQL hiện có một cách idempotent
    để bổ sung trạng thái COMPENSATION_FAILED khi nâng cấp schema không xóa volume.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE payment_transactions DROP CONSTRAINT IF EXISTS chk_payment_tx_status"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE payment_transactions ADD CONSTRAINT chk_payment_tx_status "
                "CHECK (status IN ('PENDING_OTP', 'PROCESSING', 'COMPLETED', 'FAILED', 'COMPENSATED', 'COMPENSATION_FAILED', 'EXPIRED'))"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE saga_step_logs DROP CONSTRAINT IF EXISTS chk_saga_step_status"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE saga_step_logs ADD CONSTRAINT chk_saga_step_status "
                "CHECK (step_status IN ('SUCCESS', 'FAILED', 'COMPENSATED', 'COMPENSATION_FAILED'))"
            )
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database schema for %s...", settings.SERVICE_NAME)
    Base.metadata.create_all(bind=engine)
    try:
        sync_enum_check_constraints()
    except Exception as exc:
        logger.warning("Check constraint sync skipped/warning: %s", str(exc))
    yield


app = FastAPI(
    title="TDTU iBanking - Payment Service (Saga Orchestrator)",
    description="Microservice điều phối Saga thanh toán học phí, kiểm soát Idempotency-Key, xác thực OTP và hoàn tiền tự động (Saga Compensation).",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    start_time = time.perf_counter()

    response = await call_next(request)

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    response.headers["X-Request-ID"] = correlation_id
    logger.info(
        "corr_id=%s | method=%s | path=%s | status=%d | duration=%.2fms",
        correlation_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    if isinstance(exc.detail, dict):
        code = exc.detail.get("code", "HTTP_ERROR")
        message = exc.detail.get("message", "Đã xảy ra lỗi khi xử lý yêu cầu.")
        details = exc.detail.get("details", None)
    else:
        code = "HTTP_ERROR"
        message = str(exc.detail)
        details = None

    return JSONResponse(
        status_code=exc.status_code,
        headers={"X-Request-ID": correlation_id},
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "correlation_id": correlation_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    return JSONResponse(
        status_code=422,
        headers={"X-Request-ID": correlation_id},
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Dữ liệu đầu vào không hợp lệ.",
                "details": exc.errors(),
                "correlation_id": correlation_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        },
    )


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "service": settings.SERVICE_NAME,
        "status": "UP",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


app.include_router(payments.router)
