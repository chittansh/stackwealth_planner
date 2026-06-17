"""/api/upload — accepts files / pasted text → ingest pipeline → plan deltas.

The main `POST /api/upload/{id}` endpoint returns a streaming NDJSON response.
Each line is a JSON event the frontend can render live, so the user sees
"extracting 14 fields…" instead of a multi-second blank spinner.

Event shapes (one per line):
    {"event":"file_started","filename":"...","size":N}
    {"event":"parsing","parser_hint":"xlsx"}                    # LLM call started
    {"event":"heartbeat","stage":"llm","elapsed_ms":N}          # every 2s during LLM
    {"event":"parsed","parser_used":"xlsx:llm","field_count":N} # LLM returned
    {"event":"field","path":"...","value":...,"ok":true}        # per leaf write
    {"event":"row_added","path":"...","row_id":"...","label":"..."}
    {"event":"rejected","path":"...","reason":"..."}
    {"event":"fsi_synced","derived":{...}}
    {"event":"file_done","summary":{...}}
    {"event":"done","summaries":[...]}                          # always last
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import StreamingResponse

from ..db import get_plan
from ..skills.anomalies import detect_plan_anomalies
from ..skills.intake import ingest
from ..skills.scenario import apply_add, apply_set, confirm_field, force_fsi_sync


def _normalize_partial_state(ps: dict[str, Any]) -> dict[str, Any]:
    """Fix common LLM mis-categorizations before they reach apply_set:

    - `monthly_expenses.sip_investments` → `monthly_investments.mutual_fund_sip`
    - Mirror liquid totals into `freedom_score_inputs.liquid_assets_current_value`
    """
    if not isinstance(ps, dict):
        return ps
    me = ps.get("monthly_expenses")
    mi = ps.setdefault("monthly_investments", {}) if isinstance(ps.get("monthly_investments"), dict) or "monthly_investments" not in ps else ps["monthly_investments"]
    if isinstance(me, dict) and me.get("sip_investments"):
        sip = me.pop("sip_investments")
        if isinstance(mi, dict):
            mi["mutual_fund_sip"] = (mi.get("mutual_fund_sip") or 0) + sip
        else:
            ps["monthly_investments"] = {"mutual_fund_sip": sip}

    fsi = ps.get("freedom_score_inputs")
    lc = ps.get("liquid_capital")
    if isinstance(fsi, dict) and isinstance(lc, dict) and not fsi.get("liquid_assets_current_value"):
        total_liquid = sum(
            float(lc.get(k) or 0)
            for k in ("savings_account_balance", "idle_cash_for_investment", "fd_breakable_for_investment")
        )
        if total_liquid > 0:
            fsi["liquid_assets_current_value"] = total_liquid
    return ps


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


def _parser_hint_from_filename(filename: str, mime: str) -> str:
    lower = (filename or "").lower()
    m = (mime or "").lower()
    if lower.endswith(".pdf") or m == "application/pdf":
        return "pdf"
    if lower.endswith(".xlsx") or lower.endswith(".xls") or "spreadsheet" in m:
        return "xlsx"
    if lower.endswith(".csv") or m == "text/csv":
        return "csv"
    if lower.endswith(".docx") or "wordprocessing" in m:
        return "docx"
    if m.startswith("image/") or lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return "image"
    if m.startswith("audio/") or m.startswith("video/"):
        return "audio"
    return "text"


@router.post("/{id}")
async def upload_files(
    id: str,
    file: list[UploadFile] = File(...),
) -> StreamingResponse:
    # Read all file bytes before kicking off the streaming response — we want
    # the multipart upload phase complete before we start emitting events.
    files_data: list[tuple[str, str, bytes]] = []
    for f in file:
        buf = await f.read()
        files_data.append((f.filename or "untitled", f.content_type or "application/octet-stream", buf))

    async def stream() -> AsyncIterator[bytes]:
        summaries: list[dict[str, Any]] = []

        def emit(obj: dict[str, Any]) -> bytes:
            return (json.dumps(obj) + "\n").encode("utf-8")

        for filename, mime, buf in files_data:
            yield emit({"event": "file_started", "filename": filename, "size": len(buf)})

            hint = _parser_hint_from_filename(filename, mime)
            yield emit({"event": "parsing", "parser_hint": hint, "filename": filename})

            # Run the LLM call as a task so we can interleave heartbeats while
            # it's waiting on Claude.
            ingest_task = asyncio.create_task(
                ingest(
                    {
                        "household_id": id,
                        "source": {
                            "kind": "file",
                            "filename": filename,
                            "mime": mime,
                            "contents_b64": base64.b64encode(buf).decode(),
                        },
                    }
                )
            )
            t0 = time.monotonic()
            while not ingest_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(ingest_task), timeout=2.0)
                except asyncio.TimeoutError:
                    yield emit({"event": "heartbeat", "stage": "llm", "elapsed_ms": int((time.monotonic() - t0) * 1000), "filename": filename})

            try:
                result = ingest_task.result()
            except Exception as err:
                summary = {
                    "filename": filename,
                    "parser_used": "failed",
                    "sections_set": [],
                    "list_rows_added": 0,
                    "fields_extracted": 0,
                    "missing": [],
                    "rejected": [],
                    "error": str(err),
                }
                summaries.append(summary)
                yield emit({"event": "file_done", "summary": summary})
                continue

            yield emit({
                "event": "parsed",
                "parser_used": result.get("parser_used", ""),
                "field_count": len(result.get("evidence") or []),
                "filename": filename,
            })

            sections_set: list[str] = []
            list_rows_added = 0
            rejected: list[dict[str, Any]] = []
            field_writes = 0
            source_type = _parser_to_source(result.get("parser_used", ""))

            # Buffer of events to flush after the write completes.
            event_buffer: list[bytes] = []

            async def _write_leaf(path: str, value: Any) -> None:
                nonlocal field_writes
                set_res = await apply_set(
                    {"household_id": id, "path": path, "value": value, "source_type": source_type}
                )
                if set_res.get("ok"):
                    field_writes += 1
                    event_buffer.append(emit({"event": "field", "path": path, "value": value, "ok": True}))
                elif "rejected" in (set_res.get("error") or ""):
                    rejected.append({"path": path, "value": value, "reason": set_res["error"]})
                    event_buffer.append(emit({"event": "rejected", "path": path, "reason": set_res["error"]}))

            async def _write(path: str, value: Any) -> None:
                nonlocal list_rows_added
                if isinstance(value, list):
                    for row in value:
                        add_res = await apply_add(
                            {"household_id": id, "path": path, "row": row, "source_type": source_type}
                        )
                        if add_res.get("ok"):
                            list_rows_added += 1
                            label = ""
                            if isinstance(row, dict):
                                label = str(row.get("fund_name") or row.get("stock_name") or row.get("goal_name") or row.get("instrument") or row.get("name") or "")
                            event_buffer.append(emit({"event": "row_added", "path": path, "row_id": add_res.get("id"), "label": label}))
                        elif "rejected" in (add_res.get("error") or ""):
                            rejected.append({"path": path, "row": row, "reason": add_res["error"]})
                            event_buffer.append(emit({"event": "rejected", "path": path, "reason": add_res["error"]}))
                elif isinstance(value, dict):
                    for sub_k, sub_v in value.items():
                        await _write(f"{path}.{sub_k}", sub_v)
                else:
                    await _write_leaf(path, value)

            partial_state = _normalize_partial_state(result.get("partial_state") or {})
            for path, value in partial_state.items():
                await _write(path, value)
                sections_set.append(path)
                # Flush buffered events for this section so the FE sees progress.
                for ev in event_buffer:
                    yield ev
                event_buffer.clear()

            derived = await force_fsi_sync(id)
            yield emit({"event": "fsi_synced", "derived": derived, "filename": filename})

            # Post-upload anomaly scan. The agent's chat prompt reads
            # `anomalies` out of the upload context and converts each
            # high-severity finding into a question for the RM rather
            # than silently producing a nonsensical plan.
            try:
                plan_after = await get_plan(id)
                anomalies = detect_plan_anomalies(plan_after) if plan_after else []
            except Exception:
                anomalies = []
            if anomalies:
                yield emit({"event": "anomalies_detected", "count": len(anomalies)})

            summary = {
                "filename": filename,
                "parser_used": result.get("parser_used", ""),
                "sections_set": sections_set,
                "list_rows_added": list_rows_added,
                "fields_extracted": len(result.get("evidence") or []),
                "writes_applied": field_writes,
                "missing": result.get("missing") or [],
                "rejected": rejected,
                "anomalies": anomalies,
            }
            summaries.append(summary)
            yield emit({"event": "file_done", "summary": summary})

        yield emit({"event": "done", "summaries": summaries})

    return StreamingResponse(stream(), media_type="application/x-ndjson")


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

    for path, value in (_normalize_partial_state(result.get("partial_state") or {})).items():
        await _write(path, value)
    await force_fsi_sync(id)
    return {"ok": True, "result": result}


@router.post("/{id}/confirm")
async def confirm(id: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    return await confirm_field(
        {"household_id": id, "field": body["field"], "value": body.get("value")}
    )
