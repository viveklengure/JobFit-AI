import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"
OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"


def _select_relevant_bullets(bullets: list, jd_analysis: dict, role_title: str) -> list:
    if not bullets:
        return []
    if len(bullets) <= 3:
        return bullets

    client = anthropic.Anthropic()
    indexed = "\n".join(f"{i}: {b}" for i, b in enumerate(bullets))
    key_themes = ", ".join(jd_analysis.get("key_themes") or [])
    matched_skills = ", ".join(jd_analysis.get("matched_skills") or [])

    prompt = (
        f"Role being applied for: {jd_analysis.get('job_title', '')}\n"
        f"Key themes: {key_themes}\n"
        f"Matched skills: {matched_skills}\n\n"
        f"Experience role: {role_title}\n"
        f"Bullets (index: text):\n{indexed}\n\n"
        "Return ONLY a JSON array of the indices (integers) of the top 3-5 most relevant bullets. "
        "Example: [0, 2, 4]. No other text."
    )

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        indices = json.loads(raw)
        selected = [bullets[i] for i in indices if isinstance(i, int) and 0 <= i < len(bullets)]
        return selected if selected else bullets[:4]
    except Exception as e:
        logger.warning(f"Bullet selection error: {e}")
        return bullets[:4]


def _find_executable(name: str, extra_paths: list = None) -> str:
    """Find an executable by checking PATH and a list of known locations."""
    import shutil
    found = shutil.which(name)
    if found:
        return found
    for path in (extra_paths or []):
        if Path(path).is_file():
            return path
    return None


def _safe_name(s: str) -> str:
    return "".join(c for c in s if c.isalnum() or c in " _-").strip().replace(" ", "_")


def build_word_resume(
    jd_analysis: dict,
    tailored_summary: str,
    context: dict,
    output_path: str = None,
) -> str:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    name = context.get("name") or "Resume"
    company = jd_analysis.get("company") or "Company"
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{_safe_name(name)}_{_safe_name(company)}_{date_str}.docx"
    output_path = output_path or str(OUTPUTS_DIR / filename)

    # Select relevant bullets per role
    experience = []
    for exp in (context.get("experience") or []):
        bullets = _select_relevant_bullets(
            exp.get("bullets") or [],
            jd_analysis,
            exp.get("title", ""),
        )
        experience.append({**exp, "bullets": bullets})

    projects = context.get("projects") or []
    skills = context.get("skills") or []
    education = context.get("education") or []
    phone = context.get("phone") or ""
    email = context.get("email") or ""
    linkedin = context.get("linkedin") or ""
    location = context.get("location") or ""

    # Build the Node.js script
    resume_data = {
        "name": name,
        "phone": phone,
        "email": email,
        "linkedin": linkedin,
        "location": location,
        "summary": tailored_summary,
        "skills": skills,
        "experience": experience,
        "projects": projects,
        "education": education,
        "outputPath": output_path,
    }

    js_script = _build_js_script(resume_data)

    # Write temp JS file into project root so node_modules/docx is resolvable
    project_root = Path(__file__).parent.parent
    tmp_js = str(project_root / "_resume_tmp.js")
    with open(tmp_js, "w") as f:
        f.write(js_script)

    node_bin = _find_executable("node", [
        "/opt/homebrew/bin/node",
        "/usr/local/bin/node",
        "/usr/bin/node",
    ])
    if not node_bin:
        raise RuntimeError("Node.js required. Install from https://nodejs.org")

    try:
        result = subprocess.run(
            [node_bin, tmp_js],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(project_root),
        )
        if result.returncode != 0:
            logger.error(f"Node.js error: {result.stderr}")
            raise RuntimeError(f"Node.js resume generation failed: {result.stderr}")
        return output_path
    except FileNotFoundError:
        raise RuntimeError("Node.js required. Install from https://nodejs.org")
    finally:
        try:
            os.unlink(tmp_js)
        except OSError:
            pass


def _build_js_script(data: dict) -> str:
    data_json = json.dumps(data, ensure_ascii=False)

    return f"""
const {{ Document, Packer, Paragraph, TextRun, AlignmentType, TabStopType,
         TabStopPosition, BorderStyle, LevelFormat, convertInchesToTwip }} = require('docx');
const fs = require('fs');

const data = {data_json};

function sectionHeader(title) {{
  return new Paragraph({{
    spacing: {{ before: 60, after: 40 }},
    border: {{
      bottom: {{ color: "000000", space: 1, style: BorderStyle.SINGLE, size: 6 }},
    }},
    children: [
      new TextRun({{
        text: title,
        bold: true,
        size: 22,
        font: "Arial",
      }}),
    ],
  }});
}}

function bullet(text) {{
  return new Paragraph({{
    bullet: {{ level: 0 }},
    spacing: {{ before: 0, after: 0 }},
    children: [
      new TextRun({{
        text: text,
        size: 21,
        font: "Arial",
      }}),
    ],
  }});
}}

const children = [];

// Name
children.push(new Paragraph({{
  alignment: AlignmentType.CENTER,
  spacing: {{ after: 40 }},
  children: [new TextRun({{ text: data.name, bold: true, size: 40, font: "Arial" }})],
}}));

// Contact line
const contactParts = [data.phone, data.email, data.linkedin, data.location].filter(Boolean);
children.push(new Paragraph({{
  alignment: AlignmentType.CENTER,
  spacing: {{ after: 80 }},
  children: [new TextRun({{ text: contactParts.join(" | "), size: 22, font: "Arial" }})],
}}));

// Summary
if (data.summary) {{
  children.push(sectionHeader("PROFESSIONAL SUMMARY"));
  children.push(new Paragraph({{
    spacing: {{ after: 40 }},
    children: [new TextRun({{ text: data.summary, size: 21, font: "Arial" }})],
  }}));
}}

// Core Competencies
if (data.skills && data.skills.length > 0) {{
  children.push(sectionHeader("CORE COMPETENCIES"));
  children.push(new Paragraph({{
    spacing: {{ after: 40 }},
    children: [new TextRun({{ text: data.skills.join(" | "), size: 21, font: "Arial" }})],
  }}));
}}

// Projects
if (data.projects && data.projects.length > 0) {{
  children.push(sectionHeader("PROJECTS"));
  for (const proj of data.projects) {{
    const techStr = proj.tech ? ` | ${{proj.tech}}` : '';
    const githubStr = proj.github ? ` | ${{proj.github}}` : '';
    children.push(new Paragraph({{
      spacing: {{ before: 40, after: 0 }},
      children: [
        new TextRun({{ text: proj.name + techStr + githubStr, bold: true, size: 22, font: "Arial" }}),
      ],
    }}));
    for (const b of (proj.bullets || [])) {{
      children.push(bullet(b));
    }}
  }}
}}

// Experience
if (data.experience && data.experience.length > 0) {{
  children.push(sectionHeader("PROFESSIONAL EXPERIENCE"));
  for (const exp of data.experience) {{
    const tabStop = convertInchesToTwip(6.5);
    children.push(new Paragraph({{
      spacing: {{ before: 40, after: 0 }},
      tabStops: [{{ type: TabStopType.RIGHT, position: tabStop }}],
      children: [
        new TextRun({{ text: exp.title || '', bold: true, size: 22, font: "Arial" }}),
        new TextRun({{ text: "\\t" + (exp.dates || ''), size: 22, font: "Arial" }}),
      ],
    }}));
    if (exp.company) {{
      children.push(new Paragraph({{
        spacing: {{ before: 0, after: 0 }},
        children: [new TextRun({{ text: exp.company, size: 21, font: "Arial", italics: true }})],
      }}));
    }}
    for (const b of (exp.bullets || [])) {{
      children.push(bullet(b));
    }}
  }}
}}

// Education
if (data.education && data.education.length > 0) {{
  children.push(sectionHeader("EDUCATION"));
  for (const edu of data.education) {{
    const tabStop = convertInchesToTwip(6.5);
    children.push(new Paragraph({{
      spacing: {{ before: 40, after: 0 }},
      tabStops: [{{ type: TabStopType.RIGHT, position: tabStop }}],
      children: [
        new TextRun({{ text: edu.degree || '', bold: true, size: 22, font: "Arial" }}),
        new TextRun({{ text: "\\t" + (edu.dates || ''), size: 22, font: "Arial" }}),
      ],
    }}));
    if (edu.school) {{
      children.push(new Paragraph({{
        spacing: {{ before: 0, after: 40 }},
        children: [new TextRun({{ text: edu.school, size: 21, font: "Arial", italics: true }})],
      }}));
    }}
  }}
}}

const doc = new Document({{
  sections: [{{
    properties: {{
      page: {{
        size: {{ width: 12240, height: 15840 }},
        margin: {{
          top: convertInchesToTwip(1),
          bottom: convertInchesToTwip(1),
          left: convertInchesToTwip(1),
          right: convertInchesToTwip(1),
        }},
      }},
    }},
    children: children,
  }}],
}});

Packer.toBuffer(doc).then(buffer => {{
  fs.writeFileSync(data.outputPath, buffer);
  console.log('Resume written to: ' + data.outputPath);
}}).catch(err => {{
  console.error('Error:', err);
  process.exit(1);
}});
"""


def build_pdf_resume(docx_path: str, output_path: str = None) -> str:
    docx_path = Path(docx_path)
    if output_path is None:
        output_path = str(docx_path.with_suffix(".pdf"))

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    soffice_bin = _find_executable("soffice", [
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/opt/homebrew/bin/soffice",
        "/usr/local/bin/soffice",
        "/usr/bin/soffice",
    ])

    if not soffice_bin:
        raise RuntimeError(
            "LibreOffice not found. Install from https://www.libreoffice.org to enable PDF export."
        )

    result = subprocess.run(
        [soffice_bin, "--headless", "--convert-to", "pdf", str(docx_path), "--outdir", str(OUTPUTS_DIR)],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        raise RuntimeError(f"LibreOffice conversion failed: {result.stderr}")

    generated_pdf = OUTPUTS_DIR / (docx_path.stem + ".pdf")
    if generated_pdf.exists() and str(generated_pdf) != output_path:
        shutil.move(str(generated_pdf), output_path)

    return output_path
