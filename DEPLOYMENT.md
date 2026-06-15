# Deployment Guide — AI Resume Tailoring Engine V1
**AnalyticsShiksha · Prepared by Jatin Nair**

---

## PRE-FLIGHT CHECKLIST (before running locally)

### 1. Confirm Python version
```bash
python3 --version   # must be 3.9 or higher
```

### 2. Confirm all 7 project files exist
```bash
ls app.py agents.py prompts.py validators.py utils.py requirements.txt .env
```
All 7 must be present. Missing any one will cause an import error at startup.

### 3. Confirm `.env` is configured
```bash
cat .env
```
Expected output:
```
GEMINI_API_KEY=your_actual_key_here
DEBUG=false
```
Get a key at: https://aistudio.google.com/app/apikey  
Replace `your_actual_key_here` with your real key before running.

### 4. Confirm `.gitignore` covers secrets
```bash
grep -E "^\.env$|secrets\.toml" .gitignore
```
Both `.env` and `.streamlit/secrets.toml` must appear.  
**Do not push either file to GitHub.**

---

## LOCAL RUN

### Step 1 — Create and activate a virtual environment
```bash
python3 -m venv venv
source venv/bin/activate          # macOS / Linux
# venv\Scripts\activate           # Windows
```

### Step 2 — Install dependencies
```bash
pip install -r requirements.txt
```
Expected packages: `streamlit`, `google-generativeai>=0.8.0,<1.0.0`, `pypdf`, `python-dotenv`.

### Step 3 — Run the app
```bash
streamlit run app.py
```
Opens at `http://localhost:8501`

### Step 4 — Smoke test with real inputs
Test with one real PDF resume and one real job description before sharing.

**Confirm the following manually:**

- [ ] PDF uploads without error (text-based resume only)
- [ ] JD text area accepts a pasted job description
- [ ] Analyze button is disabled until both inputs are present
- [ ] All 4 agent spinners appear sequentially:
  - "Extracting JD requirements..."
  - "Reading your resume..."
  - "Running gap analysis..."
  - "Generating tailoring recommendations..."
- [ ] Section 3 (JD Analysis) renders: role, company, must-have skills, keywords
- [ ] Section 4 (Gap Analysis) renders: match score with progress bar, apply recommendation badge, strength areas, missing skills
- [ ] Section 5 (Tailored Recommendations) renders all subsections
- [ ] `cannot_address` block appears as an amber `st.warning()` box
- [ ] `st.code()` copy button works on experience and project rewrites
- [ ] Uploading a second PDF resets all results (change detection working)

---

## KNOWN V1 LIMITATIONS

Document these honestly to set user expectations before sharing the tool.

| Limitation | Detail |
|---|---|
| Text-based PDFs only | Scanned or image-based PDFs cannot be read by pypdf. Users must upload a digital/text PDF. The app shows a clear error message if a scanned PDF is detected. |
| JD URL scraping not supported | Job descriptions must be pasted as plain text. LinkedIn and Naukri scraping are out of scope for V1 due to reliability concerns. Planned for V2. |
| No authentication or user accounts | Anyone with the URL can use the app. User accounts are out of scope for V1. Planned for V3. |
| No export of tailored resume | The app generates suggestions only. Users must apply changes manually to their resume. PDF/DOCX export is planned for V2. |
| Same-filename same-size file edits may not reset | If a user edits a resume and saves it under the same filename with identical file size, the change detection signature (`name:size`) will not trigger a reset. Workaround: rename the file or reload the page. |
| No persistent storage between sessions | All results are cleared when the browser tab is closed or the page is refreshed. Session state lives only for the duration of the browser session. |
| Single resume per session | V1 supports one resume per session. Multi-resume management is planned for V3. |

---

## GITHUB SETUP

### Step 1 — Create repository
- Go to github.com → New repository
- Recommended name: `resume-tailoring-engine`
- Public or private — both work with Streamlit Community Cloud

### Step 2 — Verify .gitignore before first push
```bash
git status    # .env and .streamlit/secrets.toml must NOT appear
```
If either appears: stop. Add them to `.gitignore` before proceeding.

### Step 3 — Push code
```bash
git init
git add .
git commit -m "Initial commit — AI Resume Tailoring Engine V1"
git remote add origin https://github.com/your-username/resume-tailoring-engine.git
git push -u origin main
```

### Step 4 — Verify on GitHub
Confirm these files are **not** visible in the repository:
- `.env`
- `.streamlit/secrets.toml`

---

## STREAMLIT CLOUD DEPLOYMENT

### Step 1 — Connect repository
1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Sign in with GitHub
3. Click **New app**
4. Select your `resume-tailoring-engine` repository
5. Set **Main file path** to: `app.py`
6. Click **Advanced settings**

### Step 2 — Configure secrets
In the **Secrets** field, paste:
```toml
GEMINI_API_KEY = "your_actual_key_here"
```
Replace with your real Gemini API key. This is the cloud equivalent of `.env`.

### Step 3 — Deploy
Click **Deploy**. Streamlit installs `requirements.txt` automatically.  
First deployment takes ~2 minutes.

### Step 4 — Test the live URL
Before sharing with Anmol Sir or anyone else:
- [ ] Open the live URL in an incognito window
- [ ] Upload a real resume PDF
- [ ] Paste a real job description (minimum 200 characters)
- [ ] Complete a full analysis run
- [ ] Confirm results render correctly in all 3 sections
- [ ] Confirm `cannot_address` warning block appears
- [ ] Confirm copy button works on at least one rewrite

Only share the URL after this test passes end-to-end.

---

## POST-DEPLOYMENT MONITORING (first 20 runs)

Watch for these known edge cases during initial rollout:

| Issue | Likelihood | How It Is Handled |
|---|---|---|
| Gemini returns JSON wrapped in markdown fences | High | `parse_llm_json()` strips ` ```json ``` ` fences across 3 passes |
| Gemini returns JSON with explanatory prose prefix | Medium | Pass 3 brace-extraction fallback handles `"Here is the JSON:\n{...}"` |
| `match_score` returned as string not integer | Medium | `validate_gap_analysis()` catches type mismatch — triggers retry |
| `relevant_experience_score` outside discrete bands (e.g. 55) | Medium | `validate_gap_analysis()` rejects and retries — raises `LLMValidationError` after 2 attempts |
| PDF extraction false positive on valid resume | Low | Legitimate resume text < 100 chars is extremely unlikely; threshold chosen conservatively |
| Agent 4 timeout on very large resume + JD | Low | No explicit timeout in V1. If it occurs: advise user to shorten JD or resume before re-running |
| Rate limit hit during rapid repeated runs | Low | Caught as `ResourceExhausted` → user sees "Please wait 30 seconds" message |
| Gemini API downtime | Very low | Caught as `GoogleAPIError` → user sees retry message |

**If an error recurs consistently:** enable debug mode by setting `DEBUG=true` in `.env` (local) or Streamlit Secrets (cloud). The full exception traceback will appear below the user-facing error message.

---

## FILE INVENTORY

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI + pipeline orchestration |
| `agents.py` | 4 agent wiring functions |
| `prompts.py` | Frozen production prompts v1.0 (verbatim from spec) |
| `validators.py` | JSON schema validation for all 4 agents |
| `utils.py` | PDF extraction, model factory, retry logic, JSON parsing |
| `requirements.txt` | Pinned Python dependencies |
| `.env.example` | Template for local API key configuration |
| `.gitignore` | Excludes `.env`, `secrets.toml`, `__pycache__` |
| `.streamlit/secrets.toml` | Cloud API key template (gitignored) |
| `README.md` | Setup and run instructions |
| `DEPLOYMENT.md` | This file |

---

*AI Resume Tailoring Engine · V1 · AnalyticsShiksha · Deployment Guide*
