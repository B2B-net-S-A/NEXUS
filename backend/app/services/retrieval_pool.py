"""Fasada puli kandydatów — jedno wejście, trzy strategie retrievalu.

Silnik hybrydowy (BM25 + wektory + fuzja RRF + reranker Voyage) istnieje w tym
repo od dawna, ale obsługiwał wyłącznie opcjonalny tryb ręcznej wyszukiwarki.
Główny ruch — rekomendacje, Talent Radar, propozycje, harness ewaluacyjny —
pobierał pulę po samych wektorach. Ta fasada pozwala przełączyć CAŁY ten ruch
jedną flagą (`HYBRID_POOL_ENABLED`, domyślnie OFF), z tych samych powodów, dla
których pasaże mają jeden flip: częściowe przełączenie zostawia powierzchnie
liczące na różnych zasadach.

Trzecia strategia (0278, `STRUCTURED_POOL_ENABLED`, domyślnie OFF) wybiera
członkostwo SQL-em zamiast wektorem/hybrydą — AND-of-OR po jawnych rodzinach
umiejętności must-have (patrz `_structured_pool`). Sprawdzana JAKO PIERWSZA
w `retrieve_candidate_pool`: gdy nie ma o co pytać (brak must-have) albo pada,
spada dokładnie na tę samą hybrydę/wektor, jakby jej wcale nie było.

DECYZJA, KTÓRA NIE JEST OCZYWISTA — hybryda wybiera CZŁONKOSTWO, nie wynik.
Wyniki z fuzji RRF (~1/60 na pozycję) i z rerankera żyją na INNYCH skalach niż
kosinus, a `similarity_map` konsumowana przez warstwę semantyczną scoringu jest
kalibrowana pod kosinus (gamma, frakcja neutralna). Wpuszczenie tam wyników RRF
rozstroiłoby kalibrację i zatruło cache score'ów. Dlatego przy włączonej
hybrydzie: (1) hybryda decyduje, KTO wchodzi do puli, (2) podobieństwo dla
wybranych liczone jest OSOBNO przez `similarity_for_candidate_ids` — czyli tą
samą, pasażo-świadomą miarą co dotąd. Skala semantyczna nie zmienia się wcale,
więc flaga hybrydy CELOWO nie wchodzi do `_SCORING_CACHE_INPUTS`: istniejące
wiersze cache pozostają poprawne per kandydat, zmienia się tylko to, których
kandydatów w ogóle oglądamy. Test zamraża tę decyzję.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

# Wołane przez ATRYBUT modułu, nie przez nazwę związaną przy imporcie —
# dziesiątki testów monkeypatchują `embedding_service.search_candidates_semantic`
# w miejscu kanonicznym i podmiana MUSI obejmować też tę fasadę. Nazwa związana
# lokalnie byłaby niewidzialna dla tych patchy (dokładnie tak padł
# test_compute_not_degraded_when_semantic_has_hits, zanim to naprawiono).
from app.services import embedding_service as _embedding

logger = logging.getLogger(__name__)


def hybrid_pool_enabled() -> bool:
    return bool(getattr(settings, "HYBRID_POOL_ENABLED", False))


def multi_query_enabled() -> bool:
    return bool(getattr(settings, "MULTI_QUERY_RETRIEVAL_ENABLED", False))


def structured_pool_enabled() -> bool:
    return bool(getattr(settings, "STRUCTURED_POOL_ENABLED", False))


async def _structured_pool(
    db: AsyncSession,
    query_text: str,
    must_groups: list[list[str]] | None,
    *,
    top_k: int,
    raise_on_error: bool,
) -> list[dict] | None:
    """SQL-first (0278): Postgres wybiera CZŁONKOSTWO po must-have, kosinus
    liczony jak zawsze. `None` = „ta strategia nie ma o co pytać, spadnij na
    hybrydę/wektor" — trzy niezależne, nieszkodliwe powody:

      1. brak jawnych rodzin must-have (`must_groups` puste albo `None`, albo
         wszystkie rodziny zwijają się do pustego stringa — patrz
         `hybrid_search.bm25_must_groups`);
      2. noga SQL padła i `raise_on_error=False` (awaria NOWEJ strategii nie
         może degradować puli poniżej stanu sprzed flagi — ten sam kontrakt
         co przy hybrydzie);
      3. trafień jest mniej niż `STRUCTURED_POOL_MIN_MEMBERS` — zbyt wąskie
         członkostwo nie jest ufane jako CAŁA pula.

    Sama STRATEGIA jest gated flagą przez wołającego
    (`retrieve_candidate_pool` — `structured_pool_enabled()` sprawdzane jako
    PIERWSZA instrukcja funkcji, przed dotknięciem `db`); ta funkcja zakłada,
    że już wie, że ma działać.

    Skala semantyczna bez zmian — jak w hybrydzie i multi-query: SQL wybiera
    CZŁONKOSTWO, `similarity_for_candidate_ids` liczy kosinus DLA WYBRANYCH,
    więc cache score'ów (kalibrowany pod kosinus) zostaje poprawny niezależnie
    od tego, która strategia wybrała pulę — dlatego flagi tej strategii są
    POZA `_SCORING_CACHE_INPUTS` (patrz `config.py`).
    """
    from app.services import hybrid_search

    groups = hybrid_search.bm25_must_groups(must_groups or [])
    if not groups:
        return None

    try:
        # Wołane przez ATRYBUT modułu (`hybrid_search.bm25_must_candidates`),
        # nie przez nazwę związaną przy imporcie — ten sam powód co `_embedding`
        # na górze pliku: testy monkeypatchują `hybrid_search.bm25_must_candidates`
        # w miejscu kanonicznym, a nazwa związana lokalnie byłaby dla nich
        # niewidzialna.
        ids = await hybrid_search.bm25_must_candidates(
            db, groups, limit=settings.STRUCTURED_POOL_LIMIT
        )
    except Exception:
        if raise_on_error:
            raise
        logger.exception(
            "[retrieval-pool] structured: noga SQL padła — spadek na hybrydę/wektor"
        )
        return None

    if len(ids) < settings.STRUCTURED_POOL_MIN_MEMBERS:
        return None

    # `similarity_for_candidate_ids` łyka błędy dostawcy wewnętrznie i zwraca
    # `{}` (patrz jej docstring) — nie ma tu więc czego łapać osobnym
    # try/except: brak wpisu per kandydat jest jedynym kształtem awarii, jaki
    # ta funkcja kiedykolwiek zwraca.
    cosine_by_id = await _embedding.similarity_for_candidate_ids(query_text, ids)

    unknown_count = 0
    scored: list[tuple[int, float, bool]] = []
    for candidate_id in ids:
        score = cosine_by_id.get(candidate_id)
        if score is None:
            unknown_count += 1
            scored.append((candidate_id, 0.0, True))
        else:
            scored.append((candidate_id, float(score), False))

    # Kosinus malejąco; `semantic_unknown` zawsze na końcu — klucz jawny
    # (`is_unknown, -score`), nie poleganie na tym, że 0.0 akurat jest niższe
    # niż każdy prawdziwy kosinus. Wśród samych `unknown` stabilne sortowanie
    # zachowuje kolejność SQL-a (`ts_rank DESC, updated_at DESC`).
    scored.sort(key=lambda row: (row[2], -row[1]))

    logger.info(
        "[retrieval-pool] structured: groups=%s members=%s unknown=%s",
        len(groups),
        len(ids),
        unknown_count,
    )

    pool: list[dict] = []
    for candidate_id, score, is_unknown in scored[:top_k]:
        row: dict = {"candidate_id": int(candidate_id), "score": score}
        if is_unknown:
            row["semantic_unknown"] = True
        pool.append(row)
    return pool


async def _multi_query_pool(
    query_text: str,
    variants: list[str],
    *,
    top_k: int,
    raise_on_error: bool,
) -> list[dict]:
    """Unia pul z zapytania głównego i wariantów — członkostwo z unii,
    podobieństwo z zapytania GŁÓWNEGO.

    Ta sama zasada co przy hybrydzie (docstring modułu): kosinusy względem
    różnych tekstów żyją na różnych skalach, a `similarity_map` konsumowana
    przez warstwę semantyczną jest kalibrowana pod jedną. Kandydat dosypany
    przez wariant dostaje więc kosinus policzony względem tekstu głównego —
    dlatego flaga NIE wchodzi do `_SCORING_CACHE_INPUTS` (zmienia się tylko
    to, KOGO oglądamy, nie jak liczymy).
    """
    primary = await _embedding.search_candidates_semantic(
        query_text, top_k=top_k, raise_on_error=raise_on_error
    )
    pool_by_id: dict[int, float] = {
        int(h["candidate_id"]): float(h["score"]) for h in primary
    }

    extra_ids: set[int] = set()
    for variant in variants:
        try:
            hits = await _embedding.search_candidates_semantic(
                variant, top_k=top_k, raise_on_error=False
            )
        except Exception:  # pragma: no cover — kontrakt raise_on_error=False
            hits = []
        for h in hits:
            cid = int(h["candidate_id"])
            if cid not in pool_by_id:
                extra_ids.add(cid)

    if extra_ids:
        try:
            cosine_by_id = await _embedding.similarity_for_candidate_ids(
                query_text, sorted(extra_ids)
            )
        except Exception:
            if raise_on_error:
                raise
            # Dosypka kosinusów padła — kandydaci z wariantów wchodzą z 0.0
            # (semantyka „brak sygnału", nie wykluczenie), jak w hybrydzie.
            logger.exception(
                "[retrieval-pool] multi-query: kosinusy dla wariantów niedostępne"
            )
            cosine_by_id = {}
        for cid in extra_ids:
            pool_by_id[cid] = float(cosine_by_id.get(cid) or 0.0)
        # Ci, dla których kosinusu NIE zmierzono — patrz `semantic_unknown`
        # w :func:`retrieve_candidate_pool`. Bez tego zero z awarii dosypki
        # jedzie do scoringu jako pełna kara w warstwie wartej 60 pkt i zostaje
        # zapisane w cache'u jako wynik świeży.
        unknown = {cid for cid in extra_ids if cosine_by_id.get(cid) is None}
    else:
        unknown = set()

    ranked = sorted(pool_by_id.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [
        {"candidate_id": cid, "score": score}
        if cid not in unknown
        else {"candidate_id": cid, "score": score, "semantic_unknown": True}
        for cid, score in ranked
    ]


async def retrieve_candidate_pool(
    db: AsyncSession,
    query_text: str,
    *,
    top_k: int,
    raise_on_error: bool = False,
    query_variants: list[str] | None = None,
    bm25_query: str | None = None,
    must_groups: list[list[str]] | None = None,
) -> list[dict]:
    """Zwróć pulę kandydatów w kształcie `[{candidate_id, score}]`.

    Kontrakt zwrotu jest ROZSZERZENIEM `search_candidates_semantic`, żeby pięć
    miejsc wywołania (rekomendacje, Talent Radar, propozycje, digest, eval) nie
    musiało wiedzieć, która strategia jest pod spodem. `score` to zawsze
    kosinus — patrz docstring modułu.

    Rozszerzenie to opcjonalny klucz `semantic_unknown: True` na wierszach, dla
    których kosinusu NIE zmierzono (padła dosypka albo kandydat nie ma wektora).
    Ich `score` wynosi 0.0, ale to jest „nie wiem", nie „zmierzono zero" —
    a warstwa semantyczna scoringu waży 60 pkt, więc pomylenie tych dwóch
    rzeczy zamienia awarię dostawcy w trwały, zapisany w cache'u wynik. Wołający,
    który pisze do `candidate_job_match_scores`, MUSI ten klucz czytać; kto tylko
    rankuje w pamięci, może go zignorować.

    `raise_on_error` obowiązuje na WSZYSTKICH trzech ścieżkach. Konsumenci
    fasady (poza harnessem ewaluacyjnym) wołają z domyślnym `False` i liczą na
    łagodną degradację — awaria dostawcy ma dawać pustą/uboższą pulę, nie 500
    na rekomendacjach. Flip żadnej flagi nie może tego kontraktu unieważnić.

    Flaga wyłączona ⇒ dosłownie dzisiejsza ścieżka, wywołanie za wywołanie.

    `query_variants` (runda 2): dodatkowe sformułowania zapytania dla unii pul
    przy `MULTI_QUERY_RETRIEVAL_ENABLED` — patrz `_multi_query_pool`. Ścieżka
    hybrydowa je ignoruje, bo dokładne tokeny wnosi jej własna noga BM25 —
    ale patrz akapit niżej: musi je najpierw DOSTAĆ.

    `bm25_query` (C12): wejście dla nogi BM25, ZAWSZE różne od `query_text`.
    `query_text` tej fasady jest dokumentem (wszystkich pięciu callerów buduje
    go `_build_job_text`), a `websearch_to_tsquery` ANDuje leksemy — dokument
    dawał więc ZERO trafień BM25 dla każdej oferty, przez cały czas istnienia
    hybrydy. Poprzednia wersja tego docstringa twierdziła, że „hybryda ma
    własną nogę BM25 na dokładne tokeny"; nie miała.

    Brak `bm25_query` ⇒ przekazujemy "" ⇒ nogi BM25 się nie pyta. To
    ŚWIADOMIE inna domyślna niż w `hybrid_candidates` (tam `None` znaczy „użyj
    query", bo tam `query` bywa prawdziwym zapytaniem rekrutera).

    `must_groups` (0278): rodziny umiejętności must-have tej oferty, gotowe
    pod AND-of-OR — patrz `hybrid_search.build_job_must_groups`. Konsumowane
    WYŁĄCZNIE przez strategię SQL-first (`STRUCTURED_POOL_ENABLED`); pozostałe
    dwie ścieżki (hybryda, wektor/multi-query) go ignorują, bo dokładne must
    wnosi już ich własna noga BM25 (`bm25_query`) / warstwa punktowa scoringu.
    """

    # Pierwsza instrukcja strategii = sprawdzenie flagi — PRZED jakimkolwiek
    # dotknięciem `db`. Harness (i test passthrough) wołają tę fasadę z flagą
    # OFF i `db=object()`; strategia SQL-first musi zostać nieodpalona w
    # całości, nie tylko „nie znaleźć nic".
    if structured_pool_enabled():
        structured = await _structured_pool(
            db,
            query_text,
            must_groups,
            top_k=top_k,
            raise_on_error=raise_on_error,
        )
        if structured is not None:
            return structured
        # `None` = strategia SQL-first nie ma o co pytać / padła bez
        # `raise_on_error` / trafień za mało — spadamy na hybrydę/wektor
        # dokładnie tak, jakby flaga była wyłączona. Patrz `_structured_pool`.

    if not hybrid_pool_enabled():
        if multi_query_enabled() and query_variants:
            return await _multi_query_pool(
                query_text,
                query_variants,
                top_k=top_k,
                raise_on_error=raise_on_error,
            )
        return await _embedding.search_candidates_semantic(
            query_text, top_k=top_k, raise_on_error=raise_on_error
        )

    from app.services.hybrid_search import hybrid_candidates

    try:
        hybrid = await hybrid_candidates(
            db,
            query_text,
            pool=top_k,
            final_top_k=top_k,
            use_rerank=None,
            bm25_query=bm25_query or "",
        )
    except Exception:
        if raise_on_error:
            raise
        # Hybryda w całości padła (np. wyjątek w warstwie BM25). Spadek na
        # ścieżkę semantyczną zamiast pustki: awaria NOWEGO silnika nie może
        # degradować puli poniżej stanu sprzed flagi. Jeśli przyczyną jest
        # dostawca embeddingów, ścieżka semantyczna sama połknie błąd (to jej
        # udokumentowana semantyka przy `raise_on_error=False`) i odda [].
        logger.exception(
            "[retrieval-pool] hybryda padła — spadek na ścieżkę semantyczną"
        )
        return await _embedding.search_candidates_semantic(
            query_text, top_k=top_k, raise_on_error=False
        )
    # Trzy stany nogi BM25 są rozróżnialne CELOWO — mają różne diagnozy:
    # `bm25=n/d` w każdym wierszu = ktoś zapomniał `bm25_query` na callsicie
    # (pula jedzie na samym wektorze, cicho); `bm25=0` w każdym wierszu =
    # terminy są, ale nie trafiają — to już pytanie o taksonomię, nie o kod.
    if hybrid.bm25_failed:
        logger.error("[retrieval-pool] noga BM25 padła — pula wyłącznie z wektora")
    logger.info(
        "[retrieval-pool] hybryda: bm25=%s dense_degraded=%s pula=%s",
        "n/d" if hybrid.bm25_hits is None else hybrid.bm25_hits,
        hybrid.degraded,
        len(hybrid.pairs),
    )
    ids = [candidate_id for candidate_id, _ in hybrid.pairs]
    if hybrid.degraded:
        # Noga wektorowa padła — ranking oparł się na samym BM25. To nadal
        # użyteczna pula (dokładne tokeny działają), więc nie zamieniamy jej na
        # pustkę; logujemy, bo krótka lista w takim oknie NIE znaczy „nikogo
        # nie ma".
        logger.warning(
            "[retrieval-pool] hybryda w degradacji (BM25-only) dla zapytania "
            "o długości %s",
            len(query_text or ""),
        )
    if not ids:
        return []

    # Kosinusy TYLKO dla wybranych — ta sama miara, którą scoring dostawał
    # dotąd (po Fali 2: unia wektora kandydata i najlepszego pasażu).
    try:
        cosine_by_id = await _embedding.similarity_for_candidate_ids(query_text, ids)
    except Exception:
        if raise_on_error:
            raise
        # Dosypka kosinusów padła PO udanym BM25 (np. Voyage w awarii). Pula
        # z zerowym sygnałem semantycznym > pusta pula: to dokładnie ta sama
        # semantyka co „kandydat bez wektora" niżej, tylko dla wszystkich naraz.
        logger.exception(
            "[retrieval-pool] kosinusy niedostępne — pula BM25-only z score=0.0"
        )
        cosine_by_id = {}

    pool: list[dict] = []
    for candidate_id in ids:
        score = cosine_by_id.get(candidate_id)
        if score is None:
            # Kandydat znaleziony przez BM25, ale bez ZMIERZONEGO kosinusu:
            # albo dosypka padła (gałąź wyżej), albo nie ma wektora w indeksie.
            # 0.0 = „brak sygnału semantycznego", a nie wykluczenie — pozostałe
            # warstwy scoringu (skills, lokalizacja) wciąż mogą go wynieść.
            #
            # `semantic_unknown` niesie tę różnicę DALEJ i jest tu jedyną rzeczą,
            # która broni cache'u score'ów. Wołający rozpoznawał degradację
            # wyłącznie po PUSTCE puli (`semantic_degraded = not candidate_ids`),
            # a ta gałąź z definicji zwraca listę niepustą — więc warstwa
            # semantyczna warta 60 pkt lądowała w `candidate_job_match_scores`
            # jako 0/60 ŚWIEŻE i przeżywała powrót dostawcy (klucz cache'u nie
            # zna zdrowia providera). To jest dokładnie M3-CACHE-01.
            pool.append(
                {
                    "candidate_id": int(candidate_id),
                    "score": 0.0,
                    "semantic_unknown": True,
                }
            )
            continue
        pool.append({"candidate_id": int(candidate_id), "score": float(score)})
    return pool
