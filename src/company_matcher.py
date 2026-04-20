import hashlib
import json
import logging
import time
from typing import Optional

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"
PRIMARY_ACTOR = "enosgb~ats-job-scraper"

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
    "bay_area": [
        "san francisco", "sf", "bay area", "south bay", "east bay",
        "san jose", "sunnyvale", "mountain view", "palo alto", "menlo park",
        "redwood city", "foster city", "burlingame", "san mateo",
        "santa clara", "cupertino", "fremont", "oakland", "berkeley",
        "san francisco, ca", "san jose, ca", "sunnyvale, ca",
    ],
    "remote_global": [
        "remote", "work from home", "wfh", "distributed", "anywhere",
        "united states", "us only", "north america", "usa", ", us",
        "nationwide", "all locations", "multiple locations",
    ],
}

ALL_TARGET_VARIANTS = [v for variants in LOCATION_VARIANTS.values() for v in variants]

EXCLUDE_TITLE_KEYWORDS = [
    "intern", "internship", "junior", "associate i", "entry level",
    "entry-level", "analyst i ", "analyst 1", "co-op", "graduate",
    "apprentice",
]

REQUIREMENTS_ANCHORS = [
    "requirements", "qualifications", "what you'll need",
    "what you need", "you have", "you bring", "must have",
    "minimum qualifications", "basic qualifications",
    "what we're looking for", "who you are",
]

SCORING_SYSTEM_PROMPT = """You are a precise job-fit scorer for a senior data/AI professional. Return ONLY a valid JSON array. No prose, no markdown, no explanation before or after the JSON.

The candidate is a Staff Data Analytics Engineer / Sr. TPM with 11+ years experience. Strong matches include:
- Technical Program Manager (TPM), Senior TPM, Staff TPM
- Product Manager (Data, AI, Platform, Analytics)
- Staff/Principal Data Engineer, Analytics Engineer
- Data Analytics, Advanced Analytics, BI Engineer
- AI/ML Platform roles with engineering component
- Director/VP roles for India market

These role types should score 70+ if seniority aligns. Do NOT score them low just because the title differs from a pure engineering role.

Each element must have exactly these fields:
{
  "title": string,
  "location": string,
  "department": string,
  "score": integer 0-100,
  "verdict": one of ["Strong Apply", "Apply", "Apply with Caution", "Skip"],
  "fit_reasons": [string, string],
  "gaps": [string],
  "positioning_tip": string,
  "apply_url": string
}

Scoring weights:
- Skills overlap: 35%
- Seniority alignment (Staff/Principal/Sr/Director): 20%
- Domain fit (Data, AI, Cloud, Platform): 20%
- TPM/PM component: 15%
- Location match: 10% (0% weight for Remote or blank location)

Verdict thresholds:
- Strong Apply: 85-100
- Apply: 70-84
- Apply with Caution: 55-69
- Skip: below 55"""


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()[:8]


def is_target_location(job_location: str) -> bool:
    if not job_location or not job_location.strip():
        return True  # no location = likely remote/flexible, keep it
    loc = job_location.lower().strip()
    return any(variant in loc or loc in variant for variant in ALL_TARGET_VARIANTS)


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


TARGET_TITLE_KEYWORDS = [
    # TPM / Program Management
    "technical program manager", "tpm", "program manager", "technical program",
    "delivery manager", "engineering program",
    # Product Management
    "product manager", "product management", "group product", "senior product",
    "staff product", " pm ", "(pm)", "product lead",
    # Data Engineering
    "data engineer", "analytics engineer", "data platform", "data infrastructure",
    "data pipeline", "etl", "dbt", "warehouse",
    # Analytics
    "analytics", "data analyst", "business analyst", "advanced analytics",
    "business intelligence", "bi engineer", "insights",
    # Data Science / AI / ML
    "data scientist", "data science", "machine learning engineer", "ml engineer",
    "ai engineer", "applied scientist", "ai platform", "ml platform",
    # Staff / Principal / Director
    "staff engineer", "principal engineer", "director of data", "director of engineering",
    "vp of data", "vp data", "head of data", "head of analytics",
]

def _title_is_target(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in TARGET_TITLE_KEYWORDS)

def pre_filter_jobs(jobs: list[dict]) -> list[dict]:
    target_roles = []
    location_matched = []

    for job in jobs:
        title = (job.get("title") or "").lower()
        location = job.get("location") or ""

        if any(kw in title for kw in EXCLUDE_TITLE_KEYWORDS):
            continue

        is_target = _title_is_target(job.get("title", ""))
        in_location = is_target_location(location)

        if is_target:
            target_roles.append(job)       # always keep target-title roles
        elif in_location:
            location_matched.append(job)   # keep non-target roles only if location matches

    # Deduplicate between the two lists (target_roles takes precedence)
    target_ids = {id(j) for j in target_roles}
    extra = [j for j in location_matched if id(j) not in target_ids]

    return target_roles + extra


def compress_job(job: dict) -> dict:
    plain = (job.get("description") or "").strip()
    plain_lower = plain.lower()

    req_start = len(plain)
    for anchor in REQUIREMENTS_ANCHORS:
        idx = plain_lower.find(anchor)
        if idx != -1 and idx < req_start:
            req_start = idx

    if req_start < len(plain) - 100:
        requirements_text = plain[req_start:req_start + 500]
    else:
        requirements_text = plain[-500:]

    return {
        "title": job.get("title", ""),
        "location": job.get("location", ""),
        "department": job.get("department", ""),
        "applyUrl": job.get("applyUrl", ""),
        "requirements": requirements_text.strip(),
    }


def build_resume_summary(context: dict) -> str:
    client = anthropic.Anthropic()

    raw_text = context.get("combined_text") or ""
    if not raw_text:
        parts = []
        if context.get("summary"):
            parts.append(f"Summary: {context['summary']}")
        if context.get("skills"):
            parts.append(f"Skills: {', '.join(context['skills'])}")
        if context.get("experience"):
            for exp in context["experience"][:3]:
                bullets = " ".join(exp.get("bullets") or [])
                parts.append(f"{exp.get('title')} at {exp.get('company')}: {bullets[:200]}")
        raw_text = "\n".join(parts)

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
{raw_text[:3000]}"""
        }]
    )
    return response.content[0].text


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def _try_greenhouse(slug: str) -> list[dict]:
    try:
        resp = requests.get(
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
            headers=HEADERS, timeout=15,
        )
        if resp.status_code != 200:
            return []
        jobs_raw = resp.json().get("jobs", [])
        if not jobs_raw:
            return []
        jobs = []
        for j in jobs_raw:
            loc = j.get("location", {})
            location = loc.get("name", "") if isinstance(loc, dict) else str(loc)
            jobs.append({
                "title": j.get("title", ""),
                "location": location,
                "department": (j.get("departments") or [{}])[0].get("name", "") if j.get("departments") else "",
                "description": j.get("content", ""),
                "applyUrl": j.get("absolute_url", ""),
            })
        logger.info(f"Greenhouse returned {len(jobs)} jobs for '{slug}'")
        return jobs
    except Exception as e:
        logger.debug(f"Greenhouse failed for '{slug}': {e}")
        return []


def _try_lever(slug: str) -> list[dict]:
    try:
        resp = requests.get(
            f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=200",
            headers=HEADERS, timeout=15,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not isinstance(data, list) or not data:
            return []
        jobs = []
        for j in data:
            cats = j.get("categories", {})
            jobs.append({
                "title": j.get("text", ""),
                "location": cats.get("location", ""),
                "department": cats.get("team", ""),
                "description": j.get("descriptionPlain", "") or j.get("description", ""),
                "applyUrl": j.get("hostedUrl", ""),
            })
        logger.info(f"Lever returned {len(jobs)} jobs for '{slug}'")
        return jobs
    except Exception as e:
        logger.debug(f"Lever failed for '{slug}': {e}")
        return []


def _try_ashby(slug: str) -> list[dict]:
    try:
        resp = requests.get(
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
            headers=HEADERS, timeout=15,
        )
        if resp.status_code != 200:
            return []
        jobs_raw = resp.json().get("jobPostings", [])
        if not jobs_raw:
            return []
        jobs = []
        for j in jobs_raw:
            jobs.append({
                "title": j.get("title", ""),
                "location": j.get("locationName", "") or j.get("location", ""),
                "department": j.get("departmentName", "") or j.get("department", ""),
                "description": j.get("descriptionPlain", "") or j.get("description", ""),
                "applyUrl": j.get("jobUrl", "") or j.get("applyUrl", ""),
            })
        logger.info(f"Ashby returned {len(jobs)} jobs for '{slug}'")
        return jobs
    except Exception as e:
        logger.debug(f"Ashby failed for '{slug}': {e}")
        return []


def _slug_variants(company_name: str, careers_url: str) -> list[str]:
    """Generate slug candidates from company name and URL."""
    import re
    from urllib.parse import urlparse

    slugs = []
    name = company_name.strip().lower()

    # Clean slug: alphanumeric only
    slugs.append(re.sub(r"[^a-z0-9]", "", name))
    # With hyphens
    slugs.append(re.sub(r"[^a-z0-9]+", "-", name).strip("-"))
    # First word only
    first_word = re.split(r"[^a-z0-9]", name)[0]
    if first_word:
        slugs.append(first_word)

    # Extract from URL subdomain: stripe.com → stripe
    parsed = urlparse(careers_url)
    netloc = parsed.netloc.lower().replace("www.", "").replace("careers.", "").replace("jobs.", "")
    domain_slug = netloc.split(".")[0]
    if domain_slug:
        slugs.append(domain_slug)

    # Extract from URL path: boards.greenhouse.io/instacart → instacart
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    if path_parts:
        slugs.append(path_parts[0].lower())

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for s in slugs:
        if s and s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def _detect_and_scrape(careers_url: str, company_name: str) -> tuple[list[dict], str]:
    """Auto-detect ATS and return (jobs, ats_name)."""
    from urllib.parse import urlparse
    netloc = urlparse(careers_url).netloc.lower()

    # Direct ATS URL detection
    if "greenhouse.io" in netloc or "greenhouse.io" in careers_url:
        slugs = _slug_variants(company_name, careers_url)
        for slug in slugs:
            jobs = _try_greenhouse(slug)
            if jobs:
                return jobs, "Greenhouse"
        return [], ""

    if "lever.co" in netloc:
        slugs = _slug_variants(company_name, careers_url)
        for slug in slugs:
            jobs = _try_lever(slug)
            if jobs:
                return jobs, "Lever"
        return [], ""

    if "ashbyhq.com" in netloc or "ashby" in netloc:
        slugs = _slug_variants(company_name, careers_url)
        for slug in slugs:
            jobs = _try_ashby(slug)
            if jobs:
                return jobs, "Ashby"
        return [], ""

    if "myworkdayjobs.com" in careers_url:
        jobs = _try_workday(careers_url)
        return jobs, "Workday" if jobs else ""

    # Unknown URL — try Greenhouse first (most widely used), then Lever, then Ashby
    slugs = _slug_variants(company_name, careers_url)
    for slug in slugs:
        jobs = _try_greenhouse(slug)
        if jobs:
            return jobs, "Greenhouse"
    for slug in slugs:
        jobs = _try_lever(slug)
        if jobs:
            return jobs, "Lever"
    for slug in slugs:
        jobs = _try_ashby(slug)
        if jobs:
            return jobs, "Ashby"

    return [], ""


def _try_workday(careers_url: str) -> list[dict]:
    import re
    match = re.match(r"(https://[^/]+myworkdayjobs\.com/[^/?#\s]+)", careers_url)
    if not match:
        return []
    base = match.group(1).rstrip("/")
    parts = base.split("/")
    domain = parts[2]
    tenant = domain.split(".")[0]
    site = parts[-1]
    api_url = f"https://{domain}/wday/cxs/{tenant}/{site}/jobs"
    try:
        resp = requests.post(
            api_url,
            headers={**HEADERS, "Content-Type": "application/json"},
            json={"limit": 100, "offset": 0, "searchText": "", "appliedFacets": {}},
            timeout=20,
        )
        if resp.status_code != 200:
            return []
        jobs_raw = resp.json().get("jobPostings", [])
        jobs = []
        for j in jobs_raw:
            locs = j.get("locationsText", "") or j.get("locations", "")
            if isinstance(locs, list):
                locs = ", ".join(locs)
            jobs.append({
                "title": j.get("title", ""),
                "location": locs,
                "department": "",
                "description": "",
                "applyUrl": f"https://{domain}{j.get('externalPath', '')}",
            })
        logger.info(f"Workday returned {len(jobs)} jobs")
        return jobs
    except Exception as e:
        logger.debug(f"Workday failed: {e}")
        return []


def _scrape_direct(careers_url: str) -> list[dict]:
    """Fallback: scrape careers page directly via common JSON API patterns."""
    from urllib.parse import urlparse
    parsed = urlparse(careers_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, */*",
    }

    # Phenom People ATS (used by Instacart, Target, etc.)
    phenom_endpoints = [
        f"{base}/api/jobs?start=0&num=100",
        f"{base}/api/jobs?from=0&size=100",
        f"{base}/api/jobs",
    ]
    for endpoint in phenom_endpoints:
        try:
            resp = requests.get(endpoint, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                jobs_raw = data.get("jobs") or data.get("results") or data.get("data") or []
                if jobs_raw:
                    jobs = []
                    for j in jobs_raw:
                        title = j.get("title") or j.get("jobTitle") or j.get("name") or ""
                        location = (
                            j.get("location") or j.get("city") or
                            j.get("jobLocation", {}).get("address", {}).get("addressLocality", "") or ""
                        )
                        if isinstance(location, list):
                            location = ", ".join(location)
                        job_id = j.get("id") or j.get("jobId") or j.get("reqId") or ""
                        apply_url = j.get("applyUrl") or j.get("apply_url") or f"{base}/job?id={job_id}"
                        department = j.get("category") or j.get("department") or j.get("team") or ""
                        description = j.get("description") or j.get("jobDescription") or ""
                        if title:
                            jobs.append({
                                "title": title,
                                "location": location,
                                "department": department,
                                "description": description,
                                "applyUrl": apply_url,
                            })
                    if jobs:
                        logger.info(f"Direct scrape returned {len(jobs)} jobs from {endpoint}")
                        return jobs
        except Exception as e:
            logger.debug(f"Direct scrape attempt failed ({endpoint}): {e}")
            continue

    return []


def scrape_jobs(careers_url: str, api_key: str, company_name: str = "", progress_callback=None) -> list[dict]:
    # Try direct ATS APIs first — instant, free, no Apify cost
    if progress_callback:
        progress_callback(f"Detecting ATS for {company_name}…")
    direct_jobs, ats_name = _detect_and_scrape(careers_url, company_name)
    if direct_jobs:
        if progress_callback:
            progress_callback(f"Found {len(direct_jobs)} roles via {ats_name}")
        return direct_jobs

    if progress_callback:
        progress_callback(f"Direct APIs not found — falling back to Apify scraper…")

    run_resp = requests.post(
        f"{APIFY_BASE}/acts/{PRIMARY_ACTOR}/runs?token={api_key}",
        json={"startUrls": [{"url": careers_url}], "maxItems": 100},
        timeout=30,
    )
    run_resp.raise_for_status()
    run_id = run_resp.json()["data"]["id"]

    MAX_WAIT = 120
    POLL_INTERVAL = 5
    elapsed = 0

    while elapsed < MAX_WAIT:
        status_resp = requests.get(
            f"{APIFY_BASE}/actor-runs/{run_id}?token={api_key}",
            timeout=10,
        ).json()["data"]["status"]

        if status_resp == "SUCCEEDED":
            break
        if status_resp == "FAILED":
            raise RuntimeError("Apify run failed. Check the careers URL and try again.")

        if progress_callback:
            progress_callback(f"Scraping in progress… ({elapsed + POLL_INTERVAL}s)")

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    else:
        raise TimeoutError("Apify timed out after 120s. The careers page may require login or use an unsupported ATS.")

    items_resp = requests.get(
        f"{APIFY_BASE}/actor-runs/{run_id}/dataset/items?token={api_key}",
        timeout=30,
    )
    items_resp.raise_for_status()
    jobs = items_resp.json()

    # If Apify returned nothing useful (blank titles), fall back to direct scraping
    titled = [j for j in jobs if (j.get("title") or "").strip()]
    if len(titled) < 3:
        if progress_callback:
            progress_callback("Apify couldn't parse this ATS — trying direct scrape…")
        direct = _scrape_direct(careers_url)
        if direct:
            return direct

    return jobs


def claude_score(jobs: list[dict], resume_summary: str) -> list[dict]:
    if not jobs:
        return []

    client = anthropic.Anthropic()
    compressed = [compress_job(j) for j in jobs]

    jobs_text = json.dumps(compressed, indent=2)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        system=SCORING_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"""Candidate profile:
{resume_summary}

Jobs to score:
{jobs_text}"""
        }]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    scored = json.loads(raw)
    return sorted(scored, key=lambda x: x.get("score", 0), reverse=True)


def get_strategy_summary(scored_roles: list[dict], company_name: str, resume_summary: str) -> str:
    client = anthropic.Anthropic()

    roles_text = "\n".join(
        f"- {r['title']} ({r['location']}): {r['score']}/100 — {r['verdict']}. Gaps: {', '.join(r.get('gaps') or []) or 'none'}"
        for r in scored_roles
    )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        system="You are a career strategist. Be specific and direct. No generic advice.",
        messages=[{
            "role": "user",
            "content": f"""Based on these scored roles at {company_name} and the candidate profile, provide a 3-part strategy summary:

1. Best overall role fit at this company (be specific about why)
2. Common gap pattern across roles (name the specific skill/experience gap)
3. One concrete resume/LinkedIn tailoring tip for this company

Candidate profile:
{resume_summary}

Scored roles:
{roles_text}

Keep each point to 1-2 sentences. No bullet sub-points."""
        }]
    )
    return response.content[0].text
