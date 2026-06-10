"""Legacy HTML CV renderer — internal helper for CandidateStageCV editor.

Used exclusively by ``app/api/candidate_stage_cv.py`` to seed the initial
HTML draft when a recruiter opens the brandowane CV editor on a stage. The
output is HTML (not DOCX) and is intentionally simpler than the
:mod:`app.services.cv_generator_b2b` pipeline used by ``/cv-generator``
(which is the 1:1 port of artur-t-96/CV-Generator).

Historically this code lived in ``app/api/cv_generator.py`` together with a
public ``POST /candidates/{id}/generate-cv`` endpoint. The endpoint was
removed in favour of the full B2B DOCX path; the renderer stayed because
the stage CV editor still uses it.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.models.candidate import Candidate
    from app.models.job import Job


LABELS = {
    "pl": {
        "cv_title": "Curriculum Vitae",
        "contact": "Dane kontaktowe",
        "skills": "Umiejętności",
        "experience": "Doświadczenie zawodowe",
        "education": "Edukacja",
        "languages": "Języki",
        "summary": "Podsumowanie",
        "key_skills_for_role": "Kluczowe kompetencje dla stanowiska",
        "prepared_by": "Przygotowane przez Nexus",
        "present": "obecnie",
        "phone": "Telefon",
        "email": "Email",
        "location": "Lokalizacja",
        "linkedin": "LinkedIn",
    },
    "en": {
        "cv_title": "Curriculum Vitae",
        "contact": "Contact Information",
        "skills": "Skills",
        "experience": "Professional Experience",
        "education": "Education",
        "languages": "Languages",
        "summary": "Summary",
        "key_skills_for_role": "Key Skills for This Role",
        "prepared_by": "Prepared by Nexus",
        "present": "present",
        "phone": "Phone",
        "email": "Email",
        "location": "Location",
        "linkedin": "LinkedIn",
    },
}


def _calc_experience_years(experience: list) -> int:
    """Estimate total years of experience from experience entries."""
    total_months = 0
    if not experience:
        return 0
    for exp in experience:
        start = exp.get("start", "")
        end = exp.get("end", "")
        try:
            start_year = int(str(start)[:4]) if start else None
            if end and str(end).lower() not in (
                "",
                "none",
                "null",
                "obecnie",
                "present",
                "now",
            ):
                end_year = int(str(end)[:4])
            else:
                end_year = datetime.now().year
            if start_year and end_year:
                total_months += max(0, (end_year - start_year) * 12)
        except Exception:
            pass
    return max(0, total_months // 12)


def _education_level(education: list) -> str:
    """Return highest education level from education list."""
    if not education:
        return "Brak danych"
    degrees = []
    for edu in education:
        deg = (edu.get("degree") or "").lower()
        degrees.append(deg)
    degree_priority = [
        "dokt",
        "phd",
        "magist",
        "master",
        "licencj",
        "bachelor",
        "inżynier",
        "engineer",
    ]
    for kw in degree_priority:
        for d in degrees:
            if kw in d:
                return education[0].get("degree") or "Wyższe"
    if education:
        return education[0].get("degree") or "Wyższe"
    return "Brak danych"


def _anonymize_text(text: str) -> str:
    """Replace potential company/person identifiers with placeholders."""
    text = re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "[EMAIL]", text)
    text = re.sub(r"(\+?\d[\s\-.]?){9,}", "[TELEFON]", text)
    return text


def _esc(value: object) -> str:
    """HTML-escape candidate-controlled values before f-string interpolation.

    Skills/experience/education come from imports and AI extraction of the
    candidate's own CV — without escaping, a crafted skill name is stored XSS
    served from the public share endpoint.
    """
    return html.escape(str(value or ""), quote=True)


def _generate_cv_html(
    candidate: "Candidate",
    template: str,
    language: str,
    job: Optional["Job"] = None,
) -> str:
    """Build full CV HTML string."""
    L = LABELS.get(language, LABELS["pl"])
    blind = template == "blind"

    name = (
        _esc(f"{candidate.name} {candidate.lastname}")
        if not blind
        else "Kandydat / Candidate"
    )
    email = _esc(candidate.email) if not blind and candidate.email else None
    phone = _esc(candidate.phone) if not blind and candidate.phone else None
    location = _esc(candidate.location) if not blind and candidate.location else None
    linkedin = _esc(candidate.linkedin) if not blind and candidate.linkedin else None
    ai_summary = _esc(candidate.ai_summary or "")

    skills = candidate.skills or []
    experience = candidate.experience or []
    education = candidate.education or []
    languages_list = candidate.languages or []

    if blind:
        cleaned_experience = []
        for exp in experience:
            e = dict(exp)
            e["company"] = "[Firma]"
            e["desc"] = _anonymize_text(e.get("desc") or "")
            cleaned_experience.append(e)
        experience = cleaned_experience

    job_skills_highlight: list[str] = []
    if job and job.requirements:
        req_text = job.requirements.lower()
        for skill in skills:
            skill_name = (skill.get("name") or "").lower()
            if skill_name and skill_name in req_text:
                job_skills_highlight.append(skill.get("name", ""))

    today = datetime.now().strftime("%Y-%m-%d")

    contact_rows = ""
    if email:
        contact_rows += f'<tr><td class="label">{L["email"]}</td><td>{email}</td></tr>'
    if phone:
        contact_rows += f'<tr><td class="label">{L["phone"]}</td><td>{phone}</td></tr>'
    if location:
        contact_rows += (
            f'<tr><td class="label">{L["location"]}</td><td>{location}</td></tr>'
        )
    if linkedin:
        contact_rows += (
            f'<tr><td class="label">{L["linkedin"]}</td><td>{linkedin}</td></tr>'
        )

    skills_html = ""
    if skills:
        items = []
        for s in skills:
            sname = _esc(s.get("name", ""))
            slevel = _esc(s.get("level", ""))
            syears = _esc(s.get("years", ""))
            badge = ""
            if slevel:
                badge += f' <span class="skill-badge">{slevel}</span>'
            if syears:
                badge += f' <span class="skill-years">{syears}y</span>'
            items.append(f"<li>{sname}{badge}</li>")
        skills_html = f'<ul class="skills-list">{"".join(items)}</ul>'

    exp_html = ""
    if experience:
        for exp in experience:
            role = _esc(exp.get("role") or "")
            company = _esc(exp.get("company") or "")
            start = _esc(exp.get("start") or "")
            end = _esc(exp.get("end") or L["present"])
            desc = _esc(exp.get("desc") or "")
            exp_html += f"""
<div class="exp-item">
  <div class="exp-header">
    <strong>{role}</strong>
    <span class="exp-company">{company}</span>
  </div>
  <div class="exp-dates">{start} – {end}</div>
  {f'<p class="exp-desc">{desc}</p>' if desc else ""}
</div>"""

    edu_html = ""
    if education:
        for edu in education:
            school = _esc(edu.get("school") or "")
            degree = _esc(edu.get("degree") or "")
            field = _esc(edu.get("field") or "")
            year = _esc(edu.get("year") or "")
            edu_html += f"""
<div class="edu-item">
  <strong>{school}</strong>
  {f'<div class="edu-degree">{degree}{" — " + field if field else ""}</div>' if degree else ""}
  {f'<div class="edu-year">{year}</div>' if year else ""}
</div>"""

    lang_html = ""
    if languages_list:
        items = []
        for lang in languages_list:
            lname = _esc(lang.get("lang") or lang.get("name") or "")
            llevel = _esc(lang.get("level") or "")
            items.append(f"<li>{lname}{' — ' + llevel if llevel else ''}</li>")
        lang_html = f'<ul class="lang-list">{"".join(items)}</ul>'

    summary_section = ""
    if ai_summary and not blind:
        summary_section = f"""
<section>
  <h2>{L["summary"]}</h2>
  <p class="summary-text">{ai_summary}</p>
</section>"""

    tailored_section = ""
    if job and job_skills_highlight:
        items = "".join(f"<li>{_esc(s)}</li>" for s in job_skills_highlight)
        tailored_section = f"""
<section class="highlight-section">
  <h2>{L["key_skills_for_role"]} — {_esc(job.title)}</h2>
  <ul class="skills-list highlight-list">{items}</ul>
</section>"""

    blind_badge = '<span class="blind-badge">ANONIMOWY PROFIL</span>' if blind else ""

    html = f"""<!DOCTYPE html>
<html lang="{language}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{L["cv_title"]} — {name}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
    color: #1a1a2e;
    background: #fff;
    line-height: 1.55;
  }}
  .cv-wrapper {{
    max-width: 860px;
    margin: 0 auto;
    padding: 0;
  }}
  .cv-header {{
    background: linear-gradient(135deg, #1e40af 0%, #7c3aed 100%);
    color: #fff;
    padding: 32px 40px 28px;
    position: relative;
  }}
  .cv-header-brand {{
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    opacity: 0.75;
    margin-bottom: 16px;
  }}
  .cv-header-brand .dot {{ width: 6px; height: 6px; border-radius: 50%; background: #60a5fa; }}
  .cv-name {{
    font-size: 28px;
    font-weight: 800;
    letter-spacing: -0.02em;
    margin-bottom: 4px;
  }}
  .cv-category {{
    font-size: 14px;
    opacity: 0.85;
    font-weight: 500;
  }}
  .blind-badge {{
    display: inline-block;
    margin-top: 10px;
    background: rgba(255,255,255,0.15);
    border: 1px solid rgba(255,255,255,0.3);
    color: #fff;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.1em;
    padding: 3px 10px;
    border-radius: 99px;
    text-transform: uppercase;
  }}
  .cv-header-date {{
    position: absolute;
    right: 40px;
    top: 32px;
    font-size: 11px;
    opacity: 0.6;
  }}
  .cv-body {{
    display: grid;
    grid-template-columns: 230px 1fr;
    gap: 0;
  }}
  .cv-sidebar {{
    background: #f8fafc;
    border-right: 1px solid #e2e8f0;
    padding: 28px 24px;
  }}
  .cv-main {{
    padding: 28px 32px;
  }}
  section {{
    margin-bottom: 24px;
  }}
  section:last-child {{ margin-bottom: 0; }}
  h2 {{
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #3b82f6;
    border-bottom: 2px solid #dbeafe;
    padding-bottom: 6px;
    margin-bottom: 12px;
  }}
  table.contact-table {{ width: 100%; border-collapse: collapse; }}
  table.contact-table td {{ padding: 3px 0; font-size: 12px; }}
  table.contact-table td.label {{
    color: #64748b;
    font-weight: 600;
    white-space: nowrap;
    padding-right: 8px;
    font-size: 11px;
  }}
  .skills-list {{ list-style: none; }}
  .skills-list li {{
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 0;
    border-bottom: 1px solid #f1f5f9;
    font-size: 12px;
  }}
  .skills-list li:last-child {{ border-bottom: none; }}
  .skill-badge {{
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 99px;
    background: #dbeafe;
    color: #1d4ed8;
    font-weight: 600;
  }}
  .skill-years {{ font-size: 10px; color: #94a3b8; }}
  .lang-list {{ list-style: none; }}
  .lang-list li {{ padding: 3px 0; font-size: 12px; border-bottom: 1px solid #f1f5f9; }}
  .lang-list li:last-child {{ border-bottom: none; }}
  .exp-item {{
    padding: 10px 0;
    border-bottom: 1px solid #f1f5f9;
  }}
  .exp-item:last-child {{ border-bottom: none; }}
  .exp-header {{
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 2px;
  }}
  .exp-header strong {{ font-size: 13px; color: #0f172a; }}
  .exp-company {{
    font-size: 12px;
    color: #475569;
    font-style: italic;
  }}
  .exp-dates {{ font-size: 11px; color: #94a3b8; margin-bottom: 4px; }}
  .exp-desc {{ font-size: 12px; color: #475569; line-height: 1.5; }}
  .edu-item {{
    padding: 8px 0;
    border-bottom: 1px solid #f1f5f9;
  }}
  .edu-item:last-child {{ border-bottom: none; }}
  .edu-item strong {{ font-size: 13px; }}
  .edu-degree {{ font-size: 12px; color: #475569; }}
  .edu-year {{ font-size: 11px; color: #94a3b8; }}
  .summary-text {{
    font-size: 13px;
    color: #374151;
    line-height: 1.65;
    font-style: italic;
    background: #f0f9ff;
    border-left: 3px solid #38bdf8;
    padding: 10px 14px;
    border-radius: 0 6px 6px 0;
  }}
  .highlight-section {{
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
    padding: 14px 16px;
  }}
  .highlight-section h2 {{ color: #1d4ed8; border-color: #93c5fd; }}
  .highlight-list li {{ border-bottom-color: #dbeafe; }}
  .cv-footer {{
    border-top: 1px solid #e2e8f0;
    padding: 12px 40px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 10px;
    color: #94a3b8;
    background: #f8fafc;
  }}
  .footer-brand {{ display: flex; align-items: center; gap: 6px; font-weight: 600; }}
  @media print {{
    body {{ background: #fff; }}
    .cv-wrapper {{ max-width: 100%; }}
    .cv-header {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .highlight-section {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  }}
</style>
</head>
<body>
<div class="cv-wrapper">

  <div class="cv-header">
    <div class="cv-header-brand">
      <div class="dot"></div>
      Nexus &nbsp;·&nbsp; B2B.net S.A.
    </div>
    <div class="cv-header-date">{today}</div>
    <div class="cv-name">{name}</div>
    {f'<div class="cv-category">{candidate.competence_category}</div>' if candidate.competence_category else ""}
    {blind_badge}
  </div>

  <div class="cv-body">

    <aside class="cv-sidebar">
      {f'<section><h2>{L["contact"]}</h2><table class="contact-table">{contact_rows}</table></section>' if contact_rows else ""}

      {f"<section><h2>{L['skills']}</h2>{skills_html}</section>" if skills_html else ""}

      {f"<section><h2>{L['languages']}</h2>{lang_html}</section>" if lang_html else ""}
    </aside>

    <main class="cv-main">
      {summary_section}
      {tailored_section}
      {f"<section><h2>{L['experience']}</h2>{exp_html}</section>" if exp_html else ""}
      {f"<section><h2>{L['education']}</h2>{edu_html}</section>" if edu_html else ""}
    </main>
  </div>

  <div class="cv-footer">
    <div class="footer-brand">⚡ Nexus · B2B.net S.A.</div>
    <div>{L["prepared_by"]} · {today}</div>
  </div>

</div>
</body>
</html>"""

    return html


__all__ = ["LABELS", "_generate_cv_html"]
