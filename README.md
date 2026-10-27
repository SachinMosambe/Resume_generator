# Resume Generator

Standalone app that generates client-formatted DOCX resumes from an uploaded candidate resume. Logic is ported from ATS-Engine; ATS-Engine itself is not modified.

## Stack

| Layer | Tech | Host |
|-------|------|------|
| UI | Next.js (App Router) + Tailwind | Vercel (free) |
| API | FastAPI + python-docx (Bedrock optional, off by default) | AWS EC2 (free tier) |

## Local development

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

No API keys are needed: the default faithful mode makes no LLM calls.

Tests and fidelity checks (synthetic fixtures only; no real resumes are committed):

```bash
pip install pytest
pytest
python scripts/fidelity_report.py            # per-fixture extraction/role/output counts
python scripts/fidelity_report.py --missing  # also list expected fixture facts missing from output
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
  - Response: DOCX file download with headers:
    - `X-Review-Status`: `passed` | `needs_review` | `failed` (see below)
    - `X-Review-Warnings`: URL-encoded JSON list of recruiter-facing warnings (never resume content)
    - `X-Saved-Format-Id` / `X-Saved-Format-Name` when a format was saved
  - 422 with an actionable message for scanned PDFs when OCR is not installed, and for
    oversized or overly complex DOCX archives

## Output fidelity

**Faithful mode (default).** Every parsed fact is kept: all roles (including promotions
and roles without bullets), all bullets, all education fields, all skills, and sections
the client format does not list (Publications, Volunteering, Patents, …) under their
original titles. The document grows to as many pages as the content needs. Text is not
rewritten; spellings such as `CapitalOne` stay as the candidate wrote them.

**Review status** comes from a mechanical check that compares normalized text of the
parsed source fields against the generated DOCX. It is a text-presence check, not a
semantic verification, and never a guarantee of 100% accuracy.

| Status | Meaning |
|--------|---------|
| `passed` | Every checked source field (employers, titles, dates, bullets, education, skills, certifications, other sections) was found in the output. Still skim before sending. |
| `needs_review` | Some fields were not found, pages were read with OCR, scanned pages could not be read, template sample text appeared, or a section was omitted by policy. Warnings say which. |
| `failed` | Fewer than half of the employers, titles, dates, or bullets reached the output, or the DOCX could not be opened. Do not send as-is. |

References sections are omitted from client documents by default; the omission is
reported as a warning rather than happening silently.

### Supported inputs

| Input | Support |
|-------|---------|
| Text-based PDF | Single column, two column, sidebar layouts (column bands are detected per page region; label/value tables and right-aligned dates are not mistaken for columns). Link targets such as a LinkedIn URL behind the word "LinkedIn" are kept. |
| DOCX | Body in document order, tables (merged cells deduplicated), text boxes, headers/footers, hyperlinks. Archives over 5000 entries or 100 MB uncompressed are rejected. |
| DOC | Converted with LibreOffice when installed (`setup-ec2.sh` installs it). |
| Scanned / image-only PDF pages | Read with Tesseract OCR when installed (Dockerfile and `setup-ec2.sh` install it). Without OCR, fully scanned PDFs get a 422 explaining what to upload instead; mixed PDFs keep their text pages and are marked `needs_review`. |

### Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `RESUME_OUTPUT_MODE` | `faithful` | `condensed` restores the legacy page-fit behaviour. |
| `RESUME_LLM_CONDENSE` | `false` | Condensed mode only: optional Bedrock polish. Requires `AWS_BEARER_TOKEN_BEDROCK`. |
| `RESUME_AGENT_PIPELINE` | `false` | Experimental agent pipeline. |
| `RESUME_OCR_ENABLED` | `true` | Use Tesseract for image-only pages when it is installed. |
| `RESUME_OCR_MAX_PAGES` | `10` | Pages OCR'd per upload; further scanned pages are reported as unread. |
| `RESUME_OCR_DPI` | `200` | OCR render resolution. |
| `RESUME_OCR_LANG` | `eng` | Tesseract language pack(s), e.g. `eng+deu`. |
| `TESSDATA_PREFIX` | auto | Only needed if Tesseract's language data is in a non-standard location. |

### Known limitations

- The review status is a string-presence check. It cannot tell whether a bullet was
  attached to the wrong role if the text itself is present.
- Section headings are recognized from a fixed vocabulary plus a list of common extra
  sections. An unusual heading that is in neither list is read as part of the previous
  section; its text is kept, but under that section.
- PDF client templates give approximate styling; DOCX templates are recommended.
- Page count is not predicted; faithful mode can produce longer documents than condensed mode.
- Graphic-heavy resumes (charts, skill bars, icons used as text, rotated text) may need review.
- OCR quality depends on scan quality; OCR'd documents are always marked `needs_review`.

### Privacy

- Logs record counts, statuses, and error types only; they do not record resume text,
  names, or contact details.
- Uploaded files are deleted after each request, but generated DOCX files are also
  written to `UPLOAD_DIR` (`upload_bytes_to_key`). Set a retention policy or clean that
  directory on a schedule if generated resumes must not persist on the server.
- Do not commit real resumes. Test fixtures are generated synthetically by
  `backend/tests/fixtures/build_fixtures.py`.

### Third-party licenses

| Component | License | Note |
|-----------|---------|------|
| PyMuPDF (already a dependency) | AGPL-3.0 or commercial | **Material.** Running modified AGPL code as a network service can trigger source-offer obligations. Confirm with legal, or buy a commercial license. Replacing it with pdfplumber/pypdf only would lower layout and OCR quality. |
| Tesseract OCR (system package) | Apache-2.0 | No fees. |
| LibreOffice (optional, `.doc` conversion) | MPL-2.0 | Runs as a separate process. |
| pdfplumber | MIT | |
| python-docx | MIT | |
| pypdf | BSD-3-Clause | |
| FastAPI | MIT | |

## Deploy (EC2 backend + Vercel frontend)

**Important:** pushing to GitHub does **not** update the live site by itself.
The Vercel UI only changes when Vercel redeploys; the API changes only after you
pull + restart on **EC2** (see below). Until EC2 is updated, uploads keep using
the old behavior.

### 1. Push to GitHub

Repo: `https://github.com/SachinMosambe/Resume_generator`

### 2. Backend on EC2

1. Launch Ubuntu 22.04 `t2.micro` / `t3.micro`
2. Security group inbound: **22** (SSH, your IP) and **8000** (HTTP, `0.0.0.0/0`)
3. SSH in, clone repo, run:

```bash
cd ~/Resume_generator/backend
bash deploy/setup-ec2.sh
nano .env   # set CORS_ORIGINS=https://your-app.vercel.app (Bedrock token only if using condensed mode)
sudo systemctl restart resume-api
```

4. Test: `http://YOUR_EC2_IP:8000/api/health`  
   Healthy response includes `build_id` and `output_mode: faithful`.

5. **After every code push**, update EC2:

```bash
cd ~/Resume_generator
bash backend/deploy/update-ec2.sh
curl -s http://127.0.0.1:8000/api/health
```

### 3. Frontend on Vercel

1. Import the GitHub repo
2. Root directory: `frontend`
3. Env: `NEXT_PUBLIC_API_URL` = `http://YOUR_EC2_IP:8000` (no trailing slash)
4. Deploy, then set EC2 `CORS_ORIGINS` to the Vercel URL and restart `resume-api`

### 4. CI

GitHub Actions (`.github/workflows/ci.yml`) builds the Next.js app and compiles the Python package on every push/PR to `main`.
