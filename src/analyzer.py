import json
import logging

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def analyze_jd(jd: dict, context: dict) -> dict:
    client = anthropic.Anthropic()

    candidate_summary = context.get("summary") or ""
    candidate_skills = ", ".join(context.get("skills") or [])
    experience_titles = "; ".join(
        f"{e.get('title')} at {e.get('company')}"
        for e in (context.get("experience") or [])
    )

    user_content = (
        f"JOB DESCRIPTION:\n{jd.get('jd_text', '')}\n\n"
        f"CANDIDATE PROFILE:\n"
        f"Summary: {candidate_summary}\n"
        f"Skills: {candidate_skills}\n"
        f"Experience: {experience_titles}"
    )

    system_prompt = (
        "You are a senior technical recruiter and ATS optimization expert. "
        "Analyze this job description against the candidate profile. "
        "Return a JSON object with these exact keys:\n"
        "job_title (string),\n"
        "company (string),\n"
        "required_skills (list of strings),\n"
        "matched_skills (list of strings — skills in both JD and candidate),\n"
        "gap_skills (list of strings — in JD but not in candidate),\n"
        "key_themes (list of 3-5 strings),\n"
        "seniority_level (string),\n"
        "match_score (integer 0-100),\n"
        "match_breakdown (object with keys: technical_match, experience_match, domain_match — each 0-100),\n"
        "verdict (string — one of: 'Strong Apply', 'Apply', 'Apply with Caution', 'Do Not Apply'),\n"
        "verdict_reasoning (string — 2-3 sentences explaining the verdict honestly; call out real gaps, "
        "highlight genuine strengths, and give the candidate actionable context for their decision).\n"
        "Verdict criteria: 'Strong Apply' = match_score >= 75 and no critical gaps; "
        "'Apply' = match_score 55-74 or minor gaps; "
        "'Apply with Caution' = match_score 35-54 or significant gaps that can be addressed; "
        "'Do Not Apply' = match_score < 35 or missing hard requirements (e.g. required degree, clearance, years of experience).\n"
        "Return only valid JSON. No other text."
    )

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        # Prefer scraper values only when Claude left them blank
        # But if scraper title looks like a page title (contains "Careers at" etc.), prefer Claude's
        scraped_title = jd.get("job_title", "")
        import re
        looks_like_page_title = bool(re.search(
            r'careers?\s+at|jobs?\s+at|job\s+opening', scraped_title, re.IGNORECASE
        ))
        if not result.get("job_title") or (looks_like_page_title and result.get("job_title")):
            if not looks_like_page_title and scraped_title:
                result["job_title"] = scraped_title
        if not result.get("company"):
            result["company"] = jd.get("company", "")
        return result
    except Exception as e:
        logger.error(f"JD analysis error: {e}")
        return {
            "job_title": jd.get("job_title", ""),
            "company": jd.get("company", ""),
            "required_skills": [],
            "matched_skills": [],
            "gap_skills": [],
            "key_themes": [],
            "seniority_level": "",
            "match_score": 0,
            "match_breakdown": {"technical_match": 0, "experience_match": 0, "domain_match": 0},
            "error": True,
        }
