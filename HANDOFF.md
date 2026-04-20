# KAS Archive Assistant — Handoff Notes

For the KAS web development team inheriting this prototype.

This doc covers the state of the project, what's been decided, what's outstanding, and what you need to do to get it live on the KAS Squarespace site. Pair it with `README.md` for technical setup.

---

## Current status

- **Working prototype.** Full chat flow is functional: question → retrieval over ~820 interviews → 2-sentence answer with 3 cited interview cards + thumbnails linking to YouTube.
- **Running locally and on a demo deploy** (URL shared separately). Production hosting is your decision.
- **All code + index data in this GitHub repo.** The `data/` folder contains a pre-built search index so you don't need to re-index unless the interview CSV changes.

## What's been built

1. **Python FastAPI backend** (`main.py`) — one endpoint, `POST /api/chat`. Takes a user question, returns a JSON answer + citations.
2. **Vanilla-JS chat widget** (`widget/kaschat.js` + `kaschat.css`) — floating icon bottom-right, expands to a side panel. No framework dependencies. Drops into any HTML page (including Squarespace) with two lines.
3. **One-time indexer** (`scripts/build_index.py`) — reads the master CSV, matches each interview title to its YouTube video via the YouTube Data API, embeds descriptions with Voyage AI, saves to `data/`.
4. **Demo page** (`demo/index.html`) — for local testing only. Not used on the live Squarespace site.

## Key decisions made (and why)

| Decision | Reason |
|---|---|
| **Claude Haiku 4.5** as the answer model | Fastest Anthropic model, roughly $1/1M input tokens. Responses land in ~1 s. Earlier Opus 4.7 tests were higher quality but took 3–5 s and cost 5× more. |
| **Voyage AI voyage-3-large** for embeddings | Anthropic's recommended embedding partner. Quality is excellent for this dataset size. Free tier (200M tokens) covers KAS's traffic for many months. |
| **Each question is stateless — no chat history passed back** | Earlier prototype had Claude seeing prior turns, which caused it to contradict itself on unrelated follow-up questions. Stateless is correct for a search assistant. |
| **Max 3 citation cards shown, with "See more" toggle** | Keeps focus on the interviews, not the chatbot. Feedback from KAS leadership. |
| **YouTube links go to video start, no timestamps** | Originally planned to deep-link to the moment the topic was discussed, but required scraping ~820 YouTube transcripts, which YouTube's bot protection blocked. Retrieving against descriptions instead is simpler and works reliably. If timestamps become a priority later, a residential proxy service like WebShare (~$5/mo) would unblock it. |

## Known limitations

- **Retrieval quality depends on CSV description quality.** Interviews with thin descriptions (one-liners) are harder to find. Worth a content pass on the CSV if specific interviews aren't surfacing.
- **8 CSV interviews didn't match a YouTube video** (fuzzy title matching at 72% threshold). These still show up in answers but without a working YouTube link. Acceptable for a prototype; if it's a concern, a manual title-→-video ID lookup could fix the unmatched 8.
- **No rate limiting.** The current backend will answer as many requests as it receives. For a public Squarespace site, worth adding a simple per-IP throttle (e.g., 30 requests/minute) before going live.
- **No analytics.** No tracking of what people ask or click. Easy to add with Google Analytics events or a simple logging table — recommended before a wider launch so KAS can see what visitors are actually searching for.

---

## Your action items

### 1. Get the secrets
Separately from this repo, you'll receive:
- `ANTHROPIC_API_KEY` — the Claude API key
- `VOYAGE_API_KEY` — the Voyage AI key
- `YOUTUBE_API_KEY` — only needed if you re-run the indexer with a new CSV

Store them in a password manager (1Password, etc.). Never commit them to git.

### 2. Decide on hosting
The backend needs a Python host. Options from simplest to most robust:

- **Render** (free tier, sleeps after 15 min idle — first request after sleep takes ~30 s; $7/mo tier is always-on) — easiest setup
- **Railway** (~$5/mo after free credit, always-on)
- **Fly.io** (generous free tier, needs a Dockerfile)
- **KAS's existing infrastructure** if they have a Python-capable server already

Render is fine for launch. Upgrade the plan if the 30-s cold start becomes a complaint.

### 3. Deploy the backend
See **Deployment** in `README.md`. The start command is:
```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Set `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` as environment variables in the host's dashboard.

Verify with a test request:
```bash
curl -X POST https://YOUR-BACKEND-URL/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Korean War stories"}'
```
Should return a JSON object with `answer` and `citations`.

### 4. Tighten CORS
Edit `main.py` line ~146, change `allow_origins=["*"]` to:
```python
allow_origins=["https://www.koreanamericanstory.org"]  # or wherever KAS actually lives
```
Redeploy.

### 5. Embed on Squarespace
See **Embedding the widget on the KAS Squarespace site** in `README.md`. Short version: Settings → Advanced → Code Injection → Footer, paste two lines with your backend URL, save.

Squarespace **Business plan or higher is required** for Code Injection — confirm KAS has this.

### 6. (Optional) Add rate limiting and analytics before going public
- **Rate limiting:** `slowapi` is a 1-file add-on for FastAPI. ~10 lines of code.
- **Analytics:** either pipe chat questions to a simple logging table, or fire a Google Analytics event from the widget on each submission.

Not strictly required for launch, but strongly recommended.

---

## Monthly cost estimate

Assuming 2,000 visitor questions/month (a reasonable early-launch volume):

| Service | Est. cost |
|---|---|
| Anthropic (Claude Haiku 4.5) | ~$6 |
| Voyage AI embeddings | ~$0 (free tier covers it) |
| Backend hosting (Render paid / Railway) | $5–$7 |
| **Total** | **~$12/month** |

Scales roughly linearly with traffic. 20K queries/month → ~$60. Worth checking in on after launch.

---

## If something's unclear

The repo has inline comments where they matter. The `README.md` covers setup and deployment in more detail. For anything not covered, reach out to [your contact] — happy to answer questions during the transition.
