# CLAUDE.md — JobFit AI Project Context

This file is the single source of truth for the JobFit AI project. Read it fully at the start of every CLI session before writing or modifying any code.

---

## Project overview

**JobFit AI** is a Streamlit-based job application assistant that helps a senior data/AI professional (Vivek Lengure) apply smarter and faster. It has two distinct features:

- **Feature A — Job URL Analyzer** (existing): Paste a job URL → get a match score, cover letter, hiring manager message, referral message, Word resume, and PDF resume
- **Feature B — Company Matcher** (new tab, to be built): Enter company name + paste careers page URL → Apify scrapes all open roles → Python filters by location/seniority → Claude scores qualifying roles in one batched call → ranked table + score + verdict per role

Both features share the same profile context and scoring philosophy. Never hardcode personal data — always read from documents in the `docs/` folder.

---

## Tech stack

| Layer | Technology |
|---|---|
| UI | Streamlit |
| LLM | Claude API (`claude-sonnet-4-20250514`) |
| Web scraping | Apify — `enosgb/ats-job-scraper` (primary), `blackfalcondata/greenhouse-scraper` (Greenhouse fallback) |
| Resume parsing | PyMuPDF / python-docx |
| Resume generation | Node.js + docx npm package |
| PDF export | LibreOffice (optional) |
| Env vars | `ANTHROPIC_API_KEY`, `APIFY_API_KEY` |
| Python | 3.9+ |

---

## Repo structure

```
jobfit-ai/
├── app.py                  # Streamlit entry point — tab routing lives here
├── run.py                  # CLI launcher
├── CLAUDE.md               # This file
├── requirements.txt
├── .env                    # Never commit — contains API keys
├── .env.example
├── .gitignore              # Must include: .env, docs/*.pdf, docs/*.docx, docs/*.txt
├── docs/                   # User's career documents — contents must NOT be committed
│   ├── .gitignore          # Contains: *.pdf, *.docx, *.txt, *.doc (keep folder, ignore files)
│   ├── resume.pdf / resume.docx
│   ├── work_stories.txt / .docx / .pdf
│   ├── about_me.txt / .docx
│   ├── bio.txt / .docx
│   └── README.md           # README.md is safe to commit — no personal data
├── src/
│   ├── __init__.py
│   ├── scraper.py          # Job URL scraping (Feature A)
│   ├── analyzer.py         # Match scoring and verdict (Feature A)
│   ├── generator.py        # Cover letter, messages, outreach (Feature A)
│   ├── resume_builder.py   # Word + PDF resume generation (Feature A)
│   ├── context_builder.py  # Unified document context builder (shared)
│   └── company_matcher.py  # Apify scraping + Claude scoring (Feature B — new)
└── outputs/                # Generated resumes, cover letters — add to .gitignore too
```

---

## Feature A — Job URL Analyzer (existing, do not break)

### What it does
1. Accepts a job posting URL (LinkedIn, Indeed, Greenhouse, Lever, Workday, Naukri, generic pages)
2. Scrapes the JD content
3. Analyzes it against the user's profile documents in `docs/`
4. Returns a **match score**, matched skills, gap skills, key themes
5. Issues a **verdict** with honest reasoning
6. Generates: tailored cover letter, hiring manager LinkedIn message, referral blurb
7. Builds a tailored Word resume (.docx) and PDF using the top 3–5 most relevant bullets per role

### Verdict thresholds
| Verdict | Score range |
|---|---|
| Strong Apply | ≥ 75, no critical gaps |
| Apply | 55–74, minor gaps |
| Apply with Caution | 35–54, significant but addressable gaps |
| Do Not Apply | < 35, or missing hard requirements |

### Resume tailoring rules
- Select top 3–5 most relevant bullets per role based on the JD
- Rewrite the professional summary to match the role's themes
- Never fabricate experience — reorder emphasis only
- If STAR work stories exist in `docs/`, the most relevant one anchors the cover letter body

### Output files
- `outputs/resume_[company]_[role].docx`
- `outputs/resume_[company]_[role].pdf` (if LibreOffice available)
- Cover letter, messages rendered inline in Streamlit

---

## Feature B — Company Matcher (new tab)

### What it does
1. User enters company name + pastes the company's careers page URL (e.g. `stripe.com/jobs`, `jobs.lever.co/anthropic`)
2. Apify scrapes all open roles via `enosgb/ats-job-scraper` — auto-detects ATS, no manual selection needed
3. Python filters by location and seniority before any Claude call
4. Claude scores every qualifying role against the user's resume summary in one batched call
5. Returns a ranked table of all roles + detailed cards for the top N (up to 5)

### Apify integration

**Primary actor: `enosgb/ats-job-scraper`**

This takes a company careers page URL directly — exactly what the user pastes into the UI. It auto-detects the ATS platform and returns standardized output.

| Actor | Input | ATS support | Success rate | Cost |
|---|---|---|---|---|
| `enosgb/ats-job-scraper` | Careers page URL | Greenhouse, Lever, Ashby, Workday, Rippling | 98.7% | $0.003/job |
| `blackfalcondata/greenhouse-scraper` | Careers page URL | Greenhouse only | 100% | $0.002/job |

Use `enosgb/ats-job-scraper` as primary. Fall back to `blackfalcondata/greenhouse-scraper` only if user confirms the company uses Greenhouse and the primary fails.

Do NOT use:
- `piotrv1001/company-career-page-scraper` — 83.4% success, the one we tested and it failed on Amazon
- `curious_coder/linkedin-jobs-scraper` or `linkedin-jobs-search-scraper` — wrong approach entirely, requires LinkedIn URL not careers URL, adds unnecessary friction and cost

**UI input — keep it simple:**
```
Company name: [text field]
Careers page URL: [text field — e.g. https://stripe.com/jobs or https://jobs.lever.co/anthropic]
```
That's it. No LinkedIn URL. No ATS selection. The actor detects ATS automatically.

**Actor call:**
```python
{
    "startUrls": [{"url": careers_url}],
    "maxItems": 50,
}
```

**Auth:** `APIFY_API_KEY` from `.env`
**Call:** `POST https://api.apify.com/v2/acts/enosgb~ats-job-scraper/runs?token={APIFY_API_KEY}`

**Polling with timeout — always use this pattern:**
```python
import time, requests

MAX_WAIT_SECONDS = 120
POLL_INTERVAL = 5
elapsed = 0

while elapsed < MAX_WAIT_SECONDS:
    status = requests.get(
        f"https://api.apify.com/v2/actor-runs/{run_id}?token={api_key}"
    ).json()["data"]["status"]
    if status == "SUCCEEDED":
        break
    if status == "FAILED":
        raise RuntimeError(f"Apify run failed. Check the careers URL and try again.")
    time.sleep(POLL_INTERVAL)
    elapsed += POLL_INTERVAL
else:
    raise TimeoutError("Apify timed out after 120s. The careers page may require login or use an unsupported ATS.")
```

**Output fields (standardized across all ATS platforms):**

| Field | Notes |
|---|---|
| `title` | Job title |
| `location` | Location string |
| `department` | Team / department |
| `employmentType` | Full-time, contract, etc. |
| `description` | Plain text job description (pre-stripped) |
| `applyUrl` | Direct application link |
| `postedAt` | Date posted |

Note: `description` from this actor is already plain text — do NOT run BeautifulSoup on it. Use `compress_job()` below to extract the requirements section only.

### Token optimization (critical for cost control)

**Step 1 — Deduplicate before anything else**

`enosgb/ats-job-scraper` scrapes a single company so there's no `companyName` field. Deduplicate on `(title, location)` — same role posted for two locations should be kept, same role posted twice for the same location should be dropped:

```python
def deduplicate_jobs(jobs: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for job in jobs:
        key = (
            (job.get("title") or "").lower().strip(),
            (job.get("location") or "").lower().strip(),
        )
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique
```

**Step 2 — pre_filter_jobs(): title keywords since ats-job-scraper has no seniorityLevel field**

`enosgb/ats-job-scraper` does not return a structured `seniorityLevel` field — it standardizes across ATS platforms which don't all expose seniority. Use title keyword filtering:

```python
def pre_filter_jobs(jobs: list[dict]) -> list[dict]:
    EXCLUDE_TITLE_KEYWORDS = [
        "intern", "internship", "junior", "associate i", "entry level",
        "entry-level", "analyst i ", "analyst 1", "co-op", "graduate",
        "apprentice",
    ]
    filtered = []
    for job in jobs:
        location = job.get("location") or ""
        title = (job.get("title") or "").lower()
        if not is_target_location(location):
            continue
        if any(kw in title for kw in EXCLUDE_TITLE_KEYWORDS):
            continue
        filtered.append(job)
    return filtered
```

**Step 3 — compress_job(): description is already plain text from this actor**

`enosgb/ats-job-scraper` returns `description` as plain text — no BeautifulSoup needed:

```python
REQUIREMENTS_ANCHORS = [
    "requirements", "qualifications", "what you'll need",
    "what you need", "you have", "you bring", "must have",
    "minimum qualifications", "basic qualifications",
    "what we're looking for", "who you are",
]

def compress_job(job: dict) -> dict:
    plain = (job.get("description") or "").strip()
    plain_lower = plain.lower()

    # Find requirements section — higher signal than intro boilerplate
    req_start = len(plain)
    for anchor in REQUIREMENTS_ANCHORS:
        idx = plain_lower.find(anchor)
        if idx != -1 and idx < req_start:
            req_start = idx

    if req_start < len(plain) - 100:
        requirements_text = plain[req_start:req_start + 500]
    else:
        requirements_text = plain[-500:]  # fallback: last 500 chars

    return {
        "title": job.get("title", ""),
        "location": job.get("location", ""),
        "department": job.get("department", ""),
        "applyUrl": job.get("applyUrl", ""),
        "requirements": requirements_text.strip(),
    }
```

**Step 4 — Resume summary: include system prompt or Claude writes narrative prose**

```python
def build_resume_summary(context: str) -> str:
    """Call Claude once to extract a compact scoring profile. Cache result."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        system="You are a resume parser. Return only structured data — no prose, no preamble, no explanation. Follow the format exactly.",
        messages=[{
            "role": "user",
            "content": f"""From this resume, extract:
TITLE: [current title and years of experience]
SKILLS: [top 10 technical skills, comma-separated]
DOMAINS: [top 5 domain areas, comma-separated]
SENIORITY: [Staff / Principal / Sr. / Director]
ACHIEVEMENTS: [3 most impressive achievements, one sentence each]

Resume:
{context[:3000]}"""
        }]
    )
    return response.content[0].text
    # Cache in st.session_state["resume_summary_{md5_key}"]
```

**Step 5 — Claude scoring call: explicit JSON schema required**

Always instruct Claude to return a strict JSON array. Without a defined schema, output shape varies between runs and breaks Streamlit rendering. Use this exact system prompt and output structure:

```python
SCORING_SYSTEM_PROMPT = """You are a precise job-fit scorer. Return ONLY a valid JSON array. No prose, no markdown, no explanation before or after the JSON.

Each element must have exactly these fields:
{
  "title": string,
  "location": string,
  "score": integer 0-100,
  "verdict": one of ["Strong Apply", "Apply", "Apply with Caution", "Skip"],
  "fit_reasons": [string, string],       // exactly 2 bullet points
  "gaps": [string],                      // 1-2 honest gaps, empty array if none
  "positioning_tip": string,             // one sentence
  "apply_url": string
}"""
```

**Step 6 — Resume summary: build BEFORE Apify call, not after**

`build_resume_summary()` should be called when the tab loads and a resume is found — not mid-pipeline. This way it's ready by the time Apify finishes (Apify takes 30–60s, resume summary takes 2–3s):

```python
# In app.py tab load — not inside the "Analyze" button handler
if "resume_summary" not in st.session_state:
    context = context_builder.build()          # reads docs/ folder
    if context:
        st.session_state["resume_summary"] = build_resume_summary(context)

# Inside "Analyze" button handler — resume_summary already ready
if st.button("Scan company"):
    jobs = apify_scrape(careers_url)           # 30-60s
    filtered = pre_filter_jobs(deduplicate_jobs(jobs))
    scored = claude_score(filtered, st.session_state["resume_summary"])  # 5-10s
```

**Step 7 — Handle fewer than 5 qualifying roles gracefully**

```python
top_n = min(5, len(scored_roles))
if top_n == 0:
    st.warning("No roles matched your location and seniority filters. Try a different careers URL or check if this company's ATS is supported.")
else:
    st.info(f"Showing detailed cards for top {top_n} of {len(scored_roles)} qualifying roles.")
```

**Step 8 — Full pipeline order**

```
Tab loads:
  → build_resume_summary()      # once, cached — runs immediately on tab open

User clicks "Scan company":
  → Apify: enosgb/ats-job-scraper (careers URL → raw jobs)
  → deduplicate_jobs()          # (title, location) key
  → pre_filter_jobs()           # location variants + title keywords (Python, free)
  → [compress_job() for each]   # requirements section only (~500 chars)
  → Claude batch score          # one call, max_tokens=8192, returns JSON array
  → parse JSON → render ranked table + top N cards (N = min(5, results))
```

**Token budget reference (do not exceed without raising max_tokens):**
- Input: system prompt (~300) + resume summary (~200) + 15 jobs × 120 tokens (~1,800) = ~2,300 tokens
- Output: 15 jobs × 150 tokens (~2,250) + strategy summary (~200) = ~2,450 tokens
- Total: ~4,750 tokens — well within 8,192 limit

**Cache keys for st.session_state:**
- Apify results: `f"apify_{hashlib.md5(careers_url.encode()).hexdigest()[:8]}"`
- Resume summary: `f"resume_summary_{hashlib.md5(resume_context.encode()).hexdigest()[:8]}"`
- Scored results: `f"scores_{apify_key}_{resume_key}"` — invalidates if either changes

### Scoring rubric (apply per role, in one batched Claude call)

| Dimension | Weight | What to assess |
|---|---|---|
| Skills overlap | 35% | % of required skills matched by user's profile |
| Seniority alignment | 20% | Does level match Staff / Principal / Sr.? |
| Domain fit | 20% | Data, AI, Cloud, Platform proximity |
| TPM/PM component | 15% | Cross-functional or program management elements |
| Location match | 10% | In target city list? Remote roles auto-score 10/10 on this dimension |

**Hard filters — apply in Python BEFORE sending to Claude (free CPU, saves tokens):**
- Location does not match target cities (see location filter below)
- Title contains junior/entry-level keywords: "intern", "internship", "junior", "associate i", "entry level", "entry-level", "analyst i", "analyst 1", "co-op", "graduate", "apprentice"
- Is pure ML Research Scientist (no product/engineering component)
- Requires active US security clearance
- Is at a consulting or staffing firm

### Location filter — target cities with all name variants

Vivek's target locations are fixed. Filter in Python using case-insensitive substring matching on the `location` field BEFORE the Claude call.

```python
LOCATION_VARIANTS = {
    "bengaluru": [
        "bengaluru", "bangalore", "blr", "bangalore urban",
        "bengaluru urban", "bangalore, ka", "bangalore, karnataka",
        "bengaluru, karnataka",
    ],
    "hyderabad": [
        "hyderabad", "hyd", "secunderabad", "hitec city", "cyberabad",
        "gachibowli", "madhapur", "hyderabad, telangana", "hyderabad, ts",
    ],
    "mumbai": [
        "mumbai", "bombay", "bom", "greater mumbai", "navi mumbai",
        "thane", "mumbai metropolitan", "mumbai region",
        "mumbai, maharashtra", "mumbai, mh",
    ],
    "pune": [
        "pune", "poona", "pimpri", "hinjewadi", "kharadi",
        "magarpatta", "pune metropolitan", "pune, maharashtra", "pune, mh",
    ],
    "seattle": [
        "seattle", "seattle, wa", "seattle, washington", "greater seattle",
        "seattle-tacoma", "bellevue", "redmond, wa", "kirkland, wa",
        "bothell, wa", "issaquah, wa", "puget sound", "seattle metro",
    ],
    "new_york": [
        "new york", "nyc", "new york city", "manhattan", "brooklyn",
        "queens", "jersey city", "hoboken", "tri-state", "ny metro",
        "greater new york", "new york, ny",
    ],
    "remote_us": [
        "remote, us", "remote (us)", "remote (united states)",
        "united states (remote)", "us-remote", "remote — us",
        "remote / us", "anywhere in us", "distributed (us)",
        "remote, united states",
    ],
    "remote_india": [
        "remote, india", "remote (india)", "india (remote)",
        "in-remote", "anywhere in india", "distributed (india)",
        "pan india", "india remote", "remote — india",
    ],
}

ALL_TARGET_VARIANTS = [v for variants in LOCATION_VARIANTS.values() for v in variants]

def is_target_location(job_location: str) -> bool:
    if not job_location:
        return False
    loc = job_location.lower().strip()
    # Plain "remote" alone is ambiguous — keep it, Claude will clarify
    if loc in ("remote", "work from home", "wfh", "distributed", "anywhere"):
        return True
    return any(variant in loc or loc in variant for variant in ALL_TARGET_VARIANTS)

def pre_filter_jobs(jobs: list[dict]) -> list[dict]:
    EXCLUDE_TITLE_KEYWORDS = [
        "intern", "internship", "junior", "associate i", "entry level",
        "entry-level", "analyst i ", "analyst 1", "co-op", "graduate",
        "apprentice",
    ]
    filtered = []
    for job in jobs:
        title = (job.get("title") or "").lower()
        location = job.get("location") or ""
        if not is_target_location(location):
            continue
        if any(kw in title for kw in EXCLUDE_TITLE_KEYWORDS):
            continue
        filtered.append(job)
    return filtered
```

**Location nuances to remember:**
- "Remote" alone (no country) is kept — Claude scores location match at 50% and flags ambiguity in verdict
- Bellevue + Redmond, WA included under Seattle — Amazon HQ is Bellevue, Microsoft is Redmond
- Navi Mumbai + Thane included under Mumbai — commutable and frequently listed separately
- Hinjewadi often listed without "Pune" in the string — variant list handles this
- Jersey City + Hoboken (NJ) included under New York — NYC-commutable, common for finance/tech firms
- Location scoring weight drops from 10% to 0% for Remote roles (location is already a match — don't penalize)

### Apply verdict (shown per role)

Every scored role must include a verdict — not just a score. Use these thresholds:

| Verdict | Score | Display |
|---|---|---|
| Strong Apply | 85–100 | 🟢 Strong Apply |
| Apply | 70–84 | 🔵 Apply |
| Apply with Caution | 55–69 | 🟡 Apply with Caution |
| Skip | below 55 | 🔴 Skip |

Each verdict must include 1–2 sentences of honest reasoning — specific strengths called out, real gaps named. No generic filler like "this could be a good fit."

### Output format

**Ranked summary table** (all qualifying roles, sorted by score descending, shown as `st.dataframe`):

| Rank | Job title | Team | Location | Score | Verdict |
|---|---|---|---|---|---|

**Top 5 detailed cards** (rendered as `st.expander`, one per role):
- Score + verdict banner (color-coded)
- Why I fit: 2–3 bullets with specific skill/experience matches
- Gaps to address: 1–2 honest gaps to prep for or address in cover letter
- Quick positioning tip: one sentence on how to frame the application
- Apply: direct link to ATS

**Strategy summary** (below all cards):
- Which role type is the best overall fit at this company
- Any pattern in gaps across all roles (e.g., "most roles want Spark — highlight your pipeline work")
- One specific resume/LinkedIn tailoring tip for this company

### UI placement
- New tab labeled **"Company Matcher"** in `app.py`'s tab list
- Tab order: existing tabs first, Company Matcher last
- Resume source (in priority order):
  1. Auto-load from `docs/resume.pdf` or `docs/resume.docx` if it exists — no upload needed
  2. If not found, show optional `st.file_uploader` — uploaded file is used for this session only, not saved to `docs/`
- Build `resume_summary` in `st.session_state` immediately on tab load — before user clicks anything
- Show a progress spinner while Apify is running ("Scraping live job listings from [company]...")
- Show job count fetched and filtered count before scoring begins: "Found 47 roles → 12 match your location and seniority filters → scoring now..."

---

## Shared profile context (used by both features)

The user's profile is **never hardcoded**. It is always built dynamically from documents in `docs/`. The `context_builder.py` module merges all documents into a unified context string passed to Claude.

For reference, here is the user's background (used to validate scoring accuracy only — do not hardcode into prompts):

- **Name:** Vivek Lengure
- **Current title:** Staff Data Analytics Engineer / Sr. TPM
- **Experience:** 11+ years
- **Education:** MS Information Systems (UT Dallas), BE Electronics (Univ. of Mumbai)
- **Core skills:** SQL, Python, dbt, Spark, Airflow, AWS (Redshift, Glue, QuickSight), Tableau, LLM integration (Claude API, LangChain, ChromaDB), RAG pipelines, TPM/program delivery
- **Target roles:** Staff/Principal Data Engineer, Sr./Staff TPM (Data/AI/Platform), Data PM, AI PM; Director/VP for India market only
- **Salary floor:** ₹50L (India), $140K (US)
- **Target locations:** Seattle, Bay Area, Remote (US); Bengaluru, Mumbai, Hyderabad, Pune (India)

---

## Coding conventions

- All Claude API calls use `claude-sonnet-4-20250514` with `max_tokens=4096` — **except `company_matcher.py` which must use `max_tokens=8192`**
- All prompts are in the `src/` file relevant to their feature — no inline prompts in `app.py`
- Streamlit state management via `st.session_state` — never re-run Claude calls on rerenders
- All API keys loaded via `python-dotenv` from `.env` — never hardcoded
- Error handling: if Apify run fails or times out, show a clear Streamlit error with the HTTP status and suggest checking the URL
- Logging: use Python `logging` module at INFO level, not `print()`
- Type hints on all functions

---

## What NOT to do

- Never commit files in `docs/` — they contain personal PII (resume, work stories, bio). The `docs/.gitignore` must exclude `*.pdf`, `*.docx`, `*.txt`
- Never commit files in `outputs/` — generated resumes contain personal data
- Never fabricate job listings — always fetch live via Apify
- Never hardcode Vivek's personal details into prompt strings
- Never re-run expensive Apify scrapes on Streamlit rerenders — cache in `st.session_state` using key `f"apify_{md5(url)[:8]}"`
- Never pass the full resume text to the scoring call — extract a 200-word resume summary once, cache it with key `f"resume_summary_{md5(context)[:8]}"`, reuse across all scoring calls
- Never use global `max_tokens=4096` in `company_matcher.py` — must be `max_tokens=8192`
- Never modify Feature A tabs or their output format when adding Feature B
- Never use a model other than `claude-sonnet-4-20250514` without explicit instruction
- Never commit `.env` or any file containing API keys
