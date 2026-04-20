# KAS Archive Assistant

An AI chat widget that lets visitors to the Korean American Story Legacy Project site search the oral-history archive in plain English. Answers include direct links and thumbnails to the matching interviews on YouTube.

## What it does

A visitor clicks the chat icon in the bottom-right corner of the KAS homepage, types a question like *"Tell me about Korean War experiences"* or *"Stories about immigrating to Ohio"*, and the assistant replies with a brief 2-sentence answer and 3 clickable interview cards (with thumbnails) that link to the exact YouTube videos. A "See more" button reveals additional matches.

## Architecture

```
Browser                      Backend (Python)                  External APIs
-------                      ----------------                  -------------
widget (JS + CSS) ────POST────▶ FastAPI /api/chat
                                    │
                                    ├──▶ Voyage AI  (embed query → vector)
                                    │
                                    ├──▶ numpy cosine similarity against
                                    │    pre-computed embeddings of all
                                    │    ~820 interviews (records + chunks)
                                    │
                                    └──▶ Claude Haiku 4.5
                                         (generate 2-sentence answer with
                                         numbered citations)
                                    │
                                ◀─── JSON { answer, citations[] }
widget renders answer + citation cards
```

**Key components:**

| Path | What it is |
|---|---|
| `main.py` | FastAPI backend. One endpoint: `POST /api/chat`. Also serves the demo page at `/` and the widget files at `/widget/*`. |
| `widget/kaschat.js` + `kaschat.css` | The drop-in chat widget. Self-contained vanilla JS — no framework required. |
| `demo/index.html` | Mock KAS homepage for local testing. **Not used in production** — the live site is Squarespace. |
| `scripts/build_index.py` | One-time indexer. Reads the CSV, matches titles to YouTube videos, embeds descriptions with Voyage, saves to `data/`. |
| `data/` | Pre-built search index (records, chunks, embeddings). Checked into git so deployment doesn't need to re-index. |

**External services:**

- **Anthropic Claude Haiku 4.5** — generates the answer. Tiny per-query cost.
- **Voyage AI (voyage-3-large)** — embeddings for semantic search. Free tier covers KAS's expected traffic.
- **YouTube Data API v3** — used ONLY by the indexer to fetch the channel's video list. Not called at runtime.

---

## Local development

### Prerequisites
- Python 3.13 (Voyage's SDK doesn't support 3.14+ yet)
- A `.env` file at the project root with the three API keys:
  ```
  ANTHROPIC_API_KEY=sk-ant-...
  VOYAGE_API_KEY=pa-...
  YOUTUBE_API_KEY=AIza...
  KAS_YOUTUBE_HANDLE=KoreanAmericanStory
  ```

### Setup
```bash
git clone https://github.com/sophieliew/KASChatbot.git
cd KASChatbot
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run the indexer (only when the CSV changes)
```bash
python scripts/build_index.py
```
This rebuilds `data/records.json`, `data/chunks.json`, and `data/chunk_embeddings.npy`. Takes ~1 minute. It also caches the YouTube channel video list in `data/youtube_videos.json` so reruns are fast.

### Run the server
```bash
uvicorn main:app --reload
```
Open http://localhost:8000 — the demo page loads with the chat widget in the corner.

---

## Deployment

Any Python host with environment-variable support works. The backend is a standard ASGI FastAPI app.

### Required at runtime
- **Python 3.11+**
- **Environment variables:** `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`
- **Start command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Build command:** `pip install -r requirements.txt`

Note: The indexer needs `YOUTUBE_API_KEY` and `KAS_YOUTUBE_HANDLE` too, but those can be set temporarily for the one-off indexing run and don't need to live in production env.

### Recommended platforms

| Platform | Free tier? | Notes |
|---|---|---|
| **Render** | Yes (sleeps after 15 min idle, ~30 s cold start) | Easiest setup. $7/mo tier is always-on. |
| **Railway** | $5 credit/mo | Always-on. |
| **Fly.io** | Generous free | Always-on, needs a Dockerfile. |
| **Vercel** | Yes (serverless, cold-start penalty) | Free tier is non-commercial only; needs Pro ($20/mo) for production. |

### CORS
`main.py` allows all origins (`allow_origins=["*"]`). Once the production URL is known, tighten this to `https://koreanamericanstory.org` (or wherever KAS's site actually lives).

---

## Embedding the widget on the KAS Squarespace site

Squarespace allows custom HTML/CSS/JS via **Code Injection**. Requires a **Squarespace Business plan or higher** (Personal plan does not allow code injection).

### Steps

1. Log into Squarespace → KAS site.
2. **Settings → Advanced → Code Injection**.
3. In the **Footer** box, paste:

   ```html
   <link rel="stylesheet" href="https://YOUR-BACKEND-URL/widget/kaschat.css">
   <script src="https://YOUR-BACKEND-URL/widget/kaschat.js"></script>
   ```

   Replace `YOUR-BACKEND-URL` with the deployed backend's URL (e.g. `https://kaschat.onrender.com`). **No trailing slash.**

4. **Save.** The widget will appear in the bottom-right corner of every page on the site.

### To restrict to specific pages only
Instead of Code Injection, use a **Code Block** on just the pages where you want the widget. Paste the same two lines.

### Notes
- The widget self-attaches to the page — no CSS conflicts with Squarespace templates (selectors are all prefixed with `.kaschat-`).
- The backend must be served over **HTTPS** (Squarespace is HTTPS-only; browsers block mixed content).
- If the backend URL changes, update the two lines in Code Injection.

---

## Updating the interview data

When KAS adds new interviews or edits the CSV:

1. Replace `AI Chat Bot - KAS Legacy Project Metadata - LP Metadata_10212025.csv` with the new version (same filename, or update the path in `scripts/build_index.py`).
2. Delete `data/youtube_videos.json` if you want to re-fetch the channel video list (otherwise it'll use the cache).
3. Run `python scripts/build_index.py`.
4. Commit the changes under `data/` and redeploy.

No code changes needed.

---

## Estimated costs

Based on Haiku 4.5 and Voyage 3-large pricing as of deployment:

| Usage level | Est. monthly cost |
|---|---|
| 500 queries/month (light use) | ~$1.50 |
| 5,000 queries/month | ~$15 |
| 50,000 queries/month | ~$150 |

Hosting (Render $7, Railway ~$5) adds on top.

---

## Troubleshooting

**500 error on `/api/chat`:** Check backend logs for the stack trace. Most common causes: wrong `ANTHROPIC_API_KEY` / `VOYAGE_API_KEY`, or the data files missing from the deploy bundle.

**Widget loads but chat says "Could not reach the server":** Backend URL is wrong or CORS isn't allowing the origin. Check the browser DevTools Network tab.

**Chat returns irrelevant interviews:** The retrieval is based on the CSV descriptions. If newer interviews have thin descriptions, update the CSV and re-run the indexer.

**Response time is slow (>5 s):** Likely a cold start on a serverless/sleeping tier. Upgrade to an always-on plan.
