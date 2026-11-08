from typing import Dict, Any, Optional
import httpx
from fastapi import Request, Response, HTTPException, status
from app.config import settings

http_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    global http_client
    if http_client is None:
        limits = httpx.Limits(max_connections=100, max_keepalive_connections=40)
        http_client = httpx.AsyncClient(timeout=15.0, limits=limits)
    return http_client


async def close_http_client() -> None:
    global http_client
    if http_client is not None:
        await http_client.aclose()
        http_client = None


async def forward_request(
    request: Request,
    target_url: str,
    jwt_claims: Optional[Dict[str, Any]] = None,
) -> Response:
    client = get_http_client()
    correlation_id = getattr(request.state, "correlation_id", "")

    headers: Dict[str, str] = {
        "X-Request-ID": correlation_id,
        "X-Internal-Service-Token": settings.INTERNAL_SERVICE_SECRET,
    }
    if "authorization" in request.headers:
        headers["Authorization"] = request.headers["authorization"]
    if "idempotency-key" in request.headers:
        headers["Idempotency-Key"] = request.headers["idempotency-key"]
    if "content-type" in request.headers:
        headers["Content-Type"] = request.headers["content-type"]

    if jwt_claims:
        if jwt_claims.get("sub"):
            headers["X-User-ID"] = str(jwt_claims["sub"])
        if jwt_claims.get("username"):
            headers["X-Username"] = str(jwt_claims["username"])
        if jwt_claims.get("email"):
            headers["X-User-Email"] = str(jwt_claims["email"])

    body_bytes = await request.body()
    query_params = dict(request.query_params)

    try:
        downstream_resp = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            params=query_params,
            content=body_bytes if body_bytes else None,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "DOWNSTREAM_SERVICE_UNAVAILABLE",
                "message": f"Không thể kết nối tới microservice đích ({target_url}): {str(exc)}",
            },
        )

    response_headers = {
        "X-Request-ID": correlation_id,
        "Content-Type": downstream_resp.headers.get(
            "content-type", "application/json"
        ),
    }

    return Response(
        content=downstream_resp.content,
        status_code=downstream_resp.status_code,
        headers=response_headers,
    )
