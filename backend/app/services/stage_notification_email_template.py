"""HTML+text template dla maila powiadamiającego o ruchu kandydata na stage.

Hardcoded szablon PL — w MVP nie konfigurujemy treści per regułą. Zmienne
podstawiane bezpiecznie (escaping HTML zrobione przez `html.escape` żeby
imiona kandydatów typu O'Brien czy nazwy klientów ze znakami specjalnymi
nie wybiły layoutu).
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


_WARSAW_TZ = ZoneInfo("Europe/Warsaw") if ZoneInfo else None


def _format_warsaw(dt: datetime) -> str:
    """Format YYYY-MM-DD HH:MM w strefie Warsaw."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if _WARSAW_TZ is not None:
        dt = dt.astimezone(_WARSAW_TZ)
    return dt.strftime("%Y-%m-%d %H:%M")


def render_stage_email(
    *,
    recipient_name: str,
    candidate_full_name: str,
    candidate_first_name: str,
    stage_name: str,
    client_name: Optional[str],
    job_title: str,
    job_id: int,
    mover_name: str,
    moved_at: datetime,
    notes: Optional[str],
    link: str,
) -> tuple[str, str, str]:
    """Zwraca ``(subject, text_body, html_body)``.

    Wszystkie zmienne escape'owane HTML-em w htmlowej wersji. Tekstowa wersja
    surowa (plain text fallback dla klientów bez HTML).
    """
    safe_recipient = html.escape(recipient_name or "")
    safe_candidate = html.escape(candidate_full_name)
    safe_stage = html.escape(stage_name)
    safe_client = html.escape(client_name or "")
    safe_job = html.escape(job_title)
    safe_mover = html.escape(mover_name)
    safe_link = html.escape(link, quote=True)
    moved_at_local = _format_warsaw(moved_at)

    subject_client_part = f" ({client_name})" if client_name else ""
    subject = f"Kandydat {candidate_first_name} → {stage_name}{subject_client_part}"

    text_lines = [
        f"Cześć {recipient_name},",
        "",
        f"Kandydat {candidate_full_name} został przeniesiony na etap „{stage_name}”.",
        "",
        f"Klient: {client_name or '—'}",
        f"Projekt: {job_title} (#{job_id})",
        f"Przeniósł: {mover_name}",
        f"Czas: {moved_at_local} (Warsaw)",
    ]
    if notes and notes.strip():
        text_lines.extend(["", f"Notatka przy ruchu:\n{notes.strip()}"])
    text_lines.extend(
        [
            "",
            f"Karta kandydata: {link}",
            "",
            "— Nexus ATS",
        ]
    )
    text_body = "\n".join(text_lines)

    notes_block_html = ""
    if notes and notes.strip():
        safe_notes = html.escape(notes.strip()).replace("\n", "<br>")
        notes_block_html = (
            '<p style="margin:16px 0 0"><strong>Notatka przy ruchu:</strong><br>'
            f"{safe_notes}</p>"
        )

    html_body = (
        '<div style="font-family:Arial,sans-serif;line-height:1.5;color:#222">'
        f"<p>Cześć {safe_recipient},</p>"
        f"<p>Kandydat <strong>{safe_candidate}</strong> został przeniesiony "
        f"na etap <strong>„{safe_stage}”</strong>.</p>"
        '<table style="border-collapse:collapse;margin:12px 0">'
        '<tr><td style="padding:4px 12px 4px 0;color:#666">Klient</td>'
        f'<td style="padding:4px 0"><strong>{safe_client or "—"}</strong></td></tr>'
        '<tr><td style="padding:4px 12px 4px 0;color:#666">Projekt</td>'
        f'<td style="padding:4px 0"><strong>{safe_job}</strong> (#{job_id})</td></tr>'
        '<tr><td style="padding:4px 12px 4px 0;color:#666">Przeniósł</td>'
        f'<td style="padding:4px 0">{safe_mover}</td></tr>'
        '<tr><td style="padding:4px 12px 4px 0;color:#666">Czas</td>'
        f'<td style="padding:4px 0">{moved_at_local} (Warsaw)</td></tr>'
        "</table>"
        f"{notes_block_html}"
        f'<p style="margin:20px 0"><a href="{safe_link}" '
        'style="display:inline-block;padding:10px 18px;'
        'background:#2563eb;color:#fff;text-decoration:none;border-radius:6px">'
        "Otwórz kartę kandydata</a></p>"
        '<hr style="border:0;border-top:1px solid #eee;margin:24px 0 12px">'
        '<p style="color:#888;font-size:12px;margin:0">Nexus ATS — '
        "powiadomienie o zmianie stage'a (skonfigurowane w "
        "ustawieniach pipeline'u).</p>"
        "</div>"
    )

    return subject, text_body, html_body
