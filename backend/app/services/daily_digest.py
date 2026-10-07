"""Treść porannego skrótu „Twój dzień w NEXUSIE” (07.10.2026).

Czyste funkcje: dostają gotową kolejkę „Czeka na Ciebie”
(`api/board_tasks.build_board_tasks` — ta sama co pulpit) i dwa dodatki
(otwarte sprawy klientów DL, terminy rekrutacji), oddają temat, tekst i HTML.
Wysyłkę i harmonogram prowadzi `tasks/daily_digest_email.py`.

Do skrótu trafia tylko to, co wymaga ruchu tej osoby. Listy informacyjne
(„U innych”, wysłane do Cpro, CV w przeglądzie u kogoś) zostają na pulpicie.
Sekcja pokazuje najwyżej `MAX_ROWS` pozycji i liczbę pozostałych.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional
from urllib.parse import quote

from app.services.email import absolute_link, open_button_html

MAX_ROWS = 5
DASHBOARD_PATH = "/dashboard#czeka-na-ciebie"


@dataclass(frozen=True)
class Row:
    text: str
    path: Optional[str] = None


@dataclass(frozen=True)
class Section:
    title: str
    total: int
    rows: tuple[Row, ...] = field(default_factory=tuple)
    path: str = DASHBOARD_PATH


def _job(row: Any) -> str:
    title = getattr(row, "job_working_title", None) or getattr(row, "job_title", "")
    client = getattr(row, "client_name", None)
    return f"{title} ({client})" if client else title


def _pair_rows(rows: list, *, suffix: str = "") -> tuple[Row, ...]:
    return tuple(
        Row(
            f"{r.candidate_name} — {_job(r)}{suffix}",
            f"/jobs/{r.job_id}?candidate={r.candidate_id}",
        )
        for r in rows
    )


def _section(
    title: str,
    rows: tuple[Row, ...],
    total: Optional[int] = None,
    path: str = DASHBOARD_PATH,
) -> Optional[Section]:
    count = len(rows) if total is None else total
    if count <= 0:
        return None
    return Section(title=title, total=count, rows=rows[:MAX_ROWS], path=path)


def _count_section(title: str, count: int, path: str) -> Optional[Section]:
    return Section(title=title, total=count, path=path) if count > 0 else None


_MISSING = {"sheet": "brak arkusza", "rate": "brak stawki"}
_PREP_REASON = {
    "missing": "brak prepu",
    "late": "prep po terminie rozmowy",
    "weak": "słaby prep",
    "unrecorded": "prep bez nagrania",
}


def build_sections(
    tasks: Any,
    *,
    open_client_cases: int = 0,
    deadlines: tuple[tuple[int, str, date], ...] = (),
) -> list[Section]:
    """Sekcje skrótu w kolejności pilności. Pusta lista = brak maila."""
    out: list[Optional[Section]] = []
    flow = tasks.flow
    transit = tasks.cv_in_transit

    # Na tę osobę czeka ktoś inny — najpierw.
    out.append(
        _section(
            "CV czeka na Twój przegląd przed wysłaniem do klienta",
            tuple(
                Row(
                    f"{t.candidate_name} — {_job(t)}",
                    f"/jobs/{t.job_id}?candidate={t.candidate_id}&review=1",
                )
                for t in tasks.dl_review
            ),
        )
    )
    out.append(_section("Do wrzucenia do Cpro", _pair_rows(tasks.cpro_to_send)))
    if transit is not None:
        out.append(
            _section(
                "CV wróciło do poprawy",
                _pair_rows(transit.returned),
                transit.returned_total,
            )
        )
    agreements = tasks.agreements
    if agreements is not None:
        out.append(
            _section(
                "Umowy B2B do potwierdzenia podpisu",
                tuple(
                    Row(
                        f"{a.contract_number} · {a.candidate_name} — {_job(a)}",
                        f"/contracts/b2b-generator?q={quote(a.contract_number)}",
                    )
                    for a in agreements.to_confirm
                ),
            )
        )
        out.append(
            _section(
                "Umowy B2B do zamknięcia",
                tuple(
                    Row(
                        f"{a.contract_number} · {a.candidate_name} — {_job(a)}",
                        f"/contracts/b2b-generator?q={quote(a.contract_number)}",
                    )
                    for a in agreements.to_close
                ),
            )
        )
    out.append(
        _section(
            "Zmiany stawki kandydata do decyzji",
            tuple(
                Row(
                    f"{r.candidate_name} — {r.job_title}: {r.previous_label or '?'} → {r.requested_label}",
                    f"/jobs/{r.job_id}?candidate={r.candidate_id}",
                )
                for r in tasks.rate_changes
            ),
        )
    )

    if flow is not None:
        out.append(
            _section(
                "Nowe rekrutacje dla Ciebie",
                tuple(Row(_job(r), f"/jobs/{r.job_id}") for r in flow.new_requests),
            )
        )
        out.append(
            _section(
                "Ogłoszenia: nowe osoby do przejrzenia",
                tuple(
                    Row(f"{_job(r)} — {r.count} os.", f"/jobs/{r.job_id}")
                    for r in flow.postings
                ),
                flow.postings_total,
            )
        )
        out.append(
            _section(
                "Twoje blokady 12 h — zdecyduj, zanim wygasną",
                _pair_rows(flow.claimed),
            )
        )
        out.append(
            _section(
                "Screening do uzupełnienia",
                tuple(
                    Row(
                        f"{r.candidate_name} — {_job(r)} ({', '.join(_MISSING.get(m, m) for m in r.missing)})"
                        if r.missing
                        else f"{r.candidate_name} — {_job(r)}",
                        f"/jobs/{r.job_id}?candidate={r.candidate_id}",
                    )
                    for r in flow.screening
                ),
            )
        )
        out.append(
            _section(
                "Zweryfikowani — przygotuj CV do QC",
                _pair_rows(flow.verified),
            )
        )
        out.append(
            _section(
                "Najlepsze propozycje z bazy",
                tuple(
                    Row(
                        f"{_job(r)} — {r.total} propozycji",
                        f"/jobs/{r.job_id}?win=add&wintab=base",
                    )
                    for r in flow.top_proposals
                ),
            )
        )
        out.append(
            _section(
                f"Czeka na odpowiedź klienta ponad {flow.waiting_client_days} dni",
                _pair_rows(flow.waiting_client),
            )
        )
        out.append(
            _section(
                "Umowy B2B niepodpisane od ponad 2 dni",
                tuple(
                    Row(
                        f"{c.contract_number} · {c.partner_name or '—'}"
                        + (f" ({c.client_name})" if c.client_name else ""),
                        f"/contracts/b2b-generator?q={quote(c.contract_number)}",
                    )
                    for c in flow.unsigned_contracts
                ),
            )
        )
        out.append(
            _count_section(
                "Zamówienia z maila do weryfikacji",
                flow.order_mail_review,
                "/contracts?view=order-mail",
            )
        )

    out.append(
        _section(
            "Telefony do kandydatów (klient milczy)",
            tuple(
                Row(
                    f"{f.candidate_name}"
                    + (
                        f" — po terminie {f.overdue_days} dni" if f.overdue_days else ""
                    ),
                    f"/candidates/{f.candidate_id}",
                )
                for f in tasks.followups
                if f.state in ("overdue", "today")
            ),
        )
    )
    out.append(
        _section(
            "Prepy do poprawy przed rozmową u klienta",
            tuple(
                Row(
                    f"{p.candidate_name} — {p.job_title}: {_PREP_REASON.get(p.reason, p.reason)}",
                    f"/calendar?cycle={p.candidate_id}-{p.job_id}",
                )
                for p in tasks.prep_attention
            ),
        )
    )
    out.append(
        _section(
            "Propozycje automatu: kto prowadzi rekrutację — do zatwierdzenia",
            tuple(
                Row(f"{p.title} → {p.user_name}", f"/jobs/{p.job_id}")
                for p in tasks.allocation_proposals
            ),
        )
    )
    pending = tasks.pending_jobs
    if pending is not None:
        out.append(
            _section(
                "Rekrutacje do dokończenia",
                tuple(Row(p.title, f"/jobs/{p.job_id}") for p in pending.items),
            )
        )
    out.append(
        _section(
            "Niedokończone formularze nowej rekrutacji",
            tuple(
                Row(f.label, f"/jobs/new?form={f.id}") for f in tasks.unfinished_forms
            ),
        )
    )
    out.append(
        _count_section(
            "Otwarte sprawy Twoich klientów i umów", open_client_cases, "/dashboard"
        )
    )

    finance = tasks.finance
    if finance is not None:
        out.append(
            _count_section(
                "Braki w zamówieniach", finance.gaps_open, "/finance?view=order-changes"
            )
        )
        out.append(
            _count_section(
                "Nowe PDF-y zamówień do pobrania",
                finance.pdfs_new,
                "/finance?view=order-pdfs",
            )
        )
        out.append(
            _count_section(
                "Nieudane maile z zamówieniami",
                finance.order_mail_failed,
                "/contracts?view=order-mail",
            )
        )
        out.append(
            _section(
                "Zatrudnieni bez zamówienia",
                _pair_rows(finance.hired_without_order),
                finance.hired_without_order_total,
            )
        )

    out.append(
        _section(
            "Terminy Twoich rekrutacji w ciągu 7 dni",
            tuple(
                Row(f"{title} — {day:%d.%m}", f"/jobs/{job_id}")
                for job_id, title, day in deadlines
            ),
        )
    )
    return [s for s in out if s is not None]


def _more(section: Section) -> int:
    return section.total - len(section.rows)


def render(name: str, sections: list[Section], today: date) -> tuple[str, str, str]:
    """Temat, tekst i HTML skrótu."""
    total = sum(s.total for s in sections)
    subject = f"[Nexus] Twój dzień {today:%d.%m}: {total} do zrobienia"
    text: list[str] = [f"Cześć {name},", "", "Co dziś na Ciebie czeka w NEXUSIE:", ""]
    parts: list[str] = [
        f"<p>Cześć {html.escape(name)},</p>",
        "<p>Co dziś na Ciebie czeka w NEXUSIE:</p>",
    ]
    for section in sections:
        text.append(f"■ {section.title} ({section.total})")
        items: list[str] = []
        for row in section.rows:
            url = absolute_link(row.path) if row.path else None
            text.append(f"  – {row.text}" + (f": {url}" if url else ""))
            label = html.escape(row.text)
            items.append(
                f'<li><a href="{html.escape(url, quote=True)}">{label}</a></li>'
                if url
                else f"<li>{label}</li>"
            )
        more = _more(section)
        if more > 0:
            text.append(f"  – i jeszcze {more}")
            items.append(f"<li>i jeszcze {more}</li>")
        section_url = absolute_link(section.path)
        if not section.rows:
            text.append(f"  {section_url}")
        text.append("")
        title_html = f'<a href="{html.escape(section_url, quote=True)}">{html.escape(section.title)}</a>'
        parts.append(
            f'<p style="margin:16px 0 4px"><strong>{title_html}</strong> ({section.total})</p>'
            + (f'<ul style="margin:0">{"".join(items)}</ul>' if items else "")
        )
    dashboard = absolute_link(DASHBOARD_PATH)
    text += [
        f"Wszystko w jednym miejscu: {dashboard}",
        "",
        "— Nexus ATS (skrót wychodzi w dni robocze o 8:00, tylko gdy coś na Ciebie czeka)",
    ]
    parts += [
        f'<p style="margin-top:20px">{open_button_html(dashboard, "Otwórz „Czeka na Ciebie”")}</p>',
        '<hr><p style="color:#888;font-size:12px">Nexus ATS — skrót wychodzi '
        "w dni robocze o 8:00, tylko gdy coś na Ciebie czeka.</p>",
    ]
    return subject, "\n".join(text), "".join(parts)
