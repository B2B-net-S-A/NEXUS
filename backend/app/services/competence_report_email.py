"""Mail „Twój raport kompetencji” do osoby, która wysłała CV z warunkami ze strony.

Rodzaj ``competence_report`` w ``notification_delivery.CATALOG``: mail do kandydata,
domyślnie wyłączony, włącza admin po próbie na adresach wewnętrznych (decyzja
Artura 25.11.2026). Na czas próby ``COMPETENCE_REPORT_TEST_RECIPIENTS`` (adresy po
przecinku) zawęża odbiorców: pętla wysyłki pyta ``recipient_allowed`` przed
``guarded_send``.

Rysujemy wyłącznie z ``ReportSnapshot`` (``competence_report_schema``), więc mail
pokazuje to, co rekruter widział w kolejce. Układ z makiety „3 · Mail z raportem”
(b2bnetwork-www ``docs/makiety/raport-24h.html``): nagłówek z tym, jak odczytaliśmy
CV, stawka na skali, lejek projektów, co otworzy więcej projektów, technologie,
projekty i opiekun. Każda część tylko wtedy, gdy ma dane.

Zasady, które łatwo cofnąć:
- nigdy nazwy klienta ani ``job_id`` (tytuł projektu jest publiczny);
- wszystko z bazy i z formularza przechodzi przez ``html.escape``;
- HTML dla Outlooka: tabele, style w linii, bez flex/grid, zmiennych CSS i pozycji
  absolutnych; skala stawki i paski lejka to komórki tabeli o policzonych
  szerokościach; bez fontów z sieci i bez obrazków.
"""

from __future__ import annotations

import html
import os
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings
from app.services.competence_report_schema import (
    MIN_GROUP,
    Lever,
    MarketRate,
    MissingTech,
    ReportJob,
    ReportSnapshot,
    TechPremium,
)

KIND = "competence_report"
TEST_RECIPIENTS_SETTING = "COMPETENCE_REPORT_TEST_RECIPIENTS"

_BURGUNDY = "#961621"
_INK = "#1F1115"
_INK2 = "#2E1A1F"
_INK_SOFT = "#5E4A4E"
_PEACH = "#FFD6C9"
_RED = "#C42329"
_RED_TEXT = "#B0222A"
_SNOW = "#FAF6F4"
_RULE = "#E6D6D3"
_WHITE = "#FFFFFF"
_TRACK = "#ECE3DC"
_F = "font-family:'Segoe UI','Helvetica Neue',Helvetica,Arial,sans-serif;"

COMPANY_LINE = "B2B.NET S.A., Al. Jerozolimskie 180, 02-486 Warszawa"
RATE_NOTE = (
    "Stawki to ostatnie stawki podane w rozmowach rekrutacyjnych B2B Network "
    f"w ciągu 12 miesięcy, grupa minimum {MIN_GROUP} osób."
)
PREMIUM_NOTE = "Premia za technologię to różnica median, nie obietnica podwyżki."

_e = html.escape


@dataclass(frozen=True)
class ReportLinks:
    edit_conditions_url: str
    unsubscribe_url: str
    #: dla nagłówka ``List-Unsubscribe`` (RFC 8058), nie dla treści maila
    one_click_unsubscribe_url: Optional[str] = None


@dataclass(frozen=True)
class RenderedMail:
    subject: str
    html: str
    text: str
    list_unsubscribe: Optional[str] = None


# ── Próba na adresach wewnętrznych ──────────────────────────────────────────


def trial_recipients() -> frozenset[str]:
    """Adresy próby (małymi literami). Pusto = brak ograniczenia."""
    raw = getattr(settings, TEST_RECIPIENTS_SETTING, None)
    if raw is None:
        raw = os.environ.get(TEST_RECIPIENTS_SETTING, "")
    return frozenset(a.strip().lower() for a in str(raw).split(",") if "@" in a)


def recipient_allowed(email: Optional[str]) -> bool:
    """Czy ten adres może dostać raport. Polityka (``guarded_send``) i tak decyduje
    o całym rodzaju; to tylko zawężenie odbiorców na czas próby."""
    address = (email or "").strip().lower()
    if "@" not in address:
        return False
    allowed = trial_recipients()
    return not allowed or address in allowed


# ── Liczby i odmiana ────────────────────────────────────────────────────────


def fmt_num(value: int) -> str:
    """Polski zapis: spacja (twarda) jako separator tysięcy."""
    return f"{int(value):,}".replace(",", " ")


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n == 1:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def _years(n: int) -> str:
    return f"{n} {_plural(n, 'rok', 'lata', 'lat')}"


def _since(months: int) -> str:
    """„od 3 lat”, „od 1 roku”, „od 8 miesięcy”."""
    if months >= 12:
        y = months // 12
        return f"od {y} {'roku' if y == 1 else 'lat'}"
    return f"od {months} {'miesiąca' if months == 1 else 'miesięcy'}"


def _projects(n: int) -> str:
    return f"{n} {_plural(n, 'projekt', 'projekty', 'projektów')}"


_MODES = {"remote": "zdalnie", "hybrid": "hybrydowo", "onsite": "w biurze"}
_CONTRACT = {"b2b": "B2B", "uop": "UoP", "any": "B2B albo UoP"}
_START = {
    "now": "start od zaraz",
    "1m": "start za miesiąc",
    "2-3m": "start za 2–3 miesiące",
    "browsing": "na razie się rozglądam",
}


def _signed(n: int) -> str:
    return f"+{fmt_num(n)}" if n > 0 else f"−{fmt_num(-n)}" if n < 0 else "0"


# ── Treść (wspólna dla HTML i tekstu) ───────────────────────────────────────


def _chips(s: ReportSnapshot) -> list[str]:
    c, p = s.conditions, s.profile
    chips = [f"{p.role_label} · {_years(p.years)}" if p.years else p.role_label]
    if p.city:
        chips.append(p.city)
    if c.modes:
        mode = " albo ".join(_MODES[m] for m in c.modes)
        if c.office_days_max is not None and set(c.modes) & {"hybrid", "onsite"}:
            d = c.office_days_max
            mode += (
                ", bez biura" if d == 0 else f", do {d} {'dnia' if d == 1 else 'dni'}"
            )
        chips.append(mode)
    chips.append(f"{fmt_num(c.rate)} zł/h {_CONTRACT[c.contract]}")
    if c.start:
        chips.append(_START[c.start])
    return chips


def _group_label(m: MarketRate) -> str:
    g = m.group
    parts = [g.role_label]
    if g.years_bucket:
        parts.append(f"{g.years_bucket} lat")
    parts.append(g.city or "cała Polska")
    return ", ".join(parts)


def _rate_title(s: ReportSnapshot) -> str:
    m, r = s.market, s.rate_position
    x = fmt_num(r.expected)
    if r.expected < m.p25:
        return f"Twoje {x} zł/h jest poniżej typowych stawek dla Twojego CV"
    if r.expected > m.p75:
        return f"Twoje {x} zł/h jest powyżej typowych stawek dla Twojego CV"
    return f"Twoje {x} zł/h jest realne dla Twojego CV"


def _rate_text(s: ReportSnapshot) -> list[str]:
    m, r = s.market, s.rate_position
    out = []
    if m.group.widened:
        where = "dla całej Polski" if not m.group.city else "w szerszej grupie"
        out.append(
            f"W węższej grupie było mniej niż {MIN_GROUP} osób, "
            f"więc porównujemy {where}."
        )
    out.append(
        f"{_group_label(m)}: połowa osób dostaje {fmt_num(m.p25)}–{fmt_num(m.p75)} zł/h, "
        f"mediana {fmt_num(m.median)}."
    )
    pct = r.expected_vs_median_pct
    if pct > 0:
        out.append(f"Twoje oczekiwania są {pct}% nad medianą.")
    elif pct < 0:
        out.append(f"Twoje oczekiwania są {-pct}% pod medianą.")
    else:
        out.append("Twoje oczekiwania są równe medianie.")
    if r.current is not None:
        side = (
            "poniżej mediany"
            if r.current < m.median
            else "powyżej mediany"
            if r.current > m.median
            else "tyle, ile mediana"
        )
        out.append(f"Dziś zarabiasz {fmt_num(r.current)}, czyli {side}.")
    return out


def _funnel_text(s: ReportSnapshot) -> str:
    n = s.funnel[-1].count
    if n == 0:
        tail = " Niżej zobaczysz, co to zmieni." if s.levers else ""
        return f"Dziś żaden projekt nie spełnia wszystkich warunków.{tail}"
    verb = _plural(n, "spełnia", "spełniają", "spełnia")
    who = " Twój opiekun odezwie się w ich sprawie." if s.owner else ""
    return f"{_projects(n)} {verb} wszystko.{who}"


def _missing_text(t: MissingTech) -> str:
    projects = "projektu" if t.of == 1 else "projektów"
    return f"W wymaganiach {t.jobs} z {t.of} {projects} dla Twojej roli."


def _owner_text(s: ReportSnapshot) -> str:
    if s.variant == "limited":
        return (
            "Zadzwoni i porozmawia o projektach. Wolisz mail? Odpisz na tę wiadomość."
        )
    return "Odezwie się w sprawie projektów. Wolisz mail? Odpisz na tę wiadomość."


LIMITED_TEXT = (
    "Dla tego CV nie umiemy jeszcze rzetelnie policzyć stawki: mamy za mało "
    "podobnych rozmów."
)


def _shows_rate(s: ReportSnapshot) -> bool:
    return s.variant == "full" and s.market is not None and s.rate_position is not None


def _greeting(first_name: Optional[str]) -> str:
    name = " ".join((first_name or "").split())[:40]
    return f"Dzień dobry, {name}." if name else "Dzień dobry."


# ── HTML ────────────────────────────────────────────────────────────────────


def _sec(inner: str, *, bg: str = _WHITE, border: bool = True) -> str:
    line = f"border:1px solid {_RULE};" if border else ""
    return (
        '<tr><td style="padding:0 0 18px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'bgcolor="{bg}" style="background:{bg};{line}border-radius:14px">'
        f'<tr><td style="padding:20px">{inner}</td></tr></table></td></tr>'
    )


def _k(label: str, color: str = _RED_TEXT) -> str:
    return (
        f'<p style="margin:0 0 8px;{_F}font-size:12px;line-height:16px;font-weight:bold;'
        f'letter-spacing:1px;text-transform:uppercase;color:{color}">{_e(label)}</p>'
    )


def _h5(text: str, color: str = _INK, margin: str = "0 0 12px") -> str:
    return (
        f'<p style="margin:{margin};{_F}font-size:22px;line-height:27px;font-weight:800;'
        f'color:{color}">{_e(text)}</p>'
    )


def _p(text: str, color: str = _INK_SOFT, *, margin: str = "0") -> str:
    return (
        f'<p style="margin:{margin};{_F}font-size:16px;line-height:24px;color:{color}">'
        f"{text}</p>"
    )


def _cell(width: int, bg: Optional[str]) -> str:
    fill = (
        f' bgcolor="{bg}" style="background:{bg};font-size:0;line-height:0"'
        if bg
        else (' style="font-size:0;line-height:0"')
    )
    return f'<td width="{width}%"{fill}>&nbsp;</td>'


def _widths(raw: list[float]) -> list[int]:
    """Szerokości w % (całkowite, suma 100), każda co najmniej 1."""
    total = sum(raw) or 1
    ints = [max(1, int(round(v * 100 / total))) for v in raw]
    ints[ints.index(max(ints))] += 100 - sum(ints)
    return ints


def _rate_scale(s: ReportSnapshot) -> str:
    """Skala p25–p75 z medianą i „Ty: X” — komórki tabeli zamiast pozycji absolutnych."""
    m, you = s.market, s.rate_position.expected
    span = max(m.p75 - m.p25, 10)
    lo = (min(m.p25, you) - span // 2) // 10 * 10
    hi = -(-(max(m.p75, you) + span // 2) // 10) * 10

    def pct(v: int) -> float:
        return (v - lo) * 100 / (hi - lo)

    marks = sorted([(m.median, _INK), (you, _RED)], key=lambda x: x[0])
    stops = [lo, m.p25, m.p75, hi] + [v for v, _ in marks]
    edges = sorted(set(stops))
    cols: list[
        tuple[float, Optional[str], Optional[str]]
    ] = []  # (szer., pasek, znacznik)
    for a, b in zip(edges, edges[1:]):
        for v, color in marks:
            if v == a:
                cols.append((1.0, color, color))
        inside = m.p25 <= a and b <= m.p75
        cols.append((pct(b) - pct(a), _PEACH if inside else _TRACK, None))
    for v, color in marks:
        if v == edges[-1]:
            cols.append((1.0, color, color))
    widths = _widths([c[0] for c in cols])

    def row(height: int, which: str) -> str:
        cells = "".join(
            _cell(w, (bar if which == "bar" else mark))
            for w, (_, bar, mark) in zip(widths, cols)
        )
        return f'<tr style="height:{height}px">{cells}</tr>'

    bar = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="table-layout:fixed">'
        + row(10, "mark")
        + row(10, "bar")
        + row(10, "mark")
        + "</table>"
    )

    lab = f"{_F}font-size:13px;line-height:18px;font-weight:bold;white-space:nowrap;"
    p_you = int(round(pct(you)))
    you_label = f'<span style="color:{_RED_TEXT}">Ty: {fmt_num(you)}</span>'
    if p_you <= 70:
        top = (
            f'<td width="{max(p_you - 2, 0)}%" style="font-size:0">&nbsp;</td>'
            f'<td style="{lab}">{you_label}</td>'
        )
    else:
        top = (
            f'<td align="right" style="{lab}">{you_label}</td>'
            f'<td width="{max(100 - p_you - 2, 0)}%" style="font-size:0">&nbsp;</td>'
        )
    top_row = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f"<tr>{top}</tr></table>"
    )

    points = [(m.p25, "p25"), (m.median, "mediana"), (m.p75, "p75")]
    positions = [pct(v) for v, _ in points]
    if (
        min(b - a for a, b in zip(positions, positions[1:])) >= 9
        and positions[-1] <= 88
    ):
        w = _widths(
            [
                positions[0],
                positions[1] - positions[0],
                positions[2] - positions[1],
                100 - positions[2],
            ]
        )
        cells = f'<td width="{w[0]}%" style="font-size:0">&nbsp;</td>' + "".join(
            f'<td width="{wi}%" style="{lab}color:{_INK}">{fmt_num(v)}</td>'
            for wi, (v, _) in zip(w[1:], points)
        )
        bottom = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0"><tr>{cells}</tr></table>'
        )
    else:
        bottom = _p(
            f"{fmt_num(m.p25)} · mediana {fmt_num(m.median)} · {fmt_num(m.p75)} zł/h",
            _INK,
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:2px 0 12px">'
        f'<tr><td style="padding:0 0 4px">{top_row}</td></tr>'
        f"<tr><td>{bar}</td></tr>"
        f'<tr><td style="padding:4px 0 0">{bottom}</td></tr></table>'
    )


def _html_rate(s: ReportSnapshot) -> str:
    return _sec(
        _k("Stawka")
        + _h5(_rate_title(s))
        + _rate_scale(s)
        + _p(_e(" ".join(_rate_text(s))))
    )


def _html_funnel(s: ReportSnapshot) -> str:
    first = s.funnel[0].count or 1
    rows = []
    for i, step in enumerate(s.funnel):
        end = i == len(s.funnel) - 1
        color = _PEACH if end else "#F7EFEC"
        bar_bg = _PEACH if end else _INK_SOFT
        width = max(2, min(100, round(step.count * 100 / first)))
        rows.append(
            '<tr><td style="padding:0 12px 10px 0">'
            f'<p style="margin:0 0 4px;{_F}font-size:15px;line-height:20px;font-weight:600;'
            f'color:{color}">{_e(step.label)}</p>'
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            f'width="{width}%"><tr><td bgcolor="{bar_bg}" style="background:{bar_bg};'
            'height:14px;font-size:0;line-height:0;border-radius:3px">&nbsp;</td></tr></table></td>'
            f'<td width="48" align="right" valign="bottom" style="padding:0 0 8px;{_F}'
            f'font-size:24px;line-height:28px;font-weight:800;color:{_PEACH if end else _WHITE}">'
            f"{fmt_num(step.count)}</td></tr>"
        )
    table = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:4px 0 8px">{"".join(rows)}</table>'
    )
    return _sec(
        _k("Projekty na Twoich warunkach", _PEACH)
        + _h5("Tyle naszych projektów zostaje po Twoich warunkach", _WHITE)
        + table
        + _p(_e(_funnel_text(s)), "#D8CBCC"),
        bg=_INK,
        border=False,
    )


def _html_lever(lever: Lever, first: bool) -> str:
    line = "" if first else "border-top:1px solid #E8B9AA;"
    hint = (
        f'<br><span style="{_F}font-size:14px;line-height:20px;color:#4A3438">{_e(lever.hint)}</span>'
        if lever.hint
        else ""
    )
    return (
        f'<tr><td style="{line}padding:12px 12px 12px 0;{_F}font-size:17px;line-height:23px;'
        f'color:{_INK}"><b>{_e(lever.label)}</b>{hint}</td>'
        f'<td align="right" style="{line}padding:12px 0;{_F}font-size:26px;line-height:30px;'
        f'font-weight:800;color:{_BURGUNDY};white-space:nowrap">+{fmt_num(lever.gain)}</td></tr>'
    )


def _html_levers(s: ReportSnapshot) -> str:
    rows = "".join(_html_lever(lever, i == 0) for i, lever in enumerate(s.levers))
    return _sec(
        _k("Co otworzy Ci więcej projektów", _BURGUNDY)
        + _h5("Jedna zmiana warunków i tyle zyskujesz")
        + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        + rows
        + "</table>",
        bg=_PEACH,
        border=False,
    )


def _big(text: str, color: str, small: str = "", size: int = 44) -> str:
    tail = (
        f'<span style="font-size:20px;line-height:24px;font-weight:800">&nbsp;{small}</span>'
        if small
        else ""
    )
    return (
        f'<p style="margin:0 0 10px;{_F}font-size:{size}px;line-height:{size + 4}px;'
        f'font-weight:800;color:{color};word-break:break-word">{text}{tail}</p>'
    )


def _html_strongest(t: TechPremium) -> str:
    small = f"{_signed(t.premium)} zł/h" if t.premium > 0 else ""
    since = _p(_e(f"Według CV używasz jej {_since(t.months)}.")) if t.months else ""
    return _k("Najmocniejsza technologia") + _big(_e(t.name), _RED, small) + since


def _html_missing(t: MissingTech) -> str:
    premium = (
        f'<b style="color:{_INK}">{_signed(t.premium)} zł/h</b> · '
        if t.premium and t.premium > 0
        else ""
    )
    return (
        _k("Czego brakuje w CV")
        + _big(_e(t.name), _INK, size=34)
        + _p(premium + _e(_missing_text(t)), _INK, margin="0 0 8px")
        + _p("Jeśli znasz tę technologię, dopisz ją do CV. Raport policzymy od nowa.")
    )


def _html_tech(s: ReportSnapshot) -> str:
    parts = [
        p
        for p in (
            _html_strongest(s.strongest_tech) if s.strongest_tech else None,
            _html_missing(s.missing_tech) if s.missing_tech else None,
        )
        if p
    ]
    if len(parts) == 1:
        return _sec(parts[0])
    box = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'bgcolor="{_WHITE}" style="background:{_WHITE};border:1px solid {_RULE};border-radius:14px">'
        '<tr><td style="padding:20px">{}</td></tr></table>'
    )
    return (
        '<tr><td style="padding:0 0 18px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td class="col" width="50%" valign="top" style="padding:0 9px 0 0">{box.format(parts[0])}</td>'
        f'<td class="col" width="50%" valign="top" style="padding:0 0 0 9px">{box.format(parts[1])}</td>'
        "</tr></table></td></tr>"
    )


def _job_meta(job: ReportJob) -> str:
    return " · ".join(x for x in (", ".join(job.skills), job.place or "") if x)


def _html_job(job: ReportJob) -> str:
    budget = (
        f'<td align="right" valign="top" style="{_F}font-size:19px;line-height:24px;font-weight:800;'
        f'color:{_PEACH};white-space:nowrap;padding-left:14px">do {fmt_num(job.budget_max)} zł/h</td>'
        if job.budget_max
        else "<td></td>"
    )
    meta = _job_meta(job)
    meta_html = (
        f'<p style="margin:6px 0 0;{_F}font-size:14px;line-height:20px;color:#D8CBCC">{_e(meta)}</p>'
        if meta
        else ""
    )
    if job.meets:
        flag = (
            f'<span style="display:inline-block;{_F}font-size:12px;line-height:16px;font-weight:bold;'
            f'background:{_PEACH};color:{_INK};padding:3px 9px;border-radius:999px">'
            "spełnia Twoje warunki</span>"
        )
    else:
        reason = job.miss_reason or "nie spełnia wszystkich warunków"
        flag = (
            f'<span style="display:inline-block;{_F}font-size:12px;line-height:16px;font-weight:bold;'
            f'border:1px solid #8A6F73;color:#F0DCDC;padding:2px 8px;border-radius:999px">'
            f"{_e(reason)}</span>"
        )
    return (
        '<tr><td style="padding:0 0 10px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'bgcolor="{_INK2}" style="background:{_INK2};border-radius:12px"><tr><td style="padding:14px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td valign="top" style="{_F}font-size:17px;line-height:23px;font-weight:bold;color:{_WHITE}">'
        f"{_e(job.title)}</td>{budget}</tr></table>"
        f'{meta_html}<p style="margin:8px 0 0">{flag}</p></td></tr></table></td></tr>'
    )


def _html_jobs(s: ReportSnapshot) -> str:
    rows = "".join(_html_job(j) for j in s.jobs)
    return _sec(
        _k("Projekty dla Ciebie", _PEACH)
        + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        + rows
        + "</table>",
        bg=_INK,
        border=False,
    )


def _initials(name: str) -> str:
    return "".join(w[0] for w in name.split()[:2]).upper() or "B2B"


def _html_owner(s: ReportSnapshot) -> str:
    name = s.owner.name
    avatar = (
        f'<td width="64" valign="middle" style="padding-right:14px">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td width="64" height="64" align="center" valign="middle" bgcolor="{_PEACH}" '
        f'style="width:64px;height:64px;background:{_PEACH};border-radius:32px;{_F}'
        f'font-size:20px;font-weight:800;color:{_BURGUNDY}">{_e(_initials(name))}</td>'
        "</tr></table></td>"
    )
    return _sec(
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'{avatar}<td valign="middle">'
        + _h5(f"{name}, Twój opiekun", margin="0 0 6px")
        + _p(_e(_owner_text(s)))
        + "</td></tr></table>"
    )


def _html_limited(s: ReportSnapshot) -> str:
    who = (
        f"{_e(s.owner.name)}, Twój opiekun, zadzwoni i porozmawia o projektach."
        if s.owner
        else "Rekruter zadzwoni i porozmawia o projektach."
    )
    return _sec(_k("Stawka") + _p(_e(LIMITED_TEXT) + " " + who, _INK))


def _link(url: str, label: str, color: str = _RED_TEXT) -> str:
    return (
        f'<a href="{_e(url, quote=True)}" style="color:{color};font-weight:bold;'
        f'text-decoration:underline">{_e(label)}</a>'
    )


def _notes(s: ReportSnapshot) -> list[str]:
    out = []
    if _shows_rate(s):
        out.append(RATE_NOTE)
    if s.strongest_tech or (s.missing_tech and s.missing_tech.premium):
        out.append(PREMIUM_NOTE)
    return out


def _html(s: ReportSnapshot, first_name: Optional[str], links: ReportLinks) -> str:
    # Chipy jako spany w linii: zawijają się na telefonie, Outlook rysuje samo tło.
    chips = " ".join(
        f'<span style="display:inline-block;{_F}font-size:14px;line-height:20px;font-weight:600;'
        f"color:{_WHITE};background:#A8333D;padding:4px 10px;border-radius:999px;"
        f'margin:0 2px 6px 0;white-space:nowrap">{_e(c)}</span>'
        for c in _chips(s)
    )
    header = (
        f'<tr><td bgcolor="{_BURGUNDY}" style="background:{_BURGUNDY};padding:28px 32px 26px">'
        f'<p style="margin:0 0 14px;{_F}font-size:18px;line-height:22px;font-weight:800;'
        f'color:{_WHITE}">B2B<span style="color:{_PEACH}">.</span>Network</p>'
        f'<p style="margin:0 0 14px;{_F}font-size:38px;line-height:40px;font-weight:800;'
        f'color:{_WHITE}">Twój raport kompetencji</p>'
        f'<div style="margin:0 0 8px;line-height:34px">{chips}</div>'
        f'<p style="margin:0;{_F}font-size:17px;line-height:25px;color:#F3D3D6">'
        f"{_e(_greeting(first_name))} Tak odczytaliśmy Twoje CV i warunki. Coś się nie zgadza? "
        f"{_link(links.edit_conditions_url, 'Popraw jednym kliknięciem', _PEACH)}.</p></td></tr>"
    )
    body = []
    if _shows_rate(s):
        body.append(_html_rate(s))
    elif s.variant == "limited":
        body.append(_html_limited(s))
    if s.funnel:
        body.append(_html_funnel(s))
    if s.variant == "full" and s.levers:
        body.append(_html_levers(s))
    if s.strongest_tech or s.missing_tech:
        body.append(_html_tech(s))
    if s.jobs:
        body.append(_html_jobs(s))
    if s.owner:
        body.append(_html_owner(s))
    note = " ".join(_notes(s) + [COMPANY_LINE + "."])
    footer = (
        f'<tr><td style="padding:18px 32px 26px;border-top:1px solid {_RULE}">'
        f'<p style="margin:0 0 8px;{_F}font-size:14px;line-height:20px">'
        f"{_link(links.edit_conditions_url, 'Popraw warunki')}&nbsp;&nbsp;·&nbsp;&nbsp;"
        f"{_link(links.unsubscribe_url, 'Nie chcę raportów')}</p>"
        f'<p style="margin:0;{_F}font-size:13px;line-height:19px;color:{_INK_SOFT}">{_e(note)}</p>'
        "</td></tr>"
    )
    preheader = (
        _rate_title(s)
        if _shows_rate(s)
        else _funnel_text(s)
        if s.funnel
        else "Tak odczytaliśmy Twoje CV i warunki."
    )
    return (
        '<!DOCTYPE html><html lang="pl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">'
        f"<title>{_e(_subject(s))}</title>"
        "<style>@media (max-width:620px){.col{display:block!important;width:100%!important;"
        "padding:0 0 18px!important}.pad{padding:16px!important}}</style></head>"
        f'<body style="margin:0;padding:0;background:#ECE3E0">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{_e(preheader)}</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'bgcolor="#ECE3E0" style="background:#ECE3E0"><tr><td align="center" style="padding:24px 8px">'
        '<table role="presentation" width="640" cellpadding="0" cellspacing="0" border="0" '
        f'bgcolor="{_SNOW}" style="width:100%;max-width:640px;background:{_SNOW};border-radius:14px">'
        + header
        + '<tr><td class="pad" style="padding:28px 28px 10px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        + "".join(body)
        + "</table></td></tr>"
        + footer
        + "</table></td></tr></table></body></html>"
    )


# ── Tekst ───────────────────────────────────────────────────────────────────


def _text(s: ReportSnapshot, first_name: Optional[str], links: ReportLinks) -> str:
    lines = [
        _greeting(first_name),
        "",
        "Twój raport kompetencji",
        " · ".join(_chips(s)),
        f"Tak odczytaliśmy Twoje CV i warunki. Coś się nie zgadza? Popraw: {links.edit_conditions_url}",
        "",
    ]
    if _shows_rate(s):
        lines += ["STAWKA", _rate_title(s), *_rate_text(s), ""]
    elif s.variant == "limited":
        who = f"{s.owner.name}, Twój opiekun," if s.owner else "Rekruter"
        lines += [
            "STAWKA",
            f"{LIMITED_TEXT} {who} zadzwoni i porozmawia o projektach.",
            "",
        ]
    if s.funnel:
        lines.append("PROJEKTY NA TWOICH WARUNKACH")
        lines += [f"- {step.label}: {fmt_num(step.count)}" for step in s.funnel]
        lines += [_funnel_text(s), ""]
    if s.variant == "full" and s.levers:
        lines.append("CO OTWORZY CI WIĘCEJ PROJEKTÓW")
        for lever in s.levers:
            hint = f" ({lever.hint})" if lever.hint else ""
            lines.append(f"- {lever.label}: +{fmt_num(lever.gain)}{hint}")
        lines.append("")
    if s.strongest_tech:
        t = s.strongest_tech
        premium = f" {_signed(t.premium)} zł/h" if t.premium > 0 else ""
        since = f" Według CV używasz jej {_since(t.months)}." if t.months else ""
        lines += [f"NAJMOCNIEJSZA TECHNOLOGIA: {t.name}{premium}.{since}", ""]
    if s.missing_tech:
        t = s.missing_tech
        premium = f" {_signed(t.premium)} zł/h." if t.premium and t.premium > 0 else ""
        lines += [
            f"CZEGO BRAKUJE W CV: {t.name}.{premium} {_missing_text(t)}",
            "Jeśli znasz tę technologię, dopisz ją do CV. Raport policzymy od nowa.",
            "",
        ]
    if s.jobs:
        lines.append("PROJEKTY DLA CIEBIE")
        for job in s.jobs:
            budget = f", do {fmt_num(job.budget_max)} zł/h" if job.budget_max else ""
            meta = _job_meta(job)
            flag = (
                "spełnia Twoje warunki"
                if job.meets
                else (job.miss_reason or "nie spełnia wszystkich warunków")
            )
            lines.append(
                f"- {job.title}{budget}{' · ' + meta if meta else ''} · {flag}"
            )
        lines.append("")
    if s.owner:
        lines += [f"{s.owner.name}, Twój opiekun. {_owner_text(s)}", ""]
    lines += [
        f"Popraw warunki: {links.edit_conditions_url}",
        f"Nie chcę raportów: {links.unsubscribe_url}",
        *_notes(s),
        COMPANY_LINE,
    ]
    return "\n".join(lines) + "\n"


def _subject(s: ReportSnapshot) -> str:
    p = s.profile
    years = f", {_years(p.years)}" if p.years else ""
    return f"Twój raport kompetencji: {p.role_label}{years}"


def render_report_email(
    snapshot: ReportSnapshot, *, first_name: Optional[str], links: ReportLinks
) -> RenderedMail:
    """Temat, HTML i tekst raportu. Czysta funkcja: bez bazy i bez wysyłki."""
    return RenderedMail(
        subject=_subject(snapshot),
        html=_html(snapshot, first_name, links),
        text=_text(snapshot, first_name, links),
        list_unsubscribe=links.one_click_unsubscribe_url,
    )
