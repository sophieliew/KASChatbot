"""
KAS Archive Assistant backend.

Local dev (from project root):
    uvicorn main:app --reload

Serves /api/chat and the demo page at http://localhost:8000.
Deployed on Vercel via its Python runtime (auto-detects `app`).
"""

import json
import os
import re
from pathlib import Path

import anthropic
import numpy as np
import voyageai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent
DATA = ROOT / "data"

load_dotenv(ROOT / ".env")

RECORDS_PATH = DATA / "records.json"
CHUNKS_PATH = DATA / "chunks.json"
CHUNK_EMB_PATH = DATA / "chunk_embeddings.npy"

for p in (RECORDS_PATH, CHUNKS_PATH, CHUNK_EMB_PATH):
    if not p.exists():
        raise SystemExit(
            f"Missing {p.name}. Run: python scripts/build_index.py"
        )

records = json.loads(RECORDS_PATH.read_text(encoding="utf-8"))
chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
chunk_embeddings = np.load(CHUNK_EMB_PATH)
norm_embeddings = chunk_embeddings / np.linalg.norm(chunk_embeddings, axis=1, keepdims=True)

voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

MODEL = "claude-haiku-4-5"
TOP_K = 6
OVER_K = 40

SYSTEM_PROMPT = """You are a warm, concise guide to the Korean American Story (KAS) Legacy Project — a video archive of oral-history interviews with Korean Americans.

Your job is to point visitors to the right interviews, not retell the stories yourself.

Format every answer like this:
- ONE short sentence directly answering the question (plain, friendly, not a summary).
- ONE short sentence previewing what the interviews cover, with inline citations [1][2][3].

Hard rules:
- Maximum 2 sentences total. Never 3.
- Do NOT summarize what the interviewees say. Let their videos speak for themselves.
- Only use information from the retrieved excerpts below. No inventing names, places, or dates.
- The retrieved list is a search result from a large archive — it is NOT the whole archive. If the retrieval doesn't match the question well, just say the search didn't surface a strong match and invite the visitor to rephrase. Never apologize for earlier answers and never claim something "isn't in the archive" — you can only see this search's results.
- Treat each question as fresh and standalone. Do not reference or reconcile with any prior turn.
- Cite as [1], [2], etc., matching the numbered list in the user turn."""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


VERSION_TAG_RE = re.compile(r"\s*\((full|edited|short|trailer)\)\s*", re.I)


def base_title(title: str) -> str:
    return VERSION_TAG_RE.sub(" ", title).strip().lower()


def is_edited(title: str) -> bool:
    return "(edited)" in title.lower()


# The CSV has separate rows for the (Full) and (Edited) cuts of many interviews.
# Their embeddings land close together, so both versions used to surface as two
# near-identical citations. Collapse them to one card per interview and prefer
# the Edited cut for visitors.
PREFERRED_RID_BY_BASE: dict[str, int] = {}
for r in records:
    bt = base_title(r["title"])
    if bt not in PREFERRED_RID_BY_BASE or is_edited(r["title"]):
        PREFERRED_RID_BY_BASE[bt] = r["id"]

CHUNK_IDX_BY_RID: dict[int, int] = {c["record_id"]: i for i, c in enumerate(chunks)}


def retrieve(query: str, k: int = TOP_K):
    """Chunk-level retrieval, deduped to one card per interview (Edited preferred)."""
    result = voyage.embed([query], model="voyage-3-large", input_type="query")
    q = np.array(result.embeddings[0], dtype=np.float32)
    q /= np.linalg.norm(q)
    scores = norm_embeddings @ q
    top_idx = np.argsort(-scores)[:OVER_K]

    best_score_by_base: dict[str, float] = {}
    for idx in top_idx:
        idx = int(idx)
        bt = base_title(records[chunks[idx]["record_id"]]["title"])
        if bt not in best_score_by_base:
            best_score_by_base[bt] = float(scores[idx])

    ranked = sorted(best_score_by_base.items(), key=lambda kv: -kv[1])[:k]
    out = []
    for bt, _ in ranked:
        rid = PREFERRED_RID_BY_BASE[bt]
        cidx = CHUNK_IDX_BY_RID[rid]
        out.append((records[rid], chunks[cidx]))
    return out


def build_context(hits):
    lines = []
    for i, (record, chunk) in enumerate(hits, 1):
        meta = []
        if record.get("interviewee"):
            meta.append(f"Interviewee: {record['interviewee']}")
        if record.get("date_recorded"):
            meta.append(f"Recorded: {record['date_recorded']}")
        header = f"[{i}] {record['title']}"
        if chunk["has_transcript"]:
            body = f"Relevant transcript excerpt: \"{chunk['text'][:600]}\""
        else:
            body = f"Description: {record['description'][:400]}"
        lines.append(header + "\n" + "\n".join(meta) + "\n" + body)
    return "\n\n".join(lines)


CITE_RE = re.compile(r"\[(\d+)\]")


def cited_indices(answer: str) -> set[int]:
    return {int(m.group(1)) for m in CITE_RE.finditer(answer)}


def citation_payload(hits, cited: set[int]):
    out = []
    for i, (record, chunk) in enumerate(hits, 1):
        if i not in cited:
            continue
        vid = record.get("youtube_video_id")
        url = record.get("youtube_url")
        thumbnail = None
        start = 0
        if vid:
            thumbnail = f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
            if chunk["has_transcript"] and chunk["start_seconds"] > 0:
                start = int(chunk["start_seconds"])
                url = f"https://www.youtube.com/watch?v={vid}&t={start}s"
        out.append({
            "index": i,
            "title": record["title"],
            "interviewee": record.get("interviewee") or None,
            "date": record.get("date_recorded") or None,
            "youtube_url": url,
            "thumbnail_url": thumbnail,
            "start_seconds": start,
        })
    return out


app = FastAPI(title="KAS Archive Assistant")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/chat")
def chat(req: ChatRequest):
    hits = retrieve(req.message)
    user_turn = (
        f"Retrieved interviews:\n\n{build_context(hits)}\n\n"
        f"---\nVisitor's question: {req.message}"
    )

    try:
        resp = claude.messages.create(
            model=MODEL,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_turn}],
        )
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Claude API error: {e.message}")

    answer = "".join(b.text for b in resp.content if b.type == "text").strip()
    cited = cited_indices(answer)
    return {"answer": answer, "citations": citation_payload(hits, cited)}


app.mount("/widget", StaticFiles(directory=ROOT / "widget"), name="widget")


@app.get("/")
def root():
    return FileResponse(ROOT / "demo" / "index.html")


@app.get("/health")
def health():
    return {"status": "ok", "records": len(records), "chunks": len(chunks)}
