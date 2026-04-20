import hashlib
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.analyzer import analyze_jd
from src.company_matcher import (
    build_resume_summary,
    claude_score,
    deduplicate_jobs,
    get_strategy_summary,
    pre_filter_jobs,
    scrape_jobs,
)
from src.context_builder import build_context
from src.generator import (
    generate_cover_letter,
    generate_hiring_manager_message,
    generate_referral_blurb,
    generate_summary,
)
from src.resume_builder import build_pdf_resume, build_word_resume
from src.scraper import scrape_job

OUTPUTS_DIR = Path(__file__).parent / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

st.set_page_config(
    page_title="JobFit AI",
    page_icon="🎯",
    layout="wide",
)

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📁 Your Documents")

    # Section 1 — Docs folder status
    docs_dir = Path(__file__).parent / "docs"
    doc_files = [
        f for f in sorted(docs_dir.iterdir())
        if f.suffix.lower() in (".pdf", ".docx", ".txt") and f.is_file()
    ] if docs_dir.exists() else []

    st.subheader("docs/ folder")
    if doc_files:
        for f in doc_files:
            st.markdown(f"✅  {f.name}")
    else:
        st.markdown("📂  docs/ folder is empty")
    st.caption("Add files to docs/ folder for persistent storage")

    st.divider()

    # Section 2 — Upload
    uploaded_files = st.file_uploader(
        "Upload documents (this session only)",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        with st.spinner("Reading uploaded documents…"):
            st.session_state["context"] = build_context(uploaded_files)

    st.divider()

    # Section 3 — Context status
    context = st.session_state.get("context")
    if context and not context.get("empty") and not context.get("parse_error"):
        st.markdown("✅  **Context ready**")
        name = context.get("name")
        if name:
            st.markdown(f"Loaded for: **{name}**")
        n_docs = len(context.get("files_found") or [])
        n_stories = len(context.get("work_stories") or [])
        n_skills = len(context.get("skills") or [])
        st.markdown(f"{n_docs} documents · {n_stories} work stories · {n_skills} skills")
    elif context and context.get("parse_error"):
        detail = context.get("error_detail", "")
        if detail:
            st.error(f"⚠️  {detail}")
        else:
            st.warning("⚠️  Context parsed with errors — raw text will be used.")

    if st.button("🔄 Reload Context"):
        with st.spinner("Rebuilding context…"):
            st.session_state["context"] = build_context()
        st.rerun()

# ── Load context on first visit ──────────────────────────────────────────────

if "context" not in st.session_state:
    with st.spinner("Loading your documents…"):
        st.session_state["context"] = build_context()

context = st.session_state.get("context", {})

# ── Onboarding ────────────────────────────────────────────────────────────────

if not context or context.get("empty"):
    st.markdown(
        """
        <div style="text-align:center; padding: 4rem 2rem;">
            <h1>🎯 Welcome to JobFit AI</h1>
            <p style="font-size:1.2rem; color:#666;">
                Add your documents to the <code>docs/</code> folder or upload them
                in the sidebar to get started.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("### Documents to add:")
    st.markdown(
        """
        - ✅  `resume.pdf` or `resume.docx` — your main resume
        - ✅  `work_stories.txt` — STAR format achievements
        - ✅  `about_me.txt` — elevator pitch / tell me about yourself
        - ✅  `bio.txt` — LinkedIn summary or professional bio
        - ✅  Any other `.pdf`, `.docx`, or `.txt` file
        """
    )
    st.stop()

# ── Main area ─────────────────────────────────────────────────────────────────

main_tab, matcher_tab = st.tabs(["🎯 Job URL Analyzer", "🏢 Company Matcher"])

# ── Company Matcher tab ───────────────────────────────────────────────────────

with matcher_tab:
    st.title("Company Matcher")
    st.subheader("Paste a company's careers page URL. Get all roles ranked by fit.")

    apify_key = os.getenv("APIFY_API_KEY", "")
    if not apify_key:
        st.error("APIFY_API_KEY not found in .env — add it to use Company Matcher.")
        st.stop()

    # Build resume summary once on tab load
    if "resume_summary" not in st.session_state and context and not context.get("empty"):
        with st.spinner("Reading your resume…"):
            try:
                st.session_state["resume_summary"] = build_resume_summary(context)
            except Exception as e:
                st.warning(f"Could not build resume summary: {e}")

    col_company, col_url = st.columns([1, 2])
    with col_company:
        company_name = st.text_input("Company name", placeholder="e.g. Stripe")
    with col_url:
        careers_url = st.text_input("Careers page URL", placeholder="e.g. https://stripe.com/jobs")

    col_scan, col_clear = st.columns([2, 1])
    with col_scan:
        scan_btn = st.button("Scan Company", type="primary")
    with col_clear:
        if st.button("🔄 Clear & Rescan"):
            keys_to_clear = [k for k in st.session_state if k.startswith(("apify_", "scores_", "strategy_", "matcher_"))]
            for k in keys_to_clear:
                del st.session_state[k]
            st.rerun()

    if scan_btn:
        if not company_name.strip() or not careers_url.strip():
            st.error("Enter both company name and careers URL.")
            st.stop()

        if "resume_summary" not in st.session_state:
            st.error("No resume loaded. Add documents to docs/ or upload in the sidebar.")
            st.stop()

        apify_cache_key = f"apify_v2_{hashlib.md5(careers_url.encode()).hexdigest()[:8]}"
        resume_key = f"resume_summary_{hashlib.md5(st.session_state['resume_summary'].encode()).hexdigest()[:8]}"
        scores_key = f"scores_{apify_cache_key}_{resume_key}"

        if apify_cache_key not in st.session_state:
            status_placeholder = st.empty()
            with st.spinner(f"Scraping live job listings from {company_name}…"):
                try:
                    def update_status(msg):
                        status_placeholder.info(msg)

                    raw_jobs = scrape_jobs(careers_url.strip(), apify_key, company_name=company_name.strip(), progress_callback=update_status)
                    st.session_state[apify_cache_key] = raw_jobs
                    status_placeholder.empty()
                except (RuntimeError, TimeoutError) as e:
                    st.error(str(e))
                    st.stop()
                except Exception as e:
                    st.error(f"Apify error ({type(e).__name__}): {e}")
                    st.stop()

        raw_jobs = st.session_state[apify_cache_key]
        deduped = deduplicate_jobs(raw_jobs)
        filtered = pre_filter_jobs(deduped)

        st.info(f"Found {len(raw_jobs)} roles → {len(filtered)} after filtering → scoring now…")

        with st.expander(f"🔍 Debug: all {len(raw_jobs)} raw roles from Apify"):
            for j in raw_jobs:
                st.markdown(f"- **{j.get('title','—')}** | `{j.get('location','—')}`")

        if len(filtered) == 0:
            st.warning("No roles matched your location and seniority filters. Try a different careers URL or check if this company's ATS is supported.")
            st.stop()

        if scores_key not in st.session_state:
            with st.spinner("Scoring roles against your profile…"):
                try:
                    scored = claude_score(filtered, st.session_state["resume_summary"])
                    st.session_state[scores_key] = scored
                except Exception as e:
                    st.error(f"Scoring error: {e}")
                    st.stop()

        scored = st.session_state[scores_key]
        st.session_state["matcher_results"] = {"scored": scored, "company_name": company_name}

    # Render results
    matcher_results = st.session_state.get("matcher_results")
    if matcher_results:
        scored = matcher_results["scored"]
        company = matcher_results["company_name"]

        # Summary table
        st.markdown("### All Qualifying Roles")
        import pandas as pd
        table_data = []
        for i, r in enumerate(scored, 1):
            verdict_icon = {"Strong Apply": "🟢", "Apply": "🔵", "Apply with Caution": "🟡", "Skip": "🔴"}.get(r.get("verdict", ""), "⚪")
            table_data.append({
                "Rank": i,
                "Job Title": r.get("title", ""),
                "Team": r.get("department", ""),
                "Location": r.get("location", ""),
                "Score": r.get("score", 0),
                "Verdict": f"{verdict_icon} {r.get('verdict', '')}",
            })
        df = pd.DataFrame(table_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Detailed cards for all roles score >= 55
        applyable = [r for r in scored if r.get("score", 0) >= 55]
        skipped = [r for r in scored if r.get("score", 0) < 55]

        if applyable:
            st.markdown(f"### Role Details ({len(applyable)} roles worth applying to)")
            for r in applyable:
                score = r.get("score", 0)
                verdict = r.get("verdict", "")
                icon, bg, fg = {
                    "Strong Apply":       ("🟢", "#d4edda", "#155724"),
                    "Apply":              ("🔵", "#cce5ff", "#004085"),
                    "Apply with Caution": ("🟡", "#fff3cd", "#856404"),
                }.get(verdict, ("⚪", "#e2e3e5", "#383d41"))

                with st.expander(f"{icon} {r.get('title', '')} — {r.get('location', '')} — {score}/100"):
                    st.markdown(
                        f'<div style="background:{bg};color:{fg};padding:10px 14px;border-radius:8px;margin-bottom:12px">'
                        f'<strong>{icon} {verdict} · {score}/100</strong>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    col_fit, col_gap = st.columns(2)
                    with col_fit:
                        st.markdown("**Why I fit**")
                        for reason in (r.get("fit_reasons") or []):
                            st.markdown(f"- {reason}")
                    with col_gap:
                        st.markdown("**Gaps to address**")
                        gaps = r.get("gaps") or []
                        if gaps:
                            for gap in gaps:
                                st.markdown(f"- {gap}")
                        else:
                            st.markdown("- No significant gaps")

                    st.markdown(f"**Positioning tip:** {r.get('positioning_tip', '')}")

                    apply_url = r.get("apply_url", "")
                    if apply_url:
                        st.markdown(f"[Apply →]({apply_url})")

        if skipped:
            with st.expander(f"🔴 {len(skipped)} roles below threshold (Skip)"):
                for r in skipped:
                    st.markdown(f"- **{r.get('title', '')}** ({r.get('location', '')}) — {r.get('score', 0)}/100")

        # Strategy summary
        st.markdown("### Strategy Summary")
        strategy_key = f"strategy_{hashlib.md5(company.encode()).hexdigest()[:8]}"
        if strategy_key not in st.session_state:
            with st.spinner("Generating strategy…"):
                try:
                    st.session_state[strategy_key] = get_strategy_summary(
                        scored, company, st.session_state.get("resume_summary", "")
                    )
                except Exception as e:
                    st.session_state[strategy_key] = f"Could not generate strategy: {e}"
        st.markdown(st.session_state[strategy_key])

# ── Job URL Analyzer tab ──────────────────────────────────────────────────────

with main_tab:
    st.title("JobFit AI — Smart Job Application Assistant")
    st.subheader("Paste a job URL. Get a tailored resume, cover letter, and more in 60 seconds.")

    col_url, col_btn = st.columns([4, 1])
    with col_url:
        job_url = st.text_input("Job Posting URL", placeholder="https://...")
    manual_jd = st.text_area(
        "Or paste the job description here (if URL scraping is blocked)",
        height=150,
    )

    generate_btn = st.button("Analyze & Generate ↗", type="primary")

    if generate_btn:
        if not context or context.get("empty"):
            st.error("No candidate context found. Please add documents to docs/ or upload them in the sidebar.")
            st.stop()

        if not job_url.strip() and not manual_jd.strip():
            st.error("Please enter a job URL or paste the job description.")
            st.stop()

        with st.status("Working on it…", expanded=True) as status:
            st.write("🌐 Scraping job posting…")
            if job_url.strip():
                jd = scrape_job(job_url.strip())
                if jd.get("error") and manual_jd.strip():
                    st.warning(f"Scraping blocked — using pasted JD instead. ({jd.get('message','')})")
                    jd = {
                        "error": False,
                        "job_title": "",
                        "company": "",
                        "location": "",
                        "jd_text": manual_jd.strip(),
                        "url": job_url.strip(),
                    }
                elif jd.get("error"):
                    st.error(jd.get("message", "Could not scrape URL"))
                    st.stop()
            else:
                jd = {
                    "error": False,
                    "job_title": "",
                    "company": "",
                    "location": "",
                    "jd_text": manual_jd.strip(),
                    "url": "",
                }

            st.write("🔍 Analyzing JD against your profile…")
            jd_analysis = analyze_jd(jd, context)

            st.write("✏️  Generating tailored content…")
            tailored_summary = generate_summary(jd_analysis, context)
            cover_letter = generate_cover_letter(jd_analysis, context)
            hm_message = generate_hiring_manager_message(jd_analysis, context)
            referral = generate_referral_blurb(jd_analysis, context)

            st.write("📄 Building resume files…")
            docx_path = None
            pdf_path = None

            try:
                docx_path = build_word_resume(jd_analysis, tailored_summary, context)
            except RuntimeError as e:
                st.warning(f"Word resume: {e}")

            if docx_path:
                try:
                    pdf_path = build_pdf_resume(docx_path)
                except RuntimeError as e:
                    st.warning(f"PDF resume: {e}")

            status.update(label="Done! ✅", state="complete", expanded=False)

        st.session_state["results"] = {
            "jd": jd,
            "jd_analysis": jd_analysis,
            "tailored_summary": tailored_summary,
            "cover_letter": cover_letter,
            "hm_message": hm_message,
            "referral": referral,
            "docx_path": docx_path,
            "pdf_path": pdf_path,
        }

    results = st.session_state.get("results")
    if not results:
        st.stop()

    jd_analysis = results["jd_analysis"]
    jd = results["jd"]

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Match Analysis",
        "📄 Tailored Resume",
        "✉️ Cover Letter",
        "💬 Outreach Messages",
        "🌐 Raw JD",
    ])

    with tab1:
        verdict = jd_analysis.get("verdict", "")
        verdict_reasoning = jd_analysis.get("verdict_reasoning", "")

        verdict_styles = {
            "Strong Apply":       ("🟢", "#d4edda", "#155724"),
            "Apply":              ("🔵", "#cce5ff", "#004085"),
            "Apply with Caution": ("🟡", "#fff3cd", "#856404"),
            "Do Not Apply":       ("🔴", "#f8d7da", "#721c24"),
        }
        icon, bg, fg = verdict_styles.get(verdict, ("⚪", "#e2e3e5", "#383d41"))
        st.markdown(
            f'<div style="background:{bg};color:{fg};padding:16px 20px;border-radius:10px;margin-bottom:16px">'
            f'<span style="font-size:1.3rem;font-weight:700">{icon} Claude\'s Verdict: {verdict}</span>'
            f'<p style="margin:8px 0 0;font-size:0.95rem">{verdict_reasoning}</p>'
            f'</div>',
            unsafe_allow_html=True,
        )

        score = jd_analysis.get("match_score", 0)
        st.markdown(f"## Match Score: {score} / 100")

        breakdown = jd_analysis.get("match_breakdown") or {}
        c1, c2, c3 = st.columns(3)
        c1.metric("Technical Match", f"{breakdown.get('technical_match', 0)}%")
        c2.metric("Experience Match", f"{breakdown.get('experience_match', 0)}%")
        c3.metric("Domain Match", f"{breakdown.get('domain_match', 0)}%")

        col_match, col_gap = st.columns(2)
        with col_match:
            st.markdown("**✅ Matched Skills**")
            for skill in (jd_analysis.get("matched_skills") or []):
                st.markdown(
                    f'<span style="background:#d4edda;color:#155724;padding:2px 8px;border-radius:12px;margin:2px;display:inline-block">{skill}</span>',
                    unsafe_allow_html=True,
                )
        with col_gap:
            st.markdown("**⚠️ Gap Skills**")
            for skill in (jd_analysis.get("gap_skills") or []):
                st.markdown(
                    f'<span style="background:#fff3cd;color:#856404;padding:2px 8px;border-radius:12px;margin:2px;display:inline-block">{skill}</span>',
                    unsafe_allow_html=True,
                )

        st.markdown("**Key Themes**")
        themes_html = " ".join(
            f'<span style="background:#e2e3e5;color:#383d41;padding:2px 10px;border-radius:12px;margin:2px;display:inline-block">{t}</span>'
            for t in (jd_analysis.get("key_themes") or [])
        )
        st.markdown(themes_html, unsafe_allow_html=True)

    with tab2:
        docx_path = results.get("docx_path")
        pdf_path = results.get("pdf_path")

        if docx_path and Path(docx_path).exists():
            with open(docx_path, "rb") as f:
                st.download_button(
                    "⬇  Download Word Resume (.docx)",
                    data=f.read(),
                    file_name=Path(docx_path).name,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
        else:
            st.info("Word resume not generated. Ensure Node.js and the `docx` npm package are installed.")

        if pdf_path and Path(pdf_path).exists():
            with open(pdf_path, "rb") as f:
                st.download_button(
                    "⬇  Download PDF Resume (.pdf)",
                    data=f.read(),
                    file_name=Path(pdf_path).name,
                    mime="application/pdf",
                )
        else:
            st.info("PDF resume not generated. Ensure LibreOffice is installed.")

        st.markdown("**Tailored Summary Preview**")
        st.markdown(f"> {results['tailored_summary']}")
        st.caption("Resume tailored to emphasize skills matching this role")

    with tab3:
        cover = st.text_area(
            "Cover Letter",
            value=results["cover_letter"],
            height=350,
            key="cover_letter_area",
        )
        word_count = len(cover.split())
        st.caption(f"Word count: {word_count}")
        if st.button("📋 Copy Cover Letter", key="copy_cover"):
            st.write("*(Select all text above and copy)*")

    with tab4:
        col_hm, col_ref = st.columns(2)
        with col_hm:
            st.markdown("**LinkedIn Message to Hiring Manager**")
            hm = st.text_area(
                "Hiring Manager Message",
                value=results["hm_message"],
                height=200,
                key="hm_area",
                label_visibility="collapsed",
            )
            if st.button("📋 Copy", key="copy_hm"):
                st.write("*(Select all text above and copy)*")
        with col_ref:
            st.markdown("**Referral Blurb**")
            ref = st.text_area(
                "Referral Blurb",
                value=results["referral"],
                height=200,
                key="ref_area",
                label_visibility="collapsed",
            )
            if st.button("📋 Copy", key="copy_ref"):
                st.write("*(Select all text above and copy)*")

    with tab5:
        m1, m2, m3 = st.columns(3)
        m1.metric("Job Title", jd_analysis.get("job_title") or jd.get("job_title", "—"))
        m2.metric("Company", jd_analysis.get("company") or jd.get("company", "—"))
        m3.metric("Location", jd.get("location", "—"))
        with st.expander("Full Job Description", expanded=False):
            st.text(jd.get("jd_text", ""))
