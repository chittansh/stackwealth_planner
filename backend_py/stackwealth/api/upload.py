"""/api/upload — accepts files / pasted text → ingest pipeline → plan deltas."""
from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile

from ..skills.intake import ingest
from ..skills.scenario import apply_add, apply_set, confirm_field, force_fsi_sync

router = APIRouter()


def _parser_to_source(parser_used: str) -> str:
    if parser_used.startswith("pdfAA"):
        return "pdf_aa"
    if parser_used.startswith("pdfGeneric"):
        return "pdf_generic"
    if parser_used.startswith("xlsx"):
        return "xlsx"
    if parser_used.startswith("csv"):
        return "csv"
    if parser_used.startswith("docx"):
        return "docx"
    if parser_used.startswith("image"):
        return "image"
    if parser_used.startswith("audio"):
        return "audio"
    return "md"


@router.post("/{id}")
async def upload_files(
    id: str,
    file: list[UploadFile] = File(...),
) -> dict[str, Any]:
    summaries = []
    for f in file:
        buf = await f.read()
        try:
            result = await ingest(
                {
                    "household_id": id,
                    "source": {
                        "kind": "file",
                        "filename": f.filename,
                        "mime": f.content_type or "application/octet-stream",
                        "contents_b64": base64.b64encode(buf).decode(),
                    },
                }
            )
        except Exception as err:
            summaries.append(
                {
                    "filename": f.filename,
                    "parser_used": "failed",
                    "sections_set": [],
                    "list_rows_added": 0,
                    "fields_extracted": 0,
                    "missing": [],
                    "error": str(err),
                }
            )
            continue

        sections_set: list[str] = []
        list_rows_added = 0
        rejected: list[dict[str, Any]] = []
        source_type = _parser_to_source(result.get("parser_used", ""))

        async def _write_leaf(path: str, value: Any) -> None:
            """Apply a single scalar/leaf write, recording rejections."""
            set_res = await apply_set(
                {"household_id": id, "path": path, "value": value, "source_type": source_type}
            )
            if not set_res.get("ok") and "rejected" in (set_res.get("error") or ""):
                rejected.append({"path": path, "value": value, "reason": set_res["error"]})

        async def _write(path: str, value: Any) -> None:
            """Walk a partial-state value. Lists → apply_add per row. Dicts →
            recurse into sub-paths so a single bad subfield doesn't poison the
            whole section. Leaves → apply_set."""
            nonlocal list_rows_added
            if isinstance(value, list):
                for row in value:
                    add_res = await apply_add(
                        {"household_id": id, "path": path, "row": row, "source_type": source_type}
                    )
                    if add_res.get("ok"):
                        list_rows_added += 1
                    elif "rejected" in (add_res.get("error") or ""):
                        rejected.append({"path": path, "row": row, "reason": add_res["error"]})
            elif isinstance(value, dict):
                for sub_k, sub_v in value.items():
                    await _write(f"{path}.{sub_k}", sub_v)
            else:
                await _write_leaf(path, value)

        for path, value in (result.get("partial_state") or {}).items():
            await _write(path, value)
            sections_set.append(path)

        # FSI finalization: the LLM may have emitted `freedom_score_inputs.*`
        # AFTER the breakdown sections, overwriting our server-derived sync
        # and double-counting EMI/SIP. Force one final sync from the breakdown
        # so the projection uses correct aggregates.
        await force_fsi_sync(id)

        summaries.append(
            {
                "filename": f.filename,
                "parser_used": result.get("parser_used", ""),
                "sections_set": sections_set,
                "list_rows_added": list_rows_added,
                "fields_extracted": len(result.get("evidence") or []),
                "missing": result.get("missing") or [],
                "rejected": rejected,
            }
        )

    return {"ok": True, "summaries": summaries}


@router.post("/{id}/text")
async def upload_text(id: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    result = await ingest(
        {
            "household_id": id,
            "source": {
                "kind": "text",
                "text": body["text"],
                "source_type": body.get("source_type", "user"),
            },
        }
    )
    async def _write(path: str, value: Any) -> None:
        if isinstance(value, list):
            for row in value:
                await apply_add(
                    {"household_id": id, "path": path, "row": row, "source_type": "user"}
                )
        elif isinstance(value, dict):
            for sub_k, sub_v in value.items():
                await _write(f"{path}.{sub_k}", sub_v)
        else:
            await apply_set(
                {"household_id": id, "path": path, "value": value, "source_type": "user"}
            )

    for path, value in (result.get("partial_state") or {}).items():
        await _write(path, value)
    return {"ok": True, "result": result}


@router.post("/{id}/confirm")
async def confirm(id: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    return await confirm_field(
        {"household_id": id, "field": body["field"], "value": body.get("value")}
    )
