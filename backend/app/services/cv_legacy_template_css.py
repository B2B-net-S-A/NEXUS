"""Arkusz wycofanego szablonu „CV firmowe” (brandowane CV etapu, ``.cv-wrapper``).

Szablon wycofano w generatorze CV v3 (23.09.2026) razem z rendererem
``cv_html_renderer.py`` — nowych dokumentów w tym układzie już nie ma. W bazie
zostają jednak CV etapów zapisane w nim wcześniej, a publiczny link
(``cv_public_document``) musi je pokazać ze stylami: sanitizer wycina
``<style>`` z treści, więc arkusz dokładamy wyłącznie z kodu.

Stała jest zamrożoną kopią ``<style>`` z ostatniej wersji renderera
(wywołanego bez danych kandydata, wariant ``standard``/``pl``). Szablon się już
nie zmienia, więc kopia nie ma się z czym rozjechać.
"""

LEGACY_BRANDED_CSS = """
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
    color: #1a1a2e;
    background: #fff;
    line-height: 1.55;
  }
  .cv-wrapper {
    max-width: 860px;
    margin: 0 auto;
    padding: 0;
  }
  .cv-header {
    background: linear-gradient(135deg, #1e40af 0%, #7c3aed 100%);
    color: #fff;
    padding: 32px 40px 28px;
    position: relative;
  }
  .cv-header-brand {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    opacity: 0.75;
    margin-bottom: 16px;
  }
  .cv-header-brand .dot { width: 6px; height: 6px; border-radius: 50%; background: #60a5fa; }
  .cv-name {
    font-size: 28px;
    font-weight: 800;
    letter-spacing: -0.02em;
    margin-bottom: 4px;
  }
  .cv-category {
    font-size: 14px;
    opacity: 0.85;
    font-weight: 500;
  }
  .blind-badge {
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
  }
  .cv-header-date {
    position: absolute;
    right: 40px;
    top: 32px;
    font-size: 11px;
    opacity: 0.6;
  }
  .cv-body {
    display: grid;
    grid-template-columns: 230px 1fr;
    gap: 0;
  }
  .cv-sidebar {
    background: #f8fafc;
    border-right: 1px solid #e2e8f0;
    padding: 28px 24px;
  }
  .cv-main {
    padding: 28px 32px;
  }
  section {
    margin-bottom: 24px;
  }
  section:last-child { margin-bottom: 0; }
  h2 {
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #3b82f6;
    border-bottom: 2px solid #dbeafe;
    padding-bottom: 6px;
    margin-bottom: 12px;
  }
  table.contact-table { width: 100%; border-collapse: collapse; }
  table.contact-table td { padding: 3px 0; font-size: 12px; }
  table.contact-table td.label {
    color: #64748b;
    font-weight: 600;
    white-space: nowrap;
    padding-right: 8px;
    font-size: 11px;
  }
  .skills-list { list-style: none; }
  .skills-list li {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 0;
    border-bottom: 1px solid #f1f5f9;
    font-size: 12px;
  }
  .skills-list li:last-child { border-bottom: none; }
  .skill-badge {
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 99px;
    background: #dbeafe;
    color: #1d4ed8;
    font-weight: 600;
  }
  .skill-years { font-size: 10px; color: #94a3b8; }
  .lang-list { list-style: none; }
  .lang-list li { padding: 3px 0; font-size: 12px; border-bottom: 1px solid #f1f5f9; }
  .lang-list li:last-child { border-bottom: none; }
  .exp-item {
    padding: 10px 0;
    border-bottom: 1px solid #f1f5f9;
  }
  .exp-item:last-child { border-bottom: none; }
  .exp-header {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 2px;
  }
  .exp-header strong { font-size: 13px; color: #0f172a; }
  .exp-company {
    font-size: 12px;
    color: #475569;
    font-style: italic;
  }
  .exp-dates { font-size: 11px; color: #94a3b8; margin-bottom: 4px; }
  .exp-desc { font-size: 12px; color: #475569; line-height: 1.5; }
  .edu-item {
    padding: 8px 0;
    border-bottom: 1px solid #f1f5f9;
  }
  .edu-item:last-child { border-bottom: none; }
  .edu-item strong { font-size: 13px; }
  .edu-degree { font-size: 12px; color: #475569; }
  .edu-year { font-size: 11px; color: #94a3b8; }
  .summary-text {
    font-size: 13px;
    color: #374151;
    line-height: 1.65;
    font-style: italic;
    background: #f0f9ff;
    border-left: 3px solid #38bdf8;
    padding: 10px 14px;
    border-radius: 0 6px 6px 0;
  }
  .highlight-section {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
    padding: 14px 16px;
  }
  .highlight-section h2 { color: #1d4ed8; border-color: #93c5fd; }
  .highlight-list li { border-bottom-color: #dbeafe; }
  .cv-footer {
    border-top: 1px solid #e2e8f0;
    padding: 12px 40px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 10px;
    color: #94a3b8;
    background: #f8fafc;
  }
  .footer-brand { display: flex; align-items: center; gap: 6px; font-weight: 600; }
  /* Telefon (audyt responsywności 23.09.2026): sztywna siatka 230px + 1fr
     zostawiała ~40 px na treść przy ~340 px iframe'a. */
  @media (max-width: 640px) {
    .cv-body { grid-template-columns: 1fr; }
    .cv-sidebar { border-right: 0; border-bottom: 1px solid #e2e8f0; padding: 20px 16px; }
    .cv-main { padding: 20px 16px; }
    .cv-header { padding: 24px 16px 20px; }
    .cv-header-date { position: static; margin-top: 8px; }
    .cv-footer { padding: 12px 16px; flex-wrap: wrap; gap: 4px; }
  }
  @media print {
    body { background: #fff; }
    .cv-wrapper { max-width: 100%; }
    .cv-header { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .highlight-section { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }
"""
