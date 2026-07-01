# ResumeIQ — AI Resume Tailoring Engine
**Built by Jatin Nair · AnalyticsShiksha · v3.3-stable**

> *"Given this resume and this JD — should I apply, why, and what truthful changes maximize my chances?"*

---

## What It Does

ResumeIQ accepts a resume PDF and a job description, runs 4 sequential AI agents, and produces a structured career fit report:

- **Match score** with weighted breakdown (must-haves 60%, good-to-haves 20%, experience 15%, keywords 5%)
- **Fit recommendation** — High / Medium / Low Fit with explicit reasoning
- **Gap analysis** — missing skills, missing keywords, experience gaps
- **Strategic positioning summary** — how to present your candidacy for this specific role
- **Tailored resume rewrites** — summary, skills section, experience bullets, project descriptions
- **Gaps that cannot be closed** (`cannot_address`) — skills the engine will never fabricate

---

## Why It's Different

Most resume tools rewrite your resume to sound better. ResumeIQ refuses to invent skills you don't have. Every recommendation traces to evidence in your resume. If a skill is missing, the engine says so — it doesn't add "Snowflake" to your profile because the JD mentioned it. The `cannot_address` field exists precisely to tell you what can't be fixed through rewording, so you can make an honest decision about whether to apply.

The engine was built and evaluated against an 8-case golden dataset with a weighted rubric and a 5-rule anti-hallucination gate. See [`docs/Evaluation_Framework.md`](docs/Evaluation_Framework.md) for methodology.

---

## Architecture

4 agents run sequentially. Each has one responsibility — mixing extraction, scoring, and creative rewriting in one prompt degrades all three.

| Agent | Responsibility |
|---|---|
| **JD Analyzer** | Extracts must-have skills, good-to-haves, responsibilities, keywords, and qualifier examples from the JD |
| **Resume Analyzer** | Extracts candidate profile — tools, skills, experience, keywords — with no inference |
| **Gap Analyzer** | Scores the match using the weighted model; identifies strength areas and genuine gaps |
| **Tailoring Agent** | Generates evidence-only recommendations; blocked by an inference gate from fabricating adjacent skills |

All agents return structured JSON only. This allows the UI to render each section independently, validators to check required keys, and the `cannot_address` field to be machine-readable.

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Streamlit |
| LLM | Gemini 2.5 Flash (`temperature=0`) |
| PDF Extraction | pypdf |
| JSON Parsing | Custom 3-pass parser with fence-stripping and brace extraction |
| Validation | Custom validators.py — required key checks and score bounds |
| Language | Python 3.9+ |

---

## Quick Start (Local)

### 1. Clone the repository
```bash
git clone https://github.com/JATIN317/AI-Resume-Tailoring-Engine.git
cd AI-Resume-Tailoring-Engine
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
```bash
cp .env.example .env
```

Edit `.env`:
```
GEMINI_API_KEY=your_actual_key_here
```

Get a free key at: https://aistudio.google.com/app/apikey

> **Note:** Free tier is sufficient for testing. For sustained use across multiple resumes, enable billing — Gemini 2.5 Flash costs approximately $0.075 per 1M input tokens. A single analysis run uses roughly 8,000–12,000 tokens across all 4 agents.

### 5. Run the app
```bash
streamlit run app.py
```

Opens at `http://localhost:8501`

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

## File Structure

```
AI-Resume-Tailoring-Engine/
├── app.py              ← Streamlit UI + pipeline orchestration
├── agents.py           ← 4 agent functions
├── prompts.py          ← System prompts + user message constructors (v3.3)
├── validators.py       ← JSON key validation + score bounds checking
├── utils.py            ← PDF extraction, JSON parsing, retry logic
├── requirements.txt
├── .env.example        ← API key template
├── CHANGELOG.md        ← Version history
└── docs/
    ├── Engineering_Decisions.md   ← Debugging methodology and root cause analyses
    └── Evaluation_Framework.md   ← Golden dataset, rubric, and evaluation process
```

---

## Evaluation Methodology

ResumeIQ was evaluated against a structured golden dataset before each release:

- **8 test cases** — 4 resume profiles × 7 real job descriptions
- **Deliberately includes** 2 LOW FIT cases (overqualification + domain mismatch) to verify the engine rejects correctly, not just scores highly
- **8-dimension weighted rubric** — JD Understanding, Gap Analysis, Rewrites, Keyword Strategy, Prioritization, UX, Explainability, Recruiter Value
- **5-rule anti-hallucination gate** — hard overrides that cap dimension scores or the entire run when fabrication is detected
- **Pattern tracker** — 15 patterns discovered, diagnosed, and resolved across V1→V3.3

Full methodology: [`docs/Evaluation_Framework.md`](docs/Evaluation_Framework.md)

---

## Requirements

- Python 3.9+
- Text-based PDF resume (scanned / image PDFs not supported)
- Gemini API key

---

## V4 Roadmap

- **AI-Generated PDF Resume** — apply tailoring recommendations and produce a downloadable, ATS-safe resume PDF using ReportLab
- **JD URL Extraction** — paste a job posting URL instead of JD text; LinkedIn URLs will fall back to manual paste with a clear message

---

## Docs

- [`docs/Engineering_Decisions.md`](docs/Engineering_Decisions.md) — root cause analyses for P08, P14, P15; debugging methodology
- [`docs/Evaluation_Framework.md`](docs/Evaluation_Framework.md) — evaluation design, rubric, pattern tracker summary

---

*ResumeIQ · AnalyticsShiksha · Built by Jatin Nair*
