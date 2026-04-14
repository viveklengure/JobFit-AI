# JobFit AI — Smart Job Application Assistant

Paste a job URL and get 6 tailored outputs in ~60 seconds: a Word resume, a PDF resume, a cover letter, a hiring manager LinkedIn message, a referral blurb, and an ATS gap analysis.

Everything is driven by documents you provide — no hardcoded personal data anywhere.

---

## What JobFit AI does

1. **Scrapes** a job posting URL (LinkedIn, Indeed, Greenhouse, Lever, Workday, Naukri, generic pages)
2. **Analyzes** the JD against your profile: match score, matched skills, gap skills, key themes
3. **Gives a verdict** — Claude tells you whether to apply, with honest reasoning
4. **Generates** tailored content via Claude: summary, cover letter, outreach messages
5. **Builds** a formatted Word resume (.docx) and PDF using only the most relevant bullets per role

---

## Setup

```bash
cd jobfit-ai
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
npm install -g docx             # Required for Word resume generation
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

**Dependencies:**
- Python 3.9+
- Node.js (for Word resume) — install from https://nodejs.org
- LibreOffice (for PDF export) — install from https://www.libreoffice.org *(optional)*

---

## How to use

1. **Add your documents** to the `docs/` folder (see `docs/README.md`)
2. **Run the app:**
   ```bash
   python run.py       # then select Option 1
   # or directly:
   streamlit run app.py
   ```
3. **Paste a job URL** and click **Analyze & Generate**

---

## Supported document types

| File | Purpose |
|------|---------|
| `resume.pdf` / `resume.docx` | Main resume |
| `work_stories.txt` / `.docx` / `.pdf` | STAR format achievements |
| `about_me.txt` / `.docx` | Elevator pitch |
| `bio.txt` / `.docx` | LinkedIn bio / narrative |
| Any `.pdf`, `.docx`, `.txt` | The app reads everything |

All documents are merged into one unified context before generating any output.

---

## Claude's Verdict

After analyzing the JD, Claude returns one of four verdicts displayed as a banner at the top of the Match Analysis tab:

| Verdict | Criteria |
|---------|----------|
| 🟢 **Strong Apply** | Match score ≥ 75, no critical gaps |
| 🔵 **Apply** | Match score 55–74, minor gaps |
| 🟡 **Apply with Caution** | Match score 35–54, significant but addressable gaps |
| 🔴 **Do Not Apply** | Match score < 35, or missing hard requirements |

Each verdict includes 2–3 sentences of honest reasoning — real gaps called out, genuine strengths highlighted, and actionable context for your decision.

---

## How resume tailoring works

- Claude reads all your experience bullets and selects the **top 3-5 most relevant** per role based on the JD
- The professional summary is **rewritten** to emphasize skills and themes matching this specific role
- All facts stay accurate — JobFit AI reorders emphasis but **never fabricates experience**
- If STAR work stories are provided, the most relevant one anchors the cover letter body paragraph

---

## Interview talking points

1. **Fully dynamic context engine** — no hardcoded data anywhere; reads any career document and builds a unified profile via Claude
2. **Multi-output generation** — resume (Word + PDF), cover letter, hiring manager message, referral blurb, and ATS gap analysis from a single URL
3. **Context-aware prompting** — STAR stories feed cover letters, elevator pitch feeds tone matching, all sourced from uploaded documents
