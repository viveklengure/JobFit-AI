import logging

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _extract_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def _try_structured_selectors(soup: BeautifulSoup) -> str:
    selectors = [
        # LinkedIn
        ".description__text",
        ".show-more-less-html__markup",
        # Greenhouse
        "#content",
        ".job__description",
        # Lever
        ".posting-page",
        ".section-wrapper",
        # Workday
        '[data-automation-id="jobPostingDescription"]',
        # Indeed
        "#jobDescriptionText",
        # Naukri
        ".job-desc",
        ".job-description",
        # Generic
        "article",
        '[class*="description"]',
        '[class*="job-detail"]',
        '[id*="description"]',
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            return el.get_text(separator="\n", strip=True)
    return ""


def scrape_job(url: str) -> dict:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code in (403, 401, 429):
            return {
                "error": True,
                "message": f"Could not scrape URL (HTTP {resp.status_code}). Try pasting the job description manually.",
                "url": url,
            }
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        title_tag = soup.find("title")
        page_title = title_tag.get_text(strip=True) if title_tag else ""

        jd_text = _try_structured_selectors(soup) or _extract_text(soup)

        # Heuristic: pull job title and company from common meta / h1
        job_title = ""
        company = ""
        location = ""

        # Try specific job title selectors first (before falling back to generic h1/og:title)
        job_title_selectors = [
            # Workday
            '[data-automation-id="jobPostingHeader"]',
            '[data-automation-id="Job_Posting_Title"]',
            # Greenhouse
            ".app-title",
            "h1.job-title",
            # Lever
            ".posting-headline h2",
            # LinkedIn
            "h1.top-card-layout__title",
            "h1.t-24",
            # Indeed
            "h1.jobsearch-JobInfoHeader-title",
            # Generic specific patterns
            '[class*="job-title"]',
            '[class*="jobtitle"]',
            '[class*="position-title"]',
            '[class*="posting-title"]',
            '[class*="role-title"]',
            '[itemprop="title"]',
        ]
        for sel in job_title_selectors:
            el = soup.select_one(sel)
            if el:
                job_title = el.get_text(strip=True)
                break

        # Fall back to h1
        if not job_title:
            h1 = soup.find("h1")
            if h1:
                job_title = h1.get_text(strip=True)

        # Fall back to og:title, stripping common "Careers at X" / "Jobs at X" noise
        if not job_title:
            og_title = soup.find("meta", property="og:title")
            if og_title:
                job_title = og_title.get("content", "")

        # Strip noisy suffixes like " - Careers at PayPal", " | Jobs", etc.
        import re
        job_title = re.sub(
            r'\s*[-|–]\s*(careers?\s+at|jobs?\s+at|job\s+opening|apply\s+now|work\s+at).*$',
            '',
            job_title,
            flags=re.IGNORECASE,
        ).strip()

        # Last resort: page title with same cleanup
        if not job_title:
            job_title = re.sub(
                r'\s*[-|–]\s*(careers?\s+at|jobs?\s+at|job\s+opening|apply\s+now|work\s+at).*$',
                '',
                page_title,
                flags=re.IGNORECASE,
            ).strip()

        for sel in ['[class*="company"]', '[class*="employer"]', '[data-automation-id="company"]']:
            el = soup.select_one(sel)
            if el:
                company = el.get_text(strip=True)
                break

        for sel in ['[class*="location"]', '[data-automation-id="location"]']:
            el = soup.select_one(sel)
            if el:
                location = el.get_text(strip=True)
                break

        return {
            "error": False,
            "job_title": job_title,
            "company": company,
            "location": location,
            "jd_text": jd_text,
            "url": url,
        }
    except requests.RequestException as e:
        logger.error(f"Scrape error: {e}")
        return {
            "error": True,
            "message": f"Could not scrape URL: {e}",
            "url": url,
        }
    except Exception as e:
        logger.error(f"Unexpected scrape error: {e}")
        return {
            "error": True,
            "message": "Could not scrape URL",
            "url": url,
        }
