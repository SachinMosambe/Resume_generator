# Resume Generator

Standalone app that generates client-formatted DOCX resumes from an uploaded candidate resume. Logic is ported from ATS-Engine; ATS-Engine itself is not modified.

## Stack

| Layer | Tech | Host |
|-------|------|------|
| UI | Next.js (App Router) + Tailwind | Vercel (free) |
| API | FastAPI + Bedrock + python-docx | AWS EC2 (free tier) |

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
- `GET /api/formats` — list saved company format profiles
- `POST /api/formats` — upload PDF/DOC/DOCX format, extract + save profile
- `GET /api/formats/{id}` — format detail + schema preview
- `DELETE /api/formats/{id}` — delete saved format
- `POST /api/generate` — multipart form:
  - `resume` (required): PDF/DOC/DOCX
  - `template_source`: `aptino_default` | `client_format` | `saved_format`
  - `template` (required if client_format): PDF/DOC/DOCX company format
  - `format_id` (required if saved_format): saved profile id
  - `save_format` (optional): `true` to persist an uploaded client format
  - `format_name` (optional): name when saving
  - `client_name`, `job_role` (optional)
  - Response: DOCX file download (may include `X-Saved-Format-Id` header)

## Deploy (EC2 backend + Vercel frontend)

### 1. Push to GitHub

Repo: `https://github.com/SachinMosambe/Resume_generator`

### 2. Backend on EC2

1. Launch Ubuntu 22.04 `t2.micro` / `t3.micro`
2. Security group inbound: **22** (SSH, your IP) and **8000** (HTTP, `0.0.0.0/0`)
3. SSH in, clone repo, run:

```bash
cd ~/Resume_generator/backend
bash deploy/setup-ec2.sh
nano .env   # set AWS_BEARER_TOKEN_BEDROCK + CORS_ORIGINS=https://your-app.vercel.app
sudo systemctl restart resume-api
```

4. Test: `http://YOUR_EC2_IP:8000/api/health`

### 3. Frontend on Vercel

1. Import the GitHub repo
2. Root directory: `frontend`
3. Env: `NEXT_PUBLIC_API_URL` = `http://YOUR_EC2_IP:8000` (no trailing slash)
4. Deploy, then set EC2 `CORS_ORIGINS` to the Vercel URL and restart `resume-api`

### 4. CI

GitHub Actions (`.github/workflows/ci.yml`) builds the Next.js app and compiles the Python package on every push/PR to `main`.
