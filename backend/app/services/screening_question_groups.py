"""Pytania screeningowe kilku rekrutacji w jednej rozmowie (14.10.2026, D3).

Decyzja Artura: pytanie o to samo w dwóch rekrutacjach zadajemy raz,
a odpowiedź trafia do arkusza każdej z nich pod JEJ identyfikatorem pytania
(identyfikatory są pozycyjne per rekrutacja — ``q1`` z A to nie ``q1`` z B).

„O to samo” = ten sam tekst po złożeniu (bez polskich znaków, wielkości liter
i interpunkcji) albo reguła ``prior_screening.questions_match`` W OBIE STRONY
(te same słowa treści ≥ 60% i te same technologie — „Ile lat z Javą?” i „Ile
lat z Pythonem?” to różne pytania). Pytania o stawkę, dostępność, lokalizację
i tryb pracy (``has_own_layer``) łączymy wyłącznie po tym samym tekście —
reguła słów jest dla nich zbyt luźna. W grupie jest najwyżej jedno pytanie
z każdej rekrutacji; łączymy chciwie, w kolejności rekrutacji i pytań.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from app.services.prior_screening import _fold, has_own_layer, questions_match

_PUNCT = re.compile(r"[^\w\s]+")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class QuestionRef:
    job_id: int
    question_id: str
    text: str


def _normalized(text: str) -> str:
    return _SPACES.sub(" ", _PUNCT.sub(" ", _fold(text))).strip()


def same_question(a: str, b: str) -> bool:
    if _normalized(a) and _normalized(a) == _normalized(b):
        return True
    if has_own_layer(a) or has_own_layer(b):
        return False
    return questions_match(a, b) is not None and questions_match(b, a) is not None


def group_questions(
    questions_by_job: Mapping[int, Mapping[str, str]],
    job_order: Sequence[int],
    pairs: Sequence[tuple[tuple[int, str], tuple[int, str]]] = (),
) -> list[list[QuestionRef]]:
    """Grupy pytań: każda lista to jedno pytanie do zadania w rozmowie.

    ``pairs`` — pary „to samo pytanie” potwierdzone przy łączeniu bliźniaków
    (0614, 28.10.2026): mają pierwszeństwo przed regułą tekstu, bo pytania
    napisane innymi słowami reguła rozdzielała (ZOB-2947 i ZOB-2964: 0 z 8)."""
    partners: dict[tuple[int, str], set[tuple[int, str]]] = {}
    for a, b in pairs:
        partners.setdefault(a, set()).add(b)
        partners.setdefault(b, set()).add(a)
    placed: dict[tuple[int, str], list[QuestionRef]] = {}
    groups: list[list[QuestionRef]] = []
    for job_id in job_order:
        for question_id, text in (questions_by_job.get(job_id) or {}).items():
            ref = QuestionRef(job_id=job_id, question_id=question_id, text=text)
            target = next(
                (
                    placed[key]
                    for key in sorted(partners.get((job_id, question_id), ()))
                    if key in placed
                    and all(member.job_id != job_id for member in placed[key])
                ),
                None,
            )
            if target is None:
                target = next(
                    (
                        group
                        for group in groups
                        if all(member.job_id != job_id for member in group)
                        and all(same_question(text, member.text) for member in group)
                    ),
                    None,
                )
            if target is None:
                target = [ref]
                groups.append(target)
            else:
                target.append(ref)
            placed[(job_id, question_id)] = target
    return groups


__all__ = ["QuestionRef", "group_questions", "same_question"]
