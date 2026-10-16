"""„Napisz od nowa” bez utraty ręcznych poprawek (Edytor CV 3, PR 5, 14.10.2026).

Nowa generacja CV zastępuje szkic etapu. Części, które rekruter poprawiał
ręcznie, zostają w jego wersji (makieta „Ekran 4”: „„Logistyka 24”
poprawiałeś ręcznie, więc zostawiłem Twoją wersję”).

Część CV to nagłówek (tytuł, „Rozważany na stanowisko”), sekcja (nagłówek
z ``data-cv-section`` i jej treść) albo stanowisko w doświadczeniu — klucz
stanowiska to firma i daty, bo nowa generacja przeredagowuje nazwę roli.
„Poprawiona ręcznie” = jej tekst w szkicu różni się od tekstu tej samej części
w generacji, z której szkic powstał. Porównujemy sam tekst: pogrubienie
(„Pogrub wymagania”) i wyrównanie to nie poprawka treści. Część usunięta ze
szkicu nie wraca, część dopisana zostaje w swoim miejscu.

Gdy nie da się tego rozpoznać (szkic nie z generatora, brak sekcji, wszystko
inne niż w generacji — np. inny kod składania HTML), bierzemy całą nową
wersję i mówimy to wprost; poprzednia zostaje w migawce szkicu.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from dataclasses import dataclass, field

from lxml import html as lxml_html
from lxml.html import HtmlElement

from app.services.cv_rodo_clause import is_rodo_text

_DASH = re.compile(r"\s*[-–—]\s*")
_HEADINGS = {"h1", "h2", "h3"}
# Tyle części musi się różnić naraz, żeby uznać, że różni się „wszystko” —
# przy dwóch częściach to może być zwykła praca rekrutera.
_ALL_CHANGED_MIN = 3


@dataclass
class _Part:
    key: str
    label: str
    blocks: list[HtmlElement] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(_plain(block) for block in self.blocks)


@dataclass(frozen=True)
class MergeResult:
    html: str
    # Etykiety części zostawionych w wersji rekrutera (po polsku, do zdania).
    kept: tuple[str, ...]
    # `False` = nie umiemy rozpoznać ręcznych poprawek; `html` to cała nowa wersja.
    recognized: bool


def _plain(element: HtmlElement) -> str:
    return " ".join(unicodedata.normalize("NFC", element.text_content()).split())


def _classes(element: HtmlElement) -> set[str]:
    return set((element.get("class") or "").split())


def _blocks(markup: str) -> list[HtmlElement]:
    """Bloki dokumentu: bez opakowania `article.cv` i bez `div.job` generatora."""
    root = lxml_html.fragment_fromstring(markup or "", create_parent="div")
    items = [child for child in root if isinstance(child.tag, str)]
    while len(items) == 1 and items[0].tag in ("article", "div", "section"):
        if "job" in _classes(items[0]):
            break
        items = [child for child in items[0] if isinstance(child.tag, str)]
    blocks: list[HtmlElement] = []
    for item in items:
        if item.tag == "div" and "job" in _classes(item):
            blocks.extend(child for child in item if isinstance(child.tag, str))
        else:
            blocks.append(item)
    return blocks


def _is_rodo(block: HtmlElement) -> bool:
    return (
        block.get("data-cv-section") == "rodo"
        or "rodo" in _classes(block)
        or is_rodo_text(_plain(block))
    )


def _label(text: str) -> str:
    text = " ".join(text.split())
    return text[:1].upper() + text[1:].lower() if text.isupper() else text


def _dates(role: HtmlElement) -> str:
    """Daty z linii stanowiska: to, co zostaje bez pogrubionej nazwy roli.

    Nazwa roli zmienia się między generacjami („Snowflake Data Engineer” →
    „Data Engineer”), daty — nie (przegląd PR 5: wzorzec dat łapał „now”
    w środku słowa i rola lądowała w wyniku dwa razy).
    """
    line = copy.deepcopy(role)
    for bold in line.xpath(".//strong|.//b"):
        bold.drop_tree()
    return _DASH.sub("-", _plain(line)).lower()


def _role_key(part: _Part) -> tuple[str, str]:
    role = next((b for b in part.blocks if b.get("data-cv-section") == "role"), None)
    employer = next(
        (b for b in part.blocks if b.get("data-cv-section") == "employer"), None
    )
    dates = _dates(role) if role is not None else ""
    if employer is not None:
        company = _plain(employer).split(" · ")[0].strip()
        if company:
            return f"role:{company.lower()}|{dates}", company
    title = _plain(role) if role is not None else part.text
    return f"role:{title.lower()}", title


def _parts(markup: str) -> tuple[list[_Part], list[HtmlElement]]:
    """Części CV w kolejności i klauzula zgody osobno (zawsze z nowej wersji)."""
    parts: list[_Part] = []
    rodo: list[HtmlElement] = []
    current = _Part("head", "nagłówek CV")
    section = ""
    for block in _blocks(markup):
        marker = block.get("data-cv-section") or ""
        if _is_rodo(block):
            rodo.append(block)
            continue
        if block.tag in _HEADINGS and block.tag != "h1":
            parts.append(current)
            section = marker or _plain(block).lower()
            current = _Part(f"section:{section}", _label(_plain(block)), [block])
            continue
        if section == "experience" and marker == "role":
            parts.append(current)
            current = _Part("", "", [block])
            continue
        current.blocks.append(block)
    parts.append(current)
    seen: dict[str, int] = {}
    for part in parts:
        if not part.key:
            part.key, part.label = _role_key(part)
        # Dwa stanowiska o tym samym kluczu (ta sama firma i daty) — po kolei.
        count = seen.get(part.key, 0)
        seen[part.key] = count + 1
        if count:
            part.key = f"{part.key}#{count}"
    return [part for part in parts if part.blocks], rodo


def _html(parts: list[_Part], rodo: list[HtmlElement]) -> str:
    blocks = [block for part in parts for block in part.blocks] + rodo
    return "".join(
        lxml_html.tostring(block, encoding="unicode", with_tail=False)
        for block in blocks
    )


def merge_rewrite(previous: str, draft: str, new: str) -> MergeResult:
    """Nowa wersja CV z częściami, które rekruter poprawiał, w jego wersji.

    ``previous`` — HTML generacji, z której powstał szkic; ``draft`` — szkic
    teraz; ``new`` — HTML nowej generacji. Bez zapisu i bez sieci.
    """
    previous_parts, _ = _parts(previous)
    draft_parts, draft_rodo = _parts(draft)
    new_parts, new_rodo = _parts(new)
    rodo = new_rodo or draft_rodo

    def sections(parts: list[_Part]) -> bool:
        return any(part.key.startswith("section:") for part in parts)

    if not (sections(previous_parts) and sections(draft_parts) and sections(new_parts)):
        return MergeResult(new, (), recognized=False)

    def roles(parts: list[_Part]) -> list[str]:
        return [part.key for part in parts if part.key.startswith("role:")]

    # Stanowiska bez jednoznacznego klucza (ta sama firma i daty) albo inny
    # zestaw stanowisk w nowej generacji: nie zgadujemy, która rola jest która
    # (przegląd PR 5 — zamiana kolejności gubiła rolę bez śladu).
    if any("#" in key for key in roles(previous_parts) + roles(new_parts)) or set(
        roles(previous_parts)
    ) != set(roles(new_parts)):
        return MergeResult(new, (), recognized=False)

    before = {part.key: part.text for part in previous_parts}
    in_draft = {part.key: part for part in draft_parts}
    in_new = {part.key: part for part in new_parts}
    edited = {part.key for part in draft_parts if before.get(part.key) != part.text}
    removed = {key for key in before if key not in in_draft}
    # Liczą się części z treścią: nagłówek CV i sam nagłówek „Doświadczenie”
    # są takie same niezależnie od tego, co stało się z resztą.
    known = [
        part
        for part in draft_parts
        if part.key in before and part.key != "head" and len(part.blocks) > 1
    ]
    if len(known) >= _ALL_CHANGED_MIN and all(part.key in edited for part in known):
        return MergeResult(new, (), recognized=False)

    merged: list[_Part] = []
    for part in new_parts:
        if part.key in removed:
            continue
        mine = in_draft.get(part.key)
        merged.append(mine if mine is not None and part.key in edited else part)
    # Część dopisana ręcznie (albo poprawiona, a nowej wersji jej brak) —
    # za tą częścią, za którą stała w szkicu.
    for index, part in enumerate(draft_parts):
        if part.key not in edited or part.key in in_new:
            continue
        earlier = {other.key for other in draft_parts[:index]}
        at = max(
            (i + 1 for i, other in enumerate(merged) if other.key in earlier),
            default=0,
        )
        merged.insert(at, part)

    kept = tuple(
        part.label
        for part in merged
        if part.key in edited
        and part is in_draft.get(part.key)
        and (part.key not in in_new or in_new[part.key].text != part.text)
    )
    return MergeResult(_html(merged, rodo), kept, recognized=True)


def roles_newest_first(markup: str) -> tuple[str, int]:
    """Stanowiska w doświadczeniu od najnowszego — poprawka QC „Ułóż od najnowszego”.

    Te same części co „Napisz od nowa”: stanowisko to blok ze znacznikiem
    ``role`` w sekcji doświadczenia i wszystko do następnego stanowiska albo
    nagłówka; przenosimy je w całości. Reguła kolejności i jej granica to
    `cv_role_order` (16.10.2026). Zwraca ``(treść, ile stanowisk zmieniło
    miejsce)``; przy zerze treść jest ta sama co na wejściu.
    """
    from app.services import cv_role_order

    parts, rodo = _parts(markup)
    slots = [n for n, part in enumerate(parts) if part.key.startswith("role:")]
    if len(slots) < 2:
        return markup, 0
    texts = []
    for n in slots:
        role = parts[n].blocks[0]
        texts.append(cv_role_order.dates_text(_dates(role), _plain(role)))
    order = cv_role_order.newest_first(texts)
    if order is None or order == list(range(len(slots))):
        return markup, 0
    moved = [parts[slots[n]] for n in order]
    for slot, part in zip(slots, moved):
        parts[slot] = part
    return _html(parts, rodo), sum(1 for k, n in enumerate(order) if k != n)
