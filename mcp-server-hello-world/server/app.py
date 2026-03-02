import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from .utils import header_store

STATIC_DIR = Path(__file__).parent / "../static"

# ── Atlassian MCP Proxy Config ──────────────────────────────────────────────
# Proxies to the Atlassian MCP Streamable HTTP endpoint.
# The Bearer token is read from the ATLASSIAN_MCP_TOKEN env var,
# which must be set in the Databricks App config or .env file.
ATLASSIAN_MCP_URL = "https://mcp.atlassian.com/v1/mcp"
ATLASSIAN_TOKEN = os.environ.get("ATLASSIAN_MCP_TOKEN", "")
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Atlassian MCP Proxy on Databricks",
    description="Databricks App that proxies the Atlassian MCP Server",
    version="0.1.0",
)


@app.middleware("http")
async def capture_headers(request: Request, call_next):
    """Capture request headers for Databricks authentication context."""
    header_store.set(dict(request.headers))
    return await call_next(request)


# ── Status / Health ─────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def serve_index():
    """Serve the status page or a JSON health check."""
    if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
        return FileResponse(STATIC_DIR / "index.html")
    return {
        "message": "Atlassian MCP Proxy running on Databricks",
        "status": "healthy",
        "atlassian_mcp_url": ATLASSIAN_MCP_URL,
        "token_configured": bool(ATLASSIAN_TOKEN),
    }


# ── MCP Reverse Proxy ──────────────────────────────────────────────────────

async def _proxy_to_atlassian(request: Request):
    """
    Forward an incoming MCP request to the remote Atlassian MCP Server,
    injecting the Bearer token.  Handles both regular JSON responses and
    streaming SSE responses (used by Streamable HTTP transport).
    """
    body = await request.body()

    # Build headers to forward
    proxy_headers: dict[str, str] = {
        "Authorization": f"Bearer {ATLASSIAN_TOKEN}",
        "Accept": request.headers.get(
            "accept", "application/json, text/event-stream"
        ),
    }
    if "content-type" in request.headers:
        proxy_headers["Content-Type"] = request.headers["content-type"]
    if "mcp-session-id" in request.headers:
        proxy_headers["Mcp-Session-Id"] = request.headers["mcp-session-id"]

    # Open a streaming connection to Atlassian
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
    )

    try:
        req = client.build_request(
            method=request.method,
            url=ATLASSIAN_MCP_URL,
            content=body if request.method in ("POST", "PUT", "PATCH") else None,
            headers=proxy_headers,
        )
        response = await client.send(req, stream=True)

        content_type = response.headers.get("content-type", "")

        # Collect response headers we want to forward back
        resp_headers: dict[str, str] = {}
        if "mcp-session-id" in response.headers:
            resp_headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]

        if "text/event-stream" in content_type:
            # ── SSE streaming response ──────────────────────────────────
            async def sse_generator():
                try:
                    async for chunk in response.aiter_bytes():
                        yield chunk
                finally:
                    await response.aclose()
                    await client.aclose()

            return StreamingResponse(
                sse_generator(),
                status_code=response.status_code,
                media_type="text/event-stream",
                headers={
                    **resp_headers,
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )
        else:
            # ── Regular JSON response ───────────────────────────────────
            content = await response.aread()
            await response.aclose()
            await client.aclose()
            return Response(
                content=content,
                status_code=response.status_code,
                media_type=content_type or "application/json",
                headers=resp_headers,
            )

    except Exception as e:
        await client.aclose()
        return Response(
            content=(
                f'{{"error": "{str(e)}",'
                f' "message": "Failed to proxy to Atlassian MCP server"}}'
            ),
            status_code=502,
            media_type="application/json",
        )


@app.api_route("/mcp", methods=["GET", "POST", "DELETE"], include_in_schema=False)
async def mcp_proxy(request: Request):
    """Proxy all MCP traffic to the Atlassian MCP Server."""
    return await _proxy_to_atlassian(request)


@app.api_route("/mcp/", methods=["GET", "POST", "DELETE"], include_in_schema=False)
async def mcp_proxy_slash(request: Request):
    """Same proxy, trailing-slash variant."""
    return await _proxy_to_atlassian(request)

