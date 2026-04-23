# JobFit AI — Smart Job Application Assistant

Two features in one app:

- **Job URL Analyzer** — paste a single job URL, get a match score, tailored resume, cover letter, hiring manager message, and referral blurb in ~60 seconds
- **Company Matcher** — paste a company's careers page URL, get every open role scraped and scored against your profile in one shot

Everything is driven by documents you provide — no hardcoded personal data anywhere.

---

## Feature A — Job URL Analyzer

1. **Scrapes** a job posting URL (LinkedIn, Indeed, Greenhouse, Lever, Workday, Naukri, generic pages)
2. **Analyzes** the JD against your profile: match score, matched skills, gap skills, key themes
3. **Gives a verdict** — Claude tells you whether to apply, with honest reasoning
4. **Generates** tailored content via Claude: summary, cover letter, outreach messages
5. **Builds** a formatted Word resume (.docx) and PDF using only the most relevant bullets per role

---

## Feature B — Company Matcher

1. Enter a company name and paste their careers page URL
2. App auto-detects the ATS (Greenhouse, Lever, Ashby, Workday) and fetches all open roles directly via their public APIs — no scraping, instant
3. Filters out junior/intern titles; keeps all roles matching your target profile (TPM, PM, Data Engineer, Analytics, etc.)
4. Claude scores every qualifying role against your resume in one batched call
5. Returns a ranked table of all roles + detailed cards for every role scoring ≥ 55 (Apply with Caution or better)
6. Ends with a strategy summary: best role fit, common gap pattern, one tailoring tip

**Supported ATS platforms (direct API — no Apify needed):**
- Greenhouse (Instacart, Stripe, Anthropic, Databricks, Datadog, Coinbase, and hundreds more)
- Lever (auto-detected from lever.co URL)
- Ashby (auto-detected from ashbyhq.com URL)
- Workday (when the full myworkdayjobs.com URL is provided)

**ATS detection order:** URL pattern first → then tries Greenhouse/Lever/Ashby by company name slug → falls back to Apify for unsupported platforms

---

## System Architecture

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                         JOBFIT AI — END TO END FLOW                         ║
╚══════════════════════════════════════════════════════════════════════════════╝

📁 YOUR DOCUMENTS (docs/ folder)
   resume.pdf · work_stories.txt · about_me.txt · bio.txt
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  context_builder.py  —  Document Ingestion Layer    │
│  PyMuPDF / pdfplumber (PDF) · python-docx (DOCX)   │
│  Merges all files → sends to Claude for parsing     │
│  Output: structured JSON profile (skills, exp, bio) │
└─────────────────────────────────────────────────────┘
         │
         │  Unified candidate context (cached in st.session_state)
         │
         ├──────────────────────────────────────────────────────────┐
         │                                                          │
         ▼                                                          ▼
╔═══════════════════════════╗                   ╔══════════════════════════════╗
║  FEATURE A · Job Analyzer ║                   ║  FEATURE B · Company Matcher ║
╚═══════════════════════════╝                   ╚══════════════════════════════╝
         │                                                          │
         ▼                                                          ▼
┌─────────────────────────┐              ┌──────────────────────────────────────┐
│  scraper.py             │              │  company_matcher.py                  │
│  Job URL → HTTP GET     │              │  ATS Detection Chain:                │
│  BeautifulSoup parses   │              │  1. URL pattern (greenhouse.io etc.) │
│  title, location, JD    │              │  2. Slug guess → try Greenhouse API  │
└─────────────────────────┘              │  3. Slug guess → try Lever API       │
         │                               │  4. Slug guess → try Ashby API       │
         ▼                               │  5. Workday REST API (if WD URL)     │
┌─────────────────────────┐              │  6. Apify fallback (custom ATS)      │
│  analyzer.py            │              └──────────────────────────────────────┘
│  Claude scores JD vs    │                              │
│  candidate profile      │                              ▼
│  Returns: score,        │              ┌──────────────────────────────────────┐
│  verdict, matched /     │              │  Filtering Pipeline                  │
│  gap skills, themes     │              │  deduplicate_jobs() — (title, loc)   │
└─────────────────────────┘              │  pre_filter_jobs() — drop intern /   │
         │                               │    junior titles; keep target roles  │
         ▼                               │    (TPM, PM, Analytics, Data Eng…)   │
┌─────────────────────────┐              └──────────────────────────────────────┘
│  generator.py           │                              │
│  4 Claude calls:        │                              ▼
│  · tailored summary     │              ┌──────────────────────────────────────┐
│  · cover letter         │              │  build_resume_summary()              │
│  · HM LinkedIn msg      │              │  One Claude call → compact scoring   │
│  · referral blurb       │              │  profile (title, skills, seniority,  │
└─────────────────────────┘              │  achievements) — cached in session   │
         │                               └──────────────────────────────────────┘
         ▼                                              │
┌─────────────────────────┐                            ▼
│  resume_builder.py      │              ┌──────────────────────────────────────┐
│  Claude selects top 3-5 │              │  claude_score()                      │
│  bullets per role →     │              │  Single batched Claude call          │
│  Node.js docx writes    │              │  All roles scored in one request     │
│  .docx → LibreOffice    │              │  Returns JSON array: score, verdict, │
│  converts to .pdf       │              │  fit_reasons, gaps, positioning_tip  │
└─────────────────────────┘              └──────────────────────────────────────┘
         │                                              │
         ▼                                             ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  app.py  —  Streamlit UI Layer                                               │
│                                                                              │
│  Feature A tabs:                    Feature B output:                        │
│  · Match Analysis (score, verdict)  · Ranked table (all qualifying roles)   │
│  · Tailored Resume (download)       · Detail cards (score ≥ 55)             │
│  · Cover Letter                     · Why I fit · Gaps · Positioning tip    │
│  · Outreach Messages                · Apply link · Strategy summary         │
│  · Raw JD                                                                    │
└──────────────────────────────────────────────────────────────────────────────┘
         │
         ▼
📄 outputs/  —  Generated resumes (.docx + .pdf), served as download buttons
```

---

## Project Structure

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  jobfit-ai/                                                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  ── UI LAYER ──────────────────────────────────────────────────────────────  ║
║  app.py                  Streamlit entry point; tab routing, session state   ║
║  run.py                  CLI launcher with menu                              ║
║                                                                              ║
║  ── PIPELINE (src/) ───────────────────────────────────────────────────────  ║
║  src/context_builder.py  Reads docs/ → parses via Claude → unified JSON     ║
║  src/scraper.py          HTTP + BeautifulSoup job URL scraper                ║
║  src/analyzer.py         Claude: JD vs profile → score, verdict, skills     ║
║  src/generator.py        Claude: cover letter, HM message, referral blurb   ║
║  src/resume_builder.py   Claude selects bullets → Node.js docx → PDF        ║
║  src/company_matcher.py  ATS detection, bulk scrape, filter, Claude scoring ║
║                                                                              ║
║  ── DATA ──────────────────────────────────────────────────────────────────  ║
║  docs/                   Your career documents (gitignored — personal data)  ║
║  docs/README.md          Instructions for what files to add                 ║
║  outputs/                Generated resumes per application (gitignored)      ║
║                                                                              ║
║  ── CONFIG ────────────────────────────────────────────────────────────────  ║
║  .env                    API keys: ANTHROPIC_API_KEY, APIFY_API_KEY          ║
║  .env.example            Template for .env                                  ║
║  .gitignore              Excludes .env, docs/*.pdf, docs/*.docx, outputs/   ║
║  CLAUDE.md               Full project spec and coding conventions           ║
║  requirements.txt        Python dependencies                                 ║
║  package.json            Node.js dependency (docx npm package)              ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## Setup

```bash
cd jobfit-ai
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
npm install -g docx             # Required for Word resume generation
cp .env.example .env
# Edit .env and add your keys
```

**Required in `.env`:**
```
ANTHROPIC_API_KEY=sk-ant-...
APIFY_API_KEY=apify_api_...     # Only needed for companies not on Greenhouse/Lever/Ashby
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
