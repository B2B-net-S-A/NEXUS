"""Każdy błąd WIERSZA w imporcie Traffita niesie klucz ``<encja> ext=|id=``.

Runda 6 audytu (T6-6/T6-7): ``workflow {wf_id} detail HTTP …`` i
``merge tags candidate={id}: …`` nie pasowały do ``_ERROR_REF_RE`` — błąd
był NIEPRZYPISANY, więc ``_blocking_errors`` wstrzymywał watermark
``__daily__`` bez końca, a kwarantanna nie miała czego zaparkować.

Test czyta źródło importera: komunikat bez klucza wiersza musi być na liście
błędów FAZY (wtedy nieznane wiersze i wstrzymany watermark są właściwą
odpowiedzią) — nowy błąd wiersza bez klucza łapie CI, nie produkcja.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.services.traffit import importer
from app.services.traffit.importer import PhaseProgress

_SOURCE = Path(importer.__file__)
_REF = importer._ERROR_REF_RE

# Błędy całej paczki / fazy — tu wiersz jest nieznany z definicji.
_PHASE_LEVEL_PREFIXES = (
    "{} batch rolled back after lost connection",
    "index intent: ",
    "record job reindex intent: ",
    "archive traffit jobs: ",
    "classify job categories: ",
    "cv batch commit: ",
    "files batch commit: ",
    "activities batch commit: ",
    "activities pagination incomplete: ",
    "promote_notes: ",
    "rejection_note backfill: ",
    "rejection description backfill: ",
)


def _template(node: ast.AST) -> str | None:
    """Szablon komunikatu z f-stringu (``{}`` w miejscu wstawek)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else "{}"
            for part in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _template(node.left)
        return left + "{}" if left is not None else None
    return None


def _messages() -> list[tuple[int, str]]:
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_error"
            and node.args
        ):
            tpl = _template(node.args[0])
            if tpl is not None:
                out.append((node.lineno, tpl))
    return out


def test_every_row_error_in_the_importer_carries_a_row_key():
    messages = _messages()
    assert len(messages) > 30, "parser szablonów przestał widzieć wywołania"
    unattributed = [
        (line, tpl)
        for line, tpl in messages
        if not _REF.search(tpl.replace("{}", "7"))
        and not tpl.startswith(_PHASE_LEVEL_PREFIXES)
    ]
    assert unattributed == [], (
        f"błąd wiersza bez `<encja> ext=|id=` zamraża __daily__: {unattributed}"
    )


def test_workflow_detail_and_source_tag_errors_are_attributed():
    p = PhaseProgress(phase="x")
    p.add_error("detail workflow id=5: HTTP 500")
    p.add_error("merge tags candidate_source id=42: IntegrityError()")
    assert p.error_refs == {"workflow:5", "candidate_source:42"}
    assert p.attributed_errors == 2
    # Ten sam wiersz co `map workflow id=` — jeden wpis kwarantanny.
    q = PhaseProgress(phase="x")
    q.add_error("map workflow id=5: ValueError()")
    assert q.error_refs == {"workflow:5"}


def test_phase_prefixes_are_really_unattributed():
    """Lista wyjątków nie może przepuszczać komunikatów z kluczem wiersza."""
    for prefix in _PHASE_LEVEL_PREFIXES:
        assert not re.search(_REF, prefix.replace("{}", "7")), prefix
