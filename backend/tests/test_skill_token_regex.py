"""Dopasowanie umiejętności jednym wyrażeniem regularnym — ten sam wynik co ``strpos``.

Rodzina aliasów Javy to 9 pisowni, więc dawny predykat liczył 18 razy ``strpos``,
każdy z osobnym rzutowaniem JSONB na tekst i ``lower()``: na 68 tys. kandydatów
3,4 s zamiast 0,5 s. Wyrażenie regularne jest szybsze, ale ma znaki specjalne
(``c++``, ``.net``), a na tym predykacie stoją „Musi mieć”, „Wyklucz” i alerty
zapisanych wyszukiwań, więc wynik ma się zgadzać co do osoby.

Wyrocznia w Pythonie to dokładna definicja starego predykatu: igła w cudzysłowach
albo w ucieczkach ``\\"``. Część z bazą pyta prawdziwego Postgresa, bo składnia
wyrażeń ARE nie jest składnią modułu ``re``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import literal, select

from app.services import candidate_search_predicates as predicates


def _strpos_oracle(blob: str, needles: list[str]) -> bool:
    return any(f'"{n}"' in blob or f'\\"{n}\\"' in blob for n in needles)


CASES: list[tuple[str, list[str]]] = [
    # zwykłe tokeny i całe słowo
    ('["python", "go"]', ["go"]),
    ('["django"]', ["go"]),
    ('["golang"]', ["go"]),
    # oba kodowania JSON i granice mieszane
    ('"[\\"go\\", \\"python\\"]"', ["go"]),
    ('"[\\"django\\"]"', ["go"]),
    ('["go\\"]', ["go"]),
    ('["\\"go"]', ["go"]),
    # kropka nie jest dowolnym znakiem
    ('[".net"]', [".net", "dotnet"]),
    ('["xnet"]', [".net", "dotnet"]),
    ('["node.js"]', ["node.js"]),
    ('["nodexjs"]', ["node.js"]),
    ('"[\\"asp.net core\\"]"', [".net", "asp.net core"]),
    ('["bpmn 2.0"]', ["bpmn 2.0"]),
    ('["bpmn 2x0"]', ["bpmn 2.0"]),
    # plus i inne kwantyfikatory
    ('["c++"]', ["c++", "cpp"]),
    ('["ccc"]', ["c++"]),
    ('["c"]', ["c++"]),
    ('["angular 2+"]', ["angular 2+"]),
    ('["angular 22"]', ["angular 2+"]),
    ('["a"]', ["a?"]),
    ('["a?"]', ["a?"]),
    ('["aa"]', ["a{2}"]),
    ('["a{2}"]', ["a{2}"]),
    ('["anything"]', ["*"]),
    ('["*"]', ["*"]),
    # alternatywa, nawiasy, kotwice i klasy jako zwykłe znaki
    ('["a"]', ["a|b"]),
    ('["a|b"]', ["a|b"]),
    ('["(a)"]', ["(a)"]),
    ('["a"]', ["(a)"]),
    ('["x"]', ["[x]"]),
    ('["[x]"]', ["[x]"]),
    ('["^a$"]', ["^a$"]),
    ('["a"]', ["^a$"]),
    # znaki ucieczki i cudzysłów w nazwie
    ('["a\\\\b"]', ["a\\\\b"]),
    ('["a"b"]', ['a"b']),
    ('["c#"]', ["c#"]),
    # polskie znaki i odstępy
    ('["zarządzanie projektem"]', ["zarządzanie projektem"]),
    ('["zarzadzanie projektem"]', ["zarządzanie projektem"]),
    # kilka pisowni, trafia tylko jedna
    ('["j2ee", "kafka"]', ["java", "java se", "j2ee"]),
    ('["javascript"]', ["java", "java se", "j2ee"]),
    # pusta igła: stary predykat szukał ""
    ('[""]', [""]),
    ('["a"]', [""]),
]


def test_rodzina_aliasow_to_jedno_wyrazenie() -> None:
    """Koszt ma nie rosnąć z liczbą pisowni: jedno przejście po zrzucie."""
    blob = predicates.func.lower(predicates.skills_text())
    sql = str(
        predicates._json_token_match(blob, ["java", "java se", "j2ee"]).compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "strpos" not in sql
    assert sql.count(" ~ ") == 1
    assert "java se|j2ee" in sql


def test_znaki_specjalne_sa_literalami() -> None:
    blob = predicates.func.lower(predicates.skills_text())
    pattern = predicates._json_token_match(blob, ["c++", ".net"]).right.value
    assert r"c\+\+" in pattern
    assert r"\.net" in pattern


@pytest.mark.parametrize("blob,needles", CASES)
@pytest.mark.asyncio
async def test_wyrazenie_daje_to_samo_co_strpos(blob: str, needles: list[str]) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        got = await db.scalar(
            select(predicates._json_token_match(literal(blob), needles))
        )
    assert got is _strpos_oracle(blob, needles), f"{needles!r} w {blob!r}"


@pytest.mark.asyncio
async def test_bardzo_dluga_nazwa_nie_konczy_sie_bledem() -> None:
    """Postgres odrzuca zbyt złożone wyrażenie; dawny ``strpos`` nie miał limitu."""
    from app.core.database import AsyncSessionLocal

    needle = "a" * 40_000
    async with AsyncSessionLocal() as db:
        hit = await db.scalar(
            select(predicates._json_token_match(literal(f'["{needle}"]'), [needle]))
        )
        miss = await db.scalar(
            select(predicates._json_token_match(literal('["a"]'), [needle]))
        )
    assert hit is True
    assert miss is False
