# CLAUDE.md — NEXUS (ATS)

> Ten plik trafia w całości do kontekstu każdej sesji, dlatego jest krótki:
> stos, zasady przekrojowe i indeks. Szczegółowe reguły modułów leżą w
> `docs/claude/<obszar>/` i są tak samo wiążące jak ten plik.

## Jak korzystać z reguł

- Zanim zmienisz kod w jakimś obszarze, znajdź go w indeksie na dole i
  przeczytaj w całości pliki, które go dotyczą. Tam są decyzje Artura
  i reguły, które łatwo cofnąć „przy okazji”.
- Nie wiesz, który plik: `grep -ril "<słowo>" docs/claude/`.
- Nowa reguła = nowy plik w `docs/claude/<obszar>/` (albo dopisek do
  istniejącego), pierwsza linia `# Tytuł`, potem
  `cd backend && python3 scripts/build_claude_index.py`, który odświeża indeks.
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

Każda ma pełny opis w pliku z indeksu; tu tylko to, o co najłatwiej się potknąć.

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

## Indeks reguł

Ścieżki są względne do `docs/claude/`. Wzmianki „patrz CLAUDE.md” w komentarzach
kodu sprzed 10.10.2026 odnoszą się do plików z tego indeksu.

<!-- INDEKS:START (generuje backend/scripts/build_claude_index.py — nie edytuj ręcznie) -->

### Podstawy, wdrożenie, CI — `podstawy/`

Deploy przez Coolify, `/api/health`, zmienne środowiskowe, CI i kolejka merge'ów, obciążenie, klucze API kont serwisowych, obsługa błędów API.

- `ci-gotchas.md`: CI gotchas · kolejka merge'ów, kolizje migracji, sito na PR, shardy, pokrycie, Trivy, E2E, minuty Actions, „dziś” = Europe/Warsaw
- `deploy.md`: Deploy
- `env-vars-build-time-vs-runtime.md`: Env vars (build-time vs runtime)
- `healthcheck-endpoint.md`: Healthcheck endpoint
- `konta-serwisowe-klucze-api-x-api-key.md`: Konta serwisowe / klucze API (`X-API-Key`)
- `manual-ops-cheat-sheet.md`: Manual ops cheat sheet
- `nul-w-zadaniach-i-detail-bledow-api-w-ui.md`: NUL w żądaniach i `detail` błędów API w UI (odbiór #1549)
- `observability.md`: Observability
- `po-fazie-1.md`: Po Fazie 1
- `specyfika-tej-apki.md`: Specyfika tej apki
- `stabilizacja-pod-obciazeniem-reguly-po-audycie-13.md`: Stabilizacja pod obciążeniem — reguły po audycie 13.09 i reaudycie 14.09.2026 · deploy = przerwa, ponowienia HTTP, polling, single-flight cache, XLSX, uploady
- `staging-na-laptopie.md`: Staging na laptopie — pełna kopia produkcji bez wyjścia na świat · `NEXUS_ENV=staging`, lista pętli, zapora HTTP, odtworzenie z backupu
- `tabele-worda-z-wgranych-plikow.md`: Tabele Worda z wgranych plików — komórki przez `app/core/docx_cells.py`
- `wersja-frontu-w-otwartej-karcie.md`: Otwarta karta sama przechodzi na nową wersję frontu

### Role i uprawnienia — `uprawnienia/`

Role, dziewięć uprawnień, bramki sekcji i tras, zakres Delivery Leada, kto widzi kwoty, rejestracja kont.

- `delivery-lead-widzi-kwoty-wlasnego-portfela-profil.md`: Delivery Lead widzi kwoty własnego portfela (profil klienta + Analityka)
- `delivery-lead-widzi-tylko-swoich-klientow-w.md`: Delivery Lead widzi tylko swoich klientów w modułach Delivery
- `dziewiec-uprawnien-zamiast-rol-w-bramkach.md`: Dziewięć uprawnień zamiast ról w bramkach (0410)
- `integralnosc-i-uprawnienia-reguly-po-audytach.md`: Integralność i uprawnienia — reguły po audytach Codexa 13–14.09.2026 (PR 1 i PR 2) · blokady wiersza kontraktu, bramka sekcji tras, CV nie są kasowane, kursor M365, konto za M365
- `jedna-rola-rekruter-zamiast-sourcera-rekrutera-i-tac.md`: Jedna rola „Rekruter” zamiast sourcera, rekrutera i TAC (0411)
- `rekrutacje-i-kandydatow-widza-wszyscy-stawki-do.md`: Rekrutacje i kandydatów widzą wszyscy; stawki do klienta nie widzi rekruter
- `rola-finance-pelny-odczyt-biznesowy-decyzje-artura.md`: Rola `finance` = pełny odczyt biznesowy (decyzje Artura 19.08 i 31.08)
- `rola-rada-nadzorcza-tylko-insights.md`: Rola „Rada nadzorcza” — tylko Insights z kwotami (0490)
- `role-uprawnienia-i-cele-audyt-22-09-2026.md`: Role, uprawnienia i cele — audyt 22.09.2026
- `self-service-registration-email-password.md`: Self-service registration (email/password — alternatywa dla Microsoft SSO)

### Interfejs i design — `ui/`

Design system i tokeny, responsywność, nazewnictwo w interfejsie, Ustawienia, pulpit, wygląd tabel.

- `design-system-ui-zawsze-przy-pracy-nad-wygladem.md`: Design system & UI — ZAWSZE przy pracy nad wyglądem
- `kafelek-do-uzupelnienia.md`: Kafelek „Do uzupełnienia”
- `klienci-kontrakty-finanse-spokojne-tabele.md`: Klienci, Kontrakty, Finanse — spokojne tabele
- `licznik-celow-w-gornym-pasku.md`: Licznik celów w górnym pasku · podpisane segmenty, panel po kliknięciu, „poniżej tempa”, cel DL z 30% hit ratio
- `liga-w-gornym-pasku.md`: Liga Mistrzów w górnym pasku · przycisk ligi przed licznikiem celów, `/api/competitions/my-league`, stany przycisku, menu „Wygląd”
- `nazewnictwo-rekrutacja-nie-oferta-modul-jobs.md`: Nazewnictwo: „Rekrutacja", nie „Oferta" (moduł `/jobs`)
- `parametry-adresu-natywna-historia-nie-router-replace.md`: Filtr albo zakładka w adresie: `useUrlWriter`, nie `router.replace(…, { scroll: false })` · router Next przewija stronę na górę na produkcji
- `responsywnosc-reguly-po-audycie-23-09-2026.md`: Responsywność — reguły po audycie 23.09.2026
- `ustawienia-jedno-wejscie-z-kafelkami.md`: Ustawienia = jedno wejście z kafelkami
- `wlasny-pulpit-startowy.md`: Własny pulpit startowy (0337)

### Rekrutacja: tworzenie i Profil Championa — `rekrutacja-tworzenie/`

`/jobs/new`, odczyt requestu, wiersze wymagań i umiejętności krytyczne, Profil Championa, przekazanie do searchu, pliki, portale ogłoszeń, strona kariery.

- `bez-typow-rekrutacji.md`: Bez typów rekrutacji (decyzja Artura)
- `budzet-rekrutacji-od-do.md`: Budżet rekrutacji „od–do” (0420)
- `champion-po-ludzku-i-sciaga-do-rozmowy.md`: „Champion po ludzku” i ściąga do rozmowy (0403)
- `dwie-listy-wymagan.md`: Dwie listy wymagań
- `hiring-manager-rekrutacji-lista-albo-nowa-osoba.md`: Hiring manager rekrutacji: lista albo nowa osoba
- `jobs-new-jeden-ekran-i-odczyt-pustych-pol.md`: `/jobs/new`: jeden ekran, „Wypełnij z…” i odczyt tylko pustych pól (D1–D4)
- `jobs-new-w-szesciu-sekcjach-wiersze-wymagan-deal.md`: `/jobs/new` w sześciu sekcjach: wiersze wymagań, deal breaker, kategoria i prowadzący
- `nowa-rekrutacja-strona-jobs-new-z-requestu-klienta.md`: Nowa rekrutacja = strona `/jobs/new` z requestu klienta
- `ogloszenie-jedna-tresc-strona-kariery.md`: Ogłoszenie = jedna treść; strona kariery jednym kliknięciem · „Opublikuj na stronie”, opis publiczny z ogłoszenia, „Kariera” na liście, kolejka zaległych
- `ogloszenie-na-portale-kopiuj-wklej.md`: Ogłoszenie na portale — treść do wklejenia w Pracuj.pl i JustJoin.IT (0430 i 0432) · kontrola przed skopiowaniem, „Oznacz jako opublikowane”
- `pliki-rekrutacji.md`: Pliki rekrutacji (0428)
- `profil-championa-sekcje-4-i-8-propozycja-luny-z.md`: Profil Championa: sekcje 4 i 8 + propozycja Luny z maila
- `profil-championa-szesc-sekcji-karta-klienta.md`: Profil Championa — sześć sekcji + karta klienta (przebudowa)
- `profil-championa-w-czterech-zakladkach.md`: „Profil Championa” w czterech zakładkach
- `przekazanie-propozycje-i-champion-po-audycie-06-10.md`: Przekazanie, propozycje i Champion po audycie 06.10.2026
- `publikacja-na-rocketjobs-i-justjoin-it.md`: Publikacja na RocketJobs i JustJoin.IT (0381)
- `rekrutacja-bez-szkicow.md`: Rekrutacja bez szkiców (0415–0416)
- `strona-kariery-dla-kandydatow.md`: Strona kariery dla kandydatów (kariera.b2bnetwork.pl, 0339)
- `trzy-nazwy-rekrutacji.md`: Trzy nazwy rekrutacji (0380)
- `umiejetnosci-krytyczne-i-bramka-v9.md`: Umiejętności krytyczne i bramka v9 (0405)
- `zgloszenia-z-linku-rekrutacji-przeglada-ai-przed.md`: Zgłoszenia z linku rekrutacji przegląda AI przed „Nowi” (0404)

### Rekrutacja: lista, Tablica, panel osoby — `rekrutacja-tablica/`

Lista `/jobs`, Tablica, ruch kart i bramki, panel osoby, QC CV i Cpro, przegląd DL, podobne rekrutacje, przydział rekruterów, dzwonki przekazań.

- `audyt-manualny-codexa-13-15-09-2026-reguly-ktore.md`: Audyt manualny Codexa 13–15.09.2026 — reguły, które łatwo cofnąć · budżet PLN/h, szkic Championa, „W procesie”, prep kit, tagi, pasek boczny
- `do-wyslania-do-klienta-kolejka-delivery-leada.md`: „Do wysłania do klienta” — kolejka Delivery Leada widoczna wszędzie
- `dodaj-do-rekrutacji-zamknieta-karta.md`: „Dodaj do rekrutacji”: zamknięta karta to nie „już w rekrutacji” · powód `closed_in_job`, „Przywróć” ruchem karty
- `droga-rekrutera-do-dl.md`: Droga rekrutera do DL (D1–D7)
- `duzy-podglad-po-lewej-stronie-panelu-osoby.md`: Duży podgląd po lewej stronie panelu osoby (D1–D6)
- `dzwonek-przy-przekazaniu-karty-qc-dl-cv-wyslane.md`: Dzwonek przy przekazaniu karty: QC → DL, CV wysłane → rekruter
- `follow-up-z-kandydatem-gdy-klient-milczy.md`: Follow-up z kandydatem, gdy klient milczy (0372)
- `imiennicy-w-oknie-dodawania.md`: Imiennicy w oknie „Dodaj kandydatów do pipeline” · telefon, e-mail i miasto w wierszu, szukanie po numerze, „Scal…”
- `kanban-bez-bramek.md`: Kanban bez bramek (decyzja Artura)
- `kandydaci-do-zamkniecia.md`: Kafelek „Kandydaci do zamknięcia”
- `konflikty-z-klientem-blacklist-nda-konkurent-sa.md`: Konflikty z klientem (blacklist / NDA / konkurent) są OSTRZEŻENIEM, nie blokadą (decyzja Artura)
- `lista-rekrutacji-pamieta-ostatnie-filtry.md`: Lista rekrutacji pamięta ostatnie filtry · goły `/jobs` = ostatni widok osoby, link z parametrami wygrywa, `keepScope`
- `mail-odrzucenia-tresc-i-podglad.md`: Mail odrzucenia: treść domyślna i podgląd w oknie odrzucenia · treść domyślna w kodzie, podgląd przed potwierdzeniem
- `minimum-dla-dl-przed-zweryfikowany.md`: Minimum dla Delivery Leada przed „Zweryfikowany” · lokalizacja, tryb, dostępność, „Dlaczego ten kandydat”; okno na Tablicy
- `narzedzia-rekrutera-reguly-po-audycie-17-09-2026.md`: Narzędzia rekrutera — reguły po audycie 17.09.2026 · HoR = rekruter, stawka do klienta, werdykt HM, kalendarz, powiadomienia
- `nastepna-osoba-po-odrzuceniu.md`: Po odrzuceniu z panelu osoby — od razu następna osoba · kolejka „‹ ›” = kolumna + „Kto dodał”, pasek „Odrzucono · Pokaż”
- `nordea-akceptacja-dl-przed-cpro.md`: Nordea: do kolejki Cpro dopiero po akceptacji Delivery Leada · „Akceptuj — do Cpro” ze stawką, bramka serwera, dzwonek od Cpro
- `nowe-cv-w-rekrutacji.md`: Nowe CV w rekrutacji — kafelek w panelu osoby i „Dodaj do rekrutacji z tym CV” · „Wgraj nowe CV”, `…/cv/original/upload`, „Użyj w tej rekrutacji”
- `odrzucenie-z-uzasadnieniem.md`: Odrzucenie z uzasadnieniem i rozmowa u tego samego managera
- `off-limits-sam-sie-zglosil.md`: Off-limits: „Czy sam(a) się do nas zgłosił(a)?” przy dodaniu do rekrutacji
- `pipeline-rekrutacji-bramka-ruchu-przekazanie-cv.md`: Pipeline rekrutacji — bramka ruchu, przekazanie CV, spójność ekranów
- `pipeline-v4-6-kolumn-blokada-12-h-przeglad-dl.md`: Pipeline v4 — 6 kolumn, blokada 12 h, przegląd DL (0352)
- `podobne-rekrutacje-przepiecia-i-status-requestu.md`: Podobne rekrutacje, przepięcia i status requestu (0341)
- `prostszy-ekran-rekrutacji-fakty-kafle-kandydaci-do.md`: Prostszy ekran rekrutacji — fakty, kafle „Kandydaci do dodania”, kolumna „Zamknięci”
- `przeglad-delivery-leada-v2.md`: Przegląd Delivery Leada v2 (D6, D9, D10)
- `przydzial-ludzi-do-requestow-stany-requestu-i.md`: Przydział ludzi do requestów, stany requestu i pulpit „Requesty i obłożenie” (0371)
- `qc-cv-tryb-doradczy-role-z-odczytu-potwierdzenie.md`: QC CV: tryb doradczy, role z odczytu CV, „Potwierdzone z kandydatem” · `CV_QC_ADVISORY`, potwierdzenie jako notatka
- `qc-mowi-prawde.md`: QC CV mówi prawdę · `found_in`, odpowiedzi jako źródło, zdanie w roli tylko przy opisie, „Szukałem w”
- `qc-to-nieprawda-i-jakosc-qc.md`: „To nieprawda” i „Jakość QC” (D5–D6) · pominięcie uwagi per para, blokada = obejście, trafność < 70% → informacja
- `rekrutacja-drobne-usprawnienia-ux.md`: Rekrutacja — drobne usprawnienia UX
- `rekrutacja-v3-lista-jobs-i-wiecej-w-pasku-bocznym.md`: Rekrutacja v3: lista `/jobs` i „Więcej" w pasku bocznym
- `rekrutacja-v5-8-kolumn-strzalka-przesun-dalej-qc-cv.md`: Rekrutacja v5 — 8 kolumn, strzałka „Przesuń dalej”, QC CV, firmowa kolejka Cpro (0361)
- `rekrutacja-wersja-3-jedna-tabela-panel-osoby.md`: Rekrutacja „wersja 3" — jedna tabela + panel osoby (#1641 #1657 #1659)
- `role-przy-rekrutacji-delivery-lead-rekruter.md`: Role przy rekrutacji: Delivery Lead · Rekruter · Kategoria; propozycje automatu akceptuje Head of Recruitment (0409)
- `sciezka-kandydata-przekazania-zweryfikowany-jeden.md`: Ścieżka kandydata: przekazania, „Zweryfikowany”, jeden panel osoby
- `stawka-do-klienta-po-wysylce.md`: Zmiana stawki do klienta po wysyłce CV
- `twoje-cv-w-drodze-na-pulpicie-domyslnie-u-kazdego-z.md`: „Twoje CV w drodze” na pulpicie — domyślnie u każdego, z „Usuń z pulpitu”
- `zamkniecie-rekrutacji-osoby-w-toku.md`: Zamknięcie rekrutacji ostrzega o osobach w toku · 409 `active_cards_warning`, `acknowledge_active_cards`, powody i hit ratio
- `zatrudniony-kto-i-co-jest-potrzebne.md`: „Zatrudniony”: kto przesuwa i co jest potrzebne

### Screening, notatki, stawki kandydata — `screening-notatki/`

Formularz i widok screeningu, karta rekomendacji, rodzaje notatek, wzmianki, „Stawka od” i zmiana stawki w procesie.

- `dane-po-scraperze-narzedzia-naprawy.md`: Dane po scraperze — narzędzia naprawy
- `fakty-z-notatek-rekruterow-na-profilu-kandydata.md`: Fakty z notatek rekruterów na profilu kandydata
- `historia-osoby-w-panelu-rekrutacji.md`: Historia notatek osoby w panelu rekrutacji · „Wcześniej u nas” w „Notatki i historia”, jedno zapytanie o notatki osoby
- `jeden-formularz-screeningu.md`: Jeden formularz screeningu (0424)
- `jeden-widok-screening-zamiast-karty-rekomendacji.md`: Jeden widok „Screening” zamiast karty rekomendacji
- `karta-rekomendacji-z-notatek.md`: Karta rekomendacji z notatek (0413)
- `karta-rekomendacji-z-notatki-i-uloz-w-zdanie.md`: Karta rekomendacji z notatki i „Ułóż w zdanie” (0421)
- `notatki-przypiecie-odpowiedzi-automaty-bez-notatek.md`: Notatki: przypięcie, odpowiedzi, automaty bez notatek (0399)
- `podsumowanie-aktywnosci-kandydata-ai.md`: Podsumowanie aktywności kandydata (AI)
- `pole-notatki-rosnie-duze-okno-szkic.md`: Pole notatki: rośnie z tekstem, duże okno pisania, szkic · Enter w dużym oknie = nowa linia, szkic w sessionStorage
- `rekrutacja-bez-pytan-i-pomin-brakujace.md`: Rekrutacja bez pytań screeningowych i „Pomiń brakujące” poza przepięciem · „Zweryfikowany” bez Profilu Championa, kto pomija pytania
- `rodzaj-notatki-co-czyta-ai-wyszukiwanie-i-rekruter.md`: Rodzaj notatki — co czyta AI, wyszukiwanie i rekruter (0412)
- `screening-wybor-gotowego-cv-z-profilu-i-edycja.md`: Screening: wybór gotowego CV z profilu i edycja
- `stawka-od-i-historia-stawek-kandydata.md`: „Stawka od” i historia stawek kandydata (0414)
- `stawki-pary-z-notatek-gdy-etap-ich-nie-ma.md`: Stawki pary z notatek, gdy etap ich nie ma · stawka z karty i notatki wysyłki tylko jako podpowiedź
- `w-bazie-od-data-wejscia-do-bazy.md`: „W bazie od” — kiedy osoba trafiła do bazy · `source_created_at` (0437), „Nowy w bazie” do 14 dni
- `wzmianki-w-notatkach-i-czatach.md`: Wzmianki „@” w notatkach i czatach
- `zmiana-stawki-kandydata-w-trakcie-procesu.md`: Zmiana stawki kandydata w trakcie procesu (0418)

### Kandydaci i wyszukiwanie — `kandydaci-wyszukiwanie/`

Lista i profil kandydata, słowa kluczowe, kolejność „Dopasowanie”, Talent Radar, kategorie kompetencji, indeks wektorowy, „Moi ludzie”, podgląd CV.

- `competence-categories.md`: Competence Categories (od 24.09.2026 CZTERY — podział profili, filtr, badge wszędzie)
- `dwa-silniki-wyszukiwania-jedna-semantyka-filtrow.md`: Dwa silniki wyszukiwania — jedna semantyka filtrów
- `ekran-kandydaci-i-profil-kandydata-uproszczenie.md`: Ekran „Kandydaci” i profil kandydata — uproszczenie
- `filtr-rekrutacje-bral-nie-bral-bez-procesu.md`: Blok „Rekrutacje” w filtrze „Rekrutacje i historia”: brał / nie brał udziału, bez procesu w toku · odpowiednik „Nieprzypisany” z Traffita, zakres klienta
- `imie-bez-dopiskow.md`: Imię i nazwisko bez dopisków (D6) · dopiski z Traffita, `candidate_name_rules`, 422 przy wpisie, migracje 0436 i 0481
- `imie-cyrylica-w-dopasowaniu-maili.md`: Imię cyrylicą w dopasowaniu maili i w bramce CV
- `indeks-wektorowy-dryf-degradacja-i-pula-ofert.md`: Indeks wektorowy: dryf, degradacja i pula ofert
- `kolejnosc-dopasowanie-i-gorne-pole-listy.md`: Kolejność „Dopasowanie” i górne pole listy
- `moi-ludzie-lista-rekrutera-dzwonek-przy-nowej.md`: „Moi ludzie" — lista rekrutera, dzwonek przy nowej rekrutacji, postać w rogu
- `podglad-cv-pdf-js-lupa-szukaj-w-cv.md`: Podgląd CV: pdf.js + lupa „Szukaj w CV”
- `slowa-kluczowe-przez-korpus-zlozony-lista-najpierw.md`: Słowa kluczowe przez korpus złożony + lista „najpierw id” (0385)
- `szukaj-recznie-nie-wycina-sygnaly-mile-widziane.md`: „Szukaj ręcznie” nie wycina — sygnały „Mile widziane”
- `ta-sama-osoba-ten-sam-e-mail.md`: Ta sama osoba = ten sam e-mail; nowe CV czytane od razu · duplikaty w oknach, /from-cv, poczcie i imporcie; LinkedIn z adresu profilu
- `talent-radar-wklejasz-request-ranking-bazy-bez.md`: Talent Radar (wklejasz request → ranking bazy, bez zakładania rekrutacji)
- `usun-plik-z-profilu-kandydata.md`: „Usuń z profilu” przy pliku kandydata (0435) · kto usuwa (admin, Head of Recruitment), co zostaje w magazynie, jak przywrócić
- `wyszukiwanie-reczne-podpowiedzi-przycisk-szukaj.md`: Wyszukiwanie ręczne: podpowiedzi, przycisk „Szukaj”, pamięć
- `znacznik-pracuje-u-nas.md`: Znacznik „Pracuje u nas” — jedna reguła na każdym ekranie · pracuje / kończy / zaczyna u nas, „Potwierdź zatrudnienie”, dzwonek do DL

### Generator CV i automaty — `generator-cv/`

Generator CV, reguły CV klienta, zgoda RODO, interaktywne CV, automaty rekrutacji (nocny przegląd bazy, auto-match, auto-CV).

- `automaty-rekrutacji-v3.md`: Automaty rekrutacji v3 (migracja 0335)
- `autonomiczny-przeplyw-cv.md`: Autonomiczny przepływ CV
- `cv-po-potwierdzeniu.md`: CV po potwierdzeniu — bez auto-CV po „Zweryfikowany” · trzy potwierdzenia, `CV_AUTO_GENERATE_WITHOUT_CONFIRMATION`, „Powstało z”, „Odrzuć to CV”
- `cv-w-procesie.md`: CV w procesie (D4) · źródła AI w karcie, jedna lista „Do poprawy”
- `edytor-cv-pelny-ekran.md`: Edytor CV na cały ekran — kartka, bloki, źródła, stała klauzula RODO · kontrakt HTML ↔ Word, „Do poprawy”, AI na zaznaczeniu, historia wersji
- `generator-cv-domyslnie-sciezka-sprzed-przebudowy.md`: Generator CV — domyślnie ścieżka sprzed przebudowy (`legacy_v7`)
- `generator-cv-tylko-w-rekrutacji.md`: Generator CV tylko w rekrutacji
- `generator-cv-v3-jeden-ekran-od-osoby.md`: Generator CV v3 — jeden ekran od osoby
- `interaktywne-cv-publiczny-link-do-wygenerowanego-cv.md`: Interaktywne CV (publiczny link do wygenerowanego CV)
- `naglowek-stanowiska-nie-zostaje-sam-na-dole-strony.md`: Nagłówek stanowiska nie zostaje sam na dole strony
- `reguly-cv-per-klient-pelna-recepta-delivery-leada.md`: Reguły CV per klient — pełna recepta Delivery Leada
- `silnik-cv-bez-wypelniacza.md`: Silnik CV bez wypełniacza (D1–D3) · bez punktu MUST, pytanie ≠ fakt, `cv_role_title`, lata, notatki bez stawek
- `zrzut-zgody-rodo-na-koncu-cv-wymog-pko-bp.md`: Zrzut zgody RODO na końcu CV (wymóg PKO BP)

### AI i Jarvis — `ai-jarvis/`

Rejestr modeli per funkcja, brak limitów AI, Jarvis (narzędzia, przewodniki ekranów, pamięć, umowy ramowe).

- `jarvis-2-pomoc-na-ekranie-dzien-pracy-pamiec.md`: Jarvis 2 — pomoc na ekranie, dzień pracy, pamięć (0355)
- `jarvis-asystent-agent-w-shellu.md`: Jarvis — asystent-agent w shellu (0330, zastępuje MINDY)
- `jarvis-czyta-umowy-ramowe-klientow.md`: Jarvis czyta umowy ramowe klientów (0426)
- `modele-ai-per-funkcja-decyzja-z-badania-na-danych.md`: Modele AI per funkcja — decyzja z badania na danych produkcyjnych
- `nexus-bez-limitow-ai.md`: NEXUS bez limitów AI (decyzja Artura)

### Klienci — `klienci/`

Profil i karta klienta, scalanie i usuwanie klientów, Historia zdarzeń, Centrum e-Zdrowia.

- `audyt-pomylonych-klientow-get-api-admin-client.md`: Audyt pomylonych klientów — `GET /api/admin/client-mixups`
- `centrum-e-zdrowia-umowy-ramowe-czesci-umowy.md`: Centrum e-Zdrowia: umowy ramowe (części) → umowy wykonawcze + zamówienia MD
- `jednorazowe-czyszczenie-nieaktywnych-klientow.md`: Jednorazowe czyszczenie „Nieaktywnych klientów" (migracja 0303)
- `karta-klienta-client-playbooks.md`: Karta klienta (`client_playbooks`)
- `klienci-profil-tabela-konsultantow-stawki-z.md`: Klienci → Profil: tabela konsultantów + stawki z harmonogramu
- `scalenie-cardif-pelne-przeniesienie-danych.md`: Pełne scalenie klienta-duplikatu: BNP Paribas Cardif (52) → Cardif Assurances (38335) · `cardif_client_merge_repair`, najpierw dane, potem flaga; wzór na duplikaty
- `usuwanie-klienta-z-profilu-historia-zdarzen.md`: Usuwanie klienta z profilu + Historia zdarzeń (migracja 0307)

### Kontrakty i umowy B2B — `kontrakty/`

Generator umów B2B, cykl życia kontraktu, zakończenie i cofnięcie, synchronizacja kontrakt ↔ zamówienia, dokumenty, zakładki rejestru.

- `aktywacja-umowy-end-date-nie-jest-wymagane-umowa.md`: Aktywacja umowy: `end_date` NIE jest wymagane (umowa bezterminowa)
- `analityka-kontraktow-utylizacja-i-kafle-sum.md`: Analityka kontraktów: utylizacja i kafle sum
- `cofnij-zakonczenie-i-powrot-po-przerwie.md`: „Cofnij zakończenie" i „Powrót po przerwie" (0368)
- `data-rozpoczecia-umowy-start-zamowienia.md`: Data rozpoczęcia umowy ≠ start zamówienia (korekta)
- `dokumenty-kontraktow-z-sharepointa.md`: Dokumenty kontraktów z SharePointa (ticket 9, 0402)
- `domyslny-widok-modulu-kontrakty-aktywne-i-konczace.md`: Domyślny widok modułu Kontrakty: Aktywne **i** Kończące się
- `foldery-w-dokumentach-kontraktu.md`: Foldery w zakładce Dokumenty kontraktu (0494)
- `generator-umow-b2b-trzy-zakladki-cyklu-zycia-umowy.md`: Generator Umów B2B — trzy zakładki cyklu życia umowy
- `kafelek-kontraktora-status-zamowienia-musi-zgadzac.md`: Kafelek kontraktora: status zamówienia musi zgadzać się z okresem
- `kontakt-do-konsultanta-na-umowie.md`: Kontakt do konsultanta na umowie (migracja 0320)
- `kontrakty-i-zamowienia-lista-z-panelem.md`: Kontrakty i Zamówienia: lista z panelem (wersja B)
- `podpis-umowy-b2b-oznacza-autor-zespol-dl-tcm.md`: Podpis umowy B2B oznacza autor, zespół rekrutacji, DL klienta albo TCM
- `podpis-umowy-b2b-w-nexusie.md`: Podpis umowy B2B w NEXUSIE — druga droga obok „Oznacz jako podpisaną” (0499)
- `przedluzenie-zamowienia-wskrzesza-zakonczony.md`: Przedłużenie zamówienia wskrzesza zakończony kontrakt
- `rejestr-aneksow-i-aneks-w-kontrakcie.md`: Rejestr aneksów i aneks w kontrakcie od wygenerowania · jeden stan aneksu, aneks do umowy spoza Nexusa, zakładka „Aneksy”
- `stawki-z-rekrutacji-w-zamowieniu-i-umowie.md`: Stawki z rekrutacji w zamówieniu i umowie (D7)
- `synchronizacja-kontrakt-zamowienia.md`: Synchronizacja kontrakt ↔ zamówienia (migracja 0304)
- `umowa-b2b-jest-bezterminowa-dopoki-ktos-jej-recznie.md`: Umowa B2B jest bezterminowa, dopóki ktoś jej ręcznie nie zakończy
- `zakladka-konczace-sie-30d-tylko-zamowienia-bez.md`: Zakładka „Kończące się 30d" — tylko zamówienia bez kontynuacji
- `zakladka-zakonczeni-decyduje-umowa-nie-okres.md`: Zakładka „Zakończeni" — decyduje umowa, nie okres zamówienia
- `zakonczenie-wspolpracy-okno-rozwiazanie-umowy.md`: Zakończenie współpracy = okno + rozwiązanie umowy + Generator (0367)

### Zamówienia i poczta zamówień — `zamowienia/`

Poczta zamówień i odczyt PDF per klient, zamówienia MD, kosztowe i okresowe, import zużycia MD, alerty Delivery Leada, instrukcja zamówień.

- `cykl-zycia-zamowienia-zamowienia-kosztowe-i.md`: Cykl życia zamówienia, zamówienia kosztowe i powiadomienia Delivery Leada
- `decyzja-delivery-leada-po-zakonczeniu-wspolpracy.md`: Decyzja Delivery Leada po zakończeniu współpracy konsultanta MD
- `eksport-zamowien-do-excela-pokazuje-stan-na-dzis.md`: Eksport zamówień do Excela pokazuje stan NA DZIŚ
- `faktury-do-klientow-z-ksef.md`: Faktury do klientów z KSeF (E8 cz. 1)
- `historia-zamowienia-zuzycie-md-i-importy-md.md`: Historia zamówienia, „Zużycie MD" i „Importy MD" (ticket 7)
- `instrukcja-zamowien-w-pomocy-przestempluj-po.md`: Instrukcja zamówień w Pomocy — przestempluj po ZMIANIE LOGIKI ZAMÓWIEŃ
- `md-oczekujace-na-kolejne-zamowienie.md`: Import MD: wiersz bez numeru czeka na kolejne zamówienie (0492)
- `odczyt-pdf-w-formularzu-nowego-zamowienia.md`: Odczyt PDF w formularzu NOWEGO zamówienia
- `okno-nowe-zamowienie-jeden-odczyt-pdf-a-karty.md`: Okno „Nowe zamówienie" — jeden odczyt PDF-a, karty wszystkich osób
- `panel-moi-klienci-na-dashboardzie-delivery-leada.md`: Panel „Moi klienci" na dashboardzie Delivery Leada (migracja 0310)
- `polityki-odczytu-pdf-per-klient-jeden-wzorzec.md`: Polityki odczytu PDF per klient — jeden wzorzec, bramka per klient
- `pr2-multiposting-scalanie-kandydatow-tagi-mail.md`: PR2: multiposting, scalanie kandydatów, tagi, mail aplikacji, przepięcie kontraktu, anulowanie zamówień MD
- `przejecie-pozostalych-md-i-karta-szkicu.md`: Przejęcie pozostałych MD i karta szkicu (ticket, migracja 0357)
- `usuniecie-zamowienia-przecenia-historie-dialog-musi.md`: Usunięcie zamówienia przecenia historię — dialog musi to powiedzieć
- `zamowienia-wielo-konsultantowe-bik-polkomtel-bnp.md`: Zamówienia wielo-konsultantowe (BIK / Polkomtel / BNP) + import zużycia MD
- `zamowienia-z-maila-zamowienia-b2bnetwork-pl-czytnik.md`: Zamówienia z maila `zamowienia@b2bnetwork.pl` — czytnik app-only, skrzynka współdzielona
- `zamowienie-md-i-zamowienie-okresowe-to-dwa.md`: Zamówienie MD i zamówienie okresowe to DWA niezależne byty
- `zapis-zamowienia-network-error-znaczy-nieobsluzone.md`: Zapis zamówienia: „Network Error" znaczy nieobsłużone 500
- `zuzycie-zamowienia-kosztowego.md`: Zakładka „Zużycie” przy zamówieniu kosztowym (0493)

### Finanse i Insights — `finanse-insights/`

Finanse → Zmiany w zamówieniach, Zamówienia PDF, Insights (Rywalizacja, Zespół, Firma, raporty).

- `finanse-zamowienia-pdf.md`: Finanse → „Zamówienia PDF"
- `finanse-zmiany-w-zamowieniach.md`: Finanse → Zmiany w zamówieniach
- `finanse-zrobione-w-zmianach-zip-y-i-pobrania-w.md`: Finanse: „Zrobione" w Zmianach, ZIP-y i pobrania w Zamówieniach PDF (0354)
- `insights-insights-parytet-z-dynareporterem-na.md`: Insights (`/insights`) — parytet z DynaReporterem na danych NEXUSA

### Powiadomienia i maile — `powiadomienia/`

Ikony paska, kategorie i wyciszenia, powiadomienia dla ról, maile do zespołu.

- `maile-do-zespolu-poranny-skrot-kilka-maili-od-razu.md`: Maile do zespołu: poranny skrót + kilka maili od razu
- `moje-powiadomienia-kategorie-i-wyciszenia-per-osoba.md`: Moje powiadomienia — kategorie i wyciszenia per osoba (0349)
- `okienko-czaty-w-gornym-pasku.md`: Okienko „Czaty” w górnym pasku
- `okienko-rozmowy-w-gornym-pasku.md`: Okienko „Rozmowy” w górnym pasku · zadania z cyklu (`mine`), czas z agendy, gaszenie osobną trasą, pigułka telefonu
- `pasek-tematy-bez-dzwonka.md`: Pasek bez dzwonka: ikony z jednym tematem
- `powiadomienia-dla-rol-i-jeden-ekran-powiadomienia.md`: Powiadomienia dla ról i jeden ekran „Powiadomienia” (0425)
- `zmiana-notatki-i-terminu-rozmowy.md`: Zmieniona notatka z oznaczeniem i przełożona rozmowa u klienta · `notify_mentions`, `interview_changed` (0500), kto dostaje

### Integracje — `integracje/`

Traffit, COMPASS, CloudTalk, kalendarz i rozmowy u klienta, prepy w Teams, archiwum pytań.

- `archiwum-pytan-z-rozmow-u-klienta.md`: Archiwum pytań z rozmów u klienta (0383)
- `cloudtalk-telefonia.md`: CloudTalk (telefonia)
- `integracja-compass-nexus-kontraktorzy-cykl-zycia.md`: Integracja COMPASS ↔ NEXUS (kontraktorzy + cykl życia)
- `kalendarz-rozmowy-u-klienta.md`: Kalendarz = „Rozmowy u klienta” (0338)
- `prepy-w-teams-transkrypt-notatka-i-ocena-prepu.md`: Prepy w Teams → transkrypt, notatka i ocena prepu (0370)
- `przeniesienie-rekrutacji-z-traffita-falami.md`: Przeniesienie rekrutacji z Traffita do NEXUSA falami · próba i wykonanie fali, lista osób per stan = źródło prawdy
- `pytania-z-rozmowy-bez-terminu.md`: Pytania z rozmowy u klienta także bez terminu w NEXUSIE · „Kiedy rozmowa?”, `questions_missing` po 24 h, debrief bez wydarzenia, bramka przed „Umową”
- `rozmowa-bez-prepu-2.md`: Rozmowa u klienta bez Prepu 2 — wyjątek, nie wybór (0482)
- `terminy-z-maila-klienta.md`: Terminy rozmowy z wklejonego maila klienta (0485) · „Wklej maila od klienta”, cytat sprawdza kod, mail nie jest zapisywany
- `traffit-daily-sync-scheduled-import.md`: Traffit daily sync (scheduled import) · wyłączony na stałe 14.10.2026 (`traffit_retired.py`, 410) — co zostało tylko w Traffit

### Ludzie w NEXUSIE — `ludzie/`

Moduły przeniesione z Compassa (bez Akademii) i sprzęt recepcji.

- `modul-ludzie-dostep-schemat-i-przelaczenie.md`: „Ludzie w NEXUSIE” — dostęp, schemat, przełączenie z Compassa
- `opieka-mapa-technologii-i-sprawy.md`: Opieka, mapa technologii, ATLAS, administracja@
- `runbook-przelaczenia-z-compassa.md`: Runbook przełączenia z Compassa na „Ludzi w NEXUSIE”
- `sprzet-i-protokoly-recepcji.md`: Sprzęt i protokoły recepcji (D2–D10)
- `urlopy-czas-place-wejscie-odejscie.md`: Urlopy i M365, „Mój miesiąc”, płace, wejście i odejście
- `zgody-wydatki-i-premie-poza-umowa.md`: Zgody na wydatki i premie poza umową (0483)

### Programy — `programy/`

Akademia i program praktykanta — oba ukryte z UI od 17.10.2026.

- `akademia-nabor-do-programow-szkoleniowych.md`: Akademia — nabór do programów szkoleniowych (0369)
- `praktykant-telefony-na-dzis.md`: Praktykant — „Telefony na dziś” (0374)

### Audyty przekrojowe — `audyty/`

Reguły po audytach 22–25.09.2026 — przeczytaj przed zmianą w poczcie zamówień, MD, kontraktach, bezpieczeństwie albo integracjach.

- `audyt-22-09-2026-druga-runda-reguly-po-naprawie.md`: Audyt 22.09.2026, druga runda — reguły po naprawie · podgląd DOCX, CSP, limit ciała żądania, kontrola AI CV, retencja, MD, poczta zamówień
- `audyt-22-09-2026-reguly-po-naprawie.md`: Audyt 22.09.2026 — reguły po naprawie · tokeny OAuth, mail M365 jednorazowy, podpis, kanonizacja umiejętności, analityka
- `audyt-25-09-2026-reguly-po-naprawie.md`: Audyt 25.09.2026 — reguły po naprawie · rundy 1–13: poczta zamówień, MD, kontrakty, rekrutacja, bezpieczeństwo, integracje, tokeny

<!-- INDEKS:END -->
