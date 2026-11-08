import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Dict, Any
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.security import verify_jwt_token
from app.proxy import forward_request, get_http_client, close_http_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | [%(name)s] | %(message)s",
)
logger = logging.getLogger(settings.SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s on port 8000...", settings.SERVICE_NAME)
    get_http_client()
    yield
    await close_http_client()


app = FastAPI(
    title="TDTU iBanking - API Gateway",
    description="Single Entry Point API Gateway: điều hướng request, gắn X-Request-ID (Correlation-ID) để tracing xuyên suốt và xác thực JWT tập trung.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Gateway-Latency-Ms"],
)


@app.middleware("http")
async def correlation_id_and_tracing_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    start_time = time.perf_counter()

    response = await call_next(request)

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    response.headers["X-Request-ID"] = correlation_id
    response.headers["X-Gateway-Latency-Ms"] = f"{elapsed_ms:.2f}"
    logger.info(
        "GATEWAY_TRACE | corr_id=%s | method=%s | path=%s | status=%d | latency=%.2fms",
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
        code = exc.detail.get("code", "GATEWAY_HTTP_ERROR")
        message = exc.detail.get("message", "Lỗi xử lý tại API Gateway.")
        details = exc.detail.get("details", None)
    else:
        code = "GATEWAY_HTTP_ERROR"
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


# ============================================================================
# HEALTH & CLUSTER STATUS ENDPOINTS
# ============================================================================
@app.get("/health", tags=["Health & Observability"])
def gateway_health():
    return {
        "service": settings.SERVICE_NAME,
        "status": "UP",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/health/services", tags=["Health & Observability"])
async def cluster_services_health(request: Request):
    """
    Kiểm tra trạng thái hoạt động của cả 4 Microservices phía sau API Gateway.
    """
    client = get_http_client()
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    services_map = {
        "auth-account-service": f"{settings.AUTH_ACCOUNT_SERVICE_URL}/health",
        "tuition-service": f"{settings.TUITION_SERVICE_URL}/health",
        "payment-service": f"{settings.PAYMENT_SERVICE_URL}/health",
        "notification-otp-service": f"{settings.NOTIFICATION_OTP_SERVICE_URL}/health",
    }
    statuses: Dict[str, Any] = {}
    for name, url in services_map.items():
        try:
            resp = await client.get(url, headers={"X-Request-ID": correlation_id}, timeout=3.0)
            statuses[name] = resp.json() if resp.status_code == 200 else {"status": "DEGRADED"}
        except Exception as exc:
            statuses[name] = {"status": "DOWN", "error": str(exc)}

    return {
        "gateway": "UP",
        "correlation_id": correlation_id,
        "services": statuses,
    }


# ============================================================================
# 1. AUTH & ACCOUNT ROUTES -> auth-account-service (:8001)
# ============================================================================
@app.post("/api/v1/auth/login", tags=["1. Auth & Account"])
async def route_login(request: Request):
    target_url = f"{settings.AUTH_ACCOUNT_SERVICE_URL}/auth/login"
    return await forward_request(request, target_url)


@app.get("/api/v1/accounts/demo-users", tags=["1. Auth & Account"])
async def route_demo_users(request: Request):
    target_url = f"{settings.AUTH_ACCOUNT_SERVICE_URL}/accounts/demo-users"
    return await forward_request(request, target_url)


@app.get("/api/v1/accounts/me", tags=["1. Auth & Account"])
async def route_accounts_me(
    request: Request,
    jwt_claims: Dict[str, Any] = Depends(verify_jwt_token),
):
    target_url = f"{settings.AUTH_ACCOUNT_SERVICE_URL}/accounts/me"
    return await forward_request(request, target_url, jwt_claims=jwt_claims)


# ============================================================================
# 2. TUITION ROUTES -> tuition-service (:8002)
# ============================================================================
@app.get("/api/v1/tuitions", tags=["2. Tuition Lookup"])
async def route_list_tuitions(
    request: Request,
    jwt_claims: Dict[str, Any] = Depends(verify_jwt_token),
):
    target_url = f"{settings.TUITION_SERVICE_URL}/tuitions"
    return await forward_request(request, target_url, jwt_claims=jwt_claims)


@app.get("/api/v1/tuitions/{student_id}", tags=["2. Tuition Lookup"])
async def route_lookup_tuition(
    student_id: str,
    request: Request,
    jwt_claims: Dict[str, Any] = Depends(verify_jwt_token),
):
    target_url = f"{settings.TUITION_SERVICE_URL}/tuitions/{student_id}"
    return await forward_request(request, target_url, jwt_claims=jwt_claims)


# ============================================================================
# 3. PAYMENT & SAGA ROUTES -> payment-service (:8003)
# ============================================================================
@app.post("/api/v1/payments/initiate", tags=["3. Payment Workflow & Saga"])
async def route_initiate_payment(
    request: Request,
    jwt_claims: Dict[str, Any] = Depends(verify_jwt_token),
):
    target_url = f"{settings.PAYMENT_SERVICE_URL}/payments/initiate"
    return await forward_request(request, target_url, jwt_claims=jwt_claims)


@app.post(
    "/api/v1/payments/{transaction_id}/confirm-otp",
    tags=["3. Payment Workflow & Saga"],
)
async def route_confirm_otp(
    transaction_id: str,
    request: Request,
    jwt_claims: Dict[str, Any] = Depends(verify_jwt_token),
):
    target_url = (
        f"{settings.PAYMENT_SERVICE_URL}/payments/{transaction_id}/confirm-otp"
    )
    return await forward_request(request, target_url, jwt_claims=jwt_claims)


@app.get("/api/v1/payments/history", tags=["3. Payment Workflow & Saga"])
async def route_payment_history(
    request: Request,
    jwt_claims: Dict[str, Any] = Depends(verify_jwt_token),
):
    target_url = f"{settings.PAYMENT_SERVICE_URL}/payments/history"
    return await forward_request(request, target_url, jwt_claims=jwt_claims)


@app.get(
    "/api/v1/payments/{transaction_id}", tags=["3. Payment Workflow & Saga"]
)
async def route_payment_detail(
    transaction_id: str,
    request: Request,
    jwt_claims: Dict[str, Any] = Depends(verify_jwt_token),
):
    target_url = f"{settings.PAYMENT_SERVICE_URL}/payments/{transaction_id}"
    return await forward_request(request, target_url, jwt_claims=jwt_claims)


@app.get(
    "/api/v1/payments/{transaction_id}/demo-otp",
    tags=["3. Payment Workflow & Saga"],
)
async def route_payment_demo_otp(
    transaction_id: str,
    request: Request,
    jwt_claims: Dict[str, Any] = Depends(verify_jwt_token),
):
    target_url = (
        f"{settings.PAYMENT_SERVICE_URL}/payments/{transaction_id}/demo-otp"
    )
    return await forward_request(request, target_url, jwt_claims=jwt_claims)


@app.post("/api/v1/system/reset-demo", tags=["4. Demo & Test Reset"])
async def route_reset_demo_system(request: Request):
    """
    Khôi phục toàn bộ dữ liệu mẫu trên cả 4 Microservices phục vụ chạy Automated Tests & Demo.
    """
    target_url = f"{settings.PAYMENT_SERVICE_URL}/payments/reset-demo"
    return await forward_request(request, target_url)
