"""Treści maila odrzucenia i dopisek o pozostałych rekrutacjach (17.10.2026).

Decyzje Artura z 17.10.2026 (makiety:
https://claude.ai/artifact/HvWWRjHpxovrQeNbLJudYL):

- D1: mail od „Zweryfikowany” w górę — osoba, z którą rozmawialiśmy, myśli,
  że bierze udział w procesie. Do „Zweryfikowany” i „QC CV” CV nie trafiło do
  klienta, więc treść „przed klientem” nie mówi, że „wybrano innego kandydata”
  (D4). Treść „po kliencie” to tekst z 13.10.2026 bez zmian.
- D2: osoba, która jest jeszcze w innych rekrutacjach, nie może z maila
  wyczytać, że odpada ze wszystkich. Dopisek „To dotyczy tylko tej
  rekrutacji — nadal bierzesz udział w…” zastępuje zakończenie i jest liczony
  w chwili wysyłki (znacznik w zapisanej treści), poza polem edycji.
- D5: nazwy rekrutacji z kodu strony kariery; nazwa, w której po czyszczeniu
  nadal widać kod zlecenia albo klienta, nie trafia do kandydata. Od
  18.10.2026 (wariant B) zapasowo tytuł dla rekrutera do pierwszego „ · ”,
  jeśli przechodzi tę samą kontrolę (``pick_mail_title``).
- D3: osoba odrzucona w drugiej rekrutacji, zanim wyszedł pierwszy mail,
  dostaje jeden wspólny (``merged_text``, dopisek „tych rekrutacji”).

Czyste funkcje — bez bazy. Zapytania są w ``rejection_email_scheduler``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from app.services.email_template_variables import plain_text_to_html
from app.services.public_profile_lint import lint_public_texts

TEXT_AFTER_CLIENT = "after_client"
TEXT_BEFORE_CLIENT = "before_client"
# Wspólny mail o kilku rekrutacjach (D3) — bez „przed/po kliencie”.
TEXT_MERGED = "merged"

DEFAULT_SUBJECT = "Informacja zwrotna — {job_title}"

# Treść Artura z 13.10.2026 (D2: „Życzymy”), podzielona na część do poprawy
# w oknie i zakończenie, które przy pozostałych rekrutacjach zastępuje dopisek.
_BODY_AFTER_CLIENT = (
    "Cześć {name},\n"
    "\n"
    "dziękujemy za udział w rekrutacji na stanowisko {job_title}. "
    "Niestety został wybrany inny kandydat."
)
_BODY_BEFORE_CLIENT = (
    "Cześć {name},\n"
    "\n"
    "dziękujemy za rozmowę i czas poświęcony na rekrutację na stanowisko "
    "{job_title}. Po przeanalizowaniu wymagań projektu zdecydowaliśmy, że "
    "w tym procesie nie przedstawimy Twojej kandydatury."
)
CLOSING = (
    "Życzymy powodzenia i zachęcamy do udziału w przyszłych procesach rekrutacyjnych!"
)

# Miejsce dopisku w zapisanej treści (HTML). `plain_text_to_html` zamienia
# „<” na encję, więc tekst wpisany w oknie nie podrobi znacznika.
OTHER_PROCESSES_MARKER = "<!-- nexus:pozostale-rekrutacje -->"

# Ciąg czterech cyfr to w nazwie od klienta numer zapytania albo zlecenia
# (pomiar 17.10.2026: 33 z 201 nazw po czyszczeniu strony kariery).
_CODE_RE = re.compile(r"\d{4,}")


@dataclass(frozen=True)
class DefaultText:
    """Temat, część do poprawy w oknie i zakończenie (zwykły tekst)."""

    subject: str
    body: str
    closing: str

    def full(self) -> str:
        return f"{self.body}\n\n{self.closing}"


def default_text(*, candidate_name: str, job_title: str, kind: str) -> DefaultText:
    template = _BODY_BEFORE_CLIENT if kind == TEXT_BEFORE_CLIENT else _BODY_AFTER_CLIENT
    name = (candidate_name or "").strip()
    title = (job_title or "").strip()
    return DefaultText(
        subject=DEFAULT_SUBJECT.format(job_title=title),
        body=template.format(name=name, job_title=title),
        closing=CLOSING,
    )


_COUNT_WORDS = {2: "dwóch", 3: "trzech", 4: "czterech"}


def _join_pl(items: Sequence[str]) -> str:
    """„A”, „A i B”, „A, B i C”."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " i " + items[-1]


def merged_text(*, candidate_name: str, job_titles: Sequence[str]) -> DefaultText:
    """Jeden mail o kilku rekrutacjach tej samej osoby (D3, 17.10.2026)."""
    titles = [t.strip() for t in job_titles if t and t.strip()]
    count = len(job_titles)
    how_many = _COUNT_WORDS.get(count, str(count))
    name = (candidate_name or "").strip()
    return DefaultText(
        subject=DEFAULT_SUBJECT.format(job_title=", ".join(titles)),
        body=(
            f"Cześć {name},\n\n"
            f"dziękujemy za udział w rekrutacjach na stanowiska {_join_pl(titles)}. "
            f"W tych {how_many} procesach nie przechodzisz dalej."
        ),
        closing=CLOSING,
    )


def title_safe_for_mail(title: Optional[str], client_names: Iterable[str]) -> bool:
    """Nazwa bez numeru zlecenia i bez nazwy klienta (reguły strony kariery).

    Do nazw klienta dochodzi ich pierwsze słowo z co najmniej 4 literami —
    „Nordea” z „Nordea Bank Abp”, jak przy czyszczeniu tytułu
    (``job_public_profile._prefix_candidates``); sama kontrola strony kariery
    porównuje całe nazwy.
    """
    clean = (title or "").strip()
    if not clean or _CODE_RE.search(clean):
        return False
    names: list[str] = []
    for raw in client_names:
        name = (raw or "").strip()
        if not name:
            continue
        names.append(name)
        first = name.split(" ", 1)[0]
        if sum(ch.isalpha() for ch in first) >= 4:
            names.append(first)
    return not lint_public_texts([clean], client_names=names)


def pick_mail_title(
    default: str, working_title: Optional[str], client_names: Iterable[str]
) -> tuple[str, bool]:
    """Nazwa do maila bez zatwierdzonego opisu strony kariery i czy jest bezpieczna.

    Najpierw nazwa od klienta po czyszczeniu (``default_public_title``). Gdy
    nadal widać w niej numer albo klienta, tytuł dla rekrutera do pierwszego
    „ · ” — reszta to umiejętności i lata (decyzja Artura 18.10.2026, wariant
    B: w 21 z 35 takich rekrutacji znika ręczna poprawka). Gdy i on nie
    przechodzi kontroli, zostaje nazwa od klienta z ostrzeżeniem.
    """
    names = list(client_names)
    if title_safe_for_mail(default, names):
        return default, True
    head = (working_title or "").split(" · ", 1)[0].strip()
    if title_safe_for_mail(head, names):
        return head, True
    return default, False


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def other_processes_text(
    titles: Sequence[Optional[str]], *, merged: bool = False
) -> Optional[str]:
    """Dopisek o pozostałych rekrutacjach — ``None``, gdy nie ma żadnej.

    ``titles`` — nazwa dla kandydata albo ``None``, gdy nazwy nie można
    pokazać (wtedy liczba: „i jeszcze 1 inna rekrutacja”). ``merged`` — mail
    o kilku rekrutacjach naraz: „To dotyczy tylko tych rekrutacji”.
    """
    if not titles:
        return None
    scope = "tych rekrutacji" if merged else "tej rekrutacji"
    named = [t for t in titles if t]
    unnamed = len(titles) - len(named)
    total = len(titles)
    one = total == 1
    later = (
        "Odezwiemy się, gdy będziemy mieć w nim nowe informacje."
        if one
        else "Odezwiemy się, gdy będziemy mieć w nich nowe informacje."
    )
    if not named:
        where = (
            "w jeszcze jednej naszej rekrutacji"
            if one
            else f"w jeszcze {total} naszych rekrutacjach"
        )
        return f"To dotyczy tylko {scope} — nadal bierzesz udział {where}.\n\n{later}"
    lead = (
        f"To dotyczy tylko {scope} — nadal bierzesz udział w naszym "
        "pozostałym procesie:"
        if one
        else f"To dotyczy tylko {scope} — nadal bierzesz udział w naszych "
        "pozostałych procesach:"
    )
    lines = [f"• {t}" for t in named]
    if unnamed:
        rest = _plural(
            unnamed, "inna rekrutacja", "inne rekrutacje", "innych rekrutacji"
        )
        lines.append(f"• i jeszcze {unnamed} {rest}")
    return lead + "\n" + "\n".join(lines) + f"\n\n{later}"


def fill_other_processes(
    body_html: str, titles: Sequence[Optional[str]], *, merged: bool = False
) -> str:
    """Znacznik → dopisek z listą z chwili wysyłki albo zwykłe zakończenie.

    Treść bez znacznika (szablon, odrzucenie bez dopisku) wraca bez zmian.
    """
    if OTHER_PROCESSES_MARKER not in body_html:
        return body_html
    text = other_processes_text(titles, merged=merged) or CLOSING
    return body_html.replace(OTHER_PROCESSES_MARKER, plain_text_to_html(text))
