"""/api/feedback — user feedback → Langfuse score."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..langfuse_client import flush_langfuse, get_langfuse

router = APIRouter()


@router.post("")
async def feedback(request: Request) -> JSONResponse:
    body: dict[str, Any] = await request.json() if (await request.body()) else {}

    if not body.get("trace_id"):
        return JSONResponse(content={"ok": False, "error": "trace_id is required"}, status_code=400)
    value = body.get("value")
    if not isinstance(value, (int, float)):
        return JSONResponse(content={"ok": False, "error": "value (number) is required"}, status_code=400)

    lf = get_langfuse()
    if lf is None:
        print("[feedback] received but langfuse is disabled")
        return JSONResponse(content={"ok": True, "recorded": False})

    try:
        lf.score(
            trace_id=body["trace_id"],
            observation_id=body.get("observation_id"),
            name=body.get("name") or "user-feedback",
            value=value,
            data_type="NUMERIC",
            comment=body.get("comment"),
        )
        flush_langfuse()
        return JSONResponse(content={"ok": True, "recorded": True})
    except Exception as err:
        print(f"[feedback] failed: {err}")
        return JSONResponse(content={"ok": False, "error": str(err)}, status_code=500)
