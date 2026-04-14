import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.analyzer import analyze_jd
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
        # Step 1 — Scrape
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

        # Step 2 — Analyze
        st.write("🔍 Analyzing JD against your profile…")
        jd_analysis = analyze_jd(jd, context)

        # Step 3 — Generate content
        st.write("✏️  Generating tailored content…")
        tailored_summary = generate_summary(jd_analysis, context)
        cover_letter = generate_cover_letter(jd_analysis, context)
        hm_message = generate_hiring_manager_message(jd_analysis, context)
        referral = generate_referral_blurb(jd_analysis, context)

        # Step 4 — Build resume
        st.write("📄 Building resume files…")
        docx_path = None
        pdf_path = None
        docx_error = None
        pdf_error = None

        try:
            docx_path = build_word_resume(jd_analysis, tailored_summary, context)
        except RuntimeError as e:
            docx_error = str(e)
            st.warning(f"Word resume: {docx_error}")

        if docx_path:
            try:
                pdf_path = build_pdf_resume(docx_path)
            except RuntimeError as e:
                pdf_error = str(e)
                st.warning(f"PDF resume: {pdf_error}")

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

# ── Results tabs ──────────────────────────────────────────────────────────────

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

# Tab 1 — Match Analysis
with tab1:
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

# Tab 2 — Tailored Resume
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

# Tab 3 — Cover Letter
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

# Tab 4 — Outreach Messages
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

# Tab 5 — Raw JD
with tab5:
    m1, m2, m3 = st.columns(3)
    m1.metric("Job Title", jd_analysis.get("job_title") or jd.get("job_title", "—"))
    m2.metric("Company", jd_analysis.get("company") or jd.get("company", "—"))
    m3.metric("Location", jd.get("location", "—"))
    with st.expander("Full Job Description", expanded=False):
        st.text(jd.get("jd_text", ""))
