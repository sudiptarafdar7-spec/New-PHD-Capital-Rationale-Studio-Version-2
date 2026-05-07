# PHD Capital Rationale Studio

PHD Capital Rationale Studio automates the generation of professional financial rationale reports from diverse data sources, including multimedia and text.

## Run & Operate
- **Run:** `flask run` (backend), `npm run dev` (frontend)
- **Build:** `npm run build` (frontend)
- **Typecheck:** `npm run typecheck`
- **Codegen:** _Populate as you build_
- **DB Push:** `flask db upgrade`
- **Required Env Vars:** `DATABASE_URL`, `JWT_SECRET_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`, `ASSEMBLYAI_API_KEY`

## Stack
- **Frontend:** React 18 (with TypeScript), Vite, Radix UI, Tailwind CSS
- **Backend:** Flask (Python 3.11), Flask-JWT-Extended, Flask-CORS, bcrypt
- **Database:** PostgreSQL (Neon)
- **ORM:** SQLAlchemy (implicit via Flask-SQLAlchemy)
- **Validation:** _Populate as you build_
- **Build Tool:** Vite

## Where things live
- **Frontend Source:** `src/`
- **Backend Source:** `backend/`
- **DB Schema:** `backend/models/`
- **API Contracts:** Defined by Flask API endpoints in `backend/api/`
- **Theme Files:** `tailwind.config.js`, `src/index.css`

## Architecture decisions
- **Unified `jobs` and `saved_rationale` tables:** For multi-tool compatibility and consistent status tracking.
- **Dual AI Provider Architecture (Gemini/OpenAI):** Leverages Gemini for stock extraction with grounding and OpenAI for general analysis.
- **Server-side Voice Typing with large Vosk Hindi model:** Voice Typing uses `vosk-model-hi-0.22` (~1.5 GB) — the LARGE Vosk Hindi acoustic model — for offline, on-server transcription. No external API, no per-minute cost. The Gemini 2.5 Pro engine (`transcribe_gemini.py`) is retained in the codebase as a legacy fallback but no live Voice Typing entry point imports it anymore. Trade-offs the user explicitly accepted by choosing Vosk: no speaker diarization (no `वक्ता 1:` labels), no automatic punctuation, code-switched Hindi/English may be transliterated rather than translated. See `backend/pipeline/voice_typing/transcribe_vosk.py`. The `ensure_model()` function downloads + extracts the model on first use under `backend/models/vosk/vosk-model-hi-0.22/` with an fcntl exclusive lock and `.complete` marker. `deploy.sh` (step 7/9) and `update.sh` (step 5b) pre-fetch the model on the VPS so the first Voice Typing job doesn't stall.
- **Intelligent CMP fallback and Chart Generation:** Robust logic for fetching market prices and generating charts, handling market hours and data availability.
- **Cross-Environment Path Resolution:** `backend/utils/path_utils.py` ensures file path compatibility across deployment environments.

## Product
- **Rationale Tools:** Supports Media (YouTube), Premium (AI text), Manual, and Bulk (batch text with translation) rationale generation.
- **Media Presence Workspace:** Tracks daily TV/YouTube appearances, processing via AI Transcribe or the full Media Rationale pipeline.
- **Voice Typing Tool:** Server-side transcription with reviewable stages and AI-powered arrangement, feeding into Bulk Rationale.
- **Live Transcribe Tool:** Real-time transcription of YouTube live streams, including speaker diarization and AI extraction of specific analyses.
- **User and API Key Management:** CRUD operations for users (Admin/Employee roles) and secure storage of external API keys.
- **PDF Template Management:** Configurable templates for standardized financial reports.
- **File Management:** Handles master CSVs, logos, custom fonts, and YouTube cookies.
- **Channel/Platform Management:** CRUD for various platforms with logo upload capabilities.
- **Stock Autocomplete:** Intelligent stock symbol autocomplete using master CSV data.

## User preferences
- Keep frontend design unchanged (layout, forms, fields, animations, effects, flow)
- Use Flask for backend REST API
- Use PostgreSQL for database
- JWT tokens for authentication
- Role-based access control (admin/employee)

## Ayushi AI Assistant
- Floating bottom-right chat widget (`src/components/AyushiAssistant.tsx`) mounted globally in `App.tsx` (auth-gated). Avatar `src/assets/ayushi.webp` with green pulsing live dot + red counter for failed jobs.
- Backend: `backend/api/assistant.py` (POST `/chat`, GET `/active-jobs`, GET `/job/<id>/diagnose`). System knowledge lives in `backend/services/assistant_doc.py` (`SYSTEM_DOC` + `build_system_prompt`).
- GPT-4o is forced to JSON via `response_format={'type':'json_object'}`. Returns `{message, actions[], suggestions[]}`. Actions are whitelisted server-side: `navigate`(only `PAGE_KEYS`), `highlight`(only `[data-tour='…']`), `wait`(0-5000ms).
- Tour anchors are `data-tour` attributes. Add new anchors **both** on the DOM element AND in `TOUR_ANCHORS` inside `assistant_doc.py`. Current set:
  - Sidebar nav: `nav-<pageKey>` for every page (dashboard, media-presence, voice-typing, ai-transcribe, live-transcribe, bulk-rationale, media-rationale, premium-rationale, manual-rationale, generate-chart, saved-rationale, profile, users, api-keys, pdf-template, upload-files, channel-logos).
  - Page CTAs: `mp-new-entry`, `vt-new`, `ait-new`, `lt-new`, `bulk-input`, `bulk-generate`, `premium-generate`, `chart-generate`, `users-new`, `channel-new`, `pdf-save`.
  - Upload Files cards: `upload-masterFile`, `upload-companyLogo`, `upload-youtubeCookies`.
  - API Keys cards: `api-openai`, `api-gemini`, `api-assemblyai`, `api-dhan`, `api-youtubedata`, `api-google_cloud`.
  - Dynamic: `job-view-<jobId>` on each Dashboard row's "View Details" button — AI substitutes `<jobId>` from `blob.jobId`.
- Selector validator in `assistant.py` accepts ANY `[data-tour='…']` (regex-only), so dynamic ids work without backend code changes — but the LLM only knows what's in `TOUR_ANCHORS`, so always update it.
- LLM call: `gpt-4o`, `temperature=0.25`, `max_tokens=1500`, `response_format=json_object`. Tokens were bumped from 900 to fit full multi-step tour plans.
- `SYSTEM_DOC` in `assistant_doc.py` contains a 25-entry tour playbook covering "make a YouTube rationale", "Bulk from text", "Premium", "single chart", "voice typing", "ai transcribe", "live transcribe", "where are my PDFs", diagnose-this-job, add user / channel / logo / cookies / master CSV / API keys, change password, activity log, etc. Extend by adding more numbered examples there — keep the JSON-action format identical.
- Auto-failure detection: widget polls `/active-jobs` every 30s; new failed jobs auto-pop the chat with the job pre-selected as `jobContextId` and a diagnosis prompt.
- **Step-by-step tour engine:** `runActions` collects all `highlight` actions into a numbered tour. Each highlight scrolls to the target, draws an animated emerald cutout (ring pulse + halo ping + bouncing arrow), and shows a bubble with `Step X of Y` + progress bar + Next/Done + Skip. The promise resolves on Next, Skip, **or when the user clicks the highlighted element itself** (capture-phase listener). Chat panel auto-collapses during the tour and re-opens on completion. Spotlight rect re-computes on `scroll`/`resize`. Keyframes (`ayushiRing`, `ayushiHalo`, `ayushiArrowDown/Up`, `ayushiPing`) are inline.
- **Tours are user-initiated, not auto-run.** Backend system prompt instructs GPT-4o to plan the **complete** multi-step tour from one user line. Frontend stores `pendingActions` on the chat message and renders a green **"Start tour · N steps"** button below the message — `runActions` only fires when the user clicks it. The button is one-shot (cleared from the message after click).
- **Markdown in chat:** assistant messages render via `react-markdown` (`MD` component in `AyushiAssistant.tsx`) with inline-styled components for paragraphs, lists, bold, code, links — never raw `**asterisks**` in the UI. User messages stay plain.
- Widget bubble + chat panel use **inline styles** (not Tailwind utilities) for `position/size/background/z-index` because Tailwind v4 in this project sometimes drops arbitrary `z-[9990]` and dynamic classes. Solid bg is `#0f172a` (slate-900). Don't switch back to bg utility classes unless you verify they survive the Tailwind v4 build.
- Click "pop" sound is synthesized via Web Audio (`playPop()` at top of `AyushiAssistant.tsx`); wired to bubble open, suggestion chips, send button, job-picker items. No audio asset shipped.
- Job titles in `/active-jobs` follow `Channel · DD-MM-YYYY · HH:MM` format (matching dashboard rows), falling back to `video_title` → `title` → `tool_used + short id`. Never `(untitled)`.

## Gotchas
- **Bulk Rationale "Edit Input":** Overwriting `bulk-input.txt` requires careful handling to reset the pipeline.
- **Voice Typing `RateLimitError`:** OpenAI `gpt-4o` large transcripts are chunked to avoid 429 errors.
- **Voice Typing requires the large Vosk Hindi model on disk (~2.8 GB extracted):** No external API key needed — transcription runs offline on the server. The model auto-downloads from `https://alphacephei.com/vosk/models/vosk-model-hi-0.22.zip` on first use and is cached under `backend/models/vosk/vosk-model-hi-0.22/`. On the VPS, `deploy.sh` and `update.sh` pre-fetch it so the first job doesn't wait. `GEMINI_API_KEY` and `ASSEMBLYAI_API_KEY` are NOT used by Voice Typing (Gemini is for stock extraction in Premium/AI; AssemblyAI is for AI Transcribe and Live Transcribe).
- **YouTube Embedding:** Use `getYouTubeEmbedUrl` from `src/lib/youtube-utils.ts` to prevent rendering issues; provide an "Open video" fallback for invalid URLs.
- **Sticky CSS-Grid Pitfall:** Wrap sticky elements in a non-sticky div within a grid to ensure correct behavior.
- **Voice Typing jobs list:** `list_jobs` LEFT JOINs the spawned Bulk Rationale child to surface `bulkJobStatus`/`bulkJobProgress`. Long error bodies are shown in a popup.
- **Unified job title format:** All jobs use `backend/utils/job_title.build_job_title` and are rendered with `<JobTitle>` for consistent branding.
- **AssemblyAI v3 streaming `speech_model` is mandatory:** The `assemblyai` SDK's `StreamingParameters` needs to be overridden to inject `speech_model=u3-rt-pro` for successful handshake.
- **Live Transcribe HLS capture (Python-driven):** Custom Python daemon thread in `_HLSSegmentFetcher` handles YouTube's raw ADTS-AAC segments, piping them to `ffmpeg` for transcription.
- **Live Transcribe lifecycle:** Implements a detailed status flow (`live`, `awaiting_review`, `extracting`, etc.) with `recover_orphans()` for worker recovery and specific speaker mapping.
- **AI Transcribe page is jobs-list + popup:** The main page is a list of jobs, with new job creation via a dialog, mirroring LiveTranscribe and VoiceTyping.
- **AI Transcribe 5-step review pipeline:** Standalone AI Transcribe jobs follow a 5-step Download → Transcribe → Translate → Extract → Send-to-Bulk pipeline with user review at each stage.
- **Voice Typing 5-step review pipeline:** Mirrors AI Transcribe — Transcribe (Vosk) → Review → Translate to English (GPT-4o, reuses `_translate_text` from `ai_transcribe_service`) → Review → Extract Pradip's Analysis (`arrange_transcript`) → Review → Send to Bulk. Statuses: `recording` → `awaiting_review` → `translating` → `awaiting_translate_review` → `arranging` → `awaiting_arrange_review` → `bulk_started`. Endpoints: `POST /jobs/<id>/translate`, `POST /jobs/<id>/arrange` (now consumes `translatedText`), `POST /jobs/<id>/send-to-bulk`. Right pane is a 3-tab UI (Transcript / Translation / Arrangement).
- **Bulk Step 4 review table:** Enforces canonical column order and enables auto-fill for stock data via Dhan Scrip Master lookup on `STOCK SYMBOL` blur/Enter.

## Pointers
- **React Context API:** [React Docs on Context](https://react.dev/learn/passing-props-with-context)
- **Radix UI:** [Radix UI Documentation](https://www.radix-ui.com/docs/)
- **Tailwind CSS:** [Tailwind CSS Documentation](https://tailwindcss.com/docs)
- **Flask Documentation:** [Flask Quickstart](https://flask.palletsprojects.com/en/latest/quickstart/)
- **Flask-JWT-Extended:** [Flask-JWT-Extended Documentation](https://flask-jwt-extended.readthedocs.io/en/stable/)
- **PostgreSQL:** [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- **Vosk ASR:** [Vosk API Documentation](https://alphacephei.com/vosk/api)
- **OpenAI API:** [OpenAI API Reference](https://platform.openai.com/docs/api-reference)
- **Google Gemini API:** [Google Gemini API Documentation](https://ai.google.dev/docs)
- **Dhan API:** [Dhan API Documentation](https://dhanhq.com/api/)