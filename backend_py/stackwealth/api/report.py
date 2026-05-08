"""/api/report — PDF render."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

from ..skills.report import render_plan_pdf

router = APIRouter()


@router.get("/{id}/pdf")
async def report_pdf(id: str) -> Response:
    r = await render_plan_pdf(id)
    if r.get("ok"):
        return Response(
            content=r["bytes"],
            media_type="application/pdf",
            headers={
                "content-disposition": f'attachment; filename="stackwealth-plan-{id}.pdf"',
            },
        )
    return HTMLResponse(content=r["html"])
