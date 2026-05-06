# PHD Capital Rationale Studio

Internal tool that automates production of professional financial-rationale PDF
reports from YouTube videos, audio recordings, live streams, and bulk text input.

- **Frontend** — React 18 + TypeScript + Vite + Tailwind + Radix UI
- **Backend** — Flask (Python 3.11) + JWT auth + PostgreSQL
- **AI** — OpenAI GPT-4o, Google Gemini 2.5 Pro, AssemblyAI, Dhan market data

---

## Quick start (local development)

```bash
# Backend
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://user:pass@localhost:5432/phd_dev
python -m backend.app                # runs on :8000

# Frontend (new terminal)
npm install
npm run dev                          # runs on :5000, proxies /api → :8000
```

Default seeded admin (created by `python -m backend.seed_data`):
`admin@phdcapital.in` / `admin123`

---

## Production deployment

One-line installer for `new.researchrationale.in` — see [DEPLOYMENT.md](./DEPLOYMENT.md):

```bash
curl -fsSL https://raw.githubusercontent.com/sudiptarafdar7-spec/New-PHD-Capital-Rationale-Studio-Version-2/main/deploy.sh | sudo bash
```

For subsequent updates (after first install), use the faster `update.sh`:

```bash
curl -fsSL https://raw.githubusercontent.com/sudiptarafdar7-spec/New-PHD-Capital-Rationale-Studio-Version-2/main/update.sh | sudo bash
```

---

## Repo layout

```
src/                React frontend (pages, components, lib, assets)
backend/
  api/              Flask blueprints (auth, jobs, rationales, assistant, …)
  pipeline/         Long-running workers (voice typing, live transcribe, bulk, premium)
  services/         Shared services (assistant doc, manual_v2)
  utils/            DB, path, OpenAI/Gemini config helpers
  models/           SQLAlchemy-style helper models
  migrations/       Idempotent SQL upgrade scripts
deploy.sh           One-line VPS installer (FRESH or UPGRADE)
DEPLOYMENT.md       Production deployment guide
replit.md           Architecture notes & gotchas (read this!)
```
# New-PHD-Capital-Rationale-Studio-Version-2
