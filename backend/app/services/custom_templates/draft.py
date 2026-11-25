"""Szkic wzoru z asystentem: funkcja AI ``legal_template_draft``.

Model dostaje WYŁĄCZNIE treść wzoru (akapity z polami ``{{ klucz }}``, bez
danych osób — wzór ich nie ma, a numery i adresy e-mail i tak są maskowane)
i polecenie człowieka. Odpowiada listą zmian akapitów i nowych pól (JSON).
Kod nakłada zmiany na DOCX (``docx_ops``), odrzuca każdą zmianę z instrukcją
Jinja (``{% … %}``) albo polem spoza listy, a gotowy szablon i tak przechodzi
walidację sandboxa. Kwoty słownie, daty i formy Pan/Pani liczy kod — model
pisze tylko zdania.

Model jest dodatkiem (``CLAUDE.md``): bez klucza albo przy awarii szkic zostaje
bez zmian, a ścieżka „wgraj Word → pola → zapis” działa.
"""

from __future__ import annotations

import copy
import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.text.paragraph import Paragraph
from starlette.concurrency import run_in_threadpool

from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import fallbacks_for, model_for
from app.services.custom_templates.detect import _PERSONAL
from app.services.custom_templates.docx_ops import (
    DocxOpsError,
    paragraphs,
    replace_span,
    scrub_package,
)
from app.services.custom_templates.fields import (
    KINDS,
    SOURCES,
    CustomField,
    FieldsError,
    allowed_paths,
    parse_fields,
)

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.legal_template_draft
MAX_PROMPT_CHARS = 90_000
MAX_INSTRUCTION = 3000
MAX_CHANGES = 40
MAX_CHANGE_TEXT = 4000
MAX_NEW_FIELDS = 20
MAX_BRIEF_PARAGRAPHS = 120

SYSTEM = (
    "Jesteś asystentem prawnym spółki B2B.net S.A. (outsourcing specjalistów IT "
    "w modelu B2B). Przygotowujesz WZÓR umowy po polsku — bez danych konkretnych "
    "osób. Miejsca do wypełnienia zapisujesz wyłącznie jako {{ klucz }} (klucz: małe "
    "litery, cyfry, podkreślenia, kropki, np. {{ partner.nip }}). Nie wpisujesz "
    "kwot słownie, dat ani form Pan/Pani — to robi system: kwota {{ x }} ma zapis "
    "słownie {{ x_words }}, formy rodzajowe to {{ g.g_pan }} (Panem/Panią), "
    "{{ g.g_prowadzacy }} (prowadzącym/prowadzącą), {{ g.g_zwanym }} (zwanym/zwaną). "
    "Dane spółki: {{ company.name }}, {{ company.address }}, {{ company.nip }}, "
    "{{ company.krs }}, {{ company.representative }}. Nie używasz {% %}. Umowa B2B "
    "nie może mieć znamion stosunku pracy (art. 22 § 1 KP); przeniesienie praw "
    "autorskich wymaga formy pisemnej (art. 53 pr. aut.). Nie cytujesz przepisów, "
    "których nie znasz dokładnie. Odpowiadasz WYŁĄCZNIE obiektem JSON."
)

_CHANGE_PROMPT = """Wzór bazowy (akapity z numerami):
{paragraphs}

Pola wzoru (klucz — etykieta):
{fields}

Polecenie osoby tworzącej nowy wzór:
{instruction}

Zwróć JSON:
{{"summary": "1–2 zdania, co zmieniasz",
  "title": "nowy tytuł umowy albo null",
  "changes": [{{"op": "replace" | "insert_after" | "delete", "i": numer akapitu,
               "text": "nowa treść akapitu (dla delete pusto)", "reason": "krótko po co"}}],
  "new_fields": [{{"key": "…", "label": "…", "kind": "text|textarea|date|money|bool",
                  "group": "Partner|Klient|Dokument|Pieniądze|…",
                  "source": "candidate|ceidg|clients|manual"}}]}}
Zmieniaj tylko to, czego wymaga polecenie; resztę wzoru zostaw bez zmian."""

_BRIEF_PROMPT = """Opis nowego wzoru umowy:
{instruction}

Zwróć JSON:
{{"summary": "1–2 zdania",
  "title": "tytuł umowy",
  "paragraphs": [{{"style": "title" | "heading" | "body", "text": "…"}}],
  "new_fields": [{{"key": "…", "label": "…", "kind": "text|textarea|date|money|bool|gender",
                  "group": "…", "source": "candidate|ceidg|clients|manual"}}]}}
Komparycja: {{{{ company.name }}}} z siedzibą w Warszawie, {{{{ company.address }}}},
KRS {{{{ company.krs }}}}, NIP {{{{ company.nip }}}}, reprezentowana przez
{{{{ company.representative }}}}, a {{{{ g.g_pan }}}} {{{{ partner.name_instrumental }}}}
{{{{ g.g_prowadzacy }}}} działalność gospodarczą pod firmą {{{{ partner.legal_name }}}},
NIP {{{{ partner.nip }}}}. Paragrafy jako nagłówki „§ 1 …”. Dodaj klauzulę
informacyjną RODO dla Partnera."""


@dataclass
class DraftResult:
    docx: bytes
    fields: list[CustomField]
    summary: str = ""
    title: str | None = None
    changes: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ai_used: bool = False


def _mask(text: str) -> str:
    """Wzór nie ma danych osób, ale na wszelki wypadek: numery i e-maile
    do modelu nie idą (``CLAUDE.md`` — dane osób tylko jako znaczniki)."""
    for rx, _ in _PERSONAL:
        text = rx.sub("[usunięte]", text)
    return text


def numbered_paragraphs(docx_bytes: bytes) -> list[tuple[int, str]]:
    document = docx.Document(io.BytesIO(docx_bytes))
    return [(i, p.text) for i, p in enumerate(paragraphs(document)) if p.text.strip()]


def _parse_reply(reply: str) -> dict[str, Any] | None:
    start, end = reply.find("{"), reply.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(reply[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def call_model(prompt: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja: testy ją podmieniają."""
    from app.services.claude_client import call_claude_text  # noqa: PLC0415

    return call_claude_text(
        model=model_for(FEATURE),
        fallback_models=list(fallbacks_for(FEATURE)),
        max_tokens=8000,
        temperature=0,
        thinking={"type": "disabled"},
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )


def model_available() -> bool:
    from app.services.llm_providers import api_key_configured  # noqa: PLC0415

    return api_key_configured(model_for(FEATURE))


def _new_fields(
    raw: object, existing: list[CustomField]
) -> tuple[list[CustomField], list[str]]:
    known = {f.key for f in existing}
    proposed: list[dict[str, Any]] = []
    for item in (raw if isinstance(raw, list) else [])[:MAX_NEW_FIELDS]:
        if not isinstance(item, dict) or str(item.get("key") or "") in known:
            continue
        kind = str(item.get("kind") or "text")
        proposed.append(
            {
                "key": str(item.get("key") or "").strip(),
                "label": item.get("label"),
                "kind": kind
                if kind in KINDS and kind not in ("list", "select")
                else "text",
                "group": item.get("group"),
                "source": item.get("source")
                if item.get("source") in SOURCES
                else "manual",
                "required": kind != "bool",
            }
        )
    accepted: list[CustomField] = []
    warnings: list[str] = []
    for item in proposed:
        try:
            accepted.extend(parse_fields([item]))
        except FieldsError as exc:
            warnings.append(f"Pole od asystenta pominięte: {exc}")
    try:
        parse_fields([*map(_as_json, existing), *map(_as_json, accepted)])
    except FieldsError as exc:
        return [], [f"Pola od asystenta pominięte: {exc}"]
    return accepted, warnings


def _as_json(f: CustomField) -> dict[str, Any]:
    data = f.to_public()
    data.pop("source_label", None)
    return data


_PLACEHOLDER = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")


def _text_problem(text: str, allowed: set[str]) -> str | None:
    if "{%" in text or "%}" in text:
        return "instrukcja {% %}"
    for m in _PLACEHOLDER.finditer(text):
        if m.group(1) not in allowed:
            return f"pole „{m.group(1)[:40]}”"
    if "{{" in _PLACEHOLDER.sub("", text) or "}}" in _PLACEHOLDER.sub("", text):
        return "niedomknięte pole"
    return None


def apply_changes(
    docx_bytes: bytes,
    fields: list[CustomField],
    data: dict[str, Any],
    *,
    title: str,
) -> DraftResult:
    """Nałóż zmiany od modelu na DOCX. Każda zmiana z instrukcją Jinja albo
    nieznanym polem jest pomijana z ostrzeżeniem — reszta wchodzi."""
    new_fields, warnings = _new_fields(data.get("new_fields"), fields)
    all_fields = [*fields, *new_fields]
    paths = allowed_paths(all_fields)
    allowed = set(paths.scalars)
    document = docx.Document(io.BytesIO(docx_bytes))
    all_p = paragraphs(document)
    raw_changes = data.get("changes") if isinstance(data.get("changes"), list) else []
    applied: list[dict[str, Any]] = []
    # Od końca: wstawienia i usunięcia nie przesuwają numerów wcześniejszych.
    valid = [
        c
        for c in raw_changes[:MAX_CHANGES]
        if isinstance(c, dict)
        and isinstance(c.get("i"), int)
        and 0 <= c["i"] < len(all_p)
    ]
    for change in sorted(valid, key=lambda c: c["i"], reverse=True):
        op = change.get("op")
        target: Paragraph = all_p[change["i"]]
        text = str(change.get("text") or "")[:MAX_CHANGE_TEXT].strip()
        reason = str(change.get("reason") or "")[:300]
        before = target.text
        if op in ("replace", "insert_after"):
            problem = _text_problem(text, allowed) if text else "pusta treść"
            if problem:
                warnings.append(f"Zmiana akapitu {change['i']} pominięta: {problem}.")
                continue
        try:
            if op == "replace":
                replace_span(target, 0, len(target.text), text)
            elif op == "insert_after":
                clone = copy.deepcopy(target._p)
                target._p.addnext(clone)
                new = Paragraph(clone, target._parent)
                replace_span(new, 0, len(new.text), text)
            elif op == "delete":
                target._p.getparent().remove(target._p)
            else:
                warnings.append(f"Nieznana operacja „{str(op)[:20]}” pominięta.")
                continue
        except DocxOpsError as exc:
            warnings.append(f"Zmiana akapitu {change['i']} pominięta: {exc}")
            continue
        applied.append(
            {
                "op": op,
                "i": change["i"],
                "before": before if op != "insert_after" else "",
                "after": text if op != "delete" else "",
                "context": before if op == "insert_after" else "",
                "reason": reason,
            }
        )
    applied.sort(key=lambda c: (c["i"], c["op"] != "replace"))
    buf = io.BytesIO()
    document.save(buf)
    new_title = data.get("title") if isinstance(data.get("title"), str) else None
    return DraftResult(
        docx=scrub_package(buf.getvalue(), new_title or title),
        fields=all_fields,
        summary=str(data.get("summary") or "")[:600],
        title=(new_title or "")[:150] or None,
        changes=applied,
        warnings=warnings,
        ai_used=True,
    )


def build_from_brief(data: dict[str, Any]) -> DraftResult:
    """Nowy DOCX z akapitów od modelu (ścieżka „Sam opis”)."""
    document = docx.Document()
    raw = data.get("paragraphs") if isinstance(data.get("paragraphs"), list) else []
    new_fields, warnings = _new_fields(data.get("new_fields"), [])
    gender = CustomField(
        key="partner.gender",
        label="Płeć Partnera (formy Pan/Pani)",
        kind="gender",
        group="Partner",
        source="candidate",
        required=True,
    )
    fields = [*new_fields]
    if not any(f.key == gender.key for f in fields):
        fields.insert(0, gender)
    allowed = set(allowed_paths(fields).scalars)
    for item in raw[:MAX_BRIEF_PARAGRAPHS]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()[:MAX_CHANGE_TEXT]
        if not text:
            continue
        problem = _text_problem(text, allowed)
        if problem:
            # Pole, którego model nie zgłosił, staje się widoczną luką do poprawy.
            text = (
                _PLACEHOLDER.sub(
                    lambda m: m.group(0) if m.group(1) in allowed else "……", text
                )
                .replace("{%", "")
                .replace("%}", "")
            )
            warnings.append(f"Akapit „{text[:40]}…”: {problem} zamienione na lukę.")
        style = item.get("style")
        p = document.add_paragraph()
        run = p.add_run(text)
        if style in ("title", "heading"):
            run.bold = True
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    buf = io.BytesIO()
    document.save(buf)
    title = str(data.get("title") or "Wzór własny")[:150]
    return DraftResult(
        docx=scrub_package(buf.getvalue(), title),
        fields=fields,
        summary=str(data.get("summary") or "")[:600],
        title=title,
        warnings=warnings,
        ai_used=True,
    )


def change_prompt(
    docx_bytes: bytes, fields: list[CustomField], instruction: str
) -> str:
    numbered = "\n".join(
        f"[{i}] {_mask(t)}" for i, t in numbered_paragraphs(docx_bytes)
    )
    field_lines = "\n".join(f"{f.key} — {f.label}" for f in fields) or "(brak)"
    prompt = _CHANGE_PROMPT.format(
        paragraphs=numbered[:MAX_PROMPT_CHARS],
        fields=field_lines,
        instruction=_mask(instruction[:MAX_INSTRUCTION]),
    )
    return prompt


def brief_prompt(instruction: str) -> str:
    return _BRIEF_PROMPT.format(instruction=_mask(instruction[:MAX_INSTRUCTION]))


async def ask(prompt: str) -> dict[str, Any] | None:
    """Wywołanie modelu poza pętlą zdarzeń; awaria = ``None`` (wołający
    deklaruje ``ai_feature`` i mówi człowiekowi, że szkic został bez zmian)."""
    try:
        reply = await run_in_threadpool(call_model, prompt)
    except Exception as exc:  # noqa: BLE001 — AI to dodatek
        logger.warning("legal_template_draft: model failed (%s)", type(exc).__name__)
        return None
    return _parse_reply(reply)
