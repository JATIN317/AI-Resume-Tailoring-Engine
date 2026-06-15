# AI Resume Tailoring Engine — v1
**AnalyticsShiksha · Built by Jatin Nair**

---

## What It Does

Accepts a resume PDF and a job description, then runs 4 sequential AI agents to produce:
- Match score with weighted breakdown
- Apply recommendation (High / Medium / Low Fit)
- Gap analysis (missing skills, missing keywords)
- Tailored resume suggestions (summary, skills, experience bullets, projects)
- Gaps that cannot be closed through rewording (`cannot_address`)

---

## Quick Start (Local)

### 1. Clone the repository

```bash
git clone https://github.com/your-username/resume-tailoring-engine.git
cd resume-tailoring-engine
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure your API key

Copy the env template and fill in your Gemini API key:

```bash
cp .env.example .env
```

Edit `.env`:

```
GEMINI_API_KEY=your_actual_key_here
```

Get a key at: https://aistudio.google.com/app/apikey

### 5. Run the app

```bash
streamlit run app.py
```

The app opens at `http://localhost:8501`

---

## Deployment (Streamlit Community Cloud)

1. Push this repository to GitHub (public or private)
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repository
4. Set `GEMINI_API_KEY` under **Settings → Secrets**:
   ```
   GEMINI_API_KEY = "your_actual_key_here"
   ```
5. Deploy — Streamlit installs `requirements.txt` automatically

---

## Requirements

- Python 3.9+
- Text-based PDF resume (not scanned / image PDFs)
- Gemini API key (free tier sufficient for testing)

---

## File Structure

```
resume-tailoring-engine/
├── app.py           ← Streamlit UI + pipeline orchestration
├── agents.py        ← 4 agent functions
├── prompts.py       ← All 4 frozen system prompts (verbatim)
├── validators.py    ← JSON key validation + score bounds checking
├── utils.py         ← PDF extraction, JSON parsing, retry logic
├── requirements.txt
├── .env             ← Local API key (gitignored)
└── .streamlit/
    └── secrets.toml ← Cloud API key (gitignored)
```

---

## Notes

- Prompts are frozen (v1.0) and must not be modified without versioning
- All agents run at `temperature=0` for deterministic output
- Supports text-based PDFs only — scanned PDFs are not supported in V1
- V1 does not include export, authentication, or version tracking (see spec for V2+ roadmap)
