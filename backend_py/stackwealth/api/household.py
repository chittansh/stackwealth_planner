"""/api/household — multi-household preview + merge."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..skills.household import merge, preview

router = APIRouter()


@router.post("/preview")
async def preview_route(request: Request) -> JSONResponse:
    b = await request.json()
    return JSONResponse(content=await preview(b))


@router.post("/merge")
async def merge_route(request: Request) -> JSONResponse:
    b = await request.json()
    return JSONResponse(content=await merge(b))
