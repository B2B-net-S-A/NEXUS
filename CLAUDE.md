# CLAUDE.md — NEXUS (ATS)

> Ten plik trafia w całości do kontekstu każdej sesji, dlatego jest krótki:
> stos, zasady przekrojowe i lista obszarów. Szczegółowe reguły modułów leżą w
> `docs/claude/<obszar>/` i są tak samo wiążące jak ten plik.

## Jak korzystać z reguł

- Zanim zmienisz kod w jakimś obszarze, znajdź go na liście obszarów na dole,
  a jego pliki w „Pliki reguł NEXUSA” z początku sesji (hook SessionStart
  z `.claude/settings.json`; bez hooka: `ls docs/claude/<obszar>/`), i przeczytaj
  w całości te, które go dotyczą. Tam są decyzje Artura i reguły, które łatwo
  cofnąć „przy okazji”.
- Nie wiesz, który plik: `grep -ril "<słowo>" docs/claude/`.
- Nowa reguła = nowy plik w `docs/claude/<obszar>/` (albo dopisek do
  istniejącego), pierwsza linia `# Tytuł`. Tego pliku nie zmieniasz: lista
  plików nie stoi tu od 25.10.2026, bo dwa PR-y z regułą w jednym obszarze
  miały konflikt w kolejce merge'ów. Nowy obszar = wpis w `GROUPS`
  w `backend/scripts/build_claude_index.py` i `python3 scripts/build_claude_index.py`
  (z `backend/`).
- Do tego pliku nie dopisuj sekcji. 10.10.2026 miał 926 KB (ok. 530 tys.
  tokenów z okna 1 mln): każda sesja startowała w połowie zapełniona, a po
  zmianie pliku aplikacja wklejała go drugi raz i sesje kończyły się błędem
  „Prompt is too long”, którego kompaktowanie nie naprawiało. Limit 40 KB
  pilnuje `backend/tests/test_claude_md_index.py`.

## Stack & ports

- **Backend:** FastAPI 0.115 + SQLAlchemy 2.0 (async, asyncpg) + Alembic — `backend/`, port 8000.
- **Frontend:** Next.js 15.1 (App Router, React 19, TypeScript 5.7) — `frontend/`, port 3000.
- **Database:** Postgres 16-alpine (compose service) + Qdrant (vector DB, embeddings przez Voyage AI).
- **Auth:** JWT + RBAC.
- **Local AI:** Ollama (llama3.2) — opcjonalnie, dla offline pracy.
- **Test:** pytest + pytest-asyncio (BE) + Vitest + Playwright (FE).
- **Sentry:** `sentry-sdk[fastapi]` w `backend/requirements.txt`.

**Specyfika:** monorepo z dwoma podkatalogami `backend/` + `frontend/`, każdy ze swoim Dockerfile i package mgr.
Hosting: Coolify na Hetznerze, API `https://api.nexus.dynaminds.pl`.

## Praca i wdrożenie w skrócie

Szczegóły: `docs/claude/podstawy/ci-gotchas.md`, `deploy.md`, `healthcheck-endpoint.md`.

- Gałąź od świeżego `origin/main`, zmiany tylko przez PR. Na PR-ze biegnie
  sito (testy zmienionych plików + strażnicy repo), pełny pytest i frontend
  dopiero w kolejce merge'ów. Pełny bieg na gałęzi: `gh workflow run CI --ref <gałąź>`.
- Gotowy PR wchodzi do kolejki sam; sesja kończy `gh pr merge <nr> --squash --auto`.
  Draft albo etykieta `wstrzymaj` = nie wchodzi. Wypadł z kolejki: najpierw
  przyczyna z logów `merge_group`, potem poprawka.
- Wdrożenia pon–pt 18:00–08:00 (Warszawa), w weekend zawsze; w dzień roboczy
  `emergency` tylko na polecenie Artura. Potem `/api/health` → `version` = SHA
  z maina ze zmianą; dopiero wtedy test na produkcji.
- Lokalnie: `ruff`, testy bez bazy, `npx vitest run <pliki>`,
  `npm run type-check`. Testy z Postgresem sprawdza CI. Lokalny Docker
  dozwolony od 22.10.2026; stały staging na kopii produkcji to
  `docker-compose.staging.yml` (nowa pętla w lifespanie = wpis w
  `app/core/staging.py`). → `podstawy/staging-na-laptopie.md`
- Zmienne środowiskowe na produkcji zmienia wyłącznie workflow „Coolify set env”.
- Repo i logi Actions są publiczne: bez nazwisk, stawek i sekretów w kodzie,
  testach, logach i paragonach migracji.

## Zasady przekrojowe

Każda ma pełny opis w pliku w `docs/claude/`; tu tylko to, o co najłatwiej się potknąć.

- **Schemat bazy:** migracja Alembic i lustro DDL w `backend/entrypoint.sh`
  (alembic na produkcji bywa osierocony, entrypoint jest wtedy wdrożeniem).
  → `podstawy/healthcheck-endpoint.md`
- **„Dziś” to kalendarz firmy** (Europe/Warsaw): `business_today()` /
  `local_now()` z `app/core/scheduling.py`, nigdy `date.today()` ani data z UTC.
  → `podstawy/ci-gotchas.md`
- **Nowa trasa `/api/**`** ma bramkę sekcji albo opisany wyjątek, a w Delivery
  i Finansach alias z `api/permission_access.py` jako zależność trasy. Zmiana
  dostępu = diff wzorca `tests/data/authz_golden/`.
  → `uprawnienia/dziewiec-uprawnien-zamiast-rol-w-bramkach.md`
- **Ról `sourcer` i `tac` nie ma** (aliasy rekrutera), nie ma też typów
  rekrutacji. → `uprawnienia/jedna-rola-rekruter-zamiast-sourcera-rekrutera-i-tac.md`,
  `rekrutacja-tworzenie/bez-typow-rekrutacji.md`
- **Moduł z `@limiter.limit`** nie może mieć `from __future__ import annotations`
  (ciało żądania ląduje wtedy jako parametr query → 422).
- **Nazewnictwo:** w interfejsie i komunikatach `/jobs` to „Rekrutacje”, nie
  „Oferty”; warstwa techniczna zostaje po angielsku. → `ui/nazewnictwo-rekrutacja-nie-oferta-modul-jobs.md`
- **Front:** kolory wyłącznie z tokenów; tekst błędu przez `apiErrorMessage`;
  potwierdzenia przez `useConfirmV2()`, nigdy natywne `confirm()`/`alert()`;
  wysokość ekranu w `dvh`; awaria zapytania nie może wyglądać jak pusta lista
  (pusty stan wisi na `isSuccess`). → `ui/design-system-ui-zawsze-przy-pracy-nad-wygladem.md`,
  `ui/responsywnosc-reguly-po-audycie-23-09-2026.md`
- **Ekran docelowy to laptop 1280 × 720**: po zmianie UI przeklikaj też w tym
  rozmiarze, nie tylko na dużym monitorze.
- **Makiety i „jak to teraz wygląda”** pokazujesz na stagingu z laptopa:
  „przed” to zrzut z `localhost:3100`, „po” to kod z gałęzi na porcie 3101
  na tych samych danych; rysunek od zera tylko na wyraźną prośbę.
  → `ui/makiety-na-stagingu.md`
- **Zmiana na styku ról** (rekruter → DL → HoR, kwota tylko dla części ról)
  przechodzi na stagingu całą ścieżkę każdą rolą, zanim powstanie PR;
  logowanie jako dowolna osoba: `python -m scripts.staging_login_as`.
  → `podstawy/test-calej-sciezki-na-stagingu.md`
- **Nic nie znika z ekranów bez śladu:** inwentarze funkcji
  (`recruitment-feature-inventory.json`, `orders-contracts-feature-inventory.json`,
  `candidate-profile-feature-inventory.json`) i ich testy.
- **Ruch karty w rekrutacji** tylko przez `usePipelineMoveCore` / `usePipelineMove`;
  własne `POST /api/pipeline/move` na nowym ekranie to regresja.
  → `rekrutacja-tablica/sciezka-kandydata-przekazania-zweryfikowany-jeden.md`
- **AI:** model funkcji tylko z rejestru `services/ai_models.py`, wywołanie
  w kontekście `ai_feature()`; wynik modelu jest dodatkiem, nigdy warunkiem
  działania ścieżki. → `ai-jarvis/modele-ai-per-funkcja-decyzja-z-badania-na-danych.md`
- **Stemple:** zmiana logiki zamówień albo ekranu z przewodnikiem Jarvisa
  wymaga przeglądu i `python3 scripts/stamp_orders_procedure.py` /
  `stamp_screen_guides.py`. → `zamowienia/instrukcja-zamowien-w-pomocy-przestempluj-po.md`,
  `ai-jarvis/jarvis-2-pomoc-na-ekranie-dzien-pracy-pamiec.md`
- **Harnessy `/preview/*`** mają wyłącznie fikcyjne dane i nie wysyłają zapytań.

## Obszary reguł

Ścieżki są względne do `docs/claude/`. Wzmianki „patrz CLAUDE.md” w komentarzach
kodu sprzed 10.10.2026 odnoszą się do plików z tych katalogów.

<!-- INDEKS:START (generuje backend/scripts/build_claude_index.py — nie edytuj ręcznie) -->

- **Podstawy, wdrożenie, CI** — `podstawy/`: Deploy przez Coolify, `/api/health`, zmienne środowiskowe, CI i kolejka merge'ów, obciążenie, klucze API kont serwisowych, obsługa błędów API.
- **Role i uprawnienia** — `uprawnienia/`: Role, dziewięć uprawnień, bramki sekcji i tras, zakres Delivery Leada, kto widzi kwoty, rejestracja kont.
- **Interfejs i design** — `ui/`: Design system i tokeny, responsywność, nazewnictwo w interfejsie, Ustawienia, pulpit, wygląd tabel.
- **Rekrutacja: tworzenie i Profil Championa** — `rekrutacja-tworzenie/`: `/jobs/new`, odczyt requestu, wiersze wymagań i umiejętności krytyczne, Profil Championa, przekazanie do searchu, pliki, portale ogłoszeń, strona kariery.
- **Rekrutacja: lista, Tablica, panel osoby** — `rekrutacja-tablica/`: Lista `/jobs`, Tablica, ruch kart i bramki, panel osoby, QC CV i Cpro, przegląd DL, podobne rekrutacje, przydział rekruterów, dzwonki przekazań.
- **Screening, notatki, stawki kandydata** — `screening-notatki/`: Formularz i widok screeningu, karta rekomendacji, rodzaje notatek, wzmianki, „Stawka od” i zmiana stawki w procesie.
- **Kandydaci i wyszukiwanie** — `kandydaci-wyszukiwanie/`: Lista i profil kandydata, słowa kluczowe, kolejność „Dopasowanie”, Talent Radar, kategorie kompetencji, indeks wektorowy, „Moi ludzie”, podgląd CV.
- **Generator CV i automaty** — `generator-cv/`: Generator CV, reguły CV klienta, zgoda RODO, interaktywne CV, automaty rekrutacji (nocny przegląd bazy, auto-match, auto-CV).
- **AI i Jarvis** — `ai-jarvis/`: Rejestr modeli per funkcja, brak limitów AI, Jarvis (narzędzia, przewodniki ekranów, pamięć, umowy ramowe).
- **Klienci** — `klienci/`: Profil i karta klienta, scalanie i usuwanie klientów, Historia zdarzeń, Centrum e-Zdrowia.
- **Kontrakty i umowy B2B** — `kontrakty/`: Generator umów B2B, cykl życia kontraktu, zakończenie i cofnięcie, synchronizacja kontrakt ↔ zamówienia, dokumenty, zakładki rejestru.
- **Zamówienia i poczta zamówień** — `zamowienia/`: Poczta zamówień i odczyt PDF per klient, zamówienia MD, kosztowe i okresowe, import zużycia MD, alerty Delivery Leada, instrukcja zamówień.
- **Finanse i Insights** — `finanse-insights/`: Finanse → Zmiany w zamówieniach, Zamówienia PDF, Insights (Rywalizacja, Zespół, Firma, raporty).
- **Powiadomienia i maile** — `powiadomienia/`: Ikony paska, kategorie i wyciszenia, powiadomienia dla ról, maile do zespołu.
- **Integracje** — `integracje/`: Traffit, COMPASS, CloudTalk, kalendarz i rozmowy u klienta, prepy w Teams, archiwum pytań.
- **Ludzie w NEXUSIE** — `ludzie/`: Moduły przeniesione z Compassa (bez Akademii) i sprzęt recepcji.
- **Programy** — `programy/`: Akademia i program praktykanta — oba ukryte z UI od 17.10.2026.
- **Audyty przekrojowe** — `audyty/`: Reguły po audytach 22–25.09.2026 — przeczytaj przed zmianą w poczcie zamówień, MD, kontraktach, bezpieczeństwie albo integracjach.

<!-- INDEKS:END -->
