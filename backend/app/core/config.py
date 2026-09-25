import logging
import os
import warnings
from datetime import date, datetime
from typing import List, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Nexus ATS"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Database (PostgreSQL)
    DATABASE_URL: str = "postgresql+asyncpg://nexus:nexus@localhost:5432/nexus"

    # Qdrant (vector store for semantic search)
    # UWAGA: NIE ma tu `QDRANT_API_KEY`. Żadna z 25 konstrukcji `QdrantClient()`
    # w `app/` i `scripts/` nie przekazuje `api_key`, a `qdrant-client` nie
    # podchwytuje go z env — gałka byłaby więc no-opem obiecującym operatorowi
    # uwierzytelnione połączenie do vector store, którego nie ma. Zanim wróci
    # tu jako pole, musi istnieć JEDNA fabryka klienta (kandydat:
    # `embedding_service._get_qdrant_client`), przez którą przechodzą wszystkie
    # miejsca — inaczej włączenie `service.api_key` po stronie Qdranta zwróci
    # 401 na części ścieżek, a te łapią wyjątki i renderują puste dopasowania.
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION: str = "nexus_candidates"

    # Voyage AI (embeddings)
    VOYAGE_API_KEY: str = ""
    # voyage-3 — model, którym zbudowano PRODUKCYJNE kolekcje Qdranta (decyzja
    # F16 z badania 16.09.2026: voyage-3/3.5/4/4-large/3-large statystycznie
    # nierozróżnialne na 80 ofertach, OpenAI text-embedding-3-large gorszy —
    # nie ma po co przeliczać 62 tys. wektorów). Do 16.09 kod mówił
    # `voyage-3-large`, a prod `voyage-3` — ten rozjazd wysyłał w eval
    # `full_search_measurement` na ścieżkę referencyjną. Nazwa wchodzi do klucza
    # cache scoringu; podmiana wymaga re-embedu (scripts/reembed_collections.py).
    VOYAGE_MODEL: str = "voyage-3"
    # Estimated USD per million embedding tokens (not invoice totals).
    # Public list prices verified 2026-09-09: https://docs.voyageai.com/docs/pricing
    # Env JSON replaces this map for negotiated tariffs; {} disables estimates.
    # Models absent from the map remain unpriced, never implicitly $0.
    AI_SEARCH_EMBEDDING_PRICES: dict[str, float] = {
        "voyage-3": 0.06,
        "voyage-3-large": 0.18,
    }
    # Rozmiar wektora NIE jest tu konfigurowalny — jedynym źródłem prawdy jest
    # `embedding_service.VECTOR_SIZE = 1024`, którym utworzono kolekcje Qdranta.
    # Dawne pole `EMBEDDING_DIMENSION` nie było czytane nigdzie: operator, który
    # by je zmienił, dostałby ciszę zamiast innych wektorów (a realna zmiana
    # wymaga i tak re-embeddingu całej kolekcji — `scripts/reembed_collections.py`).
    # Voyage Rerank — WYŁĄCZONY decyzją F17 z badania 16.09.2026. Na produkcji
    # był no-opem: `retrieve_candidate_pool` woła `hybrid_candidates(pool=top_k,
    # final_top_k=top_k)`, więc reranker przestawiał kolejność wewnątrz puli,
    # którą i tak sortuje `canonical_fit` (identyczne metryki dla 4 rerankerów
    # i „off"). Dosypka 500→rerank-3→200 dała R@20n +0.001 [−0.008; +0.011],
    # n.s. — koszt i opóźnienie bez zysku. Włączenie = `RERANKER_ENABLED=true`
    # w Coolify; kod ścieżki zostaje (graceful passthrough przy błędzie API).
    VOYAGE_RERANK_MODEL: str = "rerank-2.5"
    RERANKER_ENABLED: bool = False

    # ── AI matching telemetry (plan PR2) ──────────────────────────────────────
    # Append-only impression/outcome logging so weights can eventually be
    # learned from what recruiters actually saw + did, not from biased
    # placement history. OFF by default: with the flag off, every telemetry
    # write is a no-op (no rows, no hot-path cost). Kill-switch without redeploy
    # via Coolify env. Salt pseudonymises user/client ids in the analytics
    # tables; falls back to SECRET_KEY when unset so ids are never stored raw.
    AI_MATCH_TELEMETRY_ENABLED: bool = False
    AI_MATCH_TELEMETRY_SALT: str = ""
    # Dedicated pepper for low-entropy candidate/source identity fingerprints.
    # It must be stable and independent from JWT signing material: rotating
    # SECRET_KEY must not invalidate the provenance audit trail.
    CANDIDATE_IDENTITY_FINGERPRINT_KEY: str = ""

    # ── AI scoring contract v2 (plan PR4) ─────────────────────────────────────
    # OFF by default → scoring behaviour is byte-for-byte unchanged. When ON, a
    # resolved weight profile is normalised so its six layers sum to EXACTLY 100
    # (fixes the champion-budget-110 bug: the 5-weight API + a default
    # champion_fit=10 could yield a 110-point budget). The active version string
    # (scoring_service.scoring_algorithm_version()) derives from this flag, so
    # flipping it auto-invalidates the match-score cache — no manual sweep.
    AI_SCORING_CONTRACT_V2: bool = False
    # Profil CV v7: dopasowany must/nice liczy się w pełni, gdy CV pokazuje użycie
    # w ostatnich 3 latach (albo nie podaje dat); 3–6 lat temu = 0,75; dawniej = 0,5.
    # Profile bez osi technologii mają wagi 1,0, więc ich wyniki się nie zmieniają.
    # WYŁĄCZONE do czasu `scripts/eval_matching.py --scorer canonical` przed/po.
    AI_SCORING_SKILL_RECENCY: bool = False

    # ── AI indexing outbox (plan PR5) ─────────────────────────────────────────
    # Durable "source change → reindex" queue so an embedding update can never be
    # silently dropped. Both OFF by default:
    #   AI_INDEX_OUTBOX_ENABLED — when ON, candidate/job write paths ENQUEUE a
    #     reindex event (same transaction) instead of embedding inline; when OFF
    #     they embed inline exactly as today.
    #   AI_INDEX_WORKER_ENABLED — when ON, the background worker drains the
    #     outbox (build doc + hash in Python, upsert/delete in Qdrant, retry with
    #     dead-letter). When OFF the worker loop exits immediately.
    # Keep the worker OFF until the outbox has been observed healthy; it must
    # only maintain freshness of the unchanged v1 schema (no mass re-embed).
    AI_INDEX_OUTBOX_ENABLED: bool = False
    AI_INDEX_WORKER_ENABLED: bool = False
    AI_INDEX_WORKER_INTERVAL_SECONDS: int = 30
    # Short pause only after a full successful batch; idle/error polling uses
    # AI_INDEX_WORKER_INTERVAL_SECONDS. Set both equally to restore fixed polling.
    AI_INDEX_WORKER_BUSY_INTERVAL_SECONDS: int = 1
    AI_INDEX_WORKER_BATCH: int = 50
    AI_INDEX_MAX_ATTEMPTS: int = 5

    # ── Index drift reconciler ────────────────────────────────────────────────
    # Periodic sweep comparing each entity's DESIRED embedding hash with the one
    # the outbox recorded as actually indexed, enqueueing the difference. Exists
    # because three Traffit import phases change embedding-text fields and
    # record no reindex intent — patching those three fixes three, not the next
    # one somebody adds.
    #
    # OFF by default and MUST NOT be enabled before the provider health probes:
    # with AI_INDEX_MAX_ATTEMPTS=5, a Voyage outage plus a reconciler feeding
    # the worker burns the whole backlog into dead rows behind a green
    # healthcheck.
    # Włączony domyślnie od 18.09.2026. Audyt: 128 z 307 opublikowanych
    # rekrutacji (41,7%) bez wektora i 1 932 osierocone punkty kandydatów —
    # mechanizm, który to wyłapuje, był wyłączony ORAZ zwolniony z heartbeatu,
    # więc jego cisza nie była nawet widoczna. Reconciler nie liczy embeddingów:
    # zapisuje INTENCJE do outboxu, a wykonanie zależy od `AI_INDEX_WORKER_ENABLED`.
    AI_INDEX_RECONCILER_ENABLED: bool = True
    AI_INDEX_RECONCILER_INTERVAL_SECONDS: int = 300
    AI_INDEX_RECONCILER_BATCH: int = 500

    # ── AI canonical text schema v2 (plan PR7) ────────────────────────────────
    # OFF by default → the legacy embedding text is used unchanged. When ON, the
    # embedding document is built from labeled, PII-free canonical sections
    # (no name/email/phone/address; quality-gated summary; normalised skills).
    # Flipping this changes the embedding text → it only takes effect for
    # vectors (re)built afterwards, so a switch needs a backfill into a v2
    # collection (PR6). The active text-schema version string derives from it.
    AI_TEXT_SCHEMA_V2: bool = False

    # Runda 2 (2026-08-18): v3 = v2 + pełne CV zawsze (cap 12k; v1 ucinał na
    # 3000 znaków — 63% CV na prodzie jest dłuższych) + sekcja [NOTES] z faktów
    # potwierdzonych w rozmowach (7,3k kandydatów). Dotyczy WYŁĄCZNIE tekstu
    # kandydata; tekst oferty zostaje na dotychczasowym dispatcherze. Flip
    # wymaga zbudowanej kolekcji side-by-side (reembed z QDRANT_COLLECTION
    # wskazującym nową) i przełącza się RAZEM z QDRANT_COLLECTION — oba wpisy
    # są w _SCORING_CACHE_INPUTS, więc flip unieważnia cache score'ów.
    AI_TEXT_SCHEMA_V3: bool = False

    # Runda 2: unia pul z kilku sformułowań zapytania (pełny tekst oferty +
    # tytuł/seniority + lista skilli). Warianty decydują o CZŁONKOSTWIE puli;
    # podobieństwo semantyczne liczone osobno względem tekstu głównego (wzorzec
    # hybrydy) — dlatego flaga świadomie NIE wchodzi do _SCORING_CACHE_INPUTS.
    MULTI_QUERY_RETRIEVAL_ENABLED: bool = False

    # ── AI matching: "pokaż wszystkich kandydatów, którzy pasują" ─────────────
    # Zastępuje stary twardy cap top-10. Oba silniki (legacy /ai-matches oraz
    # hybrydowe /recommendations + proposals) zwracają TERAZ wszystkich
    # kandydatów ze score >= próg, przycięte do MATCH_MAX_RESULTS jako bezpiecznik
    # rozmiaru payloadu. Wszystkie tunowalne runtime przez Coolify env (bez
    # rebuildu — is_runtime).
    #
    # Kalibracja 2026-05-29 na żywych rozkładach z joba 15 (Scrum Master):
    #   • legacy rerank score (Voyage rerank-2.5, 0-1): klaster 0.61-0.87 →
    #     próg 0.5 trzyma trafny zbiór, ucina szum gdy poszerzymy pulę.
    #   • hybrydowy composite (0-100): historycznie ZANIŻONY (długi płaski ogon
    #     24-34 — semantycznie trafni, ale composite ciągniony w dół bo surowy
    #     cosinus + salary/location nieznane → 0 pkt). RECALIBRACJA 2026-06-23
    #     (patrz scoring_service.SEMANTIC_CALIBRATION_GAMMA / UNKNOWN_NEUTRAL_
    #     FRACTION niżej) podnosi krzywą semantyczną i traktuje brak danych jako
    #     neutralny (połowa budżetu, jak availability/champion). Trafny kandydat
    #     ląduje teraz ~55-70 zamiast ~30-37 → próg podniesiony 25 → 40, by
    #     utrzymać podobny zbiór wyników na nowej skali (tunowalny env runtime).
    # hybrydowe /recommendations + proposals (skala 0-100). Po recalibracji
    # (2026-06-23) skala jest realistyczna, więc próg podniesiony z 25 → 40.
    RECOMMENDATION_MIN_SCORE: float = 40.0
    # twardy bezpiecznik rozmiaru WYNIKU (oba silniki) — ile pozycji wraca do
    # klienta. To NIE jest rozmiar puli pobieranej z Qdranta; mylenie tych dwóch
    # zmieniłoby wielkość odpowiedzi na czterech powierzchniach naraz.
    MATCH_MAX_RESULTS: int = 200
    # Rozmiar puli pobieranej z Qdranta przed scoringiem. Zmierzone 2026-08-10 na
    # 40 ofertach i 960 pozytywach: przy puli 200 do warstwy scoringu trafia
    # 13,6% ground truth, przy 500 — 22,8%, przy 1000 — 32,6%. Sufit recall jest
    # więc ustawiany TUTAJ, nie przez wagi; do 2026-08-10 stała 200 była wpisana
    # na sztywno w czterech miejscach.
    #
    # Podniesienie do 1000 jest bezpieczne dopiero po zbatchowaniu zapytań
    # per-para w scoringu (`build_job_scoring_context`) — bez tego zimna pula
    # 1000 to ~2000 round-tripów do bazy na jedno żądanie.
    MATCH_POOL_SIZE: int = 1000
    # Warstwa bez sygnału jest USUWANA z budżetu zamiast dostawać stałą liczbę
    # punktów. Zmierzone na prodzie 2026-08-10, dlaczego to nie jest kosmetyka:
    #   * 90% ofert nie ma `nice_skills` → stara reguła dawała tam WSZYSTKIM 0/10,
    #   * 13% ofert nie ma `must_skills` → dawała WSZYSTKIM 20/20,
    #   * wszystkie trzy ścieżki `_score_salary` zwracały tę samą stałą 7,8,
    #   * `champion_fit` czyta screening, który pula z definicji wyklucza, więc
    #     każdy dostawał 6,5.
    # Żadna z tych liczb nikogo nie różnicuje — to ~28 pkt szumu na 100, który
    # windował podłogę powyżej progu RECOMMENDATION_MIN_SCORE=40 i sprawiał, że
    # próg przestawał cokolwiek znaczyć. Renormalizacja liczy wynik z warstw,
    # które REALNIE miały co ocenić, i skaluje do 100: „z tego, co dało się
    # ocenić, kandydat ma X%".
    #
    # DOMYŚLNIE WYŁĄCZONE — i to jest wynik pomiaru, nie ostrożność.
    #
    # Zmierzone 2026-08-10 na tych samych 40 ofertach, pula 1000, boost włączony:
    #   bez renormalizacji: P@5 0,110 · R@20n 0,090 · MRR 0,273 · nDCG 0,088
    #   z renormalizacją:   P@5 0,110 · R@20n 0,091 · MRR 0,282 · nDCG 0,083
    # Czyli ZERO poprawy rankingu — i to jest logiczne: stała dodana wszystkim
    # nie zmienia KOLEJNOŚCI, a P@5/R@20/MRR/nDCG zależą wyłącznie od kolejności.
    # Teza „22 pkt szumu psuje ranking" była błędna; szum jest realny, ale psuje
    # co innego.
    #
    # Co ta zmiana naprawia naprawdę: ZNACZENIE liczby. Kandydat pokazany jako
    # „43/100", gdzie 22 pkt to stałe za brak danych, wprowadza rekrutera w błąd,
    # a próg RECOMMENDATION_MIN_SCORE=40 przestaje cokolwiek odsiewać. Tego
    # jednak harness nie mierzy — on rankuje, nie filtruje.
    #
    # Włączenie zmienia skalę każdego widocznego wyniku i wymaga rekalibracji
    # progu 40, więc czeka na osobny eksperyment mierzący efekt PROGU, nie
    # kolejności. Mechanizm jest gotowy i przetestowany; brakuje dowodu, że
    # warto go włączyć. Flaga wchodzi do klucza cache, więc flip przelicza
    # wyniki leniwie, bez migracji.
    SCORE_RENORMALIZE_UNSCORED_LAYERS: bool = False
    # Gdy filtr lokalizacji jest aktywny na /recommendations, poszerzamy pulę
    # retrieve z Qdrant do tej wartości — tylko ~17% kandydatów ma jakąkolwiek
    # lokalizację, więc domyślny semantic cut (top-200) głodzi zlokalizowany
    # podzbiór. Po retrieve pre-filtrujemy po lokalizacji i scorujemy DOPIERO
    # dopasowany podzbiór, więc koszt scoringu pozostaje ograniczony.
    RECOMMENDATION_LOCATION_POOL_SIZE: int = 500

    # ── Hybrid composite calibration (recalibracja 2026-06-23) ────────────────
    # Composite 0-100 było systematycznie zaniżane: (1) surowy cosinus Voyage dla
    # trafnych kandydatów to ~0.4-0.65 → liniowe sim*budżet niedoszacowuje; (2)
    # salary/location dawały 0 przy braku danych (~99% importów bez stawki,
    # ~99.6% ofert bez lokalizacji), podczas gdy availability/champion_fit już
    # używały neutralnej połowy. Oba sterowalne runtime (env, is_runtime):
    #   • SEMANTIC_CALIBRATION_GAMMA<1 podnosi środek krzywej (0.6: cos 0.5→0.66
    #     budżetu) bez saturacji szczytu; monotoniczne → ranking zachowany.
    #     1.0 = stare liniowe zachowanie.
    #   • SCORE_UNKNOWN_NEUTRAL_FRACTION → „brak sygnału = ten ułamek budżetu".
    #     Steruje WSZYSTKIMI czterema warstwami metadanych przy braku danych
    #     (salary, location, availability, champion_fit) — jeden spójny pokrętło.
    #     0.0 = stare twarde zero.
    # Pełny rollback bez redeployu: ustaw 1.0 / 0.0.
    #
    # Dostrojenie 2026-06-30 („AI scoring dalej zbyt surowy" — joby z Traffitu):
    # ~99% importów to oferty bez lokalizacji/widełek/deadline'u/championa (np.
    # „Ferryt Developer" #240915), więc 35 z 100 pkt żyje w warstwach metadanych,
    # które mogą przyznać tylko swój neutralny ułamek. Przy 0.5 nawet idealny
    # trafny kandydat dobijał ~55. Dwie zmiany (obie zachowują ranking →
    # P@5/Recall@20/MRR/nDCG niezmienione, bo to stały addytywny shift per-job dla
    # dominującej kohorty „wszystko nieznane"):
    #   1. location przestaje twardo-zerować przy braku sygnału (brak lokalizacji
    #      oferty / brak preferencji remote kandydata) — teraz neutralny ułamek,
    #      spójnie z salary/availability/champion (patrz scoring_service).
    #   2. ułamek podniesiony 0.5 → 0.65 (benefit of the doubt dla nieznanych).
    # Efekt: trafny kandydat ~64, dotąd ~55; cała pula +~9 pkt. Mniej → 0.5;
    # więcej leniency → 0.7 (env, bez redeployu).
    SEMANTIC_CALIBRATION_GAMMA: float = 0.6
    SCORE_UNKNOWN_NEUTRAL_FRACTION: float = 0.65

    # ── AI quota enforcement at the provider boundary ────────────────────────
    # False = log every ungated LLM call but let it through; True = refuse it.
    #
    # Ships as False deliberately. Turning it on in the same deploy that adds
    # the gate would 500 every AI feature whose path we happened to miss — and
    # the whole reason this exists is that some paths were missed for months.
    # Run log-only for a cycle, read the UNGATED lines, then flip.
    AI_QUOTA_STRICT: bool = False

    # Ollama (local LLM + embeddings fallback).
    # C-12: default PUSTY, nie "http://localhost:11434". Usługi nie ma w compose
    # prod, a niepusty default sprawiał, że guard `if not host: return None`
    # w cv_parser / recommendations / embedding_service NIGDY nie chronił —
    # każda awaria Claude'a/Voyage dokładała nieudane HTTP na localhost:11434
    # i log mylący diagnozę. Fallback Ollama działa wyłącznie przy JAWNIE
    # ustawionym OLLAMA_BASE_URL (tryb offline z CLAUDE.md), tak jak opisują
    # docstringi wszystkich trzech konsumentów („if configured").
    OLLAMA_BASE_URL: str = ""
    OLLAMA_MODEL: str = "llama3.2"
    OLLAMA_EMBED_MODEL: str = "mxbai-embed-large"

    # Anthropic (Claude) — used by CV enrichment and AI job writer
    ANTHROPIC_API_KEY: str = ""
    # Dostawcy spoza Anthropic (decyzja z badania modeli 16.09.2026): GPT Luna
    # (OpenAI, umowa powierzenia) i DeepSeek V4 Pro (dane produkcyjne za zgodą
    # Artura z 16.09). Które funkcje — patrz `services/ai_models.py`; transport
    # i mapowanie błędów — `services/llm_providers.py`.
    OPENAI_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    CLAUDE_MODEL_CV: str = "claude-sonnet-5"
    # Fala 3: model dla biegu MASOWEGO. Osobny od CLAUDE_MODEL_CV, żeby zmiana
    # ekonomiki backfillu nie degradowała po cichu interaktywnej ścieżki
    # rekrutera (upload CV → profil). Do 16.09.2026 Haiku (~$0,004/CV); badanie
    # na danych produkcyjnych: Haiku wymyślał fakty w 31% CV vs 8% u Sonneta 5
    # (F10) — decyzja Artura: Sonnet 5 także w biegu masowym i lincie reguł.
    CLAUDE_MODEL_CV_BULK: str = "claude-sonnet-5"
    # Twarde sufity pojedynczego biegu — `ai_quota` sam dokumentuje się jako
    # advisory i wyścigowe, więc bieg ma własny bezpiecznik.
    CV_BACKFILL_MAX_CALLS: int = 45_000

    # ── Daty zatrudnienia na żądanie (kartoteka firmy w ATLAS-ie) ───────────
    # Domyślnie WŁĄCZONE od 17.09.2026 (decyzja Artura: NEXUS bez limitów AI,
    # maksymalnie autonomiczny). To jedyna ścieżka, w której ruch użytkownika
    # w INNEJ aplikacji (ATLAS) uruchamia płatne wywołanie modelu — koszt widać
    # w Ustawieniach → AI i w alarmie wydatków. Flaga zostaje jako wyłącznik
    # awaryjny w Coolify.
    EXPERIENCE_DATES_ON_DEMAND_ENABLED: bool = True
    # Sufit osób na JEDNO zapytanie o firmę. Kartoteka pokazuje kilka-kilkanaście
    # osób; setka to znak, że ktoś trafił w konglomerat — wtedy lepiej nie
    # zapłacić za ogon niż uzupełnić wszystko.
    EXPERIENCE_DATES_ON_DEMAND_MAX_PER_REQUEST: int = 10

    CV_CENTRAL_POLICIES_ENABLED: bool = False
    # Interaktywne CV (kafelki wymagań z cytatami, przełącznik widoku na
    # publicznym linku, czat AI, kafelki w eksporcie HTML). Wyłączone
    # 21.09.2026 decyzją Artura — generator ma być prosty; kod zostaje, powrót
    # = CV_INTERACTIVE_ENABLED=true w Coolify. Wyłączone: brak dodatkowego
    # wywołania AI mapy wymagań, link i plik HTML pokazują widok klasyczny.
    CV_INTERACTIVE_ENABLED: bool = False
    # Automatyczne kasowanie treści CV — WYŁĄCZONE (decyzja Artura 23.09.2026:
    # NEXUS trzyma wszystkie CV, także bez zgody RODO; nic nie znika samo).
    # Jedna flaga obejmuje oba automaty: wejścia generatora CV (pełne CV,
    # notatki, Champion) z generacji bez gotowego dokumentu i z CV próbnych
    # (`retire_unneeded_job_inputs`) oraz wiersze CV próbnych reguł klienta
    # starsze niż 7 dni (`retire_previews`). Usunięcie CV zostaje wyłącznie
    # ręczne (usunięcie dokumentu albo kandydata). Włączenie = true w Coolify.
    CV_JOB_INPUT_RETENTION_ENABLED: bool = False
    CV_JOB_INPUT_RETENTION_DAYS: int = 7

    # --- Fala 2: pasaże CV --------------------------------------------------
    # Kolekcja może istnieć i być wypełniona, a mimo to NIE brać udziału w
    # retrievalu. Rozdzielenie jest celowe: pozwala zbudować i zmierzyć indeks
    # na produkcji, zanim cokolwiek zacznie z niego czytać.
    CV_PASSAGES_ENABLED: bool = False
    # Fala Champion (2026-08-14): sygnały z champion_profile w scoringu —
    # stawka PLN/h Championa vs oczekiwania kandydata (warstwa finansowa
    # przestaje być wiecznie not_comparable) + lokalizacja/tryb oferty
    # z Championa, gdy job.location puste (99,6%% importów) + remote_only
    # z faktów notatkowych kandydata. Default OFF do czasu pomiaru na
    # zbiorze eval z rekrutacji posiadających Championów.
    CHAMPION_MATCH_SIGNALS_ENABLED: bool = False
    # v1.1 zmierzone 15.08 jako bundle: NO-GO (R@20n -21% — kara seniority
    # wypycha kwalifikowanych z top-20, choć MRR +12% sugerował żywy składnik).
    # Dekompozycja na dwie niezależne flagi, każda z własnym pomiarem:
    CHAMPION_SENIORITY_PENALTY_ENABLED: bool = False
    CHAMPION_AVAILABILITY_FALLBACK_ENABLED: bool = False
    # Dostępność v2: kara mnożnikowa tylko za twardą kolizję jawnych dat
    # (kolumna/explicit z notatek vs start Championa + 30 dni grace) — bez
    # decay dla dat wyprowadzanych z wypowiedzenia (przyczyna NO-GO fallbacku).
    CHAMPION_AVAILABILITY_CONFLICT_ENABLED: bool = False
    # 4a: rozszerzone rodziny aliasów umiejętności (skill_taxonomy_extended)
    # w mapie scoringu — górują na derived-must z Championa/JD dla terminów
    # spoza bazowej taksonomii (git/jira/maven/servicenow…). Flip po pomiarze.
    SKILL_ALIAS_EXTENDED_ENABLED: bool = False
    # Pula kandydatów przez hybrydę (BM25+dense+RRF, opcjonalnie rerank) zamiast
    # samych wektorów. Selekcja członkostwa; skala semantyczna bez zmian — patrz
    # retrieval_pool.py. Włączać dopiero PO pomiarze pasaży (dźwignie się
    # nakładają i włączone razem są niemierzalne).
    HYBRID_POOL_ENABLED: bool = False
    # Sufit członkostwa nogi BM25 w puli (zawór na zalew: termin trafiający
    # w dziesiątki tysięcy CV mógłby zająć całą pulę i wypchnąć trafienia
    # gęste). `_bm25_pool_limit` czytało to przez `getattr` z domyślną 200,
    # a pole NIE BYŁO tu zadeklarowane — więc zmienną środowiskową nie dało się
    # go przestawić i kod sam to przyznawał w komentarzu. Deklaracja zamienia
    # martwe pokrętło w działające; wartość domyślna bez zmian, więc samo
    # dodanie tej linii niczego nie przestawia.
    HYBRID_BM25_POOL_LIMIT: int = 200
    # Pula SQL-first po must-have (0278): zamiast wektora/hybrydy, członkostwo
    # wybiera Postgres — AND-of-OR po jawnych rodzinach umiejętności must-have
    # (`hybrid_search.bm25_must_candidates`). Kosinus dla wybranych liczony jak
    # zawsze przez `similarity_for_candidate_ids` — skala semantyczna bez zmian,
    # patrz `retrieval_pool._structured_pool`. Sprawdzana PRZED hybrydą/wektorem
    # w fasadzie; `False` = dosłownie dzisiejsza ścieżka. Włączać dopiero po
    # A/B na zamrożonym zbiorze ofert z Championami (harness `eval_matching.py
    # --structured-pool`).
    STRUCTURED_POOL_ENABLED: bool = False
    # Sufit członkostwa nogi SQL-first — ta sama rola co `HYBRID_BM25_POOL_LIMIT`,
    # inny mechanizm (tu SQL wybiera całą pulę, nie tylko jedną nogę hybrydy).
    STRUCTURED_POOL_LIMIT: int = 2000
    # Poniżej tej liczby trafień SQL-first pula nie jest ufana — zbyt wąskie
    # członkostwo (np. rzadka rodzina must-have) spada na hybrydę/wektor
    # zamiast rankować garstkę kandydatów jako całą pulę. Oba pokrętła (limit,
    # próg) zmieniają wyłącznie CZŁONKOSTWO puli — kosinus per kandydat jest
    # ten sam niezależnie od tego, która strategia go wybrała — dlatego oba
    # są celowo POZA `scoring_service._SCORING_CACHE_INPUTS` (jak
    # `HYBRID_POOL_ENABLED`/`HYBRID_BM25_POOL_LIMIT` wyżej): istniejące wiersze
    # cache score'ów zostają poprawne, zmienia się tylko to, kogo w ogóle
    # oglądamy.
    STRUCTURED_POOL_MIN_MEMBERS: int = 20
    # Kill-switch trzech rubryk (0278): must-have / dni w biurze / miasto biura
    # jako dealbreakery na 5 powierzchniach (Rekomendacje, Radar, snapshot,
    # digest, /ai-matches). `False` przywraca dokładnie przedwczesne zachowanie
    # (sam budżet + jawny `exclude_remote_only`) — trzy nowe predykaty i AUTO
    # uzbrajanie `exclude_remote_only` z `wants_office` stają się no-opem; jawnie
    # przekazane `exclude_remote_only=True` nadal działa (reguła C2 na
    # `/ai-matches` przeżywa wyłącznik). Tylko członkostwo — celowo POZA
    # `scoring_service._SCORING_CACHE_INPUTS` (dealbreakery działają PO
    # scoringu, nie zmieniają punktacji, którą cache przechowuje).
    RUBRIC_DEALBREAKERS_ENABLED: bool = True
    # Rozmiar puli trybu semantycznego w RĘCZNEJ wyszukiwarce kandydatów.
    # To jednocześnie SUFIT liczby wyników, którą widzi rekruter, i liczba
    # dokumentów wysyłanych do rerankera Voyage przy KAŻDYM żądaniu strony
    # (endpoint jest bezstanowy). Pokrętło istnieje, żeby dało się zmierzyć
    # 200 vs 100 evalem bez deployu — patrz `_hybrid_pool_size` w api/search.py.
    SEARCH_HYBRID_POOL_SIZE: int = 200
    # Jednorazowa migracja zapisanych wyszukiwań kandydatów na wspólną semantykę
    # filtrów (`services/saved_search_migration.py`) przy starcie skanera alertów.
    # Domyślnie OFF: migracja wstrzymuje alerty zapisów, których wynik się
    # zmienia, i powiadamia właścicieli — moment wybiera człowiek (albo admin
    # woła `POST /api/saved-searches/migrate-semantics`). Marker w `app_settings`.
    SAVED_SEARCH_SEMANTICS_MIGRATION_AUTORUN: bool = False
    # Talent Radar: wymagania MUST/NICE podane WPROST (z `parse-champion`)
    # zamiast wywodzonych regexem z prozy. Flip zmienia CZTERY rzeczy naraz,
    # nie jedną warstwę punktową:
    #   1. warstwę `skills` — `_score_skills` przestaje wywodzić must z prozy,
    #      a `nice` po raz pierwszy bywa niepuste, więc przy renormalizacji
    #      zmienia się MIANOWNIK dla każdego kandydata;
    #   2. tekst embedowanego zapytania (`_build_job_text_v1`) — czyli wektor,
    #      którym pytamy Qdranta;
    #   3. wariant retrievalu „skills" (`build_job_query_variants`);
    #   4. źródło terminów BM25 (`build_job_bm25_query` czyta `job.must_skills`
    #      JAKO PIERWSZE, na Championa spada dopiero przy pustych) — działa
    #      wyłącznie przy `HYBRID_POOL_ENABLED=true`.
    # Punkty 2-4 zmieniają PULĘ, nie tylko kolejność — dlatego default OFF do
    # czasu pomiaru evalem, z ustaloną (najlepiej wyłączoną) pozycją
    # `HYBRID_POOL_ENABLED`, inaczej dwie dźwignie są nie do rozplątania.
    TALENT_RADAR_STRUCTURED_SKILLS_ENABLED: bool = False
    QDRANT_PASSAGES_COLLECTION: str = "nexus_cv_passages"
    CV_ENRICHMENT_ENABLED: bool = True  # kill-switch without redeploy
    # Darmowe sito duplikatów przed płatnym odczytem CV (`/from-cv`, 18.09.2026).
    # Wyłącznik istnieje, bo sito czyta e-mail i telefon REGEXEM z nagłówka, a nie
    # modelem: fałszywe trafienie odmawia 409 i `BulkImportCVsV2` nie ma wtedy
    # przycisku „zapisz mimo wszystko" (ma go tylko AddCandidateFromCVModal).
    # Wyłączenie wraca do zachowania sprzed zmiany — płacimy za odczyt każdego
    # duplikatu, ale nikt nie jest zablokowany.
    FROM_CV_SIEVE_ENABLED: bool = True
    # Okno tekstu CV dla pełnego odczytu (prompt v7). Dłuższe CV jest cięte
    # 70% początek / 30% koniec, bo wykształcenie i certyfikaty są na końcu.
    CV_PARSER_INPUT_CHAR_CAP: int = 24_000

    # ── Autonomiczne dopasowanie CV ↔ rekrutacje (17.09.2026) ─────────────────
    # Po odczycie nowego/odświeżonego CV system sam sprawdza otwarte rekrutacje;
    # dopasowanego kandydata dodaje do pipeline'u (etap „Ogłoszenia”, tag
    # auto-match) i powiadamia właściciela. Publikacja rekrutacji robi to samo
    # w drugą stronę dla profili z CV z ostatnich AUTO_MATCH_JOB_LOOKBACK_DAYS.
    AUTO_MATCH_ENABLED: bool = True
    # True = pełna ocena i dziennik decyzji, bez dodawania i bez powiadomień.
    # Domyślnie True na pierwsze wdrożenie (plan: 48 h próby przed dodawaniem).
    # Przejście na żywo: `AUTO_MATCH_DRY_RUN=false` w Coolify (workflow
    # „Coolify set env") po przejrzeniu dziennika w Ustawieniach → AI.
    # ZASTĄPIONE przez `AUTO_MATCH_MODE` (21.09.2026). Zostaje jako alias
    # czytany WYŁĄCZNIE, gdy `AUTO_MATCH_MODE` nie jest ustawione:
    # true → `dry_run`, false → `add`. `None` = nikt go nie ustawił.
    AUTO_MATCH_DRY_RUN: Optional[bool] = None
    # Tryb automatu po odczycie CV / publikacji rekrutacji (rozstrzyga
    # `auto_match_outbox.auto_match_mode`):
    #   dry_run — pełna ocena i dziennik decyzji, nic więcej (stan sprzed 21.09);
    #   propose — dobry wynik trafia do skrzynki „Propozycje" rekrutacji
    #             (`job_proposals`, źródło `new_cv`); NIC nie wchodzi do pipeline'u;
    #   add     — kandydat jest dodawany na etap „Ogłoszenia" (decyzja z 17.09).
    # Puste = `propose`, chyba że ustawiono alias `AUTO_MATCH_DRY_RUN`.
    AUTO_MATCH_MODE: Optional[str] = None
    AUTO_MATCH_MIN_SCORE: float = 70.0
    AUTO_MATCH_REQUIRE_MUST: bool = True
    AUTO_MATCH_MAX_JOBS_PER_CANDIDATE: int = 3
    AUTO_MATCH_MAX_CANDIDATES_PER_JOB: int = 10
    AUTO_MATCH_JOB_LOOKBACK_DAYS: int = 90
    AUTO_MATCH_INTERVAL_SECONDS: int = 15

    # ── Automatyczny pełny przegląd bazy (21.09.2026) ────────────────────────
    # Nocna pętla (okno w `BUSINESS_TZ`) uruchamia pełny przegląd bazy dla
    # rekrutacji opublikowanych albo istotnie zmienionych od ostatniego
    # przeglądu automatycznego. Wynik (top-K po regule `is_good_match`) trafia
    # do skrzynki „Propozycje" (źródło `full_base`). False = pętla kończy się
    # przed startem, nic się nie dzieje (stan sprzed 21.09).
    AUTO_FULL_REVIEW_ENABLED: bool = True
    # audyt 22.09 r2 (PROD-03): 5/noc — przegląd to ~190 MB, 20/noc zapełniało wolumen.
    AUTO_FULL_REVIEW_MAX_PER_NIGHT: int = 5
    AUTO_FULL_REVIEW_TOP_K: int = 60
    # Osobny próg, bo pełny przegląd punktuje kanonicznym fitem, a auto-match
    # nowych CV starszym scoringiem — wspólny próg stroiłby dwa różne pomiary.
    AUTO_FULL_REVIEW_MIN_SCORE: float = 70.0
    AUTO_FULL_REVIEW_WINDOW_START_HOUR: int = 1
    AUTO_FULL_REVIEW_WINDOW_END_HOUR: int = 5
    AUTO_FULL_REVIEW_INTERVAL_SECONDS: int = 60
    # Zdarzenia rekrutacji starsze niż tyle dni nie uruchamiają przeglądu.
    AUTO_FULL_REVIEW_EVENT_LOOKBACK_DAYS: int = 14

    # ── Auto-CV po ruchu na „Zweryfikowany" (21.09.2026) ─────────────────────
    # Po commicie pojedynczego ruchu na etap „Zweryfikowany" system w tle
    # zakolejkowuje generację CV w szablonie firmowym (ta sama ścieżka co
    # POST /api/cv-generator/generate). Reguła klienta wymagająca wejść (zrzut
    # zgody RODO, notatki, numer projektu, Champion) NIE jest omijana — brak
    # wejścia = pominięcie z Activity `cv_auto_generate_skipped`. False = brak
    # jakiegokolwiek efektu po ruchu (stan sprzed 21.09).
    CV_AUTO_GENERATE_ON_VERIFIED: bool = True
    # Pobranie CV klienta, którego centralna polityka wymaga zrzutu zgody RODO
    # (PKO BP), jest zablokowane (409 `consent_required`), dopóki zrzut nie jest
    # dołączony — generacja przechodzi, zgodę można dołączyć po niej. False =
    # wyłącznik awaryjny: pobrania działają jak przed 23.09.2026.
    CV_CONSENT_DOWNLOAD_GATE_ENABLED: bool = True

    # ── QC CV — bramka przed „CV wysłane”/Cpro (Rekrutacja v5, 0361) ─────────
    # Ruch pary z kolumn Nowi/Screening/Zweryfikowany/QC CV na „CV wysłane”
    # albo na etap Cpro liczy QC CV firmowego i odmawia 409 `CV_QC_FAILED`,
    # chyba że QC przechodzi albo Delivery Lead/admin je obszedł. False =
    # ruch bez sprawdzenia (QC dalej liczy się na żądanie i na tablicy).
    CV_QC_GATE_ENABLED: bool = True

    # ── Jarvis — asystent-agent w shellu (0330, zastępuje MINDY) ─────────────
    # Wyłącznik całej funkcji: false = maskotka mówi „nie działam teraz”, trasy
    # czatu zwracają 503, reszta aplikacji nietknięta. Domyślnie false do
    # pierwszego testu na produkcji; włączenie przez workflow „Coolify set env”.
    JARVIS_ENABLED: bool = False
    # Najwięcej wywołań modelu w jednej turze (każde może wołać narzędzia).
    JARVIS_MAX_STEPS: int = 8
    # Budżet czasu całej tury (sekundy) — pętla nie zacznie kroku po terminie.
    JARVIS_TURN_TIMEOUT_SECONDS: float = 90.0
    JARVIS_MAX_TOKENS_PER_STEP: int = 1500
    # Ile ostatnich wiadomości rozmowy idzie do modelu (koszt tokenów).
    JARVIS_HISTORY_WINDOW: int = 20
    # Miękki dzienny licznik tur na osobę: INFORMUJE, nie blokuje (NEXUS nie ma
    # limitów AI — decyzja 17.09.2026). Twardą ochroną budżetu jest alarm wydatków.
    JARVIS_DAILY_SOFT_LIMIT: int = 50
    # Rozmowy starsze niż tyle dni są kasowane (dane osobowe w treści).
    JARVIS_RETENTION_DAYS: int = 30

    # Akademia (0369): pętla naboru z ogłoszeń i sortowania Luną co 10 min.
    # Bez programów nic nie robi; wyłączenie nie blokuje przycisku na ekranie.
    ACADEMY_INTAKE_ENABLED: bool = True
    # Praktykant (0374): poranne listy telefonów i powiadomienie o końcu
    # programu. Bez praktykantów nic nie robi; lista i tak powstaje przy
    # pierwszym otwarciu ekranu, więc wyłączenie nie zostawia nikogo bez pracy.
    TRAINEE_CALL_LISTS_ENABLED: bool = True
    # Godzina (BUSINESS_TZ), od której pętla składa listy danego dnia.
    TRAINEE_CALL_LISTS_HOUR: int = 5
    # Proponowana akcja bez decyzji dłużej niż tyle minut wygasa.
    JARVIS_ACTION_TTL_MINUTES: int = 15
    # Internet (decyzja 21.09.2026): wyszukiwarka tylko w turze, w której
    # użytkownik włączył przełącznik „Szukaj w internecie”. Taka tura NIE ma
    # narzędzi z danymi NEXUSA ani wcześniejszej rozmowy — dane z bazy nie mają
    # jak trafić do zapytania wysłanego na zewnątrz.
    JARVIS_WEB_ENABLED: bool = True
    # Twardy limit tur z internetem na osobę dziennie (koszt: 0,01 USD/wyszukiwanie).
    JARVIS_WEB_DAILY_LIMIT: int = 20
    JARVIS_WEB_MAX_SEARCHES_PER_TURN: int = 3
    # CSV domen: pusta lista dozwolonych = cały internet. Zablokowane zawsze
    # wygrywają. Obu naraz Anthropic nie przyjmuje — dozwolone mają pierwszeństwo.
    JARVIS_WEB_ALLOWED_DOMAINS: str = ""
    JARVIS_WEB_BLOCKED_DOMAINS: str = ""
    AUTO_MATCH_MAX_ATTEMPTS: int = 3
    AUTO_MATCH_STALE_HOURS: int = 48
    # ── „Moi ludzie" (21.09.2026) ────────────────────────────────────────────
    # Publikacja rekrutacji sprawdza listy „Moi ludzie" wszystkich rekruterów
    # i wysyła jeden dzwonek na (rekruter, rekrutacja) z osobami, które pasują.
    # Działa niezależnie od AUTO_MATCH_DRY_RUN (niczego nie dodaje do pipeline'u),
    # ale jedzie na kolejce auto-matcha — przy AUTO_MATCH_ENABLED=false stoi.
    MY_PEOPLE_MATCH_ENABLED: bool = True
    # Próg kanonicznego fitu (0-100), ten sam rząd co AUTO_MATCH_MIN_SCORE.
    MY_PEOPLE_MATCH_MIN_SCORE: int = 70
    # Najwięcej osób na jeden dzwonek jednego rekrutera.
    MY_PEOPLE_MATCH_MAX_PER_USER: int = 10
    # Ile najbliższych wektorowo osób dostaje pełną ocenę (≤ 300, sufit Qdranta).
    MY_PEOPLE_MATCH_POOL: int = 200
    # To samo dla zakładki „Do tej rekrutacji" liczonej na żądanie.
    MY_PEOPLE_PANEL_POOL: int = 60
    # CV z maila od nadawcy spoza bazy zakłada kandydata (z dedupem po treści CV).
    M365_AUTO_CREATE_CANDIDATE_FROM_CV: bool = True
    # Tylko poczta z ostatnich N dni — bez tego pierwszy bieg po wdrożeniu
    # zakładałby kandydatów z całej historii skrzynek.
    M365_AUTO_CREATE_LOOKBACK_DAYS: int = 14
    # Order-PDF extraction ("Zczytaj dane z dokumentu" w przedłużeniu). Kill-switch
    # bez redeploya, obok bramki AIFeatureKey.order_parser (master → feature → limit).
    ORDER_EXTRACTION_ENABLED: bool = True
    # F7: GPT-6 Luna (decyzja 22.09.2026 po pomiarze; 21.09 był powrót z GPT-5.6
    # Luna na Sonneta). Rejestr `ai_models` honoruje to pole jako legacy
    # override, więc domyślna wartość MUSI zgadzać się z rejestrem.
    ORDER_PARSER_MODEL: str = "gpt-6-luna"
    # ── Zamówienia z maila (ticket zamowienia@b2bnetwork.pl) ──────────────
    # Skrzynka kopii w M365 czytana przez Graph (hosting robi kopię przychodzących
    # na tę skrzynkę; oryginały zostają). Kill-switch PRZED pętlą: wyłączona
    # integracja nie budzi procesu co N sekund, żeby sprawdzić tę samą flagę.
    ORDER_MAIL_INGEST_ENABLED: bool = False
    # UPN skrzynki zamówień; połączenie M365 z tym UPN dostaje purpose='orders'
    # i jest POMIJANE przez sync skrzynek osobistych (matcher kandydatów, osie
    # czasu maili) — zamówienia klientów nie są pocztą rekrutera.
    ORDER_MAIL_UPN: str = ""
    # Jak czytnik uwierzytelnia się do tej skrzynki:
    #  - "delegated" — połączenie OAuth użytkownika-bota (wiersz M365Connection
    #    o tym UPN); wymaga konta z licencją i hasłem oraz odświeżania tokenu;
    #  - "app" — client_credentials TEJ SAMEJ rejestracji (M365_CLIENT_ID/SECRET,
    #    realny tenant w M365_MAIL_TENANT_ID) z APPLICATION `Mail.Read` zawężonym
    #    Application Access Policy do skrzynki zamówień. Skrzynka może być
    #    WSPÓŁDZIELONA (bez licencji, bez logowania) — członek listy dystrybucyjnej
    #    zamowienia@, więc hosting nie potrzebuje żadnej reguły kopii. Graph nie
    #    ma `/me` bez użytkownika, stąd ścieżki `/users/{upn}/...`.
    ORDER_MAIL_AUTH_MODE: str = "delegated"
    # Odstęp między biegami (minuty). Do 09.2026 pętla miała dwa sloty dobowe
    # (08:00 i 15:00): zamówienie, które przyszło o 08:37, czekało do 15:00.
    # Bieg jest należny, gdy od KOŃCA ostatniego minęło co najmniej tyle minut —
    # także zaraz po restarcie kontenera (bieg przerwany końca nie zapisuje)
    # i po biegu ręcznym (ten przesuwa zegar, więc nie ma dwóch biegów tuż po
    # sobie). Podłoga 5 min (`poll_interval_minutes`): bieg to kilka wywołań
    # Graph, a przy zerze pętla kręciłaby się bez przerwy.
    ORDER_MAIL_POLL_INTERVAL_MINUTES: int = 60
    ORDER_MAIL_INITIAL_LOOKBACK_DAYS: int = 7
    ORDER_MAIL_OVERLAP_HOURS: int = 2
    ORDER_MAIL_MAX_ATTACHMENT_MB: int = 25
    # CSV domen nadawców, z których przyjmujemy załączniki; pusta = wszystkie
    # (rozpoznanie klienta i tak wymaga numeru rejestrowego z rejestru, a
    # nierozpoznany dokument kończy jako wpis w dzienniku, nie w zamówieniach).
    ORDER_MAIL_SENDER_ALLOWLIST: str = ""
    # Wyłącznik automatu (kill-switch bez deployu). True = werdykt „auto"
    # zapisuje zamówienie bez kliknięcia „Zastosuj"; False = pewny plan zostaje
    # w kolejce z powodem „Automatyczny zapis jest wyłączony…". Czytany przez
    # wszystkie trzy zapisy bez aktora (odczyt maila, „Przelicz plan",
    # sprzątanie kolejki — `order_mail_ingest.hold_when_autoapply_disabled`).
    # Bramka `order_mail_gate.evaluate` go NIE czyta (ocenia dokument, nie
    # konfigurację). Ręczne „Zastosuj" działa niezależnie od flagi.
    # Do 10.09.2026 flaga była ignorowana (opisana jako „legacy").
    ORDER_MAIL_AUTOAPPLY_ENABLED: bool = True
    # CSV client_id WYKLUCZONYCH z automatu (pusta = nikt nie wykluczony —
    # spójnie z konwencją repo, w której pusta lista CSV nigdy nie znaczy
    # „wszyscy"). Klient, u którego odczyt zacznie się mylić, wraca na kolejkę
    # bez deployu.
    ORDER_MAIL_AUTOAPPLY_EXCLUDE_CLIENT_IDS: str = ""

    # ── Godzinowa ponowna weryfikacja wstrzymanych zamówień (0316) ───────────
    # Wstrzymany wpis nie wracał sam: jedyne automatyczne przeliczenie odpalało
    # się tylko po zmianie `rule_version` polityki klienta. Recheck jedzie
    # w TYM SAMYM biegu skrzynki (co `ORDER_MAIL_POLL_INTERVAL_MINUTES`),
    # lokalnie i przed Graphem, więc działa też przy awarii skrzynki.
    ORDER_MAIL_RECHECK_ENABLED: bool = True
    # Sufit na bieg: każdy recheck to ekstrakcja tekstu z PDF-a, a skan idzie
    # przez OCR. Kolejność `last_at NULLS FIRST` sprawia, że nic nie głoduje.
    ORDER_MAIL_RECHECK_MAX_DOCS: int = 100
    # Po tylu dniach przestajemy ponawiać rozpoznanie klienta dla wpisów
    # „Nie rozpoznano klienta" — te znikają z kolejki tylko ręcznie, więc bez
    # sufitu OCR-owalibyśmy je co godzinę bez końca.
    ORDER_MAIL_RECHECK_UNRECOGNIZED_DAYS: int = 90
    # Okno godzin (Europe/Warsaw = `BUSINESS_TZ`), w którym wolno ruszyć
    # AUTOMATYCZNEMU przeliczeniu; półotwarte `[start, end)`, więc ostatni bieg
    # startuje o 17:xx. Do 09.2026 recheck jechał całą dobę i zapisywał wiersz
    # historii co godzinę — 24 wiersze dziennie, w większości identyczne, a nocne
    # biegi OCR-owały PDF-y w godzinach, w których nikt i tak nic z wynikiem nie
    # zrobi. Zawężenie dotyczy WYŁĄCZNIE recheku: pobieranie poczty
    # (`ORDER_MAIL_POLL_INTERVAL_MINUTES`) i sonda `checks.order_mail` zostają
    # dobowe, bo zamówienie przysłane o 18:30 ma się pojawić o 19:00, a nie
    # nazajutrz. Ręczne „Pobierz zamówienia z maila" omija okno.
    # Wyrównanie obu wartości (`start == end`) WYŁĄCZA okno — escape hatch bez
    # deployu, gdyby ograniczenie okazało się pomyłką.
    ORDER_MAIL_RECHECK_START_HOUR_LOCAL: int = 8
    ORDER_MAIL_RECHECK_END_HOUR_LOCAL: int = 18
    # Ile nieudanych prób Z RZĘDU zanim Delivery Lead dostanie kartę. Nowy
    # kontraktor czekający na podpis umowy NIE jest liczony (patrz
    # `order_mail_recheck_reasons.classify_hold`).
    ORDER_MAIL_RECHECK_ALERT_AFTER_ATTEMPTS: int = 3
    # Bezpiecznik: dokument, którego pętla nigdy nie obejrzała (wyłączona albo
    # zatrzymana), i tak dostaje kartę po tylu godzinach czekania. Bez tego
    # awaria pętli zamieniłaby „powiadom po trzech próbach" w „nigdy".
    # UWAGA: to wartość MINIMALNA, nie efektywna. Przy zamkniętym oknie nocnym
    # stempel `last_at` każdego wstrzymanego wpisu ma nad ranem ~14 h, więc
    # sześć godzin oznaczałoby kartę dla CAŁEJ kolejki co noc. Próg efektywny
    # wylicza `order_mail_recheck_reasons.alert_after_hours()` z długości okna —
    # nie czytaj tej zmiennej wprost przy wołaniu `should_alert`.
    ORDER_MAIL_RECHECK_ALERT_AFTER_HOURS: int = 6
    # Retencja historii biegów pokazywanej pod kolejką.
    ORDER_MAIL_RECHECK_HISTORY_DAYS: int = 30
    # Resilience for the shared claude_client.call_claude() helper. Caps a hung
    # request (SDK default is 600 s) and retries transient overload/429/529/5xx.
    ANTHROPIC_TIMEOUT_SECONDS: float = 90.0
    ANTHROPIC_MAX_RETRIES: int = 2

    # CEIDG API v3 (dane.biznes.gov.pl) — token JWT do auto-uzupełniania nazwy
    # firmy JDG w Generatorze Umów B2B. Pusty = używamy tylko Białej Listy MF
    # (zwraca imię+nazwisko właściciela zamiast pełnej nazwy firmy JDG).
    # Token: dane.biznes.gov.pl → rejestracja → wygeneruj klucz API.
    CEIDG_API_TOKEN: str = ""

    # Sentry (error tracking)
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "development"

    # Ops snapshot endpoint (/api/admin/snapshot) — token auth for cron + Claude
    # Code. Empty = token auth disabled, JWT-admin still works as fallback.
    SNAPSHOT_TOKEN: str = ""

    # ── Konta serwisowe / klucze API (nagłówek X-API-Key) ────────────────────
    # Kill-switch całego mechanizmu. Domyślnie WŁĄCZONY, inaczej niż przy
    # integracjach zewnętrznych (CloudTalk, Traffit sync): tamte gadają z obcym
    # systemem i bez sekretów i tak nie działają, a tu włącznik nie chroni przed
    # niczym — bez założonego konta i wydanego klucza żadne poświadczenie nie
    # istnieje, więc powierzchnia ataku przy pustej tabeli jest zerowa. Flaga
    # zostaje jako awaryjne odcięcie CAŁEJ klasy poświadczeń jednym env-em,
    # gdyby klucz wyciekł i trzeba było zamknąć drzwi szybciej, niż idzie
    # wyklikać rewokację.
    SERVICE_ACCOUNTS_ENABLED: bool = True

    # ── Zakres OAuth zależny od trasy (audyt 22.09.2026, AUTH-01) ────────────
    # Mapa trasa → zasób żyje w `services/oauth_route_scopes.py`. Domyślnie
    # tryb CIENIA: decyzja „odmówiłbym" trafia do logu (WARNING z client_id,
    # metodą, szablonem trasy i wymaganym scope'em), a żądanie przechodzi jak
    # dotąd — kodu scraperów nie ma w repo, więc mapę uzupełniamy z logów.
    # `true` = trasa spoza mapy → 403 `route_not_exposed_to_clients`, trasa
    # z mapy bez właściwego scope'u → 403 `insufficient_scope`.
    OAUTH_ROUTE_SCOPES_ENFORCE: bool = False

    # Domyślny okres ważności nowego klucza i twardy sufit. Klucz bez terminu
    # nie jest nigdy oglądany ponownie, więc terminu nie da się tu pominąć —
    # żądanie dłuższego niż sufit jest PRZYCINANE do sufitu (patrz
    # ``service_account_auth.default_expires_at``).
    SERVICE_ACCOUNT_KEY_DEFAULT_TTL_DAYS: int = 90
    SERVICE_ACCOUNT_KEY_MAX_TTL_DAYS: int = 365

    # Co ile sekund najwyżej stemplujemy ``last_used_at`` klucza. Zapis przy
    # każdym requeście zamieniłby każdy odczyt przez API w zapis do jednego,
    # gorącego wiersza.
    SERVICE_ACCOUNT_LAST_USED_THROTTLE_SECONDS: int = 60

    # Limit tempa dla wywołań uwierzytelnianych kluczem API (slowapi, klucz = IP).
    SERVICE_ACCOUNT_RATE_LIMIT: str = "60/minute"

    # CORS — tight by default; widen via env CORS_ORIGINS='["https://app"]'
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    # Public-facing base URL for building shareable links (e.g. invite apply URLs).
    # In production: https://app.example.com. In dev: whatever the Next.js server
    # runs on (default http://localhost:3000).
    PUBLIC_BASE_URL: str = "http://localhost:3000"

    # Adres publicznej strony kariery (kariera.dynaminds.pl). Z niego budowane
    # są linki rekrutacji (`/r/<slug>`) i stały link rekrutera (`/<slug>`).
    # Pusty = fallback na PUBLIC_BASE_URL (dev/CI bez osobnej domeny).
    CAREER_PUBLIC_BASE_URL: str = ""

    # File uploads
    UPLOAD_DIR: str = "/tmp/nexus/uploads"
    MAX_UPLOAD_SIZE_MB: int = 10
    # audyt 22.09 r2 (SEC-03): limit CAŁEGO ciała żądania (POST/PUT/PATCH),
    # sprawdzany przed handlerem (app/core/body_size_limit.py).
    MAX_REQUEST_BODY_MB: int = 30

    # ── Phase 13: notification triggers ──────────────────────────────────────
    BUSINESS_TZ: str = "Europe/Warsaw"
    # Alert do DL o braku feedbacku klienta — przed końcem dnia pracy.
    CLIENT_FEEDBACK_ALERT_HOUR: int = 16
    CLIENT_FEEDBACK_ALERT_MINUTE: int = 30
    # "Zweryfikowany kandydat" utknął w cv_sent od X godzin → alert do DL.
    DL_STAGE_STALE_HOURS: int = 6
    # Górna granica okna: nie alertuj kandydatów zalegających w cv_sent dłużej
    # niż X dni. Bez tego limitu historyczny backlog (np. 10k+ kandydatów z
    # importów nigdy nieprzesuniętych) odpalał alert codziennie — patrz
    # incydent notifications 2026-05-22.
    DL_STAGE_STALE_MAX_DAYS: int = 14
    # Kandydat na nieterminalnym etapie bez zmiany od X dni → alert do rekrutera.
    STAGE_STUCK_DAYS: int = 7
    STAGE_STUCK_MAX_DAYS: int = 30  # starszych nie przypominamy (backlog importu)
    # Call completed X minut temu bez ScreeningNote → alert do rekrutera.
    CANDIDATE_FEEDBACK_AFTER_MINUTES: int = 60
    # Interwał orkiestratora (wszystkie 5 triggerów w jednej pętli).
    TRIGGERS_LOOP_INTERVAL_SECONDS: int = 300

    # ── Targ kandydatów (Candidate Marketplace) ──────────────────────────────
    # Singleton pula + auto-sync + notyfikacje po score >= threshold.
    # Kill-switch bez redeploya: MARKETPLACE_ENABLED=false wyłącza skany oraz
    # loop, ale pozostawia endpointy API (UI może dalej listować kandydatów).
    MARKETPLACE_ENABLED: bool = True
    # Próg alertów Targu (skala composite 0-100). Podniesiony 70 → 80 wraz z
    # recalibracją scoringu (2026-06-23): po podniesieniu skali stary próg 70
    # stał się osiągalny przez ~6-10× większy zbiór → ryzyko zalewu notyfikacji.
    # 80 przywraca rzadkość „tylko realnie mocne dopasowania". Tunowalny env.
    MARKETPLACE_SCORE_THRESHOLD: float = 80.0
    MARKETPLACE_DEFAULT_DURATION_DAYS: int = 30
    MARKETPLACE_SWEEP_INTERVAL_SECONDS: int = 1800  # 30 min safety net
    MARKETPLACE_TOP_K_MATCHES_PER_CANDIDATE: int = 3
    # M3-JOB-01/M3-RETR-02: pula retrieval po stronie jobów PRZED filtrem
    # statusu. Qdrant index jobów zawiera wszystkie statusy (payload nie ma
    # `status`), a baza to w większości closed joby z importu Traffit — top-30
    # semantic bywa w całości closed/draft i flow zwraca zero, mimo że niżej w
    # rankingu są dobre published joby (starvation). Szeroka pula + filtr w DB
    # to tani fix do czasu dodania statusu do payloadu.
    JOB_SEMANTIC_POOL_SIZE: int = 150
    # Rate-limit: max notyfikacji na kandydata per owner per 24h. Powyżej →
    # agregat "N nowych matchy ≥70" (Phase 2 feature; w MVP wyłączone przez 0).
    MARKETPLACE_MAX_ALERTS_PER_CANDIDATE_PER_DAY: int = 0

    # ── Szybkie przepinanie (similar-job notify) ─────────────────────────────
    # Po utworzeniu joba: jeśli istnieją Tier A podobne historyczne requesty
    # z kandydatami po etapach klienckich — notyfikacja in-app do
    # recruiter/TAC/twórcy joba. Kill-switch bez redeploya.
    SIMILAR_JOB_NOTIFY_ENABLED: bool = True
    SIMILAR_JOB_NOTIFY_MIN_CANDIDATES: int = 1

    # ── Deadline rekrutacji (job deadline alerts) ────────────────────────────
    # Daily scanner `app/tasks/job_deadline_alerts.py`: 7/3/1 dni przed
    # Job.deadline (status=published) → notyfikacja in-app + email do
    # przypisanych/delegowanych osób projektu (recruiter owner + DL + TAC +
    # aktywni collaboratorzy). Kill-switch bez redeploya; email dodatkowo
    # bramkowany przez SMTP_ENABLED. Progi jako dni.
    JOB_DEADLINE_ALERTS_ENABLED: bool = True
    JOB_DEADLINE_ALERT_THRESHOLDS_DAYS: tuple[int, ...] = (7, 3, 1)

    # ── Phase 14: post-interview feedback reminders ──────────────────────────
    # 3-stopniowy ping rekruterowi/DL po zakończonym interview.
    POST_INTERVIEW_T15_MINUTES: int = 15
    POST_INTERVIEW_T45_MINUTES: int = 45
    POST_INTERVIEW_T2H_MINUTES: int = 120
    # 0338: okno „zadzwoń do kandydata po rozmowie u klienta” (min od końca).
    # Agenda „Rozmowy u klienta” pokazuje odliczanie do jego końca.
    POST_INTERVIEW_CALL_WINDOW_MINUTES: int = 30
    # Po ilu minutach od end_time interview z status=scheduled → auto-flip na
    # completed (sygnał, że event się odbył, nawet jeśli nikt go ręcznie nie
    # oznaczył). 10 min grace period absorbuje opóźnienia.
    INTERVIEW_AUTO_COMPLETE_GRACE_MINUTES: int = 10

    # ── Email (SMTP) ─────────────────────────────────────────────────────────
    # Default: OFF. Włącza się envem SMTP_ENABLED=true. Bez credsów mailer jest
    # no-op'em (log i return) — nie blokuje triggerów ani handlerów.
    # Realni konsumenci: reset hasła, mail weryfikacyjny rejestracji, wzmianki
    # (@mention) i fallback czatu. Nagłówek tej sekcji do 2026-08-21 obiecywał
    # „fallback kanał po T+45 dla post-interview alertów" — taki kanał NIGDY
    # nie został podpięty (wrapper w `services/email.py` nie miał ani jednego
    # wywołania i został usunięty). Alerty post-interview są wyłącznie in-app;
    # włączenie SMTP ich nie wyśle.
    SMTP_ENABLED: bool = False
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "nexus@b2bnet.pl"
    SMTP_USE_TLS: bool = True
    # P1.18: refuse to send over plaintext. When True (default), STARTTLS with
    # verified CA/hostname is mandatory — no silent fallback to cleartext.
    SMTP_REQUIRE_TLS: bool = True

    # ── KPI Coach (dynamiczna analiza KPI rekruterów) ─────────────────────────
    # Interwał pętli `app/tasks/kpi_coach_nudger.py`. 300s (5min) to dobry
    # kompromis między "niemal real-time" a niską presją na DB. Clampowane
    # do >= 60s w loopie.
    KPI_COACH_LOOP_INTERVAL_SECONDS: int = 300
    # R0 (plan analytics 2026-07-16): stary nudger liczy KPI z UserActivity —
    # emisja wstrzymana (default OFF) do czasu KPI Coach v2 na kanonicznych
    # danych ATS. Historia notyfikacji w DB pozostaje nietknięta.
    KPI_COACH_NUDGER_ENABLED: bool = False

    # ── Audyt M7 PR-05: freeze niebezpiecznych aktywacji (break-glass) ────────
    # Oba domyślnie False (fail-closed). Odblokowują ryzykowne operacje, których
    # pełne zabezpieczenie przyjdzie w kolejnych falach:
    #   • debug-fire-nudge (P1.15) — smoke-test wymuszający emisję nudge'a; w
    #     produkcji dostępny WYŁĄCZNIE przez tę flagę (a i tak nie kasuje logu
    #     dedupe ani nie zwraca tracebacku),
    #   • cutover analytics (P1.7) — ustawienie legacy/live boundary jest
    #     zamrożone do czasu readiness manifestu (PR-39); break-glass służy do
    #     awaryjnego ustawienia w shadow-prep, z audytem.
    KPI_COACH_DEBUG_BREAKGLASS: bool = False
    ANALYTICS_CUTOVER_BREAKGLASS: bool = False

    # ── Recruitment Priority Lock + Carry-over Duty ────────────────────────
    # off     — persist/read the new domain without changing pipeline access,
    # shadow  — evaluate and record policy decisions, but do not reject work,
    # enforce — reject opening a new candidate/job process without an eligible
    #           active assignment (existing processes remain carry-over).
    # Safe rollout is always off -> shadow -> enforce.
    RECRUITMENT_PRIORITY_MODE: str = "off"
    RECRUITMENT_PRIORITY_WORKER_INTERVAL_SECONDS: int = 300

    # ── Analytics v1 (plan 2026-07-16, PR 2) ──────────────────────────────────
    # Tryb rolloutu:
    #   off    — router /api/analytics/v1 zwraca 503, zero zmian zachowania,
    #   shadow — endpointy v1 liczą i logują (porównanie z legacy), stare
    #            odpowiedzi UI pozostają NIEZMIENIONE,
    #   live   — v1 jest źródłem aktywnego UI (dopiero po 7 dniach shadow
    #            + canary per rola; patrz plan §8).
    # UWAGA: guardy RBAC/capabilities NIE zależą od tego flaga (R0 jest
    # niewyłączalne) — flag steruje wyłącznie NOWĄ powierzchnią v1.
    ANALYTICS_V1_MODE: str = "off"
    # Opcjonalne zawężenie aktywnych modułów v1 (csv, np. "overview,funnel").
    # Pusta wartość = wszystkie moduły w danym trybie.
    ANALYTICS_V1_MODULES: str = ""
    # KPI Coach v2 — wysyłka nudge'y po dry-run parity (plan PR 4).
    KPI_COACH_V2_NUDGES_ENABLED: bool = False

    @field_validator("ANALYTICS_V1_MODE")
    @classmethod
    def _validate_analytics_mode(cls, v: str) -> str:
        allowed = {"off", "shadow", "live"}
        if v not in allowed:
            raise ValueError(f"ANALYTICS_V1_MODE must be one of {sorted(allowed)}")
        return v

    @field_validator("RECRUITMENT_PRIORITY_MODE")
    @classmethod
    def _validate_recruitment_priority_mode(cls, v: str) -> str:
        allowed = {"off", "shadow", "enforce"}
        normalized = v.strip().lower()
        if normalized not in allowed:
            raise ValueError(
                f"RECRUITMENT_PRIORITY_MODE must be one of {sorted(allowed)}"
            )
        return normalized

    # Externally reachable base URL for the public API. Used by Outlook
    # Actionable Messages (Phase 7.5) which require Microsoft's servers to be
    # able to resolve the action target URL — localhost/tunnel won't work.
    PUBLIC_API_BASE_URL: str = "https://api.nexus.dynaminds.pl"

    # ── Microsoft 365 integration (Phase M365.1) ─────────────────────────────
    # Kill-switch for the whole integration. When False: router skips registration,
    # sync loop exits immediately — used when rolling out or reverting.
    M365_INTEGRATION_ENABLED: bool = True
    # Azure AD App Registration (multi-tenant). Empty in dev until IT Admin provides them.
    M365_CLIENT_ID: str = ""
    M365_CLIENT_SECRET: str = ""
    # "common" for multi-tenant authorize URL; actual tenant guid is recorded on the
    # connection row from the ID token claim.
    M365_TENANT_ID: str = "common"
    # Absolute URL Microsoft redirects back to after consent. Must match one of the
    # Redirect URIs configured in the Azure app.
    M365_REDIRECT_URI: str = "https://api.nexus.dynaminds.pl/api/microsoft365/callback"
    # Fernet key for token-at-rest encryption. Generate via:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Empty → TokenCipher raises at first use, not at startup (so dev/tests can run
    # without the secret as long as nothing actually calls M365 paths).
    M365_TOKEN_ENCRYPTION_KEY: str = ""
    # Separate signing key for the short-lived OAuth state JWT so it does not share
    # the main SECRET_KEY. Defaults to SECRET_KEY when empty — acceptable for dev,
    # override in prod.
    M365_STATE_SIGNING_KEY: str = ""
    # Scopes requested during authorize. MSAL adds `offline_access`, `openid`,
    # and `profile` automatically (they are reserved — passing them raises
    # ValueError). Refresh token is still returned because MSAL injects
    # `offline_access` at the token endpoint under the hood.
    M365_SCOPES: List[str] = [
        "Mail.ReadWrite",
        "Mail.Send",
        "Calendars.ReadWrite",
        "User.Read",
    ]
    # ── App-only (client_credentials) Graph mail — systemowy nadawca ─────────
    # Kanał dla POWIADOMIEŃ SYSTEMOWYCH (deadline alerts, reset hasła,
    # weryfikacja rejestracji, @mention, chat fallback, powiadomienia o
    # etapach) — inaczej niż delegated m365/sender.py (skrzynka rekrutera).
    # Gdy ON, generyczne `send_email()` (app/services/email.py) routuje przez
    # POST /users/{M365_MAIL_SENDER_UPN}/sendMail z APPLICATION permission
    # `Mail.Send` (client_credentials) zamiast SMTP.
    #
    # Wymaga w Azure App Registration APPLICATION permission `Mail.Send` +
    # admin consent, oraz realnego tenanta (client_credentials nie działa z
    # "common"). Zawężenie do jednej skrzynki: Application Access Policy.
    M365_APP_MAIL_ENABLED: bool = False
    # Dedykowana aplikacja wyłącznie do wysyłki systemowej. Gdy oba pola są
    # puste, zgodność wsteczna używa M365_CLIENT_ID/SECRET; częściowa
    # konfiguracja nie pozwala na wysyłkę.
    M365_APP_MAIL_CLIENT_ID: str = ""
    M365_APP_MAIL_CLIENT_SECRET: str = ""
    # UPN/adres skrzynki, z której wychodzą maile systemowe
    # (prod: "nexus-powiadomienia@b2bnetwork.pl").
    M365_MAIL_SENDER_UPN: str = ""
    # Tenant dla client_credentials. Pusty → fallback na M365_TENANT_ID; musi
    # być realnym tenantem (GUID lub domena), NIE "common".
    M365_MAIL_TENANT_ID: str = ""
    # Sync loop cadence; clamped to >=60s in the loop itself.
    M365_SYNC_INTERVAL_SECONDS: int = 300
    # Separate kill-switch for the background sync loop (router stays live so
    # the user can connect/disconnect via UI regardless). Default OFF in prod
    # until we're confident the loop can't exhaust the DB pool again.
    # Flip to True via Coolify env var after a stable window.
    M365_SYNC_LOOP_ENABLED: bool = False
    # Initial backfill window when user first connects.
    M365_BACKFILL_MONTHS: int = 12
    # Outlook category string that opts an email OUT of ATS sync (user-controlled).
    M365_IGNORE_CATEGORY: str = "ATS:ignore"
    # Hard cap on attachment download size (Phase 1 inline only; large upload in Phase 2).
    M365_MAX_ATTACHMENT_MB: int = 25
    # Whether to auto-parse CV attachments via cv_parser (Claude calls = $$).
    M365_AUTO_PARSE_CV: bool = True
    # Durable attachment worker cadence. Parsing is deliberately outside the
    # Graph page transaction so an LLM call cannot consume the sync timeout.
    M365_CV_PARSE_INTERVAL_SECONDS: int = 15
    # Phase 5.2 — hourly background loop that retries `matcher.match` on emails
    # synced before the candidate row existed in the DB. Cheap (LIMIT 500, single
    # SELECT + per-row UPDATEs) but kept behind a flag so it stays off until the
    # main sync loop is stable in prod.
    M365_REMATCH_ENABLED: bool = False
    # Cadence; clamped to >=600s in the loop (we never want to rematch faster
    # than 10 min — it's a catch-up job, not real-time).
    M365_REMATCH_INTERVAL_SECONDS: int = 3600
    # Look-back window. Older emails are skipped — if a candidate appears 30+ days
    # after the email, the user is expected to use manual linking from the UI.
    M365_REMATCH_LOOKBACK_DAYS: int = 30
    # Max emails to process per pass. Keeps a single iteration cheap and bounded.
    M365_REMATCH_BATCH_SIZE: int = 500
    # Phase 7.7 — append the user's Outlook signature to every outbound mail
    # so NEXUS-sent emails look identical to ones sent from Outlook itself.
    # Kill-switch if signature parsing causes regressions (e.g. unexpected
    # HTML bloating the body or duplicating an existing signature in the
    # composer template).
    M365_SIGNATURE_INJECTION_ENABLED: bool = True
    # Per-mailbox cache TTL for the parsed signature. 24h matches how often
    # most users update their signature (~never) while still surfacing
    # changes within a day. Clamped to >=60s by the cache.
    M365_SIGNATURE_CACHE_TTL_SECONDS: int = 86400

    # Phase 7.8 — periodic OneDrive scan for Teams meeting recordings.
    # Teams auto-saves the recording to the organizer's OneDrive in
    # /Recordings/<title>.mp4 once the meeting ends. We poll a few times
    # after the event (~6h cadence over the lookback window) so the link
    # appears in NEXUS without anyone uploading anything manually.
    # OFF by default — needs the Phase 7.1 columns deployed first, and we
    # only want to spend Graph quota when interviews are routinely recorded.
    M365_RECORDING_DISCOVERY_ENABLED: bool = False
    # Cadence. Clamped to >=600s inside the loop; 6h matches how long it
    # typically takes Teams to publish the recording (transcode + upload).
    M365_RECORDING_DISCOVERY_INTERVAL_SECONDS: int = 21600
    # How far back to scan. 7 days catches every realistic Teams publish
    # delay while keeping the candidate set small (a single recruiter has
    # at most a handful of interview events per week).
    M365_RECORDING_DISCOVERY_LOOKBACK_DAYS: int = 7
    # Max events to inspect per pass — bounds Graph search calls per tick.
    M365_RECORDING_DISCOVERY_BATCH_SIZE: int = 100

    # ── Prepy w Teams (0354, 23.09.2026) ─────────────────────────────────────
    # Prep 1/2 z kandydatem zakładany z NEXUSA w kalendarzu ORGANIZATORA (DL /
    # rekruter) i transkrypt z Teams → notatka + ocena prepu. Dostęp app-only
    # przez OSOBNĄ rejestrację („NEXUS Teams Prep”), nie „NEXUS ATS - Mailbox
    # and Login”: polityka dostępu Exchange zawęża aplikację do SKRZYNEK, nie
    # do uprawnień, więc dołożenie skrzynek zespołu do zakresu aplikacji
    # z `Mail.Read` dałoby jej odczyt ich poczty. Tenant = M365_MAIL_TENANT_ID.
    TEAMS_PREP_CLIENT_ID: str = ""
    TEAMS_PREP_CLIENT_SECRET: str = ""
    # Zakładanie prepów przez aplikację. OFF = trasa prepów odpowiada 503.
    TEAMS_PREP_APP_ONLY_ENABLED: bool = False
    # PATCH spotkania z automatycznym nagrywaniem/transkrypcją po utworzeniu.
    TEAMS_PREP_AUTO_TRANSCRIBE: bool = True
    # Pętla pobierająca transkrypty (kill-switch — OFF kończy ją przed pętlą).
    TEAMS_PREP_TRANSCRIPTS_ENABLED: bool = False
    TEAMS_PREP_POLL_MINUTES: int = 10
    # Od kiedy po końcu spotkania pytamy o transkrypt i jak długo czekamy,
    # zanim prep dostanie stan „bez nagrania”.
    TEAMS_PREP_FETCH_DELAY_MINUTES: int = 10
    TEAMS_PREP_FETCH_GIVE_UP_HOURS: int = 48
    # Progi oceny prepu (liczy kod, nie model). Udział kandydata = jego czas
    # mówienia / (kandydat + zespół).
    PREP_REVIEW_GOOD_COVERAGE: float = 0.8
    PREP_REVIEW_WEAK_COVERAGE: float = 0.5
    PREP_REVIEW_GOOD_TALK_SHARE: float = 0.45
    PREP_REVIEW_WEAK_TALK_SHARE: float = 0.25
    PREP_REVIEW_MIN_MINUTES: int = 10

    # ── M365 Graph push webhooks (Phase 7.3) ──────────────────────────────────
    # Push notifications replace polling once stable. Default OFF — flip to True
    # in Coolify env after deploying so the lifespan task spawns. While the flag
    # is False the renewal loop exits immediately and the POST /webhooks
    # endpoint refuses to enrol new subscriptions.
    M365_WEBHOOKS_ENABLED: bool = False
    # Public HTTPS base URL Graph will POST notifications to. Must terminate at
    # this FastAPI app — Graph rejects HTTP / IP / self-signed. Override per env.
    M365_WEBHOOK_BASE_URL: str = "https://api.nexus.dynaminds.pl"
    # How long to ask Graph to keep a single subscription alive. Graph caps at
    # 4230 min (~70h) for messages/events; we use 60 min so a missed renewal
    # only loses ~1h of pushes (polling falls back during co-existence window).
    M365_WEBHOOK_LIFETIME_MINUTES: int = 60
    # Renewal-loop cadence. Clamped to >=60s in the loop itself.
    M365_WEBHOOK_RENEWAL_INTERVAL_SECONDS: int = 600
    # Renew subscriptions whose expires_at falls inside this window. Must be
    # comfortably larger than the renewal interval so we never miss an expiry.
    M365_WEBHOOK_RENEWAL_WINDOW_MINUTES: int = 15
    # Mark a subscription inactive (deletes the row, lets the next sync re-enrol)
    # after this many consecutive renew/subscribe failures. Avoids hammering
    # Graph for a token that has been revoked server-side.
    M365_WEBHOOK_FAILURE_THRESHOLD: int = 3

    # ── SSO "Sign in with Microsoft" (Faza B) ────────────────────────────────
    # Reuses M365 Azure AD app — same client_id/secret/tenant, different redirect.
    # Empty in dev → /api/auth/microsoft/* return 503.
    MICROSOFT_LOGIN_REDIRECT_URI: str = ""
    # Email-domain whitelist for auto-provisioning. CSV string ("b2bnetwork.pl,foo.com")
    # — kept as ``str`` instead of ``List[str]`` because pydantic-settings v2 forces
    # JSON parsing for List types from env vars, which broke a plain ``b2bnetwork.pl``
    # value at startup. Use ``settings.sso_allowed_domains_list`` to get the parsed
    # list of lowercased, stripped domains.
    #
    # NB: this whitelist now governs BOTH Microsoft SSO auto-provisioning AND
    # email/password self-registration (POST /api/auth/register). The same set
    # of corporate domains is allowed to self-provision via either path.
    SSO_ALLOWED_DOMAINS: str = ""

    # ── Self-service email/password registration (POST /api/auth/register) ────
    # Kill-switch. When False the endpoint returns 503 (registration closed) and
    # the frontend /register page shows "rejestracja wyłączona". Default OFF for
    # safety — flip to True in Coolify env vault once SSO_ALLOWED_DOMAINS is set
    # to the corporate domain(s). Self-registered accounts are always created as
    # the read-only ``user`` (viewer) role, email-unverified until they click the
    # verification link; an admin elevates the role afterwards in the panel.
    SELF_REGISTRATION_ENABLED: bool = False

    # ── Logowanie email+hasło (POST /api/auth/login) ─────────────────────────
    # Kill-switch. NEXUS to narzędzie wewnętrzne — na produkcji jedyną drogą
    # wejścia ma być Microsoft SSO (ograniczone do SSO_ALLOWED_DOMAINS), więc
    # w Coolify ta flaga stoi na False i /api/auth/login, /forgot-password
    # oraz /reset-password zwracają 503.
    #
    # Default **True**, celowo — inaczej cały zestaw testów przestałby działać:
    # ``tests/conftest.py`` uwierzytelnia się przez POST /api/auth/login i
    # zależy od tego kilkadziesiąt plików testowych plus suite E2E
    # (E2E_USER_EMAIL/PASSWORD). Ochronę daje ustawienie flagi na produkcji,
    # nie usunięcie kodu.
    #
    # To jest zarazem **droga awaryjna**: gdy Azure/SSO padnie, przestawienie
    # tej flagi na True w Coolify przywraca logowanie hasłem bez deployu.
    # Konta SSO-only mają ``password_hash IS NULL`` (migracja 0081) i tak czy
    # owak nie zalogują się hasłem — break-glass wymaga konta z hasłem.
    PASSWORD_LOGIN_ENABLED: bool = True

    # ── Break-glass dla logowania hasłem ─────────────────────────────────────
    # CSV adresów email, które NADAL mogą zalogować się hasłem, gdy
    # ``PASSWORD_LOGIN_ENABLED=False``. Bez tego wyłączenie flagi na produkcji
    # (tryb SSO-only) zablokowałoby na stałe każdego admina, który ma tylko
    # hasło i żadnej ścieżki SSO — a wtedy awaria Azure/SSO = brak wejścia dla
    # nikogo. Ta wąska lista dopuszczeń trzyma logowanie ORAZ odzyskiwanie hasła
    # (/forgot-password, /reset-password) żywe dla wskazanych kont, reszta dalej
    # dostaje 503. Trzymany jako ``str`` (nie ``List[str]``) z tego samego
    # powodu co ``SSO_ALLOWED_DOMAINS`` — pydantic-settings v2 wymuszałby JSON.
    # Użyj ``settings.password_login_break_glass_email_set``. Pusta (domyślnie)
    # = brak wyjątku, zachowanie sprzed zmiany (wszyscy zablokowani).
    PASSWORD_LOGIN_BREAK_GLASS_EMAILS: str = ""

    # ── AAD group-based RBAC (Phase 7.2) ─────────────────────────────────────
    # Kill-switch. When False the SSO callback skips Graph /me/memberOf entirely
    # and falls back to legacy behaviour (new SSO users land as ``recruiter``,
    # existing users keep their role). Flip to True in Coolify env vault AFTER
    # ``AAD_GROUP_ROLE_MAP_JSON`` is populated and admin consent for the
    # ``GroupMember.Read.All`` Graph scope has been granted in the Azure app
    # registration — otherwise every login fails with a Graph 403.
    AAD_GROUP_RBAC_ENABLED: bool = False
    # JSON-encoded map ``{<aad-group-guid>: <userrole-string>}``. First match
    # wins → admins control precedence by ordering keys (Python preserves dict
    # insertion order, json.loads does too in 3.7+). Empty string = empty map
    # = every login blocked (fail-closed) when RBAC is enabled.
    # Example: '{"<uuid-admins>": "admin", "<uuid-recruiters>": "recruiter"}'.
    AAD_GROUP_ROLE_MAP_JSON: str = ""

    @field_validator("AAD_GROUP_RBAC_ENABLED")
    @classmethod
    def _force_aad_group_rbac_disabled(cls, v: bool) -> bool:
        """HARD-DISABLED 2026-07-13 — Microsoft is login-only; NEXUS roles live
        in the admin panel.

        Background: the Coolify env vault still carries
        ``AAD_GROUP_RBAC_ENABLED=true``. With RBAC on, the SSO callback
        (``app.api.auth_microsoft.callback``) re-derives every user's
        ``role``/``roles``/``is_active`` from Azure AD group membership on
        EVERY Microsoft login. That silently overwrites admin roles set in the
        NEXUS admin panel and blocks (deactivates) anyone not in a mapped AAD
        group — which is exactly what stopped teammates from logging in as
        admin. Per product decision, NEXUS role management is decoupled from
        Azure AD: Microsoft SSO authenticates identity only.

        The Coolify env var is not reachable to change directly from here, so
        this validator neutralizes the stale value in code — it always wins,
        regardless of what the env says. Tests that exercise the RBAC path set
        the flag with ``monkeypatch.setattr`` on the live settings object,
        which bypasses this validator, so they are unaffected.

        To fully re-enable AAD-group RBAC later: (1) remove this validator, and
        (2) set ``AAD_GROUP_RBAC_ENABLED=true`` in the Coolify env vault.
        """
        return False

    # ── Autenti e-signature integration (Phase Autenti.1) ───────────────────
    # Kill-switch: when False, /api/autenti/* router is not mounted, send/webhook
    # endpoints return 503, sweeper loop exits immediately. Default OFF until
    # API credentials are provisioned by Autenti sales (paid add-on).
    AUTENTI_ENABLED: bool = False
    # OAuth2 endpoints + REST base. Production defaults; sandbox URLs differ
    # only in subdomain — set via env on dev/staging deployments.
    AUTENTI_BASE_URL: str = "https://api.autenti.com/api/v2"
    AUTENTI_OAUTH_URL: str = "https://api.autenti.com/oauth2/token"
    # Client credentials (Plan A: client_credentials grant w/ `bpa` scope).
    # Empty in dev — sender service raises 503 before any HTTP call when blank.
    AUTENTI_CLIENT_ID: str = ""
    AUTENTI_CLIENT_SECRET: str = ""
    # OAuth scope — `bpa` = enterprise feature (sender as organization). If
    # Autenti sales doesn't grant it we fall back to authorization_code per
    # user (Phase 2 alternative — see plan).
    AUTENTI_OAUTH_SCOPE: str = "bpa"
    # JWKS URL used to verify webhook JWT signatures. Public key endpoint
    # documented at developers.autenti.com.
    AUTENTI_WEBHOOK_JWKS_URL: str = "https://autenti.com/developers/keys/webhook.jwks"
    # Default signature type (Pydantic Literal in API requests overrides).
    # Per plan §3: SES = Basic Electronic Signature by Autenti — sufficient
    # for B2B with JDG (98% of cases). UI offers SES | AdES | QES dropdown.
    AUTENTI_DEFAULT_SIGNATURE_TYPE: str = "SES"
    # Webhook clock skew tolerance — `iat` claim must be within this many
    # hours of "now" to be accepted. Defends against replay of old webhook
    # bodies. 24h is generous (Autenti retries up to ~10× over hours).
    AUTENTI_WEBHOOK_IAT_MAX_AGE_HOURS: int = 24
    # Background sweeper cadence (Phase 5 belt-and-braces). Polls expired
    # signatures + retries failed signed-PDF downloads. Clamped to >=300s
    # to avoid Autenti API hammering. 1h tick is plenty since the primary
    # state pump is the webhook handler.
    AUTENTI_SWEEPER_INTERVAL_SECONDS: int = 3600

    # ── In-house QES signing (Faza 1+ — drop Autenti, single-vendor KIR) ────
    # Kill-switch: when False, /api/signing/* write endpoints return 503 and
    # the signing sweeper loop exits immediately. Default OFF until KIR
    # (Szafir SDK + mSzafir) is contracted and creds provisioned. See
    # docs/in-house-qes-signature-plan.md.
    SIGNING_ENABLED: bool = False
    # Default provider for new signatures: ``szafir_sdk`` (card, client-side)
    # | ``mszafir_oneshot`` (cloud) | ``upload_validate`` | ``autenti`` (legacy).
    SIGNING_PROVIDER: str = "szafir_sdk"
    # Token TTL for the public /sign/{token} signing links (days).
    SIGNING_LINK_EXPIRY_DAYS: int = 14
    # Imiona i nazwiska osób podpisujących umowy B2B po stronie firmy (CSV).
    # Finalizacja sprawdza, że każdy podpis spoza kandydata należy do jednej
    # z nich (SIG-02). Puste = drugi podpis nie jest weryfikowany imiennie,
    # ale nadal musi to być INNA tożsamość niż kandydat.
    SIGNING_COMPANY_SIGNER_NAMES: str = ""
    # Signing sweeper cadence (timeout sweep, attach retry, expiry). Clamped
    # to >=300s in the loop.
    SIGNING_SWEEPER_INTERVAL_SECONDS: int = 3600

    # ── Signature dispatch reconciler (M5-P0.9, restart-safe recovery) ──────
    # Every signature sender persists a `draft` row and hands the actual send
    # to a background task. A restart between the 202 and completion orphans
    # the row at draft/sending forever — the expiry sweepers only touch
    # sent/in_progress. This reconciler marks such rows `failed` + notifies the
    # sender to resend. Covers all rails; each row gated by its provider's
    # kill-switch (AUTENTI_ENABLED / SIGNING_ENABLED). Loop no-ops when both off.
    # Interval clamped >=300s; grace clamped >=60s in the loop.
    SIGNATURE_RECONCILE_INTERVAL_SECONDS: int = 600
    SIGNATURE_RECONCILE_GRACE_SECONDS: int = 600

    # KIR Szafir SDK (pas główny — podpis kartą client-side). Asset/licence
    # config filled from KIR onboarding (Faza 0). Web Module JS URL is served
    # to the /sign page; empty = SDK pas unavailable (UI hides it).
    QTSP_SZAFIR_SDK_ENABLED: bool = False
    QTSP_SZAFIR_WEB_MODULE_URL: str = ""
    QTSP_SZAFIR_LICENSE_KEY: str = ""

    # KIR mSzafir One Shot (pas zapasowy — cert jednorazowy w chmurze). API
    # shape confirmed in Faza 0; empty creds = mSzafir pas returns 503.
    QTSP_MSZAFIR_ENABLED: bool = False
    QTSP_MSZAFIR_BASE_URL: str = ""
    QTSP_MSZAFIR_API_KEY_ID: str = ""
    QTSP_MSZAFIR_API_KEY_SECRET: str = ""

    # EU DSS validation sidecar (autorytatywny "is QES"). Empty = validation
    # falls back to pyHanko trust-chain only (non-authoritative).
    DSS_VALIDATION_URL: str = ""

    # ── Proxycurl LinkedIn tracking (Phase: LinkedIn sync) ──────────────────
    # Kill-switch: when False OR API key empty, sync loop exits immediately
    # and on-demand sync returns 503. Used for roll-back without redeploy.
    PROXYCURL_ENABLED: bool = True
    # API key from https://nubela.co/proxycurl — static, no per-user OAuth.
    PROXYCURL_API_KEY: str = ""
    # Loop cadence; clamped to >=60s in the loop itself. 1h tick + 7-day stale
    # candidate cutoff gives predictable cost at $0.01/lookup with caching.
    PROXYCURL_SYNC_INTERVAL_SECONDS: int = 3600
    # Candidate is due for refresh when linkedin_synced_at is NULL or older
    # than this cutoff. Default 60 days ≈ once per 2 months — sensible for
    # IT staffing (people rarely change jobs more than once per quarter) and
    # keeps Proxycurl cost predictable.
    PROXYCURL_CANDIDATE_STALE_DAYS: int = 60
    # Max candidates processed per tick (2s stagger × 50 = ~100s per tick).
    PROXYCURL_BATCH_SIZE: int = 50
    # Fuzzy company-name match threshold (0..100). >= threshold means "same
    # company" — guards against rebrand false-positives.
    PROXYCURL_COMPANY_FUZZ_THRESHOLD: int = 90

    # ── CloudTalk telephony (Phase CloudTalk.1) ──────────────────────────────
    # Kill-switch: when False, /api/calls/webhook stays in DRY-RUN (returns 200
    # with `{"status":"dry-run"}` and never writes to DB), /api/cloudtalk/*
    # endpoints return 503, sync loop exits immediately. Default OFF until
    # API_KEY_SECRET is provisioned in Coolify env vault.
    CLOUDTALK_ENABLED: bool = False
    # Public part of the API key pair from CloudTalk dashboard
    # (Settings → API Keys). Used as the Basic Auth username.
    CLOUDTALK_API_KEY_ID: str = ""
    # Secret part of the API key pair — shown ONCE by CloudTalk at generation.
    # Used as the Basic Auth password. Empty in dev — client.from_settings()
    # raises RuntimeError before any HTTP call when blank.
    CLOUDTALK_API_KEY_SECRET: str = ""
    # REST base URL — production default. CloudTalk EU/US share this host.
    CLOUDTALK_BASE_URL: str = "https://my.cloudtalk.io/api"
    # Shared secret for HMAC-SHA256 verification of inbound webhooks. The same
    # value must be configured in CloudTalk dashboard → Integrations → Webhooks
    # → Signing secret. Generated locally via `openssl rand -hex 32`; not
    # derived from the API key pair.
    CLOUDTALK_WEBHOOK_SECRET: str = ""
    # ── Webhook replay protection (M6-P0.12) ────────────────────────────────
    # When an inbound webhook carries an ``X-CloudTalk-Timestamp`` header, the
    # timestamp is folded into the HMAC-signed material and the request is
    # rejected if the timestamp is outside ±TOLERANCE seconds of now — a
    # captured request cannot be replayed once it ages past the window.
    CLOUDTALK_WEBHOOK_TOLERANCE_SECONDS: int = 300
    # When True the webhook REQUIRES a fresh ``X-CloudTalk-Timestamp`` header
    # and rejects any request without one (401). Default False so the
    # integration keeps accepting CloudTalk's legacy body-only signature; flip
    # True once you confirm your CloudTalk plan sends signed timestamps (see
    # the CloudTalk activation checklist in CLAUDE.md).
    CLOUDTALK_WEBHOOK_REQUIRE_TIMESTAMP: bool = False
    # Background sync loop cadence (Phase 5 — historical backfill + catch-up
    # after webhook downtime). Clamped to >=300s in the loop.
    CLOUDTALK_SYNC_INTERVAL_SECONDS: int = 3600
    # On first sync (or after long downtime) backfill calls from the last N
    # days. Older calls are skipped — out of scope for the ATS workflow.
    CLOUDTALK_HISTORICAL_BACKFILL_DAYS: int = 30

    # ── Traffit daily sync (scheduled import) ────────────────────────────────
    # Keeps Nexus in sync with Traffit: daily incremental delta (updated_at >=
    # watermark) + weekly full-scan reconcile safety net. The importer is the
    # same one used for the one-time migration (app/services/traffit/importer.py)
    # — every write is ON CONFLICT idempotent. Secrets (TRAFFIT_TENANT,
    # TRAFFIT_CLIENT_ID, TRAFFIT_CLIENT_SECRET, TRAFFIT_THROTTLE_RPS) are read
    # from the environment by TraffitConfig.from_env() — NOT declared here.
    #
    # Kill-switch: when False the loop exits immediately and POST
    # /api/admin/traffit/sync returns 503. Default OFF until activated.

    # ── COMPASS: dni robocze (decyzja D5) ────────────────────────────────
    # Mianownik wskaznikow „na dzien". Do 2026-08-31 Power Calling dzielil
    # przez sztywne 5 i publikowal imienna liste „ponizej progu", wiec osoba
    # na urlopie ladowala na niej pod nazwiskiem.
    #
    # SEKRET JEST WLASNY, NIE `CRON_SECRET` COMPASSA — tamten odblokowuje tez
    # /api/migrate-compliance, czyli DDL na bazie COMPASSA.
    #
    # Domyslnie WYLACZONE: bez tych trzech ustawien sync konczy sie przed
    # wyjsciem na siec, a Power Calling dalej mowi „nie wiem" zamiast zgadywac.
    COMPASS_AVAILABILITY_ENABLED: bool = False
    COMPASS_AVAILABILITY_URL: str = ""
    COMPASS_AVAILABILITY_SECRET: str = ""
    RECRUITMENT_ALLOCATION_ENABLED: bool = False

    COMPASS_WORKDAYS_ENABLED: bool = False
    COMPASS_WORKDAYS_URL: str = ""
    COMPASS_WORKDAYS_SECRET: str = ""
    # Ile miesiecy wstecz odswiezamy przy kazdym przebiegu. Wnioski urlopowe
    # bywaja akceptowane wstecznie („urlop wypisany post factum" widnieje
    # w produkcji COMPASSA), wiec sam biezacy miesiac by ich nie dogonil.
    COMPASS_WORKDAYS_LOOKBACK_MONTHS: int = 3
    COMPASS_WORKDAYS_SYNC_INTERVAL_SECONDS: int = 21600  # 6 h

    # ── COMPASS: cykl zycia pracownika ───────────────────────────────────
    # COMPASS jest zrodlem prawdy o zatrudnieniu (`employment_status` odbiera
    # tam dostep w trzech warstwach), a NEXUS flipuje `users.is_active`
    # RECZNIE — wiec konto osoby, ktora odeszla, bywa aktywne tygodniami.
    #
    # Znowu WLASNY sekret, nie `CRON_SECRET` COMPASSA (patrz wyzej) i nie ten
    # od dni roboczych: `WORKDAYS_EXPORT_SECRET` otwiera dokladnie jedna trase
    # i ta wlasnosc ma zostac.
    #
    # Domyslnie WYLACZONE. Ta petla ODBIERA ludziom dostep, wiec wlaczenie jej
    # jest decyzja operatora, nie efektem ubocznym deployu.
    COMPASS_LIFECYCLE_ENABLED: bool = False
    COMPASS_LIFECYCLE_URL: str = ""
    COMPASS_LIFECYCLE_SECRET: str = ""
    COMPASS_LIFECYCLE_SYNC_INTERVAL_SECONDS: int = 21600  # 6 h

    # ── COMPASS: provisioning klucza konta serwisowego (Etap 2) ──────────
    # Kierunek Compass→NEXUS (pobranie kontraktorów) uwierzytelnia się kluczem
    # konta serwisowego (`X-API-Key`, scope `contractors:read`). Klucz wydaje
    # normalnie admin przez Ustawienia → Konta serwisowe. Ta zmienna to
    # bramka na sytuacje, w których UI admina jest niedostępne (aktywacja
    # przez CI/env): jeśli USTAWIONA, startup NEXUSA idempotentnie zakłada
    # konto `compass-integration` (scope `contractors:read`) i klucz o TAKIM
    # skrócie, jaki wynika z podanej tu wartości. Wartość MUSI być pełnym
    # kluczem na drucie `nxs_v2_<24hex>_<sekret>` — ten sam string ustawia się
    # po stronie Compassa jako `NEXUS_CONTRACTORS_API_KEY`.
    #
    # Po aktywacji zmienną należy WYCZYŚCIĆ — klucz już żyje w bazie
    # (rewokowalny, audytowalny), a pusty env czyni ten mechanizm bezczynnym.
    # Nie loguje sekretu; przy złym formacie nie wywraca startu (log + no-op).
    COMPASS_INTEGRATION_BOOTSTRAP_KEY: str = ""

    # ── Multiposting (0360/0381): Pracuj.pl, JustJoin.IT, RocketJobs ────────
    # Flagi OFF = portal niewidoczny w UI, publikacja 409, worker kończy się
    # przed pętlą. Pracuj.pl czeka na dokumentację API (adres + klucz).
    PORTAL_PRACUJ_ENABLED: bool = False
    PORTAL_PRACUJ_API_URL: str = ""
    PORTAL_PRACUJ_API_KEY: str = ""
    # 0381: JustJoin.IT i RocketJobs to jedno Employer Public API (1EP,
    # `integrations.rocketjobs.com/docs/1ep`) — dwie flagi (dwa portale dla
    # rekrutera), jeden adres, jedna aplikacja OAuth i jedno połączone konto
    # firmy (`job_board_connections`). Portal jest „ready” dopiero przy
    # fladze + client_id/secret/redirect_uri + aktywnym połączeniu.
    PORTAL_JJIT_ENABLED: bool = False
    PORTAL_ROCKETJOBS_ENABLED: bool = False
    PORTAL_JJIT_API_URL: str = "https://jobboardcore-external.justjoin.it/external-api"
    JJIT_OAUTH_CLIENT_ID: str = ""
    JJIT_OAUTH_CLIENT_SECRET: str = ""
    # Adres zarejestrowany u dostawcy — na hoście API, jak M365:
    # https://api.nexus.dynaminds.pl/api/job-boards/jjit/callback
    JJIT_OAUTH_REDIRECT_URI: str = ""
    JJIT_OAUTH_SCOPE: str = "profile offline_access"
    # Nadpisanie jednostki organizacyjnej odczytanej z `/oauth/me` (gdy konto
    # ma kilka jednostek albo claim nie przychodzi).
    PORTAL_JJIT_ORGANIZATION_UNIT_ID: str = ""
    PORTAL_ROCKETJOBS_ORGANIZATION_UNIT_ID: str = ""
    PORTAL_JJIT_HTTP_TIMEOUT_SECONDS: float = 30.0
    JOB_PORTAL_WORKER_INTERVAL_SECONDS: int = 60
    JOB_PORTAL_MAX_ATTEMPTS: int = 5
    # Co ile godzin worker sprawdza stan żywych ogłoszeń (wygasłe/usunięte).
    JOB_PORTAL_STATUS_SYNC_HOURS: int = 6

    TRAFFIT_SYNC_ENABLED: bool = False
    # Skutki uboczne dla etapów przychodzących z importu.
    #
    # Import pisze do `candidate_stages` surowym SQL-em (świadomie — warstwa
    # komend robi ~10 zapytań i 2 blokady na wiersz, w kolejności blokad
    # NIEZGODNEJ z wsadem, co w przeszłości się zakleszczało). Skutkiem było
    # to, że automatyzacje pipeline'u dotyczyły 0,4% ruchu. Ten przełącznik
    # włącza WĄSKI, wsadowy zestaw skutków idempotentnych — nigdy maili
    # do kandydatów.
    TRAFFIT_IMPORT_SIDE_EFFECTS_ENABLED: bool = False
    # Background loop wake cadence (how often it checks whether a run is due).
    # The actual import runs at most once/day (delta) + once/week (full),
    # gated on the persisted watermark — clamped to >=300s in the loop.
    TRAFFIT_SYNC_CHECK_INTERVAL_SECONDS: int = 1800
    # UTC hour at/after which the daily delta is allowed to run (low-traffic
    # window). The first run after enabling fires immediately regardless.
    TRAFFIT_SYNC_HOUR_UTC: int = 2
    # Weekday for the heavy full-scan reconcile (0=Mon … 6=Sun).
    TRAFFIT_SYNC_FULL_WEEKDAY: int = 6
    # Overlap window subtracted from the last watermark when computing the
    # delta cutoff — absorbs clock skew / late-arriving edits. Idempotent
    # upserts make the overlap harmless.
    TRAFFIT_SYNC_DELTA_LOOKBACK_HOURS: int = 48
    # First-ever delta (no watermark yet) looks back this far to catch
    # everything changed in Traffit since the one-time migration. After that,
    # the watermark drives the cutoff.
    TRAFFIT_SYNC_INITIAL_BACKFILL_DAYS: int = 45
    # Consecutive failures after which ONE source row stops holding back the
    # delta watermark for every other row (see `_blocking_errors`). The retry
    # policy is deliberate: keep re-covering a failed record while it might be
    # transient, then park it explicitly rather than freezing the pipeline.
    # Measured on prod 2026-07-27: one candidate with a colliding e-mail had
    # frozen the daily watermark for 7 days, so `traffit=degraded` was permanent
    # and any NEW failure was invisible behind it. 5 runs ≈ 5 days at the daily
    # cadence — long enough that a real outage recovers on its own first.
    TRAFFIT_MAX_ROW_ATTEMPTS: int = 5
    # How many candidates the full reconcile sweeps for missing files in ONE
    # run. The sweep visits every Traffit candidate (not just those with no
    # files at all), which is one /files call each — ~57k at
    # TRAFFIT_THROTTLE_RPS=5 is ~3.2 h. Budgeted and resumable: the phase
    # persists an `after_id` cursor and the next run continues from there, and
    # an operator can close a backlog faster by triggering
    # POST /api/admin/traffit/sync?mode=full repeatedly.
    #
    # The budget is NOT free to raise to "cover everything in one pass", and
    # not for the obvious reason. A killed run resumes from its cursor, so the
    # sweep itself loses nothing — but a full run re-scans the UNBUDGETED
    # phases too (candidates ~57k, pipelines ~185k, activities ~397k) every
    # time, and those have no per-slice budget to skip. So each extra run costs
    # a full re-scan of everything else, which argues for a LARGER budget,
    # while a run still going during the workday is likelier to be killed
    # mid-sweep by a redeploy, which argues for a smaller one.
    #
    # 25k balances the two: the files phase runs ~1.4 h, a whole run lands
    # around 05:00 UTC (07:00 local) — before pushes to main start — and the
    # base is covered in ~3 runs instead of ~6. Combined with the nightly
    # catch-up in `should_run_full`, a backlog closes in about three nights
    # rather than a month and a half.
    TRAFFIT_SYNC_FULL_FILES_LIMIT: int = 25000
    # Delta: kandydaci z Traffita z nazwą CV (`cv_filename`), ale bez żadnego
    # pobranego dokumentu — dołączani do fazy plików niezależnie od
    # `updated_at >= run_start`. Bez tego kandydat zaimportowany w biegu, który
    # deploy zabił przed fazą plików, wypadał z zakresu każdej kolejnej delty
    # (nowy bieg = nowy `run_start`) i czekał na niedzielny pełny sweep
    # (prod 22.09.2026: 14 z 50 najnowszych bez pliku po >2 h). Okno w dniach od
    # utworzenia i sufit na bieg — trwale niepobieralne pliki nie mogą zjadać
    # każdej delty.
    TRAFFIT_SYNC_PENDING_FILES_DAYS: int = 14
    TRAFFIT_SYNC_PENDING_FILES_LIMIT: int = 500
    # Same idea for the `"? ?"` name-recovery sweep, but a much tighter budget:
    # every row costs an LLM call, and the selection is NOT self-clearing (a CV
    # that yields no name stays `"?"`), so an unbounded pass would re-pay for the
    # same `ORDER BY id` prefix forever and never reach the tail. Budgeted +
    # resumable via an `after_id` cursor, full reconcile only — delta already
    # scopes itself to the rows it just touched.
    TRAFFIT_SYNC_ENRICH_NAMES_LIMIT: int = 500
    # Sufit fazy candidates_cv_fields (parse pól skills/city/years dla
    # kandydatów dotkniętych w biegu; ~$0,008/CV na Haiku). Nocna delta to
    # zwykle dziesiątki wierszy — 200 ogranicza patologiczny bieg do ~$1,6.
    TRAFFIT_SYNC_CV_FIELDS_LIMIT: int = 200
    # Faza `candidates_cv_text`: ile zapisanych CV bez tekstu odczytać w jednym
    # biegu (ekstrakcja lokalna: pdfplumber/python-docx, OCR tylko dla skanów).
    TRAFFIT_SYNC_CV_TEXT_LIMIT: int = 1000

    # audyt 22.09 r2 (INTG-01/02, INTG-03, DATA-01/PROD-03, REC-01, DATA-03/04,
    # PROD-01) — jeden blok ustawień obszaru „Traffit, automaty, dane".
    # INTG-01: przerwana próba (deploy w trakcie) wznawia się od faz, których
    # jeszcze nie skończyła — o ile ta sama `since` i ostatni ślad próby młodszy
    # niż tyle godzin. Starsza próba = zaczynamy od nowa.
    TRAFFIT_SYNC_ATTEMPT_RESUME_HOURS: int = 24
    # INTG-03: delta `pipelines` czyta /recruitment_history od NAJNOWSZYCH
    # (`id DESC`) i kończy na stronie, na której pojawił się wpis starszy niż
    # `since` — zamiast pełnego przeglądu ~200 tys. wierszy w każdej delcie.
    TRAFFIT_PIPELINES_DELTA_TAIL: bool = True
    # REC-01: przepięcia podobnych rekrutacji dla etapów wstawionych przez import
    # (99,6% ruchów). Tylko wiersze z ostatnich tylu dni — import historii nie
    # może przepinać ludzi wysłanych do klienta rok temu.
    TRAFFIT_IMPORT_REASSIGN_ENABLED: bool = True
    TRAFFIT_IMPORT_REASSIGN_WINDOW_DAYS: int = 7
    # DATA-03/04: retencja kolejek i dzienników automatów (pętla co 6 h).
    QUEUE_RETENTION_ENABLED: bool = True
    QUEUE_RETENTION_INTERVAL_SECONDS: int = 6 * 3600
    AUTOMATION_LOG_RETENTION_DAYS: int = 30
    QUEUE_OUTBOX_RETENTION_DAYS: int = 30
    # DATA-04/PROD-10: surowe wyniki przeglądów AUTOMATYCZNYCH (~190 MB każdy)
    # żyją tyle dni; propozycje z nich są już w `job_proposals`.
    AUTO_FULL_REVIEW_RETENTION_DAYS: int = 2
    # PROD-01: katalog, w którym cron hosta zapisuje `backup-volume.json`
    # (montowany read-only do kontenera backendu).
    HOST_STATUS_DIR: str = "/run/nexus-host-status"

    # ── Notes insights sync (świeżość faktów z notatek) ─────────────────────
    # Cykliczna ekstrakcja `cv_extracted_data._notes_insights` po imporcie
    # 08.2026. Płacą wyłącznie kandydaci ze zmienionymi notatkami (fingerprint
    # + honorowanie wierszy legacy) — patrz app/tasks/notes_insights_sync.py.
    NOTES_INSIGHTS_SYNC_ENABLED: bool = False
    # Jak często pętla sprawdza, czy bieg jest należny (clamp >=300 s w pętli);
    # sam bieg jest najwyżej raz dziennie.
    NOTES_INSIGHTS_SYNC_CHECK_INTERVAL_SECONDS: int = 1800
    # Godzina UTC, od której dzienny bieg może ruszyć — PO nocnym Traffit
    # syncu (02:00), żeby ekstrakcja widziała świeżo zaimportowane notatki.
    NOTES_INSIGHTS_SYNC_HOUR_UTC: int = 4
    # Sufit kandydatów na bieg (~$0,002/kandydata na Haiku). Ogranicza koszt
    # pojedynczego dnia; zaległość zbiega w kolejnych dobach.
    NOTES_INSIGHTS_SYNC_BATCH_LIMIT: int = 300
    # Dodatkowy sufit na bieg: kandydaci, których notatki się NIE zmieniły, ale
    # ich fakty policzono starszą wersją promptu (np. przed dodaniem trybu
    # pracy, 22.09.2026). Idą po zmienionych, więc nowe notatki zawsze mają
    # pierwszeństwo. ~16 tys. wierszy przy 700/dobę = ok. 3 tygodnie,
    # ~0,004 USD/kandydata na DeepSeek. 0 = nie doganiaj starych wersji.
    NOTES_INSIGHTS_SYNC_UPGRADE_LIMIT: int = 700

    # ── Weekly eval guard (strażnik jakości matchingu) ──────────────────────
    # Cotygodniowy pomiar harnessem na zamrożonych 50 ofertach + alert regresu
    # >15% t/t (Sentry przez logger.error). Patrz app/tasks/weekly_eval.py.
    WEEKLY_EVAL_ENABLED: bool = False
    WEEKLY_EVAL_CHECK_INTERVAL_SECONDS: int = 3600
    # Niedziela (0=pon … 6=niedz), po nocnych syncach.
    WEEKLY_EVAL_WEEKDAY: int = 6
    WEEKLY_EVAL_HOUR_UTC: int = 5
    # Sufit czasu subprocesu harnessu (dzisiejsze biegi: ~12-15 min).
    WEEKLY_EVAL_TIMEOUT_SECONDS: int = 3600

    # ── Match digest (cotygodniowy push top dopasowań do rekruterów) ────────
    # Adopcja rekomendacji wymaga PUSH, nie pull: digest wysyła in-app
    # notyfikację z top świeżych dopasowań per opublikowana rekrutacja do jej
    # rekrutera/TAC. Patrz app/tasks/match_digest.py.
    MATCH_DIGEST_ENABLED: bool = False
    MATCH_DIGEST_CHECK_INTERVAL_SECONDS: int = 3600
    # Poniedziałek 06:00 UTC — początek tygodnia pracy.
    MATCH_DIGEST_WEEKDAY: int = 0
    MATCH_DIGEST_HOUR_UTC: int = 6
    # Minimalny score dopasowania w digeście — digest 20-punktowych trafień
    # to spam, który zabija zaufanie do funkcji.
    MATCH_DIGEST_MIN_SCORE: float = 55.0
    MATCH_DIGEST_TOP_N: int = 5

    # ── Retencja pełnego przeglądu bazy (candidate_search_runs/results) ─────
    # Każdy przegląd zapisuje wiersz na KAŻDEGO kandydata w bazie (z dowodami
    # w JSONB), więc bez retencji tabela wyników rośnie o całą bazę na każde
    # kliknięcie. Decyzja 10.09: 7 dni od zakończenia, ale najnowszy przegląd
    # z wynikami na (autor, otwarta rekrutacja) — a ad hoc na autora — zostaje
    # dłużej, najwyżej PROTECT_MAX_DAYS (bez tej granicy tabela rosłaby
    # z liczbą par, nie z czasem). Patrz app/tasks/candidate_search_retention.py.
    # Pętla kończy się PRZED `while True`, gdy wyłączona; interwał ma w pętli
    # podłogę 300 s.
    CANDIDATE_SEARCH_RETENTION_ENABLED: bool = True
    CANDIDATE_SEARCH_RETENTION_DAYS: int = 7
    CANDIDATE_SEARCH_RETENTION_PROTECT_MAX_DAYS: int = 90
    CANDIDATE_SEARCH_RETENTION_CHECK_INTERVAL_SECONDS: int = 3600

    # ── Global candidate contact queue ──────────────────────────────────────
    # All three gates are deliberately OFF by default.  The feature owns only
    # contact coordination inside Nexus; it never writes stages or contact
    # outcomes back to Traffit.
    CANDIDATE_CONTACT_ENABLED: bool = False
    # Enables assignment/reassignment/cooldown processing.  Keeping this
    # separate from the read/API gate allows a safe read-only rollout first.
    CANDIDATE_CONTACT_ASSIGNMENT_ENABLED: bool = False
    # Enables the strict read-only recruitment_history poller.  This still
    # requires CANDIDATE_CONTACT_ENABLED and valid Traffit read credentials.
    CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED: bool = False
    # Required cutover boundary for automatic intake.  Rows older than this
    # timestamp remain neutral historical data and never consume queue slots.
    CANDIDATE_CONTACT_ACTIVATION_AT: Optional[datetime] = None
    # Runtime loops clamp unsafe values, so a bad env cannot create a hot loop.
    CANDIDATE_CONTACT_WORKER_INTERVAL_SECONDS: int = 60
    CANDIDATE_CONTACT_WORKER_BATCH_SIZE: int = 100
    CANDIDATE_CONTACT_TRAFFIT_POLL_INTERVAL_SECONDS: int = 300
    # The remote query intentionally overlaps the durable tuple cursor.  A
    # ledger keyed by Traffit history id makes this safe and absorbs clock skew.
    CANDIDATE_CONTACT_TRAFFIT_OVERLAP_MINUTES: int = 15

    # ── Follow-up z kandydatem, gdy klient milczy (0372, 24.09.2026) ──────
    # Decyzje Artura: 14 dni kalendarzowych ciszy klienta i braku kontaktu,
    # dzwoni rekruter procesu, który zaszedł najdalej, wchodzą WYŁĄCZNIE CV
    # wysłane od 24.09.2026 (bez historii), „nie odebrał” przypomina co
    # 2 dni robocze bez limitu. Wyłącznik chowa listę i plakietki.
    CANDIDATE_FOLLOWUP_ENABLED: bool = True
    CANDIDATE_FOLLOWUP_SINCE: date = date(2026, 9, 24)
    CANDIDATE_FOLLOWUP_DAYS: int = 14
    CANDIDATE_FOLLOWUP_RETRY_BUSINESS_DAYS: int = 2

    # ── Traffit bidirectional integration (plan 2026-07-16) ────────────────
    # Twarde kill-switche środowiskowe. Runtime control w tabeli
    # `traffit_integration_control` może dodatkowo pauzować kierunek, ale
    # NIGDY nie może włączyć wyłączonego env gate'a. Bezpieczne defaulty
    # rolloutu: accept/apply/poll/send OFF; dry-run ON.
    TRAFFIT_INTEGRATION_ENABLED: bool = False
    TRAFFIT_WEBHOOK_ACCEPT_ENABLED: bool = False
    TRAFFIT_INBOUND_APPLY_ENABLED: bool = False
    TRAFFIT_POLL_ENABLED: bool = False
    TRAFFIT_OUTBOUND_ENABLED: bool = False
    TRAFFIT_DRY_RUN: bool = True

    # SHA-256 wysokoentropijnego sekretu osadzonego w URL subskrypcji webhooka.
    # Plaintext generowany raz, nigdy nie przechowywany w env ani DB. HMAC
    # konfigurować tylko jeśli tenant potwierdzi podpisywanie.
    TRAFFIT_INTEGRATION_WEBHOOK_SECRET_HASH: str = ""
    TRAFFIT_INTEGRATION_WEBHOOK_HMAC_SECRET: str = ""

    # Live streams muszą mieścić się w 15-minutowym SLO widoczności. Workery
    # clampują niebezpieczne wartości; jeden globalny limiter dla obu kierunków.
    TRAFFIT_INTEGRATION_POLL_INTERVAL_SECONDS: int = 300
    TRAFFIT_INTEGRATION_FILE_SWEEP_INTERVAL_SECONDS: int = 600
    TRAFFIT_INTEGRATION_WORKER_INTERVAL_SECONDS: int = 5
    TRAFFIT_INTEGRATION_SCHEMA_REFRESH_INTERVAL_SECONDS: int = 86400
    TRAFFIT_INTEGRATION_FULL_RECONCILE_INTERVAL_SECONDS: int = 604800
    TRAFFIT_INTEGRATION_DELTA_LOOKBACK_HOURS: int = 48
    TRAFFIT_INTEGRATION_HISTORY_API_BUDGET_PERCENT: int = 20

    # Retry/leader/tombstone safety controls.
    TRAFFIT_INTEGRATION_MAX_ATTEMPTS: int = 8
    TRAFFIT_INTEGRATION_LEASE_TTL_SECONDS: int = 90
    TRAFFIT_INTEGRATION_LEASE_HEARTBEAT_SECONDS: int = 30
    TRAFFIT_INTEGRATION_TOMBSTONE_MISSING_STRIKES: int = 2
    TRAFFIT_INTEGRATION_TOMBSTONE_GRACE_DAYS: int = 7

    # ── Microsoft Teams notifications (Phase 7.6) ────────────────────────────
    # Kill-switch: when False, /api/teams-channels/* keep working for CRUD but
    # outbound posts are no-op'd (logged, return False) so admins can stage
    # configuration before flipping the integration on. When True the AAD app
    # client credentials below MUST be set or sends will fail. Default OFF —
    # admin consent for `ChannelMessage.Send` is required first.
    TEAMS_NOTIFICATIONS_ENABLED: bool = False
    # Tenant-specific (NOT "common") — client_credentials flow requires the
    # actual tenant GUID. Defaults to M365_TENANT_ID at runtime if blank.
    TEAMS_TENANT_ID: str = ""
    # AAD app client ID. Reuses M365_CLIENT_ID at runtime if blank — same app
    # registration is fine as long as `ChannelMessage.Send` *Application*
    # permission is granted with admin consent.
    TEAMS_CLIENT_ID: str = ""
    # AAD app client secret. Reuses M365_CLIENT_SECRET at runtime if blank.
    # Application permissions need a confidential client (not public PKCE).
    TEAMS_CLIENT_SECRET: str = ""

    # ── Zamówienia wielo-konsultantowe (BIK / Polkomtel / BNP) ───────────────
    # CSV z ``client_id`` klientów rozliczanych w modelu T&M na MD, u których
    # jedno zamówienie obejmuje kilku konsultantów naraz. Każdy inny klient
    # dostaje niezmieniony widok jednoosobowy — patrz
    # ``app/services/multi_consultant_orders.py``.
    #
    # CSV (nie ``list[int]``) z tego samego powodu co ``SSO_ALLOWED_DOMAINS``:
    # pydantic-settings v2 wymusiłby na liście składnię JSON w zmiennej
    # środowiskowej. Parsuj przez ``settings.multi_consultant_order_client_ids``.
    #
    # Pusto = funkcja nieaktywna dla WSZYSTKICH klientów (fail-closed): nowe
    # tabele stoją puste, a zakładka „Zamówienia" renderuje dotychczasowy widok.
    # Dodanie kolejnego klienta to zmiana tej zmiennej w Coolify, bez deployu.
    MULTI_CONSULTANT_ORDER_CLIENT_IDS: str = ""

    # CSV z ``client_id`` klientów, u których zamówienie może być KOSZTOWE —
    # z ustaloną z góry kwotą, z której schodzi się fakturami (Polkomtel).
    #
    # Świadomie OSOBNA lista od ``MULTI_CONSULTANT_ORDER_CLIENT_IDS``, mimo że
    # dziś jest jej podzbiorem: BIK i BNP rozliczają się wyłącznie na MD, więc
    # checkbox „Zamówienie kosztowe" w ich formularzu byłby zaproszeniem do
    # założenia zamówienia, którego nikt nigdy nie rozliczy. Sklejenie obu list
    # w jedną zabrałoby możliwość tego rozróżnienia.
    #
    # Pusto = funkcja nieaktywna dla WSZYSTKICH (fail-closed).
    COST_ORDER_CLIENT_IDS: str = ""

    # ── Dziennik obserwacji poziomu seniority ───────────────────────────────
    # Poziom liczy się PRZY ODCZYCIE i tak zostaje. Ta pętla nie przechowuje
    # poziomu — obserwuje go, żeby zmiana wynikająca z przepisanej historii
    # atrybucji (import Traffita, przepięcie placementu) przestała być
    # niewidoczna. `false` → pętla kończy się PRZED pętlą, trasa odczytu
    # zostaje (dziennik historyczny musi dać się przeczytać).
    INSIGHTS_SENIORITY_JOURNAL_ENABLED: bool = True
    # Doba, bo mierzymy zdarzenie rzadkie i nienagłe. Krótszy odstęp nie
    # wykryje niczego więcej — zapis powstaje wyłącznie przy ZMIANIE.
    INSIGHTS_SENIORITY_JOURNAL_INTERVAL_HOURS: float = 24.0

    # ── Integracje zewnętrzne (scrapery pracuj.pl / JJIT) ───────────────────
    # Pętla alertów o zastoju: `false` → kończy się PRZED pętlą, badge „stale"
    # w Insights liczy się dalej z tej samej reguły (services.integration_runs).
    INTEGRATION_STALE_ALERTS_ENABLED: bool = True
    # Doba harmonogramu + 2 h zapasu na launchd/caffeinate na Macu.
    INTEGRATION_STALE_AFTER_HOURS: float = 26.0
    INTEGRATION_STALE_CHECK_MINUTES: float = 30.0
    # Jeden alert Slack na źródło na dobę; stan w `integration_alert_state`,
    # żeby restart (deploy) nie wysyłał go od nowa.
    INTEGRATION_ALERT_COOLDOWN_HOURS: float = 24.0

    # ── Import JJIT/RocketJobs w NEXUS (etap 2) ─────────────────────────────
    # Sekrety (JJIT_EMAIL, JJIT_PASSWORD, JJIT_TRAFFIT_CLIENT_ID/SECRET) idą z
    # env jak TRAFFIT_* — NIE są tu deklarowane. Kill-switch przed pętlą;
    # `false` → job nie startuje, endpoint admina /run nadal działa (ręcznie).
    JJIT_ENABLED: bool = False
    # Tydzień równoległej obserwacji: dry_run = liczy „nowi/duplikaty/błędy",
    # nic nie zapisuje w Traffit ani w NEXUS poza raportem runu.
    JJIT_DRY_RUN: bool = True
    JJIT_RUN_HOUR_LOCAL: int = 13
    JJIT_RUN_MINUTE_LOCAL: int = 0
    # Okno aplikacji per run; dedupe po `integration_external_items` i tak
    # odfiltruje powtórki, więc zapas dwóch dni nic nie kosztuje.
    JJIT_LOOKBACK_DAYS: int = 2
    JJIT_STATES: str = "published"
    # Ta sama reguła co w scraperze na Macu (decyzja 2026-09-16).
    JJIT_MATCH_MIN_SCORE: float = 65.0
    JJIT_REQUIRE_MUST_MATCH: bool = True
    # Loopback do własnego API (jeden worker uvicorna) + nazwa klienta OAuth,
    # dla którego job mintuje token (migracja 0311, acting_user = sourcer/TCM).
    JJIT_NEXUS_INTERNAL_URL: str = "http://127.0.0.1:8000"
    JJIT_OAUTH_CLIENT_NAME: str = "Scrapery pracuj.pl + JJIT"

    # ── Powiadomienia Delivery Leada ────────────────────────────────────────
    # Kill-switch całej sekcji: `false` → skaner kończy się przed pętlą, a
    # `emit` nie zapisuje niczego. Trasy odczytu zostają (log historyczny musi
    # dać się przeczytać nawet po wyłączeniu generowania nowych wpisów).
    DL_ALERTS_ENABLED: bool = True
    # Co ile godzin przemiata warunki. 24 h jak sąsiednie skanery — te alerty
    # dotyczą spraw mierzonych w dniach, nie w minutach.
    DL_ALERTS_INTERVAL_HOURS: float = 24.0
    # Próg „mało MD na zamówieniu". JEDNAKOWY dla wszystkich klientów i
    # zamówień — ticket wprost zabrania konfiguracji per klient, bo próg ma
    # znaczyć to samo w każdym raporcie.
    # Panel „Moi klienci" (09.2026): pierwsze przypomnienie przy 21 MD.
    DL_ALERT_MD_THRESHOLD: float = 21.0
    # Co ile dni ponawiać alert, którego przyczyna nie ustąpiła. Powtórka to
    # NOWY wiersz, nie aktualizacja — patrz `app/services/dl_alerts.py`.
    DL_ALERT_REPEAT_DAYS: int = 7
    # Pierwsze przypomnienie o zamówieniu KOSZTOWYM: tyle złotych zostało
    # w budżecie (budget_remaining).
    DL_ALERT_COST_BUDGET_THRESHOLD: float = 10000.0
    # Wysoki priorytet + mail dla MD i kosztowych: pozostałość wystarcza na
    # tyle dni roboczych przy dotychczasowym tempie zużycia zamówienia.
    DL_ALERT_HIGH_PRIORITY_WORKDAYS: int = 7
    # Okno przypomnień o zamówieniu okresowym / umowie z datą końca (dni).
    DL_ALERT_ENDING_WINDOW_DAYS: int = 30
    # Maile z progów (T-14, T-7, wysoki priorytet MD/kosztowy). `false`
    # zostawia karty w panelu, ale nie wysyła niczego.
    DL_ALERT_EMAIL_ENABLED: bool = True

    # CSV z ``client_id`` klientów z ROZSZERZONYM zestawem alertów zamówień
    # (BNP Paribas Bank Polska). Dwie rzeczy naraz, obie opisane w
    # ``app/services/order_alert_policy.py``:
    #   1. linia zamówienia wielo-konsultantowego dostaje kartę „kończy się
    #      okres" w panelu „Moi klienci" (mail + powtórka co 7 dni) — u
    #      pozostałych klientów tę kartę mają wyłącznie zamówienia okresowe;
    #   2. osobny alert, gdy zużycie PODSTAWY MD (``md_total``) przekroczy
    #      ``DL_ALERT_MD_BASE_USAGE_PERCENT``.
    #
    # Pusto = funkcja nieaktywna dla WSZYSTKICH (fail-closed): reguły zachowują
    # się dokładnie jak przed tą rewizją. Świadomie env, a nie zaszyte id:
    # „BNP" to RODZINA rekordów klienta (osobne wiersze oddziału i banku,
    # do tego Cardif), więc właściwy ``client_id`` ustala się na produkcji.
    EXTENDED_ORDER_ALERT_CLIENT_IDS: str = ""
    # Próg alertu o zużyciu podstawy MD (procent ``md_total``). Zakres
    # opcjonalny (``md_optional_total``) NIE wchodzi ani do licznika, ani do
    # mianownika — ticket pyta o podstawę, a opcja jest rezerwą z umowy.
    #
    # Osobny próg od ``DL_ALERT_MD_THRESHOLD``, a nie jego zamiennik: tamten
    # zostaje globalny i bezwzględny („mało MD" ma znaczyć to samo u każdego
    # klienta), a ten jest wczesnym ostrzeżeniem dla klientów z listy wyżej.
    DL_ALERT_MD_BASE_USAGE_PERCENT: float = 80.0

    # ── Finanse → Zmiany w zamówieniach: Braki ──────────────────────────────
    # Kill-switch detektora braków (zamówienie zakończone bez następcy):
    # `false` → pętla kończy się przed startem, zapis zamówienia i odczyt
    # zakładki nie wykrywają ani nie rozwiązują braków. Zapisane wpisy zostają
    # czytelne w Finansach.
    ORDER_GAPS_ENABLED: bool = True
    # Od jakiej daty końca zamówienia śledzimy braki. Bez granicy pierwszy
    # przebieg zamieniłby w „braki" lata normalnych odejść sprzed tej funkcji.
    ORDER_GAP_TRACKING_START: date = date(2026, 8, 1)
    # Ile dni wstecz od dziś wykrywamy nowe braki. Zamknięty miesiąc nie może
    # po tygodniach dostawać nowych wpisów (np. po usunięciu szkicu następcy).
    ORDER_GAP_LOOKBACK_DAYS: int = 45
    # Godzina (Europe/Warsaw) dziennego przebiegu — tuż po północy, żeby brak
    # „pojawił się następnego dnia" rano, a nie w środku dnia.
    ORDER_GAPS_RUN_HOUR_LOCAL: int = 0
    ORDER_GAPS_RUN_MINUTE_LOCAL: int = 30

    @property
    def multi_consultant_order_client_ids(self) -> frozenset[int]:
        """Parse MULTI_CONSULTANT_ORDER_CLIENT_IDS CSV into a set of client ids.

        Wpisy nienumeryczne są POMIJANE, nie wysadzają startu aplikacji: literówka
        w zmiennej środowiskowej ma wyłączyć funkcję jednemu klientowi, a nie
        położyć backend przy starcie (ta bramka nie jest krytyczna dla działania
        reszty systemu).
        """
        raw = self.MULTI_CONSULTANT_ORDER_CLIENT_IDS
        if not raw:
            return frozenset()
        ids: set[int] = set()
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                ids.add(int(chunk))
            except ValueError:
                continue
        return frozenset(ids)

    @property
    def cost_order_client_ids(self) -> frozenset[int]:
        """Parse COST_ORDER_CLIENT_IDS CSV into a set of client ids.

        Ta sama tolerancja na literówki co przy liście wielo-konsultantowej:
        nienumeryczny wpis jest pomijany, a nie wysadza startu backendu.
        """
        raw = self.COST_ORDER_CLIENT_IDS
        if not raw:
            return frozenset()
        ids: set[int] = set()
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                ids.add(int(chunk))
            except ValueError:
                continue
        return frozenset(ids)

    @property
    def extended_order_alert_client_ids(self) -> frozenset[int]:
        """Parse EXTENDED_ORDER_ALERT_CLIENT_IDS CSV into a set of client ids.

        Ta sama tolerancja na literówki co przy dwóch listach wyżej: nienumeryczny
        wpis jest pomijany, a nie wysadza startu backendu.
        """
        raw = self.EXTENDED_ORDER_ALERT_CLIENT_IDS
        if not raw:
            return frozenset()
        ids: set[int] = set()
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                ids.add(int(chunk))
            except ValueError:
                continue
        return frozenset(ids)

    @property
    def sso_allowed_domains_list(self) -> list[str]:
        """Parse SSO_ALLOWED_DOMAINS CSV into a list of lowercased domains."""
        if not self.SSO_ALLOWED_DOMAINS:
            return []
        return [
            d.strip().lower() for d in self.SSO_ALLOWED_DOMAINS.split(",") if d.strip()
        ]

    @property
    def password_login_break_glass_email_set(self) -> set[str]:
        """Parse PASSWORD_LOGIN_BREAK_GLASS_EMAILS CSV into a lowercased set.

        Emails here bypass the ``PASSWORD_LOGIN_ENABLED=False`` gate on /login,
        /forgot-password and /reset-password. Empty (default) → empty set → no
        exception (every password login stays blocked when the flag is off).
        """
        if not self.PASSWORD_LOGIN_BREAK_GLASS_EMAILS:
            return set()
        return {
            e.strip().lower()
            for e in self.PASSWORD_LOGIN_BREAK_GLASS_EMAILS.split(",")
            if e.strip()
        }

    @property
    def aad_group_role_map(self) -> dict[str, str]:
        """Parse ``AAD_GROUP_ROLE_MAP_JSON`` into a dict, raising on malformed JSON.

        We parse lazily (per-call) instead of in a ``@field_validator`` because
        validating the role values requires importing :class:`UserRole`, which
        creates a circular import at module load time
        (``app.core.config`` → ``app.models.user`` → ``app.core.database``).
        Lazy parsing keeps startup decoupled.
        """
        import json as _json

        if not self.AAD_GROUP_ROLE_MAP_JSON:
            return {}
        try:
            parsed = _json.loads(self.AAD_GROUP_ROLE_MAP_JSON)
        except _json.JSONDecodeError as exc:
            raise ValueError(
                "AAD_GROUP_ROLE_MAP_JSON is not valid JSON. "
                'Expected: \'{"<guid>": "admin", "<guid>": "recruiter"}\'. '
                f"Parser error: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError(
                "AAD_GROUP_ROLE_MAP_JSON must decode to an object, "
                f"got {type(parsed).__name__}"
            )
        # Validate role strings against UserRole enum (deferred import — see
        # docstring). Misspelled roles in env would otherwise silently no-op
        # at login → user blocked with confusing 403.
        from app.models.user import UserRole

        # ``user`` is retained in the Python/PG enum only for rolling-deploy
        # compatibility.  It is no longer a provisionable persona.
        valid_roles = {r.value for r in UserRole if r is not UserRole.user}
        out: dict[str, str] = {}
        for group_id, role in parsed.items():
            if role not in valid_roles:
                raise ValueError(
                    f"AAD_GROUP_ROLE_MAP_JSON contains unknown role {role!r} "
                    f"for group {group_id!r}. Valid: {sorted(valid_roles)}"
                )
            out[str(group_id)] = role
        return out

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        # Security: in production we MUST fail startup if SECRET_KEY is the
        # well-known default. Previously this was only a warnings.warn() call
        # which doesn't stop the container from booting — a misconfigured
        # Coolify env vault (variable missing) would silently boot with the
        # default key, making every JWT forgeable. Hard fail in production
        # turns a silent vulnerability into a noisy startup crash.
        is_default = (not v) or v.strip().lower() in {
            "change-me-in-production",
            "change-me",
        }
        # DEBUG flag is the dev-mode signal in this codebase.
        is_production = not bool(os.getenv("DEBUG", "").lower() in {"1", "true", "yes"})
        if is_default:
            if is_production:
                raise ValueError(
                    "SECRET_KEY is unset or left at the default in production. "
                    "Set a strong value in Coolify env vault. "
                    'Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
                )
            warnings.warn(
                "SECRET_KEY is unset or left at default. Set a strong value in .env. "
                'Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"',
                RuntimeWarning,
                stacklevel=2,
            )
        if len(v) < 32:
            warnings.warn(
                "SECRET_KEY is shorter than 32 chars — use at least 48 bytes of entropy.",
                RuntimeWarning,
                stacklevel=2,
            )
        return v

    @field_validator("M365_STATE_SIGNING_KEY")
    @classmethod
    def validate_m365_state_signing_key(cls, v: str) -> str:
        # Security: ensure M365_STATE_SIGNING_KEY is independent of SECRET_KEY
        # in production. Sharing the same key means an attacker who can forge
        # one type of token (user JWT) can also forge OAuth state JWTs and
        # vice versa — confused-deputy class of bug. We can't compare here
        # because Pydantic validators can't see other field values cleanly,
        # but we CAN reject the empty-string default in production (which
        # falls back to SECRET_KEY at runtime via _state_signing_key()).
        is_production = not bool(os.getenv("DEBUG", "").lower() in {"1", "true", "yes"})
        if not v and is_production:
            # Don't hard fail — the M365 integration is optional and most
            # deployments may not have configured it. But emit a stern warning
            # so admins notice during the migration.
            warnings.warn(
                "M365_STATE_SIGNING_KEY is empty in production — OAuth state "
                "JWTs will be signed with SECRET_KEY (shared signing key risk). "
                "Set this to a separate secret in Coolify env vault.",
                RuntimeWarning,
                stacklevel=2,
            )
        return v

    @model_validator(mode="after")
    def validate_candidate_identity_fingerprint_key(self) -> "Settings":
        key = self.CANDIDATE_IDENTITY_FINGERPRINT_KEY.strip()
        is_placeholder = key.casefold() in {
            "change-me",
            "change-me-in-production",
            "change-me-to-a-different-long-random-string-min-48-chars",
        }
        if not key or is_placeholder:
            if not self.DEBUG:
                raise ValueError(
                    "CANDIDATE_IDENTITY_FINGERPRINT_KEY is required in production "
                    "and must be independent from SECRET_KEY."
                )
            warnings.warn(
                "CANDIDATE_IDENTITY_FINGERPRINT_KEY is empty or a placeholder. "
                "Identity quarantine fingerprints are unavailable until a "
                "dedicated key is configured.",
                RuntimeWarning,
                stacklevel=2,
            )
            return self
        if key == self.SECRET_KEY:
            raise ValueError(
                "CANDIDATE_IDENTITY_FINGERPRINT_KEY must not equal SECRET_KEY."
            )
        if len(key) < 32:
            if not self.DEBUG:
                raise ValueError(
                    "CANDIDATE_IDENTITY_FINGERPRINT_KEY must contain at least "
                    "32 characters in production."
                )
            warnings.warn(
                "CANDIDATE_IDENTITY_FINGERPRINT_KEY is shorter than 32 characters.",
                RuntimeWarning,
                stacklevel=2,
            )
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# audyt 22.09 r2 (SEC-02): SECRET_KEY, który trafił do historii gita
# (commit bf5cb10f8). Trzymamy WYŁĄCZNIE prefiks skrótu SHA-256, nie klucz.
# Start z tym kluczem loguje błąd (main.py) — celowo NIE rzuca: odmowa startu
# położyłaby produkcję przy pierwszym auto-merge'u, a termin rotacji wybiera
# właściciel. Po rotacji ostrzeżenie znika samo.
LEAKED_SECRET_KEY_SHA256_PREFIXES = frozenset({"e76920d40b5cd73d"})


def secret_key_is_known_leaked(value: str | None) -> bool:
    if not value:
        return False
    import hashlib

    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return digest in LEAKED_SECRET_KEY_SHA256_PREFIXES


def log_if_secret_key_leaked(value: str | None) -> bool:
    """Loguje ERROR (→ Sentry), gdy działa klucz z historii gita. Nigdy nie rzuca."""
    if not secret_key_is_known_leaked(value):
        return False
    import logging

    logging.getLogger("app.core.config").error(
        "SECRET_KEY is the one leaked in git history — rotate it "
        "(procedure: new GH secret -> 'Coolify set env' redeploy=false -> Deploy)"
    )
    return True


settings = Settings()
