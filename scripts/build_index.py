"""
One-time indexer. Run this once after setting keys in .env:

    python scripts/build_index.py

Writes:
  data/youtube_videos.json   — cached list of channel videos
  data/records.json          — interview metadata (from CSV + YouTube match)
  data/chunks.json           — one searchable chunk per interview
  data/chunk_embeddings.npy  — Voyage embeddings aligned with chunks.json

Rerun when the CSV or channel changes.
"""

import csv
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import voyageai
from dotenv import load_dotenv
from googleapiclient.discovery import build
from rapidfuzz import fuzz, process

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
CSV_PATH = ROOT / "AI Chat Bot - KAS Legacy Project Metadata - LP Metadata_10212025.csv"
YT_CACHE = DATA / "youtube_videos.json"

EMBED_BATCH = 128

load_dotenv(ROOT / ".env")
VOYAGE_KEY = os.environ.get("VOYAGE_API_KEY", "")
YT_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YT_HANDLE = os.environ.get("KAS_YOUTUBE_HANDLE", "KoreanAmericanStory")

if not VOYAGE_KEY:
    sys.exit("VOYAGE_API_KEY missing from .env")
if not YT_KEY:
    sys.exit("YOUTUBE_API_KEY missing from .env")


def normalize_title(s: str) -> str:
    s = re.sub(r"\s*\((full|edited|short|trailer)\)\s*", " ", s, flags=re.I)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def extract_interviewee(contributor: str) -> str:
    if not contributor:
        return ""
    for part in contributor.split(";"):
        if "interviewee" in part.lower():
            return re.sub(r",?\s*interviewee\s*$", "", part, flags=re.I).strip()
    return ""


def fetch_all_videos():
    if YT_CACHE.exists():
        print(f"Using cached YouTube list: {YT_CACHE}")
        return json.loads(YT_CACHE.read_text())

    print(f"Fetching videos from @{YT_HANDLE}...")
    yt = build("youtube", "v3", developerKey=YT_KEY)
    ch = yt.channels().list(part="contentDetails", forHandle=YT_HANDLE).execute()
    if not ch.get("items"):
        sys.exit(f"Channel @{YT_HANDLE} not found")
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    videos = []
    page_token = None
    while True:
        resp = yt.playlistItems().list(
            playlistId=uploads, part="snippet", maxResults=50, pageToken=page_token,
        ).execute()
        for item in resp["items"]:
            videos.append({
                "id": item["snippet"]["resourceId"]["videoId"],
                "title": item["snippet"]["title"],
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    YT_CACHE.write_text(json.dumps(videos, indent=2))
    print(f"Fetched {len(videos)} videos, cached to {YT_CACHE}")
    return videos


def load_records():
    print(f"Reading {CSV_PATH.name}...")
    records = []
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = (row.get("Title") or "").strip()
            if not title:
                continue
            records.append({
                "id": len(records),
                "title": title,
                "description": (row.get("Description") or "").strip(),
                "series": (row.get("Series") or "").strip(),
                "contributor": (row.get("Contributor") or "").strip(),
                "creator": (row.get("Creator") or "").strip(),
                "date_recorded": (row.get("Date Recorded") or "").strip(),
                "keywords": (row.get("Keywords") or "").strip(),
                "interviewee": extract_interviewee(row.get("Contributor") or ""),
            })
    print(f"Loaded {len(records)} records")
    return records


def match_youtube(records, videos):
    yt_titles_norm = [normalize_title(v["title"]) for v in videos]
    matched = 0
    for r in records:
        hit = process.extractOne(
            normalize_title(r["title"]),
            yt_titles_norm,
            scorer=fuzz.WRatio,
            score_cutoff=72,
        )
        if hit:
            _, _, idx = hit
            r["youtube_video_id"] = videos[idx]["id"]
            r["youtube_url"] = f"https://www.youtube.com/watch?v={videos[idx]['id']}"
            matched += 1
        else:
            r["youtube_video_id"] = None
            r["youtube_url"] = None
    print(f"Matched {matched}/{len(records)} records to YouTube videos")


def build_chunks(records):
    """One searchable chunk per record, built from its description + metadata."""
    chunks = []
    for r in records:
        parts = [r["title"]]
        if r.get("interviewee"):
            parts.append(f"Interviewee: {r['interviewee']}")
        if r.get("description"):
            parts.append(r["description"])
        if r.get("keywords"):
            parts.append(f"Keywords: {r['keywords']}")
        chunks.append({
            "record_id": r["id"],
            "start_seconds": 0,
            "text": "\n".join(parts),
            "has_transcript": False,
        })
    return chunks


def embed_chunks(chunks):
    vo = voyageai.Client(api_key=VOYAGE_KEY)
    print(f"Embedding {len(chunks)} chunks with voyage-3-large...")
    embeddings = []
    for i in range(0, len(chunks), EMBED_BATCH):
        batch = [c["text"] for c in chunks[i:i + EMBED_BATCH]]
        result = vo.embed(batch, model="voyage-3-large", input_type="document")
        embeddings.extend(result.embeddings)
        print(f"  {min(i + EMBED_BATCH, len(chunks))}/{len(chunks)}")
    return np.array(embeddings, dtype=np.float32)


def main():
    DATA.mkdir(exist_ok=True)
    videos = fetch_all_videos()
    records = load_records()
    match_youtube(records, videos)
    chunks = build_chunks(records)
    embeddings = embed_chunks(chunks)

    (DATA / "records.json").write_text(json.dumps(records, indent=2, ensure_ascii=False))
    (DATA / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False))
    np.save(DATA / "chunk_embeddings.npy", embeddings)
    print(f"\nDone. {len(records)} records, {len(chunks)} chunks, embeddings shape {embeddings.shape}")


if __name__ == "__main__":
    main()
