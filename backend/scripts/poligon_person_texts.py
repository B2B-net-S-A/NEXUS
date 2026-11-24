"""Teksty osoby-szablonu na Poligonie, które ekran wstawia w zdanie (24.11.2026).

Filtr nagrania (`build_poligon_dataset.py`) wycina tekst spoza słownika i
zostawia w jego miejscu `null`. Dwa ekrany wstawiają takie pole w zdanie i przy
teście Poligonu z lukami pisały „null”:

- profil kandydata, pasek faktów: „null · poziom nieznany” — języki osoby
  (`language_name`, `cefr_level` spoza słownika nagrania);
- arkusz rozmowy: wcześniejsza odpowiedź kandydata „„null”” pod pytaniem
  screeningu (`text` podpowiedzi z poprzedniej rozmowy).

Odczyty osoby-szablonu (Helena Wrzosek) dostaje każda osoba ćwiczebna, więc
odpowiedzi są bez rodzaju gramatycznego i pasują do CV ćwiczebnego
(`frontend/src/lib/poligon/cv-fiction.ts`: migracja systemu płatności,
bankowość mobilna). Teksty są wymyślone, a odpowiedzi trafiają do
`meta.fiction_responses` (klucze `language_name`, `cefr_level` są spoza
słownika nagrania).
"""

from __future__ import annotations

import copy

TEMPLATE_CANDIDATE = 990105
TEMPLATE_ENTRY = 990305

LANGUAGES_KEY = f"GET /api/candidates/{TEMPLATE_CANDIDATE}/languages"
EARLIER_ANSWERS_KEY = (
    f"POST /api/pipeline/stages/{TEMPLATE_ENTRY}/screening/reassign-suggestions"
)

# Polska nazwa z kodu (jak `LANGUAGE_OPTIONS` w `lib/candidate-languages.ts`)
# i poziom jak w liście kandydatów zestawu. Język spoza słownika wypada.
LANGUAGES = {
    "pl": ("polski", None),
    "en": ("angielski", "C1"),
    "de": ("niemiecki", "B1"),
    "ru": ("rosyjski", "A1"),
}

# Odpowiedzi z poprzedniej rozmowy na pytania rekrutacji ćwiczebnej (q1–q4).
EARLIER_ANSWERS = {
    "q1": (
        "Migracja systemu płatności w banku: 4 zespoły, ok. 40 osób, budżet "
        "12 mln zł, 18 miesięcy. Rola: kierownik programu."
    ),
    "q2": (
        "Nowa bankowość mobilna: priorytety biznesu rozpisane na plan wdrożenia "
        "w trzech etapach, z harmonogramem i zależnościami między zespołami. "
        "Odpowiedzialność za zakres i terminy dostaw."
    ),
    "q3": (
        "Migracja systemu płatności w trzech spółkach grupy: ocena wpływu na "
        "każdą spółkę, podział zasobów i wspólny harmonogram wdrożenia."
    ),
    "q4": (
        "Comiesięczny raport dla komitetu sterującego (status, ryzyka, decyzje "
        "do podjęcia) i prezentacje dla zarządu po każdym etapie."
    ),
}


def with_language_names(body: dict) -> dict:
    """Języki z nazwą i poziomem; poziom zostaje pusty u języka ojczystego."""
    out = copy.deepcopy(body)
    rows = []
    for row in out.get("languages") or []:
        known = LANGUAGES.get(row.get("language_code") or "")
        if known is None:
            continue
        name, level = known
        rows.append(
            {
                **row,
                "language_name": name,
                "cefr_level": None if row.get("is_native") else level,
            }
        )
    out["languages"] = rows
    return out


def with_earlier_answers(body: dict) -> dict:
    """Podpowiedzi z treścią; pytanie spoza rekrutacji ćwiczebnej wypada."""
    out = copy.deepcopy(body)
    out["suggestions"] = [
        {**item, "text": EARLIER_ANSWERS[item["question_id"]]}
        for item in out.get("suggestions") or []
        if item.get("question_id") in EARLIER_ANSWERS
    ]
    return out


def person_texts(dataset: dict) -> tuple[dict, list[str]]:
    """Odczyty do nałożenia na zestaw i klucze, które są w całości wymyślone."""
    out = {
        LANGUAGES_KEY: with_language_names(dataset[LANGUAGES_KEY]),
        EARLIER_ANSWERS_KEY: with_earlier_answers(dataset[EARLIER_ANSWERS_KEY]),
    }
    return out, sorted(out)
