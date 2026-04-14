import logging

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"


def _call_claude(system: str, user: str, max_tokens: int = 1024) -> str:
    client = anthropic.Anthropic()
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error(f"Claude generation error: {e}")
        return ""


def generate_summary(jd_analysis: dict, context: dict) -> str:
    about_me = context.get("about_me") or ""
    bio = context.get("bio") or ""
    original_summary = context.get("summary") or ""
    skills = ", ".join(context.get("skills") or [])
    key_themes = ", ".join(jd_analysis.get("key_themes") or [])
    role = jd_analysis.get("job_title", "")
    company = jd_analysis.get("company", "")

    tone_section = ""
    if about_me or bio:
        tone_section = f"\n\nCandidate's own voice (use for tone matching):\n{about_me}\n{bio}"

    user_content = (
        f"Role: {role} at {company}\n"
        f"Key themes: {key_themes}\n"
        f"Matched skills: {', '.join(jd_analysis.get('matched_skills') or [])}\n\n"
        f"Original summary:\n{original_summary}\n\n"
        f"All skills: {skills}"
        f"{tone_section}"
    )

    system = (
        "You are an expert resume writer. Rewrite this professional summary tailored for the specific role. "
        "Emphasize the most relevant skills and experience. Keep all facts accurate — never add experience "
        "that does not exist. 3-4 sentences maximum. Match the tone of the candidate's own voice if an "
        "elevator pitch or bio is provided."
    )

    return _call_claude(system, user_content)


def generate_cover_letter(jd_analysis: dict, context: dict) -> str:
    name = context.get("name") or "the candidate"
    role = jd_analysis.get("job_title", "this role")
    company = jd_analysis.get("company", "your company")
    key_themes = ", ".join(jd_analysis.get("key_themes") or [])
    matched_skills = ", ".join(jd_analysis.get("matched_skills") or [])

    experience_bullets = []
    for exp in (context.get("experience") or [])[:3]:
        for b in (exp.get("bullets") or [])[:2]:
            experience_bullets.append(b)

    stories = context.get("work_stories") or []
    star_section = ""
    if stories:
        s = stories[0]
        star_section = (
            f"\n\nMost relevant STAR story:\n"
            f"Situation: {s.get('situation','')}\n"
            f"Task: {s.get('task','')}\n"
            f"Action: {s.get('action','')}\n"
            f"Result: {s.get('result','')}"
        )

    user_content = (
        f"Candidate name: {name}\n"
        f"Role: {role} at {company}\n"
        f"Key themes: {key_themes}\n"
        f"Matched skills: {matched_skills}\n\n"
        f"Top experience bullets:\n" + "\n".join(f"- {b}" for b in experience_bullets)
        + star_section
    )

    system = (
        "You are an expert cover letter writer. Write a professional, specific cover letter using real "
        "achievements and numbers from the candidate profile. Structure: 3 paragraphs. Para 1: why this "
        "role and connection to candidate background. Para 2: 2-3 specific achievements most relevant to "
        "the JD — if STAR work stories are provided, use the most relevant one to anchor this paragraph. "
        "Para 3: forward-looking close. If STAR work stories are provided, use the most relevant one in "
        "the body paragraph. Do not use generic phrases like 'I am excited to apply'. Under 300 words."
    )

    return _call_claude(system, user_content, max_tokens=1024)


def generate_hiring_manager_message(jd_analysis: dict, context: dict) -> str:
    name = context.get("name") or "the candidate"
    role = jd_analysis.get("job_title", "this role")
    company = jd_analysis.get("company", "your company")
    about_me = context.get("about_me") or ""

    # Pull 2-3 strong achievements across experience
    achievements = []
    for exp in (context.get("experience") or [])[:3]:
        bullets = exp.get("bullets") or []
        if bullets:
            achievements.append(bullets[0])

    tone_note = f"\n\nCandidate's own voice (match this tone exactly):\n{about_me}" if about_me else ""

    user_content = (
        f"The candidate's name: {name}\n"
        f"Role they are applying for: {role} at {company}\n"
        f"Key themes of the role: {', '.join(jd_analysis.get('key_themes') or [])}\n"
        f"Candidate's top achievements:\n" + "\n".join(f"- {a}" for a in achievements)
        + tone_note
    )

    system = (
        "Write a short LinkedIn connection request message FROM the candidate TO a hiring manager. "
        "Write in first person as the candidate. Warm and specific — mention the exact role title and "
        "one concrete achievement relevant to the role. Under 100 words. No flattery or generic openers "
        "like 'I came across your profile' or 'I am excited'. Sound like a real person, not a template."
    )

    return _call_claude(system, user_content, max_tokens=300)


def generate_referral_blurb(jd_analysis: dict, context: dict) -> str:
    name = context.get("name") or "this candidate"
    role = jd_analysis.get("job_title", "this role")
    company = jd_analysis.get("company", "your company")
    matched_skills = ", ".join(jd_analysis.get("matched_skills") or [])

    achievements = []
    for exp in (context.get("experience") or [])[:3]:
        bullets = exp.get("bullets") or []
        if bullets:
            achievements.append(f"{exp.get('title','')}: {bullets[0]}")

    user_content = (
        f"Candidate: {name}\n"
        f"Role: {role} at {company}\n"
        f"Matched skills: {matched_skills}\n"
        f"Top achievements:\n" + "\n".join(f"- {a}" for a in achievements)
    )

    system = (
        "Write a 2-3 sentence referral blurb a colleague can paste when submitting an internal referral "
        "for this candidate. Written in third person. Professional and specific — name the candidate, "
        "the role, and their most relevant achievement or skill. Complete sentences only, no truncation."
    )

    return _call_claude(system, user_content, max_tokens=300)
