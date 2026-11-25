"""„Przebieg kariery” — pasek po kolei (wariant S1, Artur 25.11.2026).

- Odcinki NIE w skali czasu: każdy pracodawca ma tyle miejsca, żeby pełna nazwa
  firmy zmieściła się w 1–2 liniach (przy ciasnocie 3), resztę szerokości dzielą
  prace łagodnie według stażu (pierwiastek) — roczna praca nie jest kreską obok
  dziewięcioletniej. Daty tylko przy rozpoczęciu (rok), bez przerw.
- Nad odcinkiem nazwa firmy, pod nim rok rozpoczęcia i stanowisko; bieżąca praca
  czerwona, na końcu „dziś” (bez bieżącej pracy — rok ostatniej).
- Tylko główna ścieżka (stanowisko w całości w innym = projekt równoległy, opis od
  str. 2); zmiana pracy z zakładką = poprzednie kończy się w dniu startu nowego.
  Kolejne stanowiska w tej samej firmie = jeden odcinek; kolejne krótkie zlecenia
  (< 9 mies.) = jeden odcinek „A · B · C”, pod nim „3 krótkie projekty”.
- Gdy pracodawców jest za dużo na szerokość strony, najstarsi idą do jednego
  jasnego odcinka „Wcześniej · N stanowisk”, pod nim „m.in.” dwie najdłuższe firmy.
- Nazwy firm zawsze w całości (nigdy „…”); szerokość napisu z metryk krojów.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace


from app.services.cv_new_layout.assets import text_width
from app.services.cv_new_layout.context import Ctx, DatedRole
from app.services.cv_new_layout.labels import counted
from app.services.cv_new_layout.styles import BRAND, BRAND_TEXT, INK, PAST, SOFT
from app.services.cv_new_layout.text import esc

MIN_MONTHS = 9
SHORT_MONTHS = 9  # krótsze kolejne zlecenia idą jednym odcinkiem
W = 180.0
BAR = 3.6
NAME_FS, ROLE_FS, DATE_FS = 2.85, 2.45, 2.5  # mm: firma, stanowisko, rok
NAME_LH, ROLE_LH = 3.2, 2.85
NAME_FONT, ROLE_FONT = "Poppins-700.ttf", "SourceSans3-600.ttf"
MIN_SEGMENT = 14.0
MAX_STOPS = 7
# Starsze lata: jasny odcinek tego samego paska.
OLDER_FILL = "#E6E0D8"

_SUFFIX = re.compile(
    r"\s*(\(.*?\)|\bsp\.?\s*z\s*o\.?\s*o\.?|\bs\.?\s*k\.?\s*a\.?|\bs\.?\s*a\.?(?=\s|$)|\bsp\.?\s*j\.?|\bpoland\b|\bpolska\b)\.?",
    re.I,
)


def company_name(company: str) -> str:
    """Nazwa firmy bez branży dopisanej w edytorze („Firma · Bankowość”), formy prawnej
    i „Polska”; wersaliki dłuższe niż 6 znaków → Tytułowo."""
    s = _SUFFIX.sub("", (company or "").split(" · ")[0]).strip(" ,.-")
    if s.isupper() and len(s) > 6:
        s = s.title()
    return s


def main_career(roles: list[DatedRole]) -> tuple[list[DatedRole], list[DatedRole]]:
    """(główna ścieżka, równoległe). Rola obejmująca ≥ 2 dłuższe stanowiska
    (freelance przez całą karierę) jest równoległa."""
    main: list[DatedRole] = []
    parallel = [
        r
        for r in roles
        if sum(
            1
            for o in roles
            if o is not r
            and o.months >= MIN_MONTHS
            and o.start >= r.start - 1e-6
            and o.end <= r.end + 2.05 / 12
        )
        >= 2
    ]
    rest = [r for r in roles if r not in parallel]
    for r in sorted(rest, key=lambda r: (r.start, -r.end)):
        if main and r.start < main[-1].end - 1e-6:
            m = main[-1]
            if r.end <= m.end + 2.05 / 12:
                parallel.append(r)
                continue
            if r.start <= m.start + 1e-6:
                parallel.append(m)
                main[-1] = r
                continue
            main[-1] = replace(m, end=r.start)
        main.append(r)
    return main, parallel


@dataclass
class Stop:
    """Odcinek paska: jeden pracodawca (kolejne stanowiska razem), grupa krótkich
    zleceń albo zwinięte „Wcześniej”."""

    company: str
    role: str
    start: float
    end: float
    current: bool
    months_known: bool = True
    count: int = 1  # ile stanowisk
    kind: str = "job"  # job | short | older
    names: list[str] = field(default_factory=list)

    @property
    def months(self) -> int:
        return max(int((self.end - self.start) * 12 + 0.25), 1)


def _merge(ctx: Ctx, roles: list[DatedRole]) -> list[Stop]:
    out: list[Stop] = []
    for r in sorted(roles, key=lambda r: r.start):
        name = company_name(r.role.company)
        if (
            out
            and name
            and out[-1].company.lower() == name.lower()
            and r.start - out[-1].end < 0.5
        ):
            last = out[-1]
            last.role = r.role.position or last.role
            last.end = max(last.end, r.end)
            last.current = last.current or ctx.is_current(r)
            last.count += 1
            continue
        out.append(
            Stop(
                name,
                r.role.position,
                r.start,
                r.end,
                ctx.is_current(r),
                r.months_known,
                names=[name] if name else [],
            )
        )
    return out


def stops(ctx: Ctx) -> list[Stop]:
    """Odcinki od najstarszego; krótkie kolejne zlecenia zgrupowane."""
    dated = [r for r in ctx.roles if r.start is not None and r.end is not None]
    main, _ = main_career(dated)
    merged = _merge(ctx, main)
    if not any(s.current for s in merged):
        # bieżąca działalność odfiltrowana jako równoległa (np. freelance) wraca na
        # koniec; tak samo, gdy główna ścieżka jest pusta (same równoległe kontrakty)
        cur = [r for r in dated if ctx.is_current(r)]
        if cur:
            r = cur[0]
            merged.append(
                Stop(
                    company_name(r.role.company),
                    r.role.position,
                    max(r.start, merged[-1].end) if merged else r.start,
                    r.end,
                    True,
                    r.months_known,
                )
            )
    if not any(s.current for s in merged):
        # bieżąca rola bez daty początku („obecnie”) — na koniec paska, nie znika
        nostart = [
            r
            for r in ctx.roles
            if r.start is None and r.end is not None and ctx.is_current(r)
        ]
        if nostart:
            r = nostart[0]
            start = merged[-1].end if merged else r.end - 1 / 12
            merged.append(
                Stop(
                    company_name(r.role.company),
                    r.role.position,
                    start,
                    r.end,
                    True,
                    False,
                    kind="nostart",
                )
            )
    grouped: list[Stop] = []
    for s in merged:
        short = s.months < SHORT_MONTHS and not s.current
        prev = grouped[-1] if grouped else None
        if short and prev is not None and prev.kind == "short":
            prev.names.append(s.company)
            prev.company = " · ".join(n for n in prev.names if n)
            prev.end = max(prev.end, s.end)
            prev.count += s.count
            prev.role = counted(ctx.lang, "short_project", len(prev.names))
            continue
        if short:
            s.kind = "short"
        grouped.append(s)
    # pojedyncze krótkie zlecenie zostaje zwykłym odcinkiem ze stanowiskiem
    for s in grouped:
        if s.kind == "short" and len(s.names) < 2:
            s.kind = "job"
    for s in grouped:
        if not s.company:
            # pusta firma to nie „własna działalność” (#42900, pętla jakości 25.11.2026):
            # odcinek podpisuje stanowisko, pod paskiem zostaje sam rok
            s.company, s.role = s.role or "—", ""
    return grouped


def collapse(ctx: Ctx, st: list[Stop], keep: int) -> list[Stop]:
    """Najwyżej `keep` odcinków: najstarsi jednym odcinkiem „Wcześniej”."""
    if len(st) <= keep:
        return st
    rest, shown = st[: len(st) - keep + 1], st[len(st) - keep + 1 :]
    count = sum(s.count for s in rest)
    longest = [
        s.company for s in sorted(rest, key=lambda s: -s.months) if s.kind != "short"
    ][:2]
    older = Stop(
        f"{ctx.t['earlier']} · {counted(ctx.lang, 'position', count)}",
        f"{ctx.t['including']} {', '.join(longest)}" if longest else "",
        rest[0].start,
        rest[-1].end,
        False,
        count=count,
        kind="older",
    )
    return [older, *shown]


def _need(s: Stop, lines: int) -> float:
    """Najmniejsza szerokość: nazwa w najwyżej `lines` liniach, najdłuższe słowo stanowiska w linii."""
    role_word = max(
        (text_width(w, ROLE_FS, ROLE_FONT) for w in s.role.split()), default=0.0
    )
    name_word = max(
        (text_width(w, NAME_FS, NAME_FONT) for w in s.company.split()), default=0.0
    )
    w = max(MIN_SEGMENT, role_word + 1.0, name_word + 0.6)
    while w < 90 and len(_wrap(s.company, w, NAME_FS, NAME_FONT)) > lines:
        w += 0.5
    return w + 2.4


def _needs(st: list[Stop]) -> list[float]:
    for lines in (2, 3):
        need = [_need(s, lines) for s in st]
        if sum(need) <= W:
            return need
    return need


def layout(ctx: Ctx) -> list[tuple[Stop, float, float]]:
    """(odcinek, x, szerokość) — od 7 pracodawców w dół, aż nazwy się zmieszczą."""
    base = stops(ctx)
    if not base:
        return []
    for keep in range(MAX_STOPS, 3, -1):
        st = collapse(ctx, base, keep)
        need = _needs(st)
        if sum(need) <= W:
            break
    cap = max([s.months for s in st if s.kind != "older"] or [12])
    weights = [max(min(s.months, cap), 1) ** 0.5 for s in st]
    prop = [W * w / sum(weights) for w in weights]
    widths = [max(n, p) for n, p in zip(need, prop)]
    over = sum(widths) - W
    if over > 0:
        flex = [w - n for w, n in zip(widths, need)]
        if sum(flex) >= over:
            widths = [w - over * f / sum(flex) for w, f in zip(widths, flex)]
    k = W / sum(widths)
    out, x = [], 0.0
    for s, w in zip(st, widths):
        out.append((s, x, w * k))
        x += w * k
    return out


def _text(
    x: float,
    y: float,
    body: str,
    *,
    anchor: str = "start",
    size: float = NAME_FS,
    weight: int = 700,
    family: str = "Poppins",
    fill: str = INK,
) -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" font-family="{family}" '
        f'font-weight="{weight}" font-size="{size}" fill="{fill}">{esc(body)}</text>'
    )


def _wrap(text: str, width: float, size: float, font: str) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and text_width(trial, size, font) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + ([cur] if cur else [])


def career_axis(ctx: Ctx) -> str:
    segments = layout(ctx)
    if not segments:
        return ""
    has_cur = any(s.current for s, _, _ in segments)
    parts: list[str] = []
    rows = []
    for s, x, w in segments:
        names = _wrap(s.company, w - 2.0, NAME_FS, NAME_FONT) or [s.company]
        roles = _wrap(s.role, w - 1.6, ROLE_FS, ROLE_FONT) if s.role else []
        rows.append((s, x, w, names, roles))
    name_lines = max(len(n) for *_, n, _ in rows)
    role_lines = max([len(r) for *_, r in rows] + [0])
    for s, x, w, names, roles in rows:
        fill = BRAND if s.current else OLDER_FILL if s.kind == "older" else PAST
        parts.append(
            f'<rect x="{x:.2f}" y="{-BAR / 2:.2f}" width="{w:.2f}" height="{BAR}" fill="{fill}" stroke="#fff" stroke-width=".8"/>'
        )
        color = SOFT if s.kind == "older" else INK
        top = -BAR / 2 - 1.5 - (len(names) - 1) * NAME_LH
        for k, line in enumerate(names):
            parts.append(
                _text(
                    x + 1.0,
                    top + k * NAME_LH,
                    line,
                    size=NAME_FS,
                    weight=700,
                    fill=color,
                )
            )
        parts.append(
            f'<line x1="{x + 0.4:.2f}" y1="{BAR / 2:.2f}" x2="{x + 0.4:.2f}" y2="{BAR / 2 + 1.6:.2f}" stroke="{INK}" stroke-width=".3"/>'
        )
        if s.kind != "nostart":  # bez daty początku nie ma roku do pokazania
            parts.append(
                _text(
                    x + 0.4,
                    BAR / 2 + 4.6,
                    str(int(s.start + 0.001)),
                    size=DATE_FS,
                    weight=700,
                    fill=BRAND_TEXT if s.current else INK,
                )
            )
        for k, line in enumerate(roles):
            parts.append(
                _text(
                    x + 0.4,
                    BAR / 2 + 8.0 + k * ROLE_LH,
                    line,
                    size=ROLE_FS,
                    weight=600,
                    family="Source Sans 3",
                    fill=SOFT,
                )
            )
    last = segments[-1][0]
    end = (
        ctx.t["today"]
        if has_cur
        else str(int(last.end + 0.001 - (1 / 24 if last.months_known else 0)))
    )
    parts.append(
        _text(
            W,
            BAR / 2 + 4.6,
            end,
            anchor="end",
            size=DATE_FS,
            weight=700,
            fill=BRAND_TEXT if has_cur else INK,
        )
    )
    y0 = -BAR / 2 - 1.5 - (name_lines - 1) * NAME_LH - NAME_FS * 0.74 - 1.0
    y1 = BAR / 2 + (8.0 + (role_lines - 1) * ROLE_LH if role_lines else 4.6) + 1.2
    return (
        f'<svg class="axis" viewBox="0 {y0:.2f} {W} {y1 - y0:.2f}" width="{W}mm" height="{y1 - y0:.2f}mm" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(parts)}</svg>'
    )
