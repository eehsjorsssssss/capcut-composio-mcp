import os
import json
from typing import Any, Optional

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.applications import Starlette
from starlette.routing import Route, Mount

NAME = "CapCut Composio Bridge"
CAPCUT_BASE_URL = os.getenv("CAPCUT_BASE_URL", "http://127.0.0.1:9001").rstrip("/")
CAPCUT_API_KEY = os.getenv("CAPCUT_API_KEY", "")
BRIDGE_API_KEY = os.getenv("BRIDGE_API_KEY", "")
CAPCUT_AUTH_HEADER = os.getenv("CAPCUT_AUTH_HEADER", "Authorization")
CAPCUT_AUTH_PREFIX = os.getenv("CAPCUT_AUTH_PREFIX", "Bearer")

mcp = MCPServer(
    NAME,
    instructions=(
        "Tools for controlling a CapCut-compatible editing API. "
        "Use create_draft, add_video, add_text, add_keyframe and save_draft "
        "to build an editing project. The bridge never exposes API secrets "
        "to tool callers."
    ),
)


def _capcut_headers() -> dict[str, str]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if CAPCUT_API_KEY:
        if CAPCUT_AUTH_PREFIX:
            headers[CAPCUT_AUTH_HEADER] = f"{CAPCUT_AUTH_PREFIX} {CAPCUT_API_KEY}"
        else:
            headers[CAPCUT_AUTH_HEADER] = CAPCUT_API_KEY
    return headers


async def _request(method: str, path: str, payload: Any | None = None) -> dict[str, Any]:
    if not path.startswith("/"):
        path = "/" + path
    url = CAPCUT_BASE_URL + path
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.request(
            method.upper(), url, headers=_capcut_headers(), json=payload
        )
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            data = response.json()
        else:
            data = {"text": response.text}
        if response.is_error:
            raise RuntimeError(f"CapCut API {response.status_code}: {data}")
        return {"status_code": response.status_code, "data": data}


@mcp.tool()
async def capcut_health() -> dict[str, Any]:
    """Check whether the configured CapCut-compatible API is reachable."""
    try:
        return await _request("GET", os.getenv("CAPCUT_HEALTH_PATH", "/health"))
    except Exception as exc:
        return {"ok": False, "error": str(exc), "base_url": CAPCUT_BASE_URL}


@mcp.tool()
async def capcut_create_draft(width: int = 1080, height: int = 1920) -> dict[str, Any]:
    """Create a vertical CapCut draft. Returns the draft_id."""
    return await _request(
        "POST",
        os.getenv("CAPCUT_CREATE_DRAFT_PATH", "/create_draft"),
        {"width": width, "height": height},
    )


@mcp.tool()
async def capcut_add_video(
    draft_id: str,
    video_url: str,
    start: float = 0,
    end: Optional[float] = None,
    volume: float = 0.0,
    transition: Optional[str] = None,
) -> dict[str, Any]:
    """Add a video clip to a draft from a URL."""
    payload: dict[str, Any] = {
        "draft_id": draft_id,
        "video_url": video_url,
        "start": start,
        "volume": volume,
    }
    if end is not None:
        payload["end"] = end
    if transition:
        payload["transition"] = transition
    return await _request(
        "POST", os.getenv("CAPCUT_ADD_VIDEO_PATH", "/add_video"), payload
    )


@mcp.tool()
async def capcut_add_text(
    draft_id: str,
    text: str,
    start: float,
    end: float,
    font_size: int = 56,
    font_color: Optional[str] = None,
    background_color: Optional[str] = None,
    shadow_enabled: bool = True,
) -> dict[str, Any]:
    """Add styled text to a draft."""
    payload: dict[str, Any] = {
        "draft_id": draft_id,
        "text": text,
        "start": start,
        "end": end,
        "font_size": font_size,
        "shadow_enabled": shadow_enabled,
    }
    if font_color:
        payload["font_color"] = font_color
    if background_color:
        payload["background_color"] = background_color
    return await _request(
        "POST", os.getenv("CAPCUT_ADD_TEXT_PATH", "/add_text"), payload
    )


@mcp.tool()
async def capcut_add_keyframe(
    draft_id: str,
    track_name: str,
    property_types: list[str],
    times: list[float],
    values: list[str],
) -> dict[str, Any]:
    """Add keyframe animation to a video track."""
    return await _request(
        "POST",
        os.getenv("CAPCUT_ADD_KEYFRAME_PATH", "/add_video_keyframe"),
        {
            "draft_id": draft_id,
            "track_name": track_name,
            "property_types": property_types,
            "times": times,
            "values": values,
        },
    )


@mcp.tool()
async def capcut_save_draft(draft_id: str) -> dict[str, Any]:
    """Save a draft and return the CapCut-compatible draft URL/result."""
    return await _request(
        "POST",
        os.getenv("CAPCUT_SAVE_DRAFT_PATH", "/save_draft"),
        {"draft_id": draft_id},
    )


@mcp.tool()
async def capcut_request(
    method: str,
    path: str,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Call an additional CapCut-compatible endpoint. Never provide API keys in payload."""
    allowed = {"GET", "POST", "PUT", "PATCH", "DELETE"}
    method = method.upper()
    if method not in allowed:
        raise ValueError(f"Unsupported method: {method}")
    return await _request(method, path, payload)


# A small composite tool for your ranking-video workflow.
@mcp.tool()
async def capcut_create_ranking_draft(
    clips: list[dict[str, Any]],
    title: str = "TOP 5",
    width: int = 1080,
    height: int = 1920,
) -> dict[str, Any]:
    """Create a simple 9:16 ranking-video draft from ordered clip dictionaries.

    Each clip may contain: video_url, start, end, label, text_start, text_end.
    This creates the draft, adds clips and labels, then saves the draft.
    """
    draft_result = await capcut_create_draft(width, height)
    data = draft_result.get("data", {})
    draft_id = data.get("draft_id")
    if not draft_id:
        raise RuntimeError(f"CapCut API did not return draft_id: {draft_result}")

    current_time = 0.0
    added = []
    for index, clip in enumerate(clips, start=1):
        duration = float(clip.get("duration", 5))
        clip_start = float(clip.get("start", 0))
        clip_end = clip.get("end")
        if clip_end is None:
            clip_end = clip_start + duration

        result = await capcut_add_video(
            draft_id=draft_id,
            video_url=clip["video_url"],
            start=clip_start,
            end=float(clip_end),
            volume=float(clip.get("volume", 0)),
            transition=clip.get("transition"),
        )
        added.append({"rank": index, "video": result})

        label = clip.get("label", f"#{index}")
        text_start = float(clip.get("text_start", current_time))
        text_end = float(clip.get("text_end", current_time + duration))
        await capcut_add_text(
            draft_id=draft_id,
            text=str(label),
            start=text_start,
            end=text_end,
            font_size=int(clip.get("font_size", 72)),
            font_color=clip.get("font_color"),
            background_color=clip.get("background_color"),
            shadow_enabled=bool(clip.get("shadow_enabled", True)),
        )
        current_time += duration

    await capcut_add_text(
        draft_id=draft_id,
        text=title,
        start=0,
        end=min(2.0, current_time or 2.0),
        font_size=64,
        shadow_enabled=True,
    )

    saved = await capcut_save_draft(draft_id)
    return {"draft_id": draft_id, "clips_added": added, "saved": saved}


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    allowed_hosts = os.getenv("ALLOWED_HOSTS", "capcut-composio-mcp.onrender.com,localhost:*,127.0.0.1:*").split(",")
    allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[x.strip() for x in allowed_hosts if x.strip()] or ["*"],
        allowed_origins=[x.strip() for x in allowed_origins if x.strip()],
    )
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host=host,
        transport_security=transport_security,
    )

    async def health(request: Request):
        return JSONResponse({"status": "ok", "service": NAME, "mcp": "/mcp"})

    app = Starlette(routes=[
        Route("/health", health, methods=["GET"]),
        Mount("/mcp", app=mcp_app),
    ])

    if BRIDGE_API_KEY:
        class BridgeAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                if request.url.path == "/mcp":
                    auth = request.headers.get("authorization", "")
                    supplied = request.headers.get("x-api-key", "")
                    expected = BRIDGE_API_KEY
                    ok = supplied == expected or auth == f"Bearer {expected}"
                    if not ok:
                        return JSONResponse({"error": "Unauthorized"}, status_code=401)
                return await call_next(request)

        app.add_middleware(BridgeAuthMiddleware)

    uvicorn.run(app, host=host, port=port)
