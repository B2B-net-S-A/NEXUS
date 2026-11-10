"""Co człowiek zmienił w CV z generatora — liczby przy zatwierdzeniu (E3, 07.11.2026).

Pomiar 07.11.2026 musiał odtwarzać punkt startowy edytora kodem renderera,
a dla co trzeciego CV się nie udało, bo renderer zmienił się po generacji.
Dlatego szkic z generatora niesie treść startu w metadanych
(``START_HTML_KEY``, zapis w ``capture_editor_origin``), a zatwierdzenie
porównuje z nią zatwierdzaną treść i zapisuje wpis ``ACTION``.

W wpisie są wyłącznie nazwy części CV i liczby bloków: repo i logi Actions
są publiczne, a wpisy przeżywają usunięcie kandydata. Podział na części
(``data-cv-section``) jest ten sam co w pomiarze 07.11, żeby liczby dało się
porównać z raportem.

Koszt jest liniowy względem treści: jeden przebieg drzewa i porównanie
wielozbiorów tekstów w każdej części, bez dopasowywania par podobnych bloków.
Blok, którego tekst zniknął, i blok z nowym tekstem w tej samej części liczą
się razem jako „zmieniony”; nadwyżka to „dodane” albo „usunięte”.

Zapis nie może zatrzymać zatwierdzenia: idzie w SAVEPOINT-cie, a każdy błąd
(także odczytu treści) kończy się ostrzeżeniem w logu.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from typing import Optional

from lxml import html as lxml_html
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.services.cv_approved_docx import BLOCKS

logger = logging.getLogger(__name__)

ACTION = "cv_approved_edit_summary"
# Klucz w `branded_render_metadata`: treść edytora tuż po wstawieniu z generatora.
START_HTML_KEY = "generated_editor_html"

STATUS_UNCHANGED = "unchanged"
STATUS_BOLD_ONLY = "bold_only"
STATUS_CHANGED = "changed"
# Szkic z zapisanym startem zastąpiono czymś spoza generatora (CV-1, 08.11.2026).
STATUS_REPLACED = "replaced"

# Co zaczyna CV z generatora: mianownik raportu i granica liczenia `assisted`.
AUTO_START_ACTIONS = frozenset(
    {"branded_cv_attached_by_automation", "branded_cv_replaced_after_new_cv"}
)
MANUAL_START_ACTIONS = frozenset(
    {"branded_cv_attached_after_generation", "branded_cv_selected_from_generator"}
)
START_ACTIONS = AUTO_START_ACTIONS | MANUAL_START_ACTIONS
_COPY_START_ACTION = "branded_cv_selected_from_other_job"
# Wpis szkicu → rodzaj podmiany. Nowa droga podmiany = wpis tutaj.
REPLACE_KINDS = {
    "branded_cv_uploaded_in_recruitment": "upload",
    "branded_cv_uploaded_from_disk": "upload",
    "branded_cv_imported_from_document": "import",
    _COPY_START_ACTION: "copy",
    "branded_cv_copied_from_other_job": "copy",
    "branded_cv_discarded": "discard",
}
REPLACE_REASONS = frozenset(
    {"client_format", "missing_experience", "newer_cv", "other"}
)

# Ślady poprawek maszynowych między startem a zatwierdzeniem (CV-3).
ASSISTED_QC_FIX = "cv_qc_fix_applied"
ASSISTED_COMMAND = "cv_command_ai"
ASSISTED_APPLIED = "cv_command_applied"

# Sekcje generatora (`h2[data-cv-section]`), których bloki liczą się pod nazwą sekcji.
_SECTIONS = frozenset(
    {"why_points", "skills", "languages", "education", "certifications"}
)
_BLOCK_TAGS = frozenset({*BLOCKS, "thead", "tbody", "tfoot", "tr", "td", "th"})
_TECH = re.compile(r"^(technologie|technologies|tech stack)\s*:", re.I)
_CONSIDERED = re.compile(r"^(rozważany na stanowisko|considered for)", re.I)
_WS = re.compile(r"\s+")
_WORD = re.compile(r"\w[\w+#/-]*")


def _norm(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def _bold_words(el) -> frozenset:
    words: set[str] = set()
    for node in el.iter("b", "strong"):
        words.update(_WORD.findall(node.text_content().lower()))
    return frozenset(words)


def _part(el, text: str, section: str, in_item: bool, rodo: bool) -> Optional[str]:
    """Nazwa części CV dla bloku; ``None`` = klauzula RODO (stała, nie liczymy).

    ``in_item`` — blok w punkcie listy (edytor pisze ``<li><p>…</p></li>``).
    """
    tag = el.tag
    classes = (el.get("class") or "").split()
    mark = el.get("data-cv-section")
    if tag == "h1":
        return "title"
    if tag in ("h2", "h3"):
        return "headings"
    if rodo:
        return None
    if mark == "considered_for" or "considered" in classes or _CONSIDERED.match(text):
        return "considered_for"
    if mark == "role" or "job-head" in classes:
        return "role"
    if mark == "employer" or "job-co" in classes:
        return "employer"
    if mark == "technologies" or _TECH.match(text):
        return "technologies"
    if mark == "duties_label" or "lbl" in classes:
        return "headings"
    if section == "experience":
        return "duties" if tag == "li" or in_item else "other"
    if section in _SECTIONS:
        return section
    return "other"


def _is_leaf(el) -> bool:
    return not any(
        isinstance(child.tag, str) and child.tag in _BLOCK_TAGS for child in el
    )


def cv_blocks(html: str) -> list[tuple[str, str, frozenset]]:
    """Bloki treści w kolejności dokumentu: ``(część, tekst, pogrubione słowa)``.

    Blok to element bez bloków w środku (jak w generatorze Worda), więc liczy
    się też wklejka z Worda: cytat, tabela, ``h4``, goły ``div``. Tekst luźny
    obok bloków — np. punkt listy nad zagnieżdżoną listą po wcięciu — jest
    osobnym blokiem rodzica.
    """
    from app.services.cv_rodo_clause import is_rodo_node, is_rodo_text

    if not (html or "").strip():
        return []
    seen: dict = {}
    root = lxml_html.fragment_fromstring(html, create_parent="div")
    out: list[tuple[str, str, frozenset]] = []
    section = "header"

    def emit(el, text: str, bold: frozenset, in_item: bool, loose: bool) -> None:
        text = _norm(text)
        if text:
            # Luźny tekst sprawdzamy po nim samym, nie po rodzicu.
            rodo = is_rodo_text(text) if loose else is_rodo_node(el, seen)
            part = _part(el, text, section, in_item, rodo)
            if part is not None:
                out.append((part, text, bold))

    def expand(el, in_item: bool) -> list[tuple]:
        """Zawartość elementu z blokami w środku, w kolejności dokumentu."""
        items: list[tuple] = [("text", el, el.text, in_item)]
        child_in_item = in_item or el.tag == "li"
        for child in el:
            if isinstance(child.tag, str):
                items.append(("node", child, None, child_in_item))
            items.append(("text", el, child.tail, in_item))
        return items

    # Stos zamiast rekurencji; zawartość odkładana od końca = kolejność dokumentu.
    stack = list(reversed(expand(root, False)))
    while stack:
        kind, el, text, in_item = stack.pop()
        if kind == "text":
            emit(el, text or "", frozenset(), in_item, loose=True)
            continue
        if el.tag in ("h2", "h3"):
            section = el.get("data-cv-section") or "other"
        if _is_leaf(el):
            emit(el, el.text_content(), _bold_words(el), in_item, loose=False)
            continue
        stack.extend(reversed(expand(el, in_item)))
    return out


def summarize_edits(start_html: str, approved_html: str) -> dict:
    """Różnice per część CV między startem z generatora a zatwierdzoną treścią.

    Tylko liczby i nazwy części — żadnego tekstu CV.
    """
    before = cv_blocks(start_html)
    after = cv_blocks(approved_html)
    old: dict[str, list] = defaultdict(list)
    new: dict[str, list] = defaultdict(list)
    for part, text, bold in before:
        old[part].append((text, bold))
    for part, text, bold in after:
        new[part].append((text, bold))

    parts: dict[str, dict] = {}
    text_changed = False
    bold_changed = False
    for part in sorted(set(old) | set(new)):
        old_bold: dict[str, list] = defaultdict(list)
        for text, bold in old[part]:
            old_bold[text].append(bold)
        remaining = Counter({text: len(bolds) for text, bolds in old_bold.items()})
        taken: Counter = Counter()
        unmatched_new = 0
        bold_blocks = 0
        for text, bold in new[part]:
            if remaining[text] > 0:
                remaining[text] -= 1
                if old_bold[text][taken[text]] != bold:
                    bold_blocks += 1
                taken[text] += 1
            else:
                unmatched_new += 1
        unmatched_old = sum(remaining.values())
        changed = min(unmatched_old, unmatched_new)
        entry = {
            "added": unmatched_new - changed,
            "removed": unmatched_old - changed,
            "changed": changed,
            "bold": bold_blocks,
        }
        if any(entry.values()):
            parts[part] = entry
            text_changed = text_changed or bool(unmatched_old or unmatched_new)
            bold_changed = bold_changed or bool(bold_blocks)

    # Te same bloki w innej kolejności (np. przestawione stanowiska) to też poprawka.
    reordered = not text_changed and [(p, t) for p, t, _ in before] != [
        (p, t) for p, t, _ in after
    ]
    if text_changed or reordered:
        status = STATUS_CHANGED
    elif bold_changed:
        status = STATUS_BOLD_ONLY
    else:
        status = STATUS_UNCHANGED
    return {
        "status": status,
        "reordered": reordered,
        "blocks_before": len(before),
        "blocks_after": len(after),
        "chars_before": sum(len(text) for _, text, _ in before),
        "chars_after": sum(len(text) for _, text, _ in after),
        "changed_parts": sorted(
            part
            for part, entry in parts.items()
            if entry["added"] or entry["removed"] or entry["changed"]
        ),
        "bold_parts": sorted(part for part, entry in parts.items() if entry["bold"]),
        "parts": parts,
    }


def has_editor_start(metadata: Optional[dict]) -> bool:
    start = (metadata or {}).get(START_HTML_KEY)
    return isinstance(start, str) and bool(start.strip())


async def _assisted_counts(db: AsyncSession, csv_id: int) -> Optional[dict[str, int]]:
    """Ile razy kod i asystent ruszały to CV od ostatniego startu (CV-3).

    ``None`` przy błędzie odczytu: wpis z liczbami zmian i tak ma powstać.
    """
    try:
        # SAVEPOINT: błąd Postgresa poza nim przerwałby transakcję zatwierdzenia,
        # a COMMIT przerwanej transakcji po cichu cofa zatwierdzenie.
        async with db.begin_nested():
            return await _count_assisted(db, csv_id)
    except Exception:  # noqa: BLE001 — pomiar nie może zatrzymać zatwierdzenia
        logger.warning(
            "[cv_edit_summary] brak liczb assisted dla candidate_stage_cv:%s",
            csv_id,
            exc_info=True,
        )
        return None


async def _count_assisted(db: AsyncSession, csv_id: int) -> dict[str, int]:
    last_start = (
        select(func.max(Activity.created_at))
        .where(
            Activity.entity_type == "candidate_stage_cv",
            Activity.entity_id == csv_id,
            Activity.action.in_(START_ACTIONS | {_COPY_START_ACTION}),
        )
        .scalar_subquery()
    )
    rows = await db.execute(
        select(Activity.action, func.count())
        .where(
            Activity.entity_type == "candidate_stage_cv",
            Activity.entity_id == csv_id,
            Activity.action.in_((ASSISTED_QC_FIX, ASSISTED_COMMAND, ASSISTED_APPLIED)),
            Activity.created_at >= func.coalesce(last_start, Activity.created_at),
        )
        .group_by(Activity.action)
    )
    counts = dict(rows.all())
    return {
        "qc_fixes": counts.get(ASSISTED_QC_FIX, 0),
        "assistant_commands": counts.get(ASSISTED_COMMAND, 0),
        "assistant_applied": counts.get(ASSISTED_APPLIED, 0),
    }


async def log_replaced_edits(
    db: AsyncSession, *, csv, kind: str, user_id: Optional[int]
) -> bool:
    """Dopisz ``ACTION`` ze statusem ``replaced``, zanim szkic zniknie (CV-1).

    Mianownikiem generatora jest start, więc CV wyrzucone i zastąpione własnym
    plikiem musi zostawić ślad z liczbami do chwili podmiany. Wołać przed
    nadpisaniem szkicu. ``True`` = wpis zapisany (szkic miał start).
    """
    metadata = csv.branded_render_metadata
    if not has_editor_start(metadata):
        return False
    try:
        summary = summarize_edits(
            metadata[START_HTML_KEY], csv.branded_draft_html or ""
        )
        async with db.begin_nested():
            db.add(
                Activity(
                    entity_type="candidate_stage_cv",
                    entity_id=csv.id,
                    action=ACTION,
                    user_id=user_id,
                    details={
                        "candidate_stage_id": csv.candidate_stage_id,
                        "job_id": csv.job_id,
                        "version": csv.branded_version,
                        "generated_document_id": csv.generated_document_id,
                        "origin": metadata.get("source") or "generator",
                        **summary,
                        "status": STATUS_REPLACED,
                        "edits_status": summary["status"],
                        "replace_kind": kind,
                        "prior_status": csv.branded_status,
                    },
                )
            )
        return True
    except Exception:  # noqa: BLE001 — pomiar nie może zatrzymać podmiany
        logger.warning(
            "[cv_edit_summary] nie zapisano podmiany dla candidate_stage_cv:%s",
            getattr(csv, "id", None),
            exc_info=True,
        )
        return False


async def record_replace_reason(
    db: AsyncSession, *, csv_id: int, user_id: int, reason: str
) -> bool:
    """Powód z pigułki dopisany do ostatniego wpisu ``replaced`` tej osoby (CV-2)."""
    entry = await db.scalar(
        select(Activity)
        .where(
            Activity.entity_type == "candidate_stage_cv",
            Activity.entity_id == csv_id,
            Activity.action == ACTION,
            Activity.user_id == user_id,
            Activity.details["status"].astext == STATUS_REPLACED,
        )
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .limit(1)
    )
    if entry is None:
        return False
    entry.details = {**(entry.details or {}), "reason": reason}
    return True


async def log_approved_edits(
    db: AsyncSession,
    *,
    csv,
    approved_html: str,
    metadata: Optional[dict],
    user_id: Optional[int],
    document_version_id: Optional[int],
    version: Optional[int],
    extra: Optional[dict] = None,
) -> None:
    """Dopisz ``ACTION`` dla zatwierdzenia CV etapu, które zaczęło się w generatorze.

    CV bez zapisanego startu (sprzed E3, z pliku, z innego CV) nie dostaje
    wpisu — nie zgadujemy, od czego zaczął człowiek. Commit robi wołający.
    """
    if not has_editor_start(metadata):
        return
    try:
        summary = summarize_edits(metadata[START_HTML_KEY], approved_html)
        assisted = await _assisted_counts(db, csv.id)
        async with db.begin_nested():
            db.add(
                Activity(
                    entity_type="candidate_stage_cv",
                    entity_id=csv.id,
                    action=ACTION,
                    user_id=user_id,
                    details={
                        "candidate_stage_id": csv.candidate_stage_id,
                        "job_id": csv.job_id,
                        "document_version_id": document_version_id,
                        "version": version,
                        "generated_document_id": csv.generated_document_id,
                        "origin": metadata.get("source") or "generator",
                        "assisted": assisted,
                        **summary,
                        **(extra or {}),
                    },
                )
            )
    except Exception:  # noqa: BLE001 — pomiar nie może zatrzymać zatwierdzenia
        logger.warning(
            "[cv_edit_summary] nie zapisano wpisu %s dla candidate_stage_cv:%s",
            ACTION,
            getattr(csv, "id", None),
            exc_info=True,
        )
