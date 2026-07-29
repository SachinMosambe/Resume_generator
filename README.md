# Resume Generator

Standalone app that generates client-formatted DOCX resumes from an uploaded candidate resume. Logic is ported from ATS-Engine; ATS-Engine itself is not modified.

## Stack

| Layer | Tech | Host |
|-------|------|------|
| UI | Next.js (App Router) + Tailwind | Vercel (free) |
| API | FastAPI + Bedrock + python-docx | Render (free) |

## Local development

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set AWS_BEARER_TOKEN_BEDROCK in .env
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open http://localhost:3000 — upload a resume, choose Aptino default or a client format, generate, and download the DOCX.

## API

- `GET /api/health` — health check
- `POST /api/generate` — multipart form:
  - `resume` (required): PDF/DOCX
  - `template_source`: `aptino_default` | `client_format`
  - `template` (required if client_format): PDF/DOCX
  - `client_name`, `job_role` (optional)
  - Response: DOCX file download

## Deploy (free tier)

### 1. Push to GitHub

Repo: `https://github.com/SachinMosambe/Resume_generator`

### 2. Backend on Render

1. New → Blueprint → select this repo (`render.yaml`), **or** New Web Service with root `backend`
2. Set env vars:
   - `AWS_BEARER_TOKEN_BEDROCK` (required)
   - `AWS_REGION` (e.g. `ap-south-1`)
   - `CORS_ORIGINS` = your Vercel URL (e.g. `https://your-app.vercel.app`)
3. Health check path: `/api/health`

**Note:** Free Render services sleep after ~15 minutes idle. The first request after sleep can take 30–60s; generation itself may take longer while Bedrock runs.

### 3. Frontend on Vercel

1. Import the GitHub repo
2. Root directory: `frontend`
3. Framework: Next.js
4. Env: `NEXT_PUBLIC_API_URL` = your Render URL (e.g. `https://resume-generator-api.onrender.com`)

### 4. CI

GitHub Actions (`.github/workflows/ci.yml`) builds the Next.js app and compiles the Python package on every push/PR to `main`. Deployments are handled by Vercel and Render Git integrations.

## Upgrade path

If Render cold starts or timeouts are painful, move the API to Railway Hobby (~$5 credit) without code changes — keep the same env vars and update `NEXT_PUBLIC_API_URL` / `CORS_ORIGINS`.
