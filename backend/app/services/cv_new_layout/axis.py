"""„Przebieg kariery” — oś w jednym pasie z flagami (wersja Q1, Artur 21–22.11.2026).

- Tylko główna ścieżka: stanowisko w całości w innym = projekt równoległy (opis od
  str. 2); zmiana pracy z zakładką = poprzednie kończy się w dniu startu nowego.
- Przerwa < 6 mies. domknięta, dłuższa = przerywana linia. Kolejne stanowiska
  w tej samej firmie = jeden odcinek. Ostatnie 12 lat; starsze (więcej niż 2)
  jako jasny odcinek z „//”, latami i liczbą stanowisk (1–2 starsze = oś od
  początku). Bez bieżącej pracy oś kończy się na ostatniej.
- Każda firma podpisana pełną nazwą (nigdy „…”), w 1–3 liniach, flagi nad
  i pod paskiem bez kolizji, układane od prawej. Szerokość napisu z metryk
  pliku Poppins 700.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Optional

from app.services.cv_new_layout.assets import text_width
from app.services.cv_new_layout.context import Ctx, DatedRole
from app.services.cv_new_layout.labels import counted
from app.services.cv_new_layout.styles import BRAND, INK, PAST, RULE, SOFT
from app.services.cv_new_layout.text import esc

MIN_MONTHS = 9
YEARS = 12
W = 180.0
FS = 3.0
LH = FS * 1.12
ASC, DESC = 0.74 * FS, 0.22 * FS
BAR = 3.8
OLDER_LEFT = 40.0  # miejsce na „Wcześniej” przed początkiem osi
# Starsze lata (Artur 23.11.2026, wariant A1): jasny odcinek tego samego paska.
OLDER_FILL = "#ECE7E1"

_SUFFIX = re.compile(
    r"\s*(\(.*?\)|\bsp\.?\s*z\s*o\.?\s*o\.?|\bs\.?\s*k\.?\s*a\.?|\bs\.?\s*a\.?(?=\s|$)|\bsp\.?\s*j\.?|\bpoland\b|\bpolska\b)\.?",
    re.I,
)


def company_name(company: str) -> str:
    """Nazwa firmy bez formy prawnej i „Polska”; wersaliki dłuższe niż 6 znaków → Tytułowo."""
    s = _SUFFIX.sub("", company or "").strip(" ,.-")
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
class Segment:
    role: DatedRole
    a: float
    b: float
    key: str
    current: bool


@dataclass(frozen=True)
class Timeline:
    y0: int
    older: tuple[DatedRole, ...]
    segments: tuple[Segment, ...]
    gaps: tuple[tuple[float, float], ...]
    nostart: tuple[DatedRole, ...]


def timeline(ctx: Ctx) -> Timeline:
    now = ctx.now
    dated = [r for r in ctx.roles if r.start is not None and r.end is not None]
    main, _ = main_career(dated)
    first = int(min(r.start for r in main)) if main else int(now) - 5
    y0 = max(first, int(now) - YEARS + 1)
    older = [r for r in main if r.end <= y0 + 0.01]
    if 0 < len(older) <= 2:
        y0, older = first, []
    inwin = [r for r in main if r.end > y0 + 0.01]
    raw: list[tuple[DatedRole, float, float]] = []
    for i, r in enumerate(inwin):
        nxt = inwin[i + 1] if i + 1 < len(inwin) else None
        end = r.end
        if nxt and nxt.start > end and nxt.start - end < 0.5:
            end = nxt.start
        raw.append((r, max(r.start, y0), end))
    # bieżąca działalność odfiltrowana jako równoległa (np. freelance) wraca na koniec pasa
    if raw and raw[-1][2] < now - 1 / 12:
        on_axis = {s[0].index for s in raw}
        current = [r for r in dated if ctx.is_current(r) and r.index not in on_axis]
        if current:
            raw.append((current[0], max(raw[-1][2], y0), now))
    segs: list[Segment] = []
    for r, a, b in raw:
        key = company_name(r.role.company).lower()
        if segs and segs[-1].key == key and a - segs[-1].b < 0.5:
            segs[-1].b = b
            segs[-1].current = segs[-1].current or ctx.is_current(r)
        else:
            segs.append(Segment(r, a, b, key, ctx.is_current(r)))
    gaps = tuple((p.b, n.a) for p, n in zip(segs, segs[1:]) if n.a - p.b >= 0.5)
    nostart = tuple(
        r
        for r in ctx.roles
        if r.start is None and r.end is not None and ctx.is_current(r)
    )
    return Timeline(y0, tuple(older), tuple(segs), gaps, nostart)


def _tw(text: str) -> float:
    return text_width(text, FS) + 0.3


def _tokens(name: str) -> list[str]:
    out: list[str] = []
    for t in name.split():
        if out and t in ("-", "–", "/", "|", "&"):
            out[-1] += " " + t
        else:
            out.append(t)
    return out


def wraps(name: str) -> list[list[str]]:
    """Pełna nazwa w 1, 2 albo 3 liniach (bez ucinania); linie możliwie równe."""
    tk = _tokens(name)
    res = [[name]]
    for n in (2, 3):
        if len(tk) < n:
            break
        best: Optional[tuple[float, list[str]]] = None

        def rec(i: int, left: int, acc: list[str]) -> None:
            nonlocal best
            if left == 1:
                lines = acc + [" ".join(tk[i:])]
                m = max(_tw(x) for x in lines)
                if best is None or m < best[0]:
                    best = (m, lines)
                return
            for j in range(i + 1, len(tk) - left + 2):
                rec(j, left - 1, acc + [" ".join(tk[i:j])])

        rec(0, n, [])
        if best:
            res.append(best[1])
    return res


def _text(
    x: float,
    y: float,
    body: str,
    *,
    anchor: str = "start",
    size: float = FS,
    weight: int = 700,
    family: str = "Poppins",
    fill: str = INK,
) -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" font-family="{family}" '
        f'font-weight="{weight}" font-size="{size}" fill="{fill}">{esc(body)}</text>'
    )


Rect = tuple[float, float, float, float]
Pole = tuple[float, float, float]


def career_axis(ctx: Ctx) -> str:
    tl = timeline(ctx)
    segs = tl.segments
    if not segs and not tl.nostart:
        return ""
    left = OLDER_LEFT if tl.older else 3.0
    has_cur = any(s.current for s in segs) or bool(tl.nostart)
    end_v = ctx.now if has_cur else (segs[-1].b if segs else ctx.now)
    span = max(end_v - tl.y0, 1e-6)

    def x(v: float) -> float:
        return left + (min(max(v, tl.y0), end_v) - tl.y0) / span * (W - left - 3)

    ay = 0.0
    top_bar, bot_bar = ay - BAR / 2, ay + BAR / 2
    pad = 1.2
    p = [
        f'<line x1="{left - 1:.2f}" y1="{ay:.2f}" x2="{W - 1:.2f}" y2="{ay:.2f}" stroke="{RULE}" stroke-width=".35"/>'
    ]
    for s in segs:
        p.append(
            f'<rect x="{x(s.a):.2f}" y="{top_bar:.2f}" width="{max(x(s.b) - x(s.a), 0.6):.2f}" height="{BAR}" '
            f'fill="{BRAND if s.current else PAST}" stroke="#fff" stroke-width=".5"/>'
        )
    for a, b in tl.gaps:
        p.append(
            f'<line x1="{x(a) + 0.5:.2f}" y1="{ay:.2f}" x2="{x(b) - 0.5:.2f}" y2="{ay:.2f}" stroke="{SOFT}" '
            f'stroke-width=".4" stroke-dasharray="1 .7"/>'
        )
    rects: list[Rect] = []
    poles: list[Pole] = []

    def ok(r: Rect, pole: Pole, relax: bool) -> bool:
        px, py0, py1 = pole
        for a in rects:
            if (
                r[1] + pad > a[0]
                and r[0] - pad < a[1]
                and r[3] + 0.5 > a[2]
                and r[2] - 0.5 < a[3]
            ):
                return False
            if not relax and a[0] - 0.6 < px < a[1] + 0.6 and py1 > a[2] and py0 < a[3]:
                return False
        if not relax:
            for qx, qy0, qy1 in poles:
                if r[0] - 0.6 < qx < r[1] + 0.6 and qy1 > r[2] and qy0 < r[3]:
                    return False
        return True

    labs = [(x(s.a), company_name(s.role.role.company), s.current) for s in segs]
    labs += [(x(end_v) - 1.4, company_name(r.role.company), True) for r in tl.nostart]
    if tl.nostart:
        p.append(
            f'<circle cx="{x(end_v) - 1.4:.2f}" cy="{ay:.2f}" r="{BAR / 2 + 0.5:.2f}" fill="{BRAND}" '
            f'stroke="#fff" stroke-width=".45"/>'
        )
    placed = []
    for xa, name, cur in sorted(labs, key=lambda t: -t[0]):
        if not name:
            continue
        best = None
        for relax, sides_now in (
            (False, ("up", "dn")),
            (False, ("dn",)),
            (True, ("up", "dn")),
        ):
            if best:
                break
            for side in sides_now:
                for nl, lines in enumerate(wraps(name)):
                    w = max(_tw(t) for t in lines) + 1.4
                    for anchor in ("start", "end"):
                        if anchor == "start" and xa + w > W:
                            continue
                        if anchor == "end" and (xa + w <= W or xa - w < left - 1):
                            continue
                        lo, hi = (
                            (xa - 0.3, xa + w)
                            if anchor == "start"
                            else (xa - w, xa + 0.3)
                        )
                        covers = anchor == "end" and any(
                            lo - 1 < ox < xa - 0.5 for ox, _, _ in labs
                        )
                        # napis w lewo nad drzewcem firmy po lewej: tak wysoko, żeby jej flaga zmieściła się pod nim
                        min_off = 1.5 + ASC + DESC + LH + 1.4 if covers else 0
                        h = (len(lines) - 1) * LH + ASC + DESC
                        for slot in range(60):
                            off = 1.5 + slot * LH / 2
                            if off < min_off:
                                continue
                            if side == "up":
                                r = (lo, hi, top_bar - off - h, top_bar - off)
                                pole = (xa, r[2] - 0.6, top_bar)
                            else:
                                r = (lo, hi, bot_bar + off, bot_bar + off + h)
                                pole = (xa, bot_bar, r[3])
                            if ok(r, pole, relax):
                                cost = (
                                    off
                                    + (0, 2.2, 7.0)[nl]
                                    + (5 if anchor == "end" else 0)
                                    + (6 if covers else 0)
                                    + (0.8 if side == "dn" else 0)
                                )
                                if best is None or cost < best[0]:
                                    best = (cost, side, lines, anchor, r, pole)
                                break
        if best is None:
            continue
        _, side, lines, anchor, r, pole = best
        rects.append(r)
        poles.append(pole)
        placed.append((xa, side, lines, anchor, r, pole, cur))
    for xa, side, lines, anchor, r, pole, cur in placed:
        color = BRAND if cur else INK
        dot_y = pole[1] if side == "up" else r[3]
        p.append(
            f'<line x1="{xa:.2f}" y1="{pole[1]:.2f}" x2="{xa:.2f}" y2="{pole[2]:.2f}" stroke="{color}" '
            f'stroke-width="{0.45 if cur else 0.35}"/>'
            f'<circle cx="{xa:.2f}" cy="{dot_y:.2f}" r=".6" fill="{color}"/>'
        )
        tx = xa + 1.4 if anchor == "start" else xa - 1.1
        for k, t in enumerate(lines):
            p.append(_text(tx, r[2] + ASC + k * LH, t, anchor=anchor))
    lo_y = min([r[2] for r in rects] + [top_bar]) - 1.0
    hi_dn = max([r[3] for r in rects if r[2] > ay] + [bot_bar])
    yy = (bot_bar + 3.4) if hi_dn <= bot_bar else hi_dn + 4.6
    marks = [s.a for s in segs] + ([segs[-1].b] if segs and not has_cur else [])
    lastx, lasty = -99.0, None
    for v in marks:
        xx, yv = x(v), int(v + 0.001)
        if xx - lastx < 8 or yv == lasty:
            continue
        lastx, lasty = xx, yv
        anchor = "end" if xx > W - 6 else "middle"
        p.append(
            f'<line x1="{xx:.2f}" y1="{bot_bar:.2f}" x2="{xx:.2f}" y2="{bot_bar + 1.0:.2f}" stroke="{INK}" stroke-width=".3"/>'
            + _text(
                xx + (0.6 if anchor == "end" else 0),
                yy,
                str(yv),
                anchor=anchor,
                size=2.6,
            )
        )
    if has_cur and x(end_v) - lastx > 11:
        p.append(_text(W - 0.4, yy, ctx.t["today"], anchor="end", size=2.6))
    older_svg, (oy0, oy1) = (
        _older_on_bar(ctx, tl.older, ay, left, yy) if tl.older else ("", (ay, ay))
    )
    p.append(older_svg)
    lo_y = min(lo_y, oy0 - 1)
    hi_y = max(yy + 1.0, oy1 + 1)
    h = hi_y - lo_y
    return (
        f'<svg class="axis" viewBox="0 {lo_y:.2f} {W} {h:.2f}" width="{W}mm" height="{h:.2f}mm" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(p)}</svg>'
    )


def _older_summary(
    ctx: Ctx, older: tuple[DatedRole, ...]
) -> tuple[int, int, list[str]]:
    a, b = int(min(r.start for r in older)), int(max(r.end for r in older))
    names: list[str] = []
    for r in sorted(older, key=lambda r: -r.months):
        n = company_name(r.role.company)
        if n and n not in names:
            names.append(n)
    return a, b, names


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


def _older_on_bar(
    ctx: Ctx, older: tuple[DatedRole, ...], ay: float, left: float, yy: float
) -> tuple[str, tuple[float, float]]:
    """Wcześniejsze lata jako jasny odcinek tego samego paska, przerwa „//” przed
    oknem; nad paskiem lata, pod nim zwykłym pismem liczba stanowisk i 2 najdłuższe firmy."""
    a, b, names = _older_summary(ctx, older)
    x0, x1 = 3.0, left - 4.0
    top_bar = ay - BAR / 2
    out = [
        f'<rect x="{x0:.2f}" y="{top_bar:.2f}" width="{x1 - x0:.2f}" height="{BAR}" fill="{OLDER_FILL}"/>'
    ]
    # przerwa w skali: dwie ukośne kreski między starszymi latami a oknem
    for dx in (0.0, 1.0):
        bx = x1 + 1.4 + dx
        out.append(
            f'<line x1="{bx - 0.7:.2f}" y1="{ay + BAR / 2 + 0.6:.2f}" x2="{bx + 0.7:.2f}" '
            f'y2="{ay - BAR / 2 - 0.6:.2f}" stroke="{SOFT}" stroke-width=".35"/>'
        )
    head = f"{a}–{b}"
    out.append(_text(x0, top_bar - 1.6, head))
    width = x1 - x0
    lead = counted(ctx.lang, "position", len(older))
    body = f"{lead}, {ctx.t['including']} {', '.join(names[:2])}" if names else lead
    lines = _wrap(body, width, 2.75, "SourceSans3-600.ttf")[:3]
    ty = ay + BAR / 2 + 3.2
    for k, ln in enumerate(lines):
        out.append(
            _text(
                x0,
                ty + k * 3.2,
                ln,
                size=2.75,
                weight=600,
                family="Source Sans 3",
                fill=INK,
            )
        )
    bottom = ty + (len(lines) - 1) * 3.2 + DESC
    return "".join(out), (top_bar - 1.6 - ASC, max(bottom, yy))
