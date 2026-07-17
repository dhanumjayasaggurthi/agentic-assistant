# RDI AI — Research & Development Intelligence Platform

Enterprise-grade AI assistant for the JNJ RDI team. Full-stack app (FastAPI + React) over the JNJ GenAI Marketplace — giving your team a Claude.ai + Claude Code experience with Chat, Agent, Image Generation, Voice, document creation, live activity feed, and admin cost monitoring over 96 internal models.

---

## Features

### Chat Mode
- Stream responses from 96+ models: GPT-4.1, GPT-5, o3/o4, Claude (Bedrock), Llama, Gemini
- Markdown rendering with syntax-highlighted code blocks and copy buttons
- File attachments (PDF, DOCX, images, code files)
- Conversation history with rename and delete
- Voice input (mic → transcription) and voice output (🔊 TTS with 6 voices)
- **Export** conversation to PDF or DOCX
- **Dark / Light mode** toggle (persisted)

### Agent Mode
Full agentic AI loop with 15 tools and interactive Allow/Deny permission cards:

| Category | Tools |
|----------|-------|
| Files | read, write, create, delete, list, search |
| Code | run Python, run Shell |
| Documents | create PDF, create PowerPoint (.pptx with image embedding), create Word (.docx), create Excel (.xlsx) |
| Web | web search (DuckDuckGo), web crawl (Playwright JS-rendered + bs4 fallback) |
| Images | generate image (DALL-E / Imagen) — appears **inline in chat** |

Switch to the **Agent** tab in the topbar. Defaults to GPT-4.1 (function-calling capable).  
> **Note:** Codex models (gpt-5.x-codex-*) skip the tool loop and use single-completion Responses API. Always use a GPT-4.x or GPT-5 chat model in Agent mode.

### Image Generation
Select any Image model from the model picker (DALL-E gpt-image-2/1.5/1, Imagen):
- Type a prompt → image appears inline in chat
- Pick aspect ratio: 1:1 · 16:9 · 9:16
- Download button on every generated image

### Live Activity Feed (Tier 6)
- Sticky collapsible banner above the input bar shows real-time agent/chat progress
- Per-step icons: 🔗 Connecting, 💬 Streaming, 🐍 Running Python, 🌐 Web crawl, 📊 Creating PPTX, etc.
- Expands to full history; auto-fades 3.5 s after completion

### Per-Conversation Workspace (Tier 3)
- Each conversation gets its own isolated sandbox: `~/rdi-ai-workspace/{user_id}/{conv_id}/`
- **Cloud mode** (default): stored in the server's home directory
- **Local mode**: choose any path on the server (set via ☁️/🖥️ button in sidebar footer)
- Files panel previews (images, PDFs, text) are scoped to the active conversation

### Cross-Chat Reference (Tier 4)
- 🔗 toggle in the topbar — when ON, the agent sees summaries of your other conversations
- Useful for projects that span multiple chats (the agent can reference prior work)
- Stored per-conversation in the database; toggleable at any time

### Admin Panel
Visible only to `is_admin=1` users (⚙️ Admin button):
- **Users tab**: add users, reset passwords, enable/disable accounts
- **Usage tab**: per-user token counts and request totals
- **💰 Costs tab**: per-user, per-model cost breakdown; filter by 7/30/90 days; running totals

### Authentication
- Password login (`admin` / `Welcome@2026` by default)
- Microsoft Azure AD SSO via MSAL browser (configure `[sso]` in config.ini)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Uvicorn (async) |
| Real-time | FastAPI WebSocket — bidirectional streaming |
| Database | **PostgreSQL + asyncpg** (primary) · SQLite/aiosqlite (local dev fallback) |
| Vector store | pgvector extension — `embeddings` table ready for RAG |
| Auth | JWT (python-jose) + bcrypt + Azure AD SSO (MSAL 3.x) |
| Frontend | React 18 (CDN) + Babel Standalone — zero build step |
| Markdown | Marked.js + Prism.js syntax highlighting |
| Providers | AsyncAzureOpenAI, boto3 (Bedrock), google-genai (Vertex) |
| Agent tools | fpdf2, python-pptx, python-docx, openpyxl, playwright, beautifulsoup4 |

---

## Project Structure

```
RDI-AI-Assistant/
├── requirements.txt              asyncpg, aiosqlite, fastapi, openai, boto3, fpdf2, …
├── config.ini                    ← YOU provide this (API keys — not in repo)
├── create_project.py             Bootstrap script for new deployments
├── run.py                        Dev / prod launcher (see Run section)
├── backend/
│   ├── main.py                   FastAPI app — HTTP + WebSocket + admin + cost routes
│   ├── config.py                 INI config loader; env var overrides; DatabaseConfig
│   ├── auth.py                   JWT + bcrypt + SSO + is_active gate
│   ├── database.py               Dual PG/SQLite — schema, CRUD, usage_events, embeddings
│   ├── ws_handler.py             WebSocket session — chat, agent, image, TTS, activity feed
│   ├── providers/
│   │   ├── azure_chat.py         GPT-4.x, o-series streaming + Responses API (o3-pro)
│   │   ├── azure_gpt5.py         GPT-5 chat + Codex (Responses API); is_codex() helper
│   │   ├── azure_audio.py        TTS (6 voices) + transcription (Whisper)
│   │   ├── azure_image.py        DALL-E image generation
│   │   ├── azure_embedding.py    text-embedding-3-large
│   │   ├── bedrock.py            Claude, Llama via JNJ gateway (x-api-key hook)
│   │   └── vertex.py             Gemini chat + Imagen (raw HTTP)
│   └── agents/
│       ├── tools.py              15 tools + contextvar workspace + PPTX image embedding
│       ├── chat_agent.py         Provider routing + history trim + system_prefix (cross-chat)
│       └── coding_agent.py       Agentic tool loop + permission gate + pre_tool_callback
├── frontend/
│   ├── index.html                CDN shell (React 18, Babel, Marked, Prism, MSAL)
│   ├── css/app.css               Light theme design system + dark mode + activity feed styles
│   └── js/
│       ├── auth.js               JWT storage + MSAL SSO flow
│       ├── ws.js                 WebSocket client + auto-reconnect
│       └── app.js                Full React app — all components and WS event handlers
└── ~/rdi-ai-workspace/           Agent sandbox (outside project — no uvicorn restarts)
    └── {user_id}/
        └── {conv_id}/            Per-conversation isolation
```

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Create `config.ini` at project root

```ini
[azure_chat]
api_key      = YOUR_KEY
endpoint     = https://genaiapimna.jnj.com/openai-chat
api_version  = 2025-01-01-preview

[azure_gpt5]
api_key      = YOUR_KEY
endpoint     = https://genaiapimna.jnj.com/openai-gpt-5
api_version  = 2025-01-01-preview

[azure_image]
api_key      = YOUR_KEY
endpoint     = https://genaiapimna.jnj.com/openai-image
api_version  = 2025-01-01-preview

[azure_audio]
api_key      = YOUR_KEY
endpoint     = https://genaiapimna.jnj.com/openai-audio
api_version  = 2025-03-01-preview

[azure_embedding]
api_key      = YOUR_KEY
endpoint     = https://genaiapimna.jnj.com/openai-embeddings
api_version  = 2022-12-01

[bedrock]
api_key      = YOUR_KEY
endpoint     = https://genaiapigwna.jnj.com
region       = us-east-1

[vertex]
api_key      = YOUR_KEY
endpoint     = https://genaiapigcpna.jnj.com
project      = GenAI

[vertex_image]
api_key      = YOUR_KEY
endpoint     = https://genaiapigcpna.jnj.com
project      = GenAI

[app]
jwt_secret   = change-me-in-production
db_path      = rdi_ai.db

# Optional — PostgreSQL (recommended for production)
# Falls back to SQLite if omitted
[database]
host     = localhost
port     = 5432
name     = rdi_ai
user     = postgres
password = YOUR_PG_PASSWORD

# Optional — enables Microsoft SSO button
[sso]
tenant_id  = YOUR_AZURE_TENANT_ID
client_id  = YOUR_AZURE_CLIENT_ID
```

#### Environment variable overrides
| Variable | Overrides |
|----------|-----------|
| `RDI_DATABASE_URL` | Full asyncpg DSN, e.g. `postgresql://user:pass@host:5432/rdi_ai` |
| `RDI_WORKSPACE_DIR` | Workspace base path (default: `~/rdi-ai-workspace`) |
| `RDI_DB_PATH` | SQLite file path (default: `rdi_ai.db`) |

### 3. Run

```bash
# Development — auto-reload on backend/ and frontend/ changes only (workspace excluded)
python run.py          # no flag = dev mode
python run.py --dev    # explicit dev flag (same as above)

# Production — 4 workers, no reload
python run.py --prod

# Custom host/port
python run.py --port 9000 --workers 8

# Or directly with uvicorn
uvicorn backend.main:app --reload --reload-dir backend --reload-dir frontend --port 8000
```

Open **http://localhost:8000** — login: `admin` / `Welcome@2026`

---

## Critical JNJ API Rules

| Rule | Detail |
|------|--------|
| GPT-5 | `max_completion_tokens` — NOT `max_tokens` (will 400 error) |
| o-series | No system prompt — strip `role:system` before sending |
| Codex | Responses API only — `POST /openai/v1/responses` on `openai-gpt-5` endpoint |
| o3-pro | Also Responses API, but on `openai-chat` endpoint |
| Bedrock | Dummy AWS creds + `before-call` event hook injects `x-api-key` |
| Vertex | `HttpOptions(headers={"x-api-key": ...})` — not native GCP auth |
| Audio | Separate `openai-audio` endpoint, `api_version=2025-03-01-preview` |
| Embeddings | `api_version=2022-12-01` |

---

## PostgreSQL Setup (optional but recommended)

```sql
-- Create database and enable pgvector
CREATE DATABASE rdi_ai;
\c rdi_ai
CREATE EXTENSION IF NOT EXISTS vector;
```

Then set `[database]` in `config.ini` or `RDI_DATABASE_URL` env var. The app auto-creates all tables on startup.  
Without PostgreSQL, the app falls back to SQLite automatically (the `embeddings` table is skipped in SQLite mode).

---

## New Deployment

```bash
python create_project.py --dir C:\path\to\new\location
cd C:\path\to\new\location
# Copy config.ini with your keys
pip install -r requirements.txt
python run.py --prod
```

---

## Default Credentials

Default username is `admin`. The initial password is set during first-time setup via `create_project.py` and stored in your `config.ini` — it is never committed to the repository.

Change the password immediately after first login via the Admin panel.

---

## Roadmap / Pending

- [x] Admin panel — user management, usage stats per user
- [x] Admin cost monitoring — per-user, per-model cost breakdown with time filters
- [x] Dark / light mode toggle in UI
- [x] Inline file preview (view created PDF/DOCX/image without downloading)
- [x] Conversation export to PDF or DOCX
- [x] Image display when agent uses `generate_image` tool (inline in chat)
- [x] Playwright web crawl (JS-rendered pages)
- [x] PostgreSQL + pgvector support (dual PG/SQLite)
- [x] Per-conversation workspace isolation (`{user_id}/{conv_id}/`)
- [x] Cross-chat reference toggle (agent sees summaries of other conversations)
- [x] Live activity feed (real-time step-by-step progress indicator)
- [x] PPTX image embedding (`image_path` + `layout` fields in create_pptx tool)
- [x] Dev/prod run script (`run.py`) with correct `--reload-dir` to exclude workspace
- [ ] RAG pipeline — upload docs to knowledge base, chunk, embed, pgvector store, inject context (`embeddings` table + `azure_embedding.py` already in place)
- [ ] SSO end-to-end test with JNJ Azure AD
- [ ] Rate limiting per user
