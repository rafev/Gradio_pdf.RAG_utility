# Paper Atlas: agentic RAG over scientific papers

A Claude-powered research agent that answers questions about a fixed (and growing) corpus of scientific papers. It draws on two sources:

- **Vector search** over passages from the papers, embedded locally on your GPU.
- **A knowledge graph** of the corpus: papers, methods, models, datasets, tasks, metrics, concepts, and typed relations between them (PROPOSES, USES, EXTENDS, EVALUATES_ON, OUTPERFORMS, CITES, …). Claude extracts it from every paper at ingest time.

The web UI is a live 3D map of that graph. As the agent searches and traverses, the papers and concepts it touches light up, and particles flow along the relations it follows. Answers stream in on the right, and every `[paper p.N]` citation can be clicked to read the source passage.

> The original single-PDF Gradio apps (Watsonx and Hugging Face) are preserved in [`legacy/`](legacy/).

## Architecture

```
corpus/papers/*.pdf
      │  python -m paper_rag.ingest   (incremental, hash-based)
      ├─ PyMuPDF text ─► section-aware chunks ─► bge-base (GPU, fp16) ─► Chroma      data/chroma/
      └─ full text ─► Claude structured extraction ─► entity merge ─► NetworkX KG     data/graph.json

python -m paper_rag.api  (FastAPI)
      ├─ /api/chat   SSE: Claude agent loop (adaptive thinking, parallel tools)
      │              tools: search_passages · list_papers · get_paper · find_entities
      │                     graph_neighbors · graph_path · papers_for_entity
      ├─ /api/graph, /api/node/…, /api/passage/…
      └─ serves frontend/dist (React + react-force-graph-3d + three.js bloom)
```

| Path | What |
|---|---|
| `src/paper_rag/ingest/` | PDF loading, chunking, embedder, Chroma store, Claude KG extraction, incremental pipeline |
| `src/paper_rag/graph/` | Knowledge graph: entity canonicalisation and aliasing, provenance per edge, queries, UI export |
| `src/paper_rag/agent/` | Tool definitions and implementations, system prompt, streaming agent loop |
| `src/paper_rag/api/` | Public app, admin console, access control (SQLite), SSE with heartbeats |
| `frontend/` | Vite + React + TypeScript UI (`index.html`) and admin console (`admin.html`) |
| `tests/` | pytest suite (no network: fake embedder, stubbed Claude) |

## Setup

Requirements: [uv](https://docs.astral.sh/uv/), Node 20+, and an NVIDIA GPU. The defaults fit comfortably in 8 GB of VRAM: the embedder peaks at about 250 MB. A CPU also works, just more slowly.

The venv and `.env` live outside the repo, in `C:\project_envs\Paper_Atlas` (override with `PAPER_ATLAS_ENV_ROOT`). Run the activation script in each new shell; it points uv at that venv and activates it:

```powershell
. .\scripts\activate.ps1
```

```bash
uv sync --extra dev                  # Python 3.12 venv, torch with CUDA 12.8
```

```bash
npm --prefix frontend install
```

```bash
npm --prefix frontend run build
```

Then copy `.env.example` to `C:\project_envs\Paper_Atlas\.env` and set `ANTHROPIC_API_KEY`. The app reads the `.env` next to the active venv, falling back to one at the repo root. The other settings in that file are optional: models, effort, embedder, and quotas.

## Build the corpus

Drop PDFs into `corpus/papers/`. The filename becomes the paper id used in citations. Then run:

```bash
uv run python -m paper_rag.ingest
```

- Re-running the command only processes new or changed PDFs.
- `--prune` removes papers whose PDF was deleted.
- `--only <file>` re-ingests a single PDF.
- `--rebuild` starts from scratch.
- `--no-kg` indexes text without calling Claude. A later normal run backfills the graph.

KG extraction makes one Claude call per paper. The prompt includes the entity names already in the corpus, so later papers reuse them and the graph merges instead of fragmenting.

## Run

**Local** (just you, no access gate):

```bash
uv run python -m paper_rag.api
```

Open http://127.0.0.1:8000.

**Public via Cloudflare quick tunnel** (visitors must be approved):

```powershell
.\scripts\serve.ps1 -Public
```

This starts:

- the app on `:8000`, which is the only port the tunnel exposes. It prints a `https://*.trycloudflare.com` URL to share.
- the **admin console** on `http://127.0.0.1:8001/?token=…`. This link is printed at startup and the token changes on every start. The console port is never tunnelled.

`cloudflared` is required for public mode. Install it with `winget install --id Cloudflare.cloudflared`.

### Access control in public mode

1. A visitor opens the public URL, enters a name and an optional reason, and waits.
2. The admin console shows the request live, with a browser notification and a sound. You choose **Approve** or **Deny**, and set how long the access lasts and how many questions it allows.
3. The visitor's page unlocks automatically and gets an HttpOnly session cookie. The server stores only a hash of it, and it can only be claimed by the browser that made the request.
4. The **Sessions** table shows each visitor's questions, tokens and estimated cost, with a **Revoke** button. **Pause public access** blocks all new requests and visitor chats instantly.
5. **Open app as admin** gives you an unlimited session in the gated app.

Built-in limits:

- at most 3 pending requests per IP and 50 pending in total;
- requests expire after 30 minutes;
- 2 concurrent chats globally, and 1 per session.

Cloudflare cuts responses that are idle for about 100 seconds. SSE sends a heartbeat every 15 s, so long agent runs survive.

## Development

```bash
uv run pytest
```

```bash
npm --prefix frontend test
```

```bash
npm --prefix frontend run dev
```

`npm run dev` starts Vite on http://127.0.0.1:5173 and proxies `/api` to `:8000` and `/admin/api` to `:8001`, so run the API alongside it.

Node colours: the seven entity types fold into three validated colour groups (methods and models; datasets, tasks and metrics; concepts and fields), plus white ringed nodes for papers. Seven separate hues could not be told apart reliably. The exact type always appears in tooltips, filters and node cards.
