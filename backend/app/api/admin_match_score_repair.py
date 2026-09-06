"""Naprawa danych po znalezisku #32 — wiersze cache z zaniżoną semantyką.

Kontekst
--------
``/jobs/{id}/pipeline-scores`` miał własną, niepełną definicję „świeżego"
wiersza cache — bez predykatu ``scoring_algorithm_version``. Po bumpie wag
wiersz przestarzały wersyjnie przechodził jako aktualny, więc endpoint NIE
pobierał dla niego podobieństwa semantycznego, liczył go z
``semantic_similarity=None`` (0 z 60 punktów, powód ``"brak embeddingu"``)
i zapisywał z powrotem jako świeży pod NOWĄ wersją algorytmu.

Kod jest naprawiony (``fresh_score_conditions`` jest jedynym miejscem definicji
świeżości). **Dane nie.** Zatruty wiersz ma bieżącą wersję i ``stale=False``,
więc poprawny predykat też uzna go za świeży i nic go nie przeliczy — zaniżony
wynik jest trwały. Ten moduł jest jednorazowym (a właściwie: powtarzalnym)
narzędziem, które takie wiersze odnajduje i **unieważnia**.

Jak odróżniamy zatrucie od prawdy
---------------------------------
„0 punktów, brak embeddingu" jest ZGODNE Z PRAWDĄ dla kandydata, który wektora
naprawdę nie ma — jego przeliczenie da dokładnie ten sam wynik i będzie czystym
kosztem. Wiersz jest zatruty wtedy i tylko wtedy, gdy mówi „brak embeddingu"
o kandydacie, który wektor MA.

Predykat jest więc DWUSTOPNIOWY:

1. **SQL — kto jest podejrzany.** Objaw (``breakdown->'semantic'->>'reason'``)
   plus obie połowy świeżości (``stale IS false`` ORAZ bieżąca
   ``scoring_algorithm_version``). Tanio, bez sieci, bez JOIN-a.
2. **Qdrant — kto naprawdę ma wektor.**
   ``embedding_service.indexed_candidate_ids`` na zbiorze RÓŻNYCH kandydatów
   z kroku 1. To ``retrieve(with_payload=False, with_vectors=False)`` paczkami
   po 256 — zero wywołań Voyage'a, zero kosztu, i pytanie zadane jedynemu
   źródłu prawdy o wektorach, czyli samej kolekcji.

Dlaczego NIE ``candidates.embedding_id`` — kolumna kłamie w OBIE strony
----------------------------------------------------------------------
Ta kolumna była wcześniej całym predykatem i oba jej kłamstwa zostały wykazane
wykonaniem, nie rozumowaniem:

**Kłamie na TAK → naddopasowanie i NIEZBIEŻNOŚĆ.**
``candidate_identity_quarantine`` woła ``delete_candidate_embedding`` (kasuje
punkt z Qdranta) i kolumny NIE czyści. Taki kandydat ma ``embedding_id``
i nie ma wektora, więc jego „0 punktów, brak embeddingu" jest PRAWDĄ. Stary
predykat go łapał, naprawa unieważniała, leniwe przeliczenie szło do Qdranta,
ten kandydata nie znał, wynik wychodził identyczny, ``_upsert_breakdown``
zdejmowało ``stale`` — i wiersz WRACAŁ do zbioru (zmierzone: ``matched=1`` →
po naprawie ``0`` → po przeliczeniu znowu ``1``). Każdy kolejny bieg
unieważniał go od nowa, w nieskończoność, płacąc za przeliczenia, które
niczego nie zmieniają.

**Kłamie na NIE → niedopasowanie trwałe.** ``scripts/reembed_collections.py``
upsertuje wektor do Qdranta i kolumny NIE pisze; jego własny docstring podaje
rozjazd z produkcji: kolumna 45 317, Qdrant 47 921 punktów, czyli ~2 604
kandydatów MA wektor przy pustej kolumnie. Ich zatrute wiersze były liczone
jako „uczciwe zera" i pomijane — a są świeże pod bieżącą wersją, więc nic ich
nigdy nie przeliczy. Zostawały zaniżone o 60 ze 100 punktów na stałe. To jest
dokładnie ta klasa, dla której to narzędzie powstało.

Qdrant milczy ⇒ PRZERYWAMY
--------------------------
``indexed_candidate_ids`` zwraca ``None`` (a nie pusty zbiór), gdy Qdrant nie
odpowiada — właśnie po to, żeby awaria nie udawała „nikt nie jest
zaindeksowany". Bierzemy to dosłownie: oba endpointy odpowiadają wtedy 503
i NIE ruszają ani jednego wiersza. Potraktowanie ``None`` jak pustki dałoby
przy podglądzie fałszywe „czysto", a przy naprawie — masowe unieważnienie
całego cache'u pod hasłem „nikt nie ma wektora".

Uczciwe zera przypinają okno skanu ⇒ KURSOR
------------------------------------------
Krok 2 wymaga materializacji kluczy, więc skan ma sufit (``scan_limit``).
Bez kursora ten sufit był PUŁAPKĄ, a nie tylko ograniczeniem: naprawiony wiersz
wypada z predykatu (dostaje ``stale=True``), ale uczciwe zero NIE WYPADA NIGDY —
nic go nie unieważnia, bo nie ma czego naprawiać. Prefiks uczciwych zer okupował
więc okno na stałe i każdy kolejny bieg czytał dokładnie ten sam zbiór.
Zmierzone: trzy biegi z rzędu po dwóch uczciwych zerach i jednym zatrutym
wierszu za sufitem dały ``matched=0, updated=0, remaining=0`` — czyli odpowiedź
czytającą się jako „gotowe", przy zatrutym wierszu nietkniętym i nieosiągalnym
NA ZAWSZE. To jest ta sama klasa cichego zaniżenia, z której powstało #32.

Dlatego skan przyjmuje ``after_candidate_id`` i zwraca
``next_after_candidate_id``: operator przepisuje jedno w drugie, aż dostanie
``null``. Kursor jest ściśle rosnący, więc pętla operatora zawsze się kończy.
Wznawianie idzie po ``candidate_id``, a nie po pełnym kluczu, więc kandydat
URWANY przez sufit jest z partii WYPUSZCZANY w całości i oglądany od nowa
w następnym oknie — inaczej jego wiersze zza sufitu wypadłyby z zasięgu
narzędzia tak samo cicho.

Kontrakt
--------
- ``GET  /api/admin/match-score-repair/preview`` — wyłącznie odczyt.
- ``POST /api/admin/match-score-repair/repair``  — ``dry_run=true`` DOMYŚLNIE.
- Podgląd i naprawa liczą TEN SAM zbiór tą samą funkcją; rozdzielenie ich
  dałoby narzędzie pokazujące jeden zbiór, a ruszające inny.
- Naprawa ustawia ``stale=True``, **nie kasuje wiersza**: skasowany traci
  ``scored_at`` i historię, unieważniony zachowuje jedno i drugie, a
  przeliczenie i tak jest leniwe (przy najbliższym odczycie).
- Zero PII na wyjściu — same identyfikatory i liczby.
- Kryterium stopu ma DWIE połowy i obie są konieczne:
  ``remaining == 0`` (w tym oknie nie ma już czego naprawiać) ORAZ
  ``next_after_candidate_id == null`` (okno sięgnęło końca tabeli). Samo
  ``remaining == 0`` znaczy tylko tyle, że okno jest domknięte — dopóki kursor
  nie jest pusty, dalej w tabeli mogą stać zatrute wiersze.
  Po przejściu na sygnał z Qdranta naprawa ZBIEGA — kandydat, którego kolekcja
  nie zna, nie wchodzi do zbioru, więc nie ma czego wskrzeszać.
"""

from __future__ import annotations

import logging
import math
from typing import Any, NamedTuple, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, and_, func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.models.match_score import CandidateJobMatchScore
from app.services.embedding_service import indexed_candidate_ids
from app.services.match_score_cache import fresh_score_conditions
from app.services.scoring_service import scoring_algorithm_version

logger = logging.getLogger(__name__)
router = APIRouter()

# Powód zapisany w warstwie semantycznej, gdy podobieństwo było ``None``
# (``scoring_service.score_semantic``). LITERAŁ, nie odwołanie do
# ``score_semantic(None).reason``: pracujemy na wierszach ZAPISANYCH
# HISTORYCZNIE, a te niosą tekst z chwili zapisu. Gdyby kod zmienił napis,
# odwołanie przestałoby pasować do danych w bazie i narzędzie po cichu
# przestałoby cokolwiek znajdować — zero trafień wygląda jak „czysto".
# Test kontraktowy pilnuje, że dziś oba są równe; rozjazd ma być decyzją.
NO_EMBEDDING_REASON = "brak embeddingu"

# Drugi powód zerowej warstwy semantycznej, wprowadzony w 09.2026 (#414):
# „nie zmierzyliśmy" zamiast „zmierzono i nie ma wektora". Narzędzie musi znać
# OBA, i to na zawsze: wiersze zapisane przed tą zmianą niosą wyłącznie ten
# pierwszy, a wiersze zapisane po niej — ten, który pasuje do przyczyny.
# Szukanie tylko jednego z nich znajduje połowę zatrutych wierszy i raportuje
# to jako komplet, czyli dokładnie ten tryb cichej porażki, przed którym
# ostrzega komentarz wyżej.
SEMANTIC_UNAVAILABLE_REASON = "pomiar niedostępny"

# Oba powody razem — jedyna lista, po której wolno filtrować „podejrzane".
ZEROED_SEMANTIC_REASONS = (NO_EMBEDDING_REASON, SEMANTIC_UNAVAILABLE_REASON)

# Domyślny sufit jednego biegu. Tabela ma na produkcji rzędy wielkości setek
# tysięcy wierszy, a UPDATE bez limitu trzyma blokady przez cały czas trwania —
# na gorącej tabeli czytanej przez każdy kanban to jest widoczne dla ludzi.
DEFAULT_REPAIR_LIMIT = 1_000
MAX_REPAIR_LIMIT = 50_000

# Sufit SKANU podejrzanych. Krok 2 predykatu wymaga materializacji kluczy
# (Qdrant nie jest tabelą, więc nie da się go dołączyć JOIN-em), a materializacja
# bez sufitu na tabeli produkcyjnej to zaproszenie do wciągnięcia setek tysięcy
# krotek do pamięci procesu API. Gdy sufit przytnie zbiór, odpowiedź niesie
# ``scan_truncated=true`` — bez tego liczby czytałoby się jako komplet, a są
# wtedy DOLNYM oszacowaniem.
DEFAULT_SCAN_LIMIT = 50_000
MAX_SCAN_LIMIT = 200_000

# Ile kluczy wchodzi do JEDNEGO ``UPDATE``. To nie jest kosmetyka wydajnościowa:
# lista krotek w ``IN`` jest przez Postgresa parsowana rekurencyjnie, więc długa
# wywraca całe zapytanie na ``StatementTooComplexError: stack depth limit
# exceeded`` — zmierzone na tej bazie między 6 000 a 8 000 krotkami (3 parametry
# na krotkę), a próg zależy od ``max_stack_depth`` serwera, więc na produkcji
# może być inny. ``limit`` sięga 50 000 i tyle właśnie woła testowy ``_drain``,
# więc bez podziału pierwszy prawdziwy przebieg kończyłby się 500-tką PO
# wykonaniu pełnego SELECT-a — i bez ani jednego naprawionego wiersza, bo
# transakcja się wycofuje. Awaria wyglądałaby przy tym jak awaria bazy, nie jak
# błąd narzędzia.
_UPDATE_CHUNK = 2_000


def _semantic_reason():
    """Wyrażenie SQL: ``breakdown -> 'semantic' ->> 'reason'``.

    Klucz ``semantic`` jest na NAJWYŻSZYM poziomie dokumentu (patrz
    ``ScoreBreakdown.as_dict``), nie w zagnieżdżonych „layers".
    """
    return CandidateJobMatchScore.breakdown["semantic"]["reason"].astext


def _looks_semantically_empty() -> list:
    """Warstwa semantyczna zeruje wynik i tłumaczy to brakiem POMIARU.

    Oba powody naraz (`ZEROED_SEMANTIC_REASONS`) — patrz komentarz przy nich.
    """
    return [_semantic_reason().in_(ZEROED_SEMANTIC_REASONS)]


# Kolumny, którymi ``fresh_score_conditions`` ZAWĘŻA zapytanie do jednej oferty
# i jednego profilu. Nie są częścią reguły świeżości — są zakresem wywołującego.
_SCOPE_COLUMNS = frozenset({"job_id", "profile_id", "candidate_id"})
_SCOPE_SENTINEL = -1  # nigdy nie istnieje; i tak odrzucamy te warunki


def _is_scope_condition(condition) -> bool:
    """Czy ten warunek zawęża zakres, zamiast orzekać o świeżości?"""
    left = getattr(condition, "left", None)
    return getattr(left, "key", None) in _SCOPE_COLUMNS


def _would_be_served_as_fresh() -> list:
    """Ten wiersz przejdzie przez ``fresh_score_conditions`` — czyli nic go nie
    przeliczy samo z siebie.

    Reguła świeżości NIE jest tu przepisana, tylko wzięta z jedynego miejsca,
    które ją definiuje. Przepisanie jej byłoby dokładnie tym błędem, z którego
    powstało #32: kopia była wierna w dniu powstania i rozjechała się po bumpie
    wag, a objawem nie był wyjątek, tylko inna liczba.

    ``fresh_score_conditions`` wymaga zakresu (oferta + profil), bo służy
    zapytaniom o konkretną ofertę; naprawa idzie po CAŁEJ tabeli. Bierzemy ją
    więc dla wartości-wartownika i odrzucamy warunki zakresu, zostawiając same
    połowy świeżości — cokolwiek się na nie w przyszłości złoży.

    Obie połowy są tu konieczne. Wiersz ``stale=True`` naprawi się sam przy
    najbliższym odczycie, a wiersz o STAREJ wersji algorytmu wypadnie z cache
    przez predykat wersji — oba są poza zakresem tej naprawy i unieważnianie
    ich byłoby czystym kosztem.
    """
    conditions = fresh_score_conditions(
        job_id=_SCOPE_SENTINEL, profile_id=_SCOPE_SENTINEL
    )
    return [c for c in conditions if not _is_scope_condition(c)]


def suspect_row_conditions() -> list:
    """KROK 1 predykatu: objaw + świeżość. Cała część rozstrzygalna w SQL-u.

    Jedna definicja dla trzech miejsc: skanu podglądu, skanu naprawy oraz
    powtórzenia predykatu w ``WHERE`` samego ``UPDATE``. To ostatnie nie jest
    nadmiarowe — między skanem a zapisem wiersz mógł zostać przeliczony na
    zdrowy albo już unieważniony zwykłą edycją kandydata; bez powtórki
    ``updated`` liczyłby wiersze, które w chwili zapisu nie były już zatrute,
    i fundował im niepotrzebne przeliczenie.

    Tu NIE MA warunku o wektorze. ``candidates.embedding_id`` wypadł
    z predykatu całkowicie (patrz docstring modułu) — o wektor pyta się Qdranta
    w kroku 2, bo tylko on zna prawdę.
    """
    return [*_looks_semantically_empty(), *_would_be_served_as_fresh()]


def _returned_after_repair_conditions() -> list:
    """Wiersz BYŁ już kiedyś unieważniony i wrócił po przeliczeniu.

    ``invalidated_at`` stempluje każde unieważnienie (nasze i każde
    ``mark_stale_*``), a ``_upsert_breakdown`` przy przeliczeniu go NIE czyści —
    więc ``scored_at > invalidated_at`` znaczy „ten wiersz policzono PO
    unieważnieniu, a objaw został".

    Po przejściu na sygnał z Qdranta ten licznik przestał być kryterium stopu
    (naprawa zbiega, bo kandydat bez wektora w ogóle nie wchodzi do zbioru),
    ale zostaje jako sygnał diagnostyczny: kandydat, który MA wektor, a mimo to
    po przeliczeniu znów raportuje „brak embeddingu", opisuje awarię gdzie
    indziej — najpewniej niedostępny Voyage albo pustą odpowiedź wyszukiwania.
    Filtrem być nie może: część wierszy naprawdę zatrutych niesie
    ``invalidated_at`` ze zwykłej edycji kandydata sprzed zatrucia
    (``mark_stale_for_candidate`` woła każdy upload CV i każdy sync z Traffita).
    """
    return [
        CandidateJobMatchScore.invalidated_at.isnot(None),
        CandidateJobMatchScore.scored_at > CandidateJobMatchScore.invalidated_at,
    ]


class _Suspect(NamedTuple):
    """Jeden podejrzany wiersz — tyle, ile trzeba do werdyktu i do raportu."""

    candidate_id: int
    job_id: int
    profile_id: int
    total_score: float
    scored_at: Any
    returned_after_repair: bool


class _Scan(NamedTuple):
    """Wynik dwustopniowego predykatu dla jednego okna."""

    poisoned: list[_Suspect]
    honest_zeros: int
    truncated: bool
    # ``None`` = okno sięgnęło końca tabeli. Wartość = wznów od tego miejsca
    # (patrz sekcja „Uczciwe zera…" w docstringu modułu).
    next_after_candidate_id: Optional[int]


def _suspect_query(scan_limit: int, after_candidate_id: int) -> Select:
    """Skan kroku 1, w deterministycznej kolejności, od kursora w górę.

    Kolejność po pełnym kluczu daje dwóm biegom po tych samych danych ten sam
    prefiks — dzięki temu ``limit`` w naprawie jest wznawialny w przewidywalny
    sposób, a test może sprawdzić, który wiersz wszedł do partii jako pierwszy.

    Pobieramy ``scan_limit + 1`` wierszy, żeby odróżnić „tyle jest" od „tyle
    zmieściło się w suficie". Bez tego rozróżnienia obcięty zbiór raportowałby
    się jako komplet i operator uznałby bazę za czystą.
    """
    return (
        select(
            CandidateJobMatchScore.candidate_id,
            CandidateJobMatchScore.job_id,
            CandidateJobMatchScore.profile_id,
            CandidateJobMatchScore.total_score,
            CandidateJobMatchScore.scored_at,
            and_(*_returned_after_repair_conditions()).label("returned"),
        )
        .where(
            CandidateJobMatchScore.candidate_id > after_candidate_id,
            *suspect_row_conditions(),
        )
        .order_by(
            CandidateJobMatchScore.candidate_id,
            CandidateJobMatchScore.job_id,
            CandidateJobMatchScore.profile_id,
        )
        .limit(scan_limit + 1)
    )


def _qdrant_unavailable() -> HTTPException:
    """503, nie pusty wynik.

    ``indexed_candidate_ids`` zwraca ``None`` wyłącznie wtedy, gdy Qdrant nie
    odpowiedział. Zamiana tego na pusty zbiór dałaby przy podglądzie fałszywe
    „czysto" (zero trafień), a przy naprawie — masowe unieważnienie cache'u pod
    hasłem „nikt nie ma wektora". Awaria musi wyglądać jak awaria.
    """
    return HTTPException(
        status_code=503,
        detail=(
            "Qdrant nie odpowiada — bez odpowiedzi z kolekcji nie da się "
            "odróżnić zatrutego wiersza od prawdziwego zera. Bieg przerwany, "
            "żaden wiersz nie został ruszony. Spróbuj ponownie, gdy "
            "/api/health zaraportuje qdrant jako zdrowy."
        ),
    )


async def _scan(db: AsyncSession, scan_limit: int, after_candidate_id: int) -> _Scan:
    """Pełny, dwustopniowy predykat: SQL, potem Qdrant.

    Qdrant pytany jest RAZ na bieg i o zbiór RÓŻNYCH kandydatów — jeden
    kandydat ma zwykle wiele wierszy cache (po jednym na ofertę), więc pytanie
    per wiersz mnożyłoby ruch przez współczynnik, który na produkcji sięga
    dziesiątek. Samo ``indexed_candidate_ids`` dzieli ten zbiór na paczki po
    256 identyfikatorów.
    """
    fetched = (await db.execute(_suspect_query(scan_limit, after_candidate_id))).all()
    truncated = len(fetched) > scan_limit
    rows = fetched[:scan_limit]

    next_after: Optional[int] = None
    if truncated:
        boundary = rows[-1][0]
        # Wiersz zza sufitu mówi, czy ostatni kandydat w oknie jest URWANY.
        # Bez tego rozróżnienia trzeba by zakładać najgorsze przy każdym oknie.
        candidate_is_split = fetched[scan_limit][0] == boundary
        if not candidate_is_split:
            # Okno kończy się dokładnie na granicy kandydata — komplet jego
            # wierszy jest w partii, więc kursor może stanąć ZA nim.
            next_after = boundary
        else:
            rest = [r for r in rows if r[0] != boundary]
            if rest:
                # Kandydata urwanego wypuszczamy z partii W CAŁOŚCI i wznawiamy
                # OD niego (``> boundary - 1``). Kursor idzie po ``candidate_id``,
                # więc przesunięcie go ZA urwanego zostawiłoby jego wiersze zza
                # sufitu poza zasięgiem narzędzia na zawsze — bez objawu, czyli
                # dokładnie tak, jak zaczęło się #32.
                rows = rest
                next_after = boundary - 1
            else:
                # Zwyrodniały przypadek: JEDEN kandydat ma więcej podejrzanych
                # wierszy niż cały sufit skanu. Wypuszczenie go zostawiłoby
                # pustą partię i kursor w miejscu, czyli pętlę operatora bez
                # końca. Bierzemy więc, co widać, i przechodzimy ZA niego —
                # resztę jego wierszy złapie bieg z wyższym ``scan_limit``.
                # Przy domyślnym suficie wymaga to kandydata z 50 000 wierszy
                # cache, czyli tyloma ofertami; realnie osiągalne tylko przy
                # ręcznie zaniżonym ``scan_limit``.
                next_after = boundary

    suspects = [
        _Suspect(
            candidate_id=r[0],
            job_id=r[1],
            profile_id=r[2],
            total_score=float(r[3]) if r[3] is not None else 0.0,
            scored_at=r[4],
            returned_after_repair=bool(r[5]),
        )
        for r in rows
    ]

    # ``sorted(set(...))`` — bez duplikatów (ten sam kandydat w wielu ofertach)
    # i w stabilnej kolejności, żeby paczkowanie było powtarzalne.
    candidate_ids = sorted({s.candidate_id for s in suspects})
    indexed = await indexed_candidate_ids(candidate_ids)
    if indexed is None:
        raise _qdrant_unavailable()

    poisoned = [s for s in suspects if s.candidate_id in indexed]
    return _Scan(
        poisoned=poisoned,
        honest_zeros=len(suspects) - len(poisoned),
        truncated=truncated,
        next_after_candidate_id=next_after,
    )


def _percentile(sorted_values: list[float], q: float) -> Optional[float]:
    """Percentyl z interpolacją liniową — to samo, co robi ``percentile_cont``.

    Rachunek przeniósł się z SQL-a do Pythona (bo zbiór rozstrzyga dopiero
    Qdrant), a liczby w podglądzie nie mogą przy tej przeprowadzce zmienić
    znaczenia — operator porównuje je między biegami.
    """
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def _round(value: Optional[float]) -> Optional[float]:
    return round(float(value), 1) if value is not None else None


@router.get("/match-score-repair/preview")
async def preview_poisoned_scores(
    _admin: AdminUser,
    sample_size: int = Query(
        default=10,
        ge=0,
        le=100,
        description="Ile przykładowych wierszy pokazać (same identyfikatory "
        "i liczby, zero PII).",
    ),
    scan_limit: int = Query(
        default=DEFAULT_SCAN_LIMIT,
        ge=1,
        le=MAX_SCAN_LIMIT,
        description="Sufit skanu podejrzanych. Po przycięciu odpowiedź niesie "
        "`scan_truncated=true`, a liczby są dolnym oszacowaniem.",
    ),
    after_candidate_id: int = Query(
        default=0,
        ge=0,
        description="Wznów skan za tym `candidate_id`. Przepisuj tu wartość "
        "`next_after_candidate_id` z poprzedniej odpowiedzi, aż wróci `null`.",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Ile wierszy naprawa ruszy, kogo dotyczą i jak bardzo są zaniżone.

    Wyłącznie odczyt (w tym odczyt z Qdranta — podgląd MUSI iść tą samą
    ścieżką co naprawa, inaczej pokazywałby inny zbiór, niż ruszy przycisk).
    Bez tego widoku nikt nie kliknie „napraw" świadomie: ``stale=True`` na
    gorącej tabeli oznacza falę przeliczeń płatnych wywołaniami Voyage'a, więc
    rozmiar zbioru musi być znany PRZED decyzją.
    """
    scan = await _scan(db, scan_limit, after_candidate_id)
    rows = scan.poisoned

    scores = sorted(s.total_score for s in rows)
    histogram: dict[int, int] = {}
    for value in scores:
        histogram[int(math.floor(value / 10.0) * 10)] = (
            histogram.get(int(math.floor(value / 10.0) * 10), 0) + 1
        )

    sample = [
        {
            "candidate_id": s.candidate_id,
            "job_id": s.job_id,
            "profile_id": s.profile_id,
            "total_score": round(s.total_score, 1),
            "scored_at": s.scored_at.isoformat() if s.scored_at else None,
        }
        for s in rows[:sample_size]
    ]

    return {
        "algorithm_version": scoring_algorithm_version(),
        "matched": len(rows),
        # Wiersze z tym samym objawem, których naprawa NIE ruszy, bo Qdrant
        # tych kandydatów nie zna — ich zero jest prawdziwe. Kontrola zdrowia
        # predykatu: sam licznik trafień nie mówi, czy cokolwiek odróżnia.
        "skipped_honest_zeros": scan.honest_zeros,
        # Ile z ``matched`` już kiedyś unieważniono, a objaw wrócił mimo
        # obecnego wektora — sygnał awarii po stronie liczenia podobieństwa
        # (np. milczący Voyage), nie kryterium stopu.
        "already_attempted": sum(1 for s in rows if s.returned_after_repair),
        "distinct_candidates": len({s.candidate_id for s in rows}),
        "distinct_jobs": len({s.job_id for s in rows}),
        "scan_limit": scan_limit,
        "scan_truncated": scan.truncated,
        # JEDNO pole zamiast reguły do złożenia z dwóch. Kryterium stopu brzmi
        # „nie ma już czego naprawiać W CAŁEJ TABELI", a wynika z KONIUNKCJI
        # (okno domknięte ORAZ kursor sięgnął końca). Operator czytający samo
        # ``remaining``/``matched`` przerywał nad zatrutą resztą tabeli —
        # udokumentowanie tej reguły nie wystarczyło, bo dokumentacja nie jest
        # w odpowiedzi, a odpowiedź jest.
        "done": len(rows) == 0 and scan.next_after_candidate_id is None,
        "after_candidate_id": after_candidate_id,
        # ``null`` = okno sięgnęło końca tabeli. Wartość = jeszcze nie koniec;
        # przepisz ją do `after_candidate_id` w kolejnym wywołaniu. Bez tego
        # pola prefiks uczciwych zer (które NIGDY nie wypadają z predykatu)
        # okupowałby okno w nieskończoność, a `matched: 0` czytałoby się jak
        # „czysto" nad zatrutą resztą tabeli.
        "next_after_candidate_id": scan.next_after_candidate_id,
        "total_score": {
            "min": _round(scores[0] if scores else None),
            "p50": _round(_percentile(scores, 0.5)),
            "p90": _round(_percentile(scores, 0.9)),
            "max": _round(scores[-1] if scores else None),
            "avg": _round(sum(scores) / len(scores) if scores else None),
        },
        # Rozkład, nie sama średnia: średnia nie pokazuje, czy zaniżenie dotyka
        # kandydatów, którzy i tak byli słabi, czy takich, którzy bez 60 punktów
        # semantyki wypadli z widoku rekrutera.
        "total_score_histogram": [
            {"from": b, "to": b + 10, "rows": n} for b, n in sorted(histogram.items())
        ],
        "sample": sample,
    }


@router.post("/match-score-repair/repair")
async def repair_poisoned_scores(
    _admin: AdminUser,
    limit: int = Query(
        default=DEFAULT_REPAIR_LIMIT,
        ge=1,
        le=MAX_REPAIR_LIMIT,
        description="Sufit wierszy w tym biegu. Naprawa jest wznawialna — "
        "wołaj do skutku, aż `remaining` spadnie do zera.",
    ),
    scan_limit: int = Query(
        default=DEFAULT_SCAN_LIMIT,
        ge=1,
        le=MAX_SCAN_LIMIT,
        description="Sufit skanu podejrzanych (patrz podgląd).",
    ),
    after_candidate_id: int = Query(
        default=0,
        ge=0,
        description="Wznów skan za tym `candidate_id`. Przesuwaj kursor "
        "dopiero, gdy `remaining` spadnie do zera w bieżącym oknie.",
    ),
    dry_run: bool = Query(
        default=True,
        description="Domyślnie TYLKO pomiar (zero zapisów). Zapis wymaga "
        "jawnego dry_run=false.",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Unieważnia zatrute wiersze cache (``stale=True``), partiami.

    NIE kasuje wierszy: skasowany traci ``scored_at`` i ślad po sobie,
    unieważniony zachowuje jedno i drugie, a przeliczenie i tak jest leniwe —
    zrobi je pierwszy odczyt, który ten wiersz obejrzy.

    Wznawianie ma DWA poziomy i mylenie ich kosztuje dane:

    1. **W OKNIE — bez kursora.** Naprawiony wiersz ma ``stale=True``, więc
       WYPADA z predykatu; kolejne wywołanie z tym samym ``after_candidate_id``
       bierze następną partię. Wołaj do skutku, aż ``remaining`` spadnie do zera.
    2. **MIĘDZY OKNAMI — kursorem.** Dopiero wtedy przepisz
       ``next_after_candidate_id`` do ``after_candidate_id``. Kolejność jest
       istotna: przesunięcie kursora przy ``remaining > 0`` zostawia za sobą
       niedokończone okno, a nic już do niego nie wróci.

    Ponieważ do zbioru wchodzą wyłącznie kandydaci, których Qdrant ZNA,
    przeliczenie ma czym zastąpić zero — dlatego naprawa ZBIEGA, inaczej niż
    w wersji opartej na ``candidates.embedding_id``, gdzie wiersze wracały
    w nieskończoność.
    """
    scan = await _scan(db, scan_limit, after_candidate_id)
    matched = len(scan.poisoned)

    if dry_run:
        logger.info(
            "[match-score-repair] dry_run: matched=%s would_update=%s version=%s",
            matched,
            min(matched, limit),
            scoring_algorithm_version(),
        )
        return {
            "status": "dry_run",
            "algorithm_version": scoring_algorithm_version(),
            "matched": matched,
            "would_update": min(matched, limit),
            "updated": 0,
            "remaining": matched,
            # Patrz komentarz przy ``done`` w podglądzie: koniunkcja, nie
            # ``remaining == 0``. Dry-run nic nie zapisuje, więc ``done`` mówi
            # tu „nie byłoby czego naprawiać w całej tabeli".
            "done": matched == 0 and scan.next_after_candidate_id is None,
            "limit": limit,
            "scan_limit": scan_limit,
            "scan_truncated": scan.truncated,
            "after_candidate_id": after_candidate_id,
            "next_after_candidate_id": scan.next_after_candidate_id,
        }

    keys = [(s.candidate_id, s.job_id, s.profile_id) for s in scan.poisoned[:limit]]

    # Zapis idzie PARTIAMI po ``_UPDATE_CHUNK`` kluczy — patrz komentarz przy
    # tej stałej: pojedynczy ``IN`` na kilku tysiącach krotek wywraca Postgresa
    # na głębokości stosu parsera, a nie na czymkolwiek związanym z danymi.
    # Partie idą w tej samej, deterministycznej kolejności co skan, więc
    # wiersze są blokowane w stałym porządku (mniej okazji do zakleszczenia
    # z równoległym ``mark_stale_*``).
    updated = 0
    for start in range(0, len(keys), _UPDATE_CHUNK):
        chunk = keys[start : start + _UPDATE_CHUNK]
        res = await db.execute(
            update(CandidateJobMatchScore)
            .where(
                tuple_(
                    CandidateJobMatchScore.candidate_id,
                    CandidateJobMatchScore.job_id,
                    CandidateJobMatchScore.profile_id,
                ).in_(chunk),
                # Predykat kroku 1 POWTÓRZONY w chwili zapisu. Kroku 2 powtórzyć
                # się nie da (Qdrant nie jest tabelą), ale on i tak nie zmienia
                # się w skali sekund — a objaw i świeżość owszem: między skanem
                # a zapisem wiersz mógł zostać przeliczony na zdrowy.
                *suspect_row_conditions(),
            )
            .values(
                stale=True,
                # Ta sama pieczęć co w ``mark_stale_*``: bez niej przeliczenie,
                # które WYSTARTOWAŁO przed naprawą, mogłoby przy zapisie
                # wyczyścić ``stale`` i wskrzesić zatruty wiersz (fenca CAS
                # w ``_upsert_breakdown``).
                invalidated_at=func.now(),
            )
        )
        updated += res.rowcount or 0
    if keys:
        await db.commit()

    # Rejestru unieważnień (``match_score_invalidations``) świadomie NIE ruszamy:
    # on jest dla przeliczeń, które NIE ZNAJDUJĄ wiersza. Tutaj wiersz istnieje,
    # więc pieczęć na nim wystarcza, a wpis do rejestru unieważniałby też
    # niezwiązane pary (candidate, *) liczone równolegle.
    #
    # ``remaining`` liczymy ODEJMOWANIEM, a nie drugim skanem: drugi skan
    # oznaczałby drugie pytanie do Qdranta o tych samych kandydatów w jednym
    # biegu — ten sam ruch sieciowy po to, żeby usłyszeć to samo.
    remaining = matched - updated
    logger.info(
        "[match-score-repair] matched=%s updated=%s remaining=%s version=%s",
        matched,
        updated,
        remaining,
        scoring_algorithm_version(),
    )
    return {
        "status": "repaired",
        "algorithm_version": scoring_algorithm_version(),
        "matched": matched,
        "updated": updated,
        "remaining": remaining,
        # Jedyne uczciwe kryterium stopu: okno domknięte ORAZ kursor u końca
        # tabeli. Dopóki ``done`` jest ``false``, wołaj dalej.
        "done": remaining == 0 and scan.next_after_candidate_id is None,
        "limit": limit,
        "scan_limit": scan_limit,
        "scan_truncated": scan.truncated,
        "after_candidate_id": after_candidate_id,
        # Przesuwaj kursor DOPIERO przy ``remaining == 0`` — patrz docstring.
        "next_after_candidate_id": scan.next_after_candidate_id,
    }
