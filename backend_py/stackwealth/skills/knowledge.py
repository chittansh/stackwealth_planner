"""
Knowledge RAG — port of skills/knowledge/index.ts.

Uses OpenAI text-embedding-3-small if OPENAI_API_KEY is set, otherwise falls
back to keyword matching. Storage: in-memory.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from .. import config

_openai_client: Any = None


def _client() -> Optional[Any]:
    global _openai_client
    if not config.OPENAI_API_KEY:
        return None
    if _openai_client is None:
        try:
            from openai import OpenAI

            _openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
        except Exception:
            _openai_client = None
    return _openai_client


_DOCS: list[dict] = []
_CHUNKS: list[dict] = []

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150


def _chunk_text(s: str) -> list[dict]:
    lines = s.split("\n")
    out: list[dict] = []
    buf = ""
    heading: Optional[str] = None

    def flush() -> None:
        nonlocal buf, out
        if buf.strip():
            out.append({"heading": heading, "text": buf.strip()})
        buf = ""

    for line in lines:
        if re.match(r"^#{1,6}\s", line):
            flush()
            heading = re.sub(r"^#{1,6}\s+", "", line).strip()
            continue
        if len((buf + "\n" + line)) > CHUNK_SIZE:
            flush()
            buf = (buf[-CHUNK_OVERLAP:] + " " + line).strip()
        else:
            buf = (buf + "\n" + line) if buf else line
    flush()
    return out


def _embed_all(texts: list[str]) -> list[list[float] | None]:
    c = _client()
    if c is None:
        return [None] * len(texts)
    try:
        r = c.embeddings.create(model="text-embedding-3-small", input=texts)
        return [d.embedding for d in r.data]
    except Exception:
        return [None] * len(texts)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


async def ingest_document(args: dict[str, Any]) -> dict:
    doc_id = str(uuid4())
    _DOCS.append(
        {
            "id": doc_id,
            "org_id": args["org_id"],
            "filename": args["filename"],
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    segs = _chunk_text(args["text"])
    embeds = _embed_all([s["text"] for s in segs])
    for i, s in enumerate(segs):
        _CHUNKS.append(
            {
                "id": str(uuid4()),
                "doc_id": doc_id,
                "org_id": args["org_id"],
                "filename": args["filename"],
                "heading": s.get("heading"),
                "text": s["text"],
                "embedding": embeds[i],
                "ord": i,
            }
        )
    return {"doc_id": doc_id, "chunk_count": len(segs)}


def list_documents(org_id: str) -> list[dict]:
    return [
        {**d, "chunk_count": sum(1 for c in _CHUNKS if c["doc_id"] == d["id"])}
        for d in _DOCS
        if d["org_id"] == org_id
    ]


async def retrieve(args: dict[str, Any]) -> dict:
    candidates = [c for c in _CHUNKS if c["org_id"] == args["org_id"]]
    if not candidates:
        return {"chunks": []}

    top_k = args.get("top_k") or 3
    c = _client()
    if c is not None:
        try:
            r = c.embeddings.create(model="text-embedding-3-small", input=args["query"])
            qv = r.data[0].embedding
            scored = sorted(
                ({"x": x, "score": _cosine(qv, x["embedding"])} for x in candidates if x["embedding"]),
                key=lambda s: -s["score"],
            )[:top_k]
            return {
                "chunks": [
                    {
                        "text": s["x"]["text"],
                        "filename": s["x"]["filename"],
                        "heading": s["x"].get("heading"),
                        "score": round(s["score"], 3),
                    }
                    for s in scored
                ]
            }
        except Exception:
            pass

    terms = [t for t in args["query"].lower().split() if len(t) >= 3]
    scored2 = []
    for x in candidates:
        hay = (x["text"] + " " + x["filename"] + " " + (x.get("heading") or "")).lower()
        score = sum(1 for t in terms if t in hay) / max(1, len(terms))
        if score > 0:
            scored2.append({"x": x, "score": score})
    scored2.sort(key=lambda s: -s["score"])
    return {
        "chunks": [
            {
                "text": s["x"]["text"],
                "filename": s["x"]["filename"],
                "heading": s["x"].get("heading"),
                "score": s["score"],
            }
            for s in scored2[:top_k]
        ]
    }
