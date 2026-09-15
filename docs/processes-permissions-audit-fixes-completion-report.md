# Domknięcie audytu procesów, uprawnień i integralności danych (14.09.2026)

Stan ustaleń F01–F08 po weryfikacji kodu na `main` z 15.09.2026 i po tej zmianie.

| # | Ustalenie | Stan |
|---|---|---|
| F01 | Feedback do cudzego spotkania | Naprawione wcześniej (`_bind_feedback_to_event`) |
| F02 | Odebrana sekcja nie zamyka API | **Domknięte w tej zmianie** — wszystkie zalogowane trasy |
| F03 | Konkurujące zmiany statusu kontraktu | **Domknięte w tej zmianie** — pozostałe komendy + zakończenie |
| F04 | Usunięcie kandydata a pliki | Naprawione wcześniej (`cv_source_cleanup`) |
| F05 | Nieaktualna karta w pipeline | Naprawione wcześniej (`expected_state_version`, front #1535) |
| F06 | Token odświeżania w URL | Naprawione wcześniej (tylko ciało żądania) |
| F07 | E2E bez zalogowanych procesów | Otwarte — wymaga decyzji i kont (niżej) |
| F08 | Brak udanego drillu backupu | Otwarte — wymaga kluczy i konfiguracji (niżej) |

## F03 — status kontraktu

**Co było jeszcze otwarte po pierwszej poprawce.** Blokada wiersza była w
`update_contract`, `update_contract_status`, `void_contract_endpoint`
i `bulk_mark_ended`. Bez niej zostały `/reopen`, `/activate`, `/finalize`,
`/terminate`, aneksy i `/bulk-extend` — w tym dokładnie scenariusz odtworzony
w audycie (`void` kontra cofnięcie do szkicu).

**Błąd niezależny od wyścigów.** `/terminate` i aneks `early_termination`
liczyły status z samej daty końca. Jedno „Zakończ współpracę” na unieważnionej
umowie zapisywało `ended` (przy przyszłej dacie `active`), a szkic z przyszłą
datą zakończenia dostawał `active` z pominięciem bramki aktywacji.

**Zmiany** (`backend/app/api/contracts.py`, `backend/app/services/contract_order_sync.py`):

- `FOR UPDATE` w `activate_contract`, `reopen_contract_endpoint`,
  `terminate_contract`, `create_contract_amendment`, `bulk_extend_contracts`
  (stała kolejność po id) oraz w `finalize_contract_draft` przez
  `_load_contract_with_relations(..., for_update=True)`.
- `_status_after_termination`: `void` → 409 z maszyny stanów przed jakimkolwiek
  zapisem (także zamówień i ścieżki powtórzenia); szkic i `ready_for_signature`
  z przyszłą datą zachowują status, a nocny `_promote_statuses` kończy je
  (`ended`) dzień po dacie końca — tylko gdy mają `terminated_at`.
- `resync_contract` odświeża po blokadzie pola cyklu życia (status, daty,
  okres zamówienia, zakończenie) — obiekt bywał załadowany przed blokadą.
- Świadomie bez zmian: kolejność blokad writerów zamówień (`client_orders`
  przed `contracts`) — znany dług, zmieniany tylko w obu miejscach naraz.

**Testy** (`backend/tests/test_contract_status_concurrency.py`): wyścigi `void`
z `/reopen`, `/activate`, `/terminate` na dwóch sesjach PostgreSQL; zakończenie
i aneks na `void` → 409 bez śladu; szkic z przyszłą datą zostaje szkicem;
`resync_contract` widzi `void` commitowany po załadowaniu obiektu; strażnik AST
dla 10 handlerów. Mutacje (usunięcie blokady w `/reopen`, sprawdzenia maszyny
stanów, odświeżenia w `resync`) czerwienią 6 testów.

## F02 — bramki sekcji

**Pomiar.** Przegląd drzewa zależności wszystkich tras `/api/**`: 146 zalogowanych
tras sprawdzało wyłącznie role. Po zmianie zostały 43 — każda na liście wyjątków
z powodem (sesja i własne konto, skrzynka powiadomień filtrowana per wiersz,
dane referencyjne wspólne dla sekcji, kontrola sekcji w treści handlera).

**Mapowanie.**

| Powierzchnia | Sekcja |
|---|---|
| Maile odmów, priorytety pracy | Pipeline |
| Obecność, import Championa | Sourcing albo Pipeline (odczyt) |
| Fireflies (`/sync` = POST) | Sourcing |
| Cortex, KPI, wagi scoringu, stary pulpit, stary DynaReporter | Insights |
| Historia zdarzeń, podgląd importu portfela | Finanse |
| Globalny strumień czatów | Pipeline **i** Sourcing |
| Pulpity v2 | per trasa: DL → Delivery, HoR i statystyki → Insights, reszta → Pipeline |
| Dziennik aktywności | statystyki → Insights, strumień → Sourcing/Pipeline/Delivery |
| Struktura zespołu | Pipeline; przypisania DL↔klient → Delivery albo Pipeline |
| Podpowiedzi klientów / rekrutacji | dowolna sekcja produktu |

Domyślna macierz ról nie odbiera nikomu dostępu. Wyjątek: wygaszony upload Excela
DynaReportera (410) ma bramkę odczytu Insights, żeby dalej odpowiadał „wygaszone”.

**Frontend.** Widżety montowane według sekcji: pulpit bez Pipeline pokazuje jeden
komunikat zamiast serii błędów 403, panele DL wymagają Delivery, KPI w topbarze
i karta aktywności na profilu wymagają Insights, obecność wymaga Sourcing albo
Pipeline, karta Fireflies wymaga Sourcing, zakładka „Historia zdarzeń” wymaga
Finansów; middleware `/settings/chats` i `/settings/team-structure` sprawdza Pipeline.

**Testy.** `test_section_ceiling_contract.py` (każda trasa ma bramkę albo wpis
z powodem; brak nieaktualnych wpisów; oczekiwane sekcje dla każdej zmienionej
trasy; `/fireflies/sync` nie jest GET), `test_section_revocation_http.py`
(recruiter z odebraną sekcją dostaje 403 `section_access_denied`, bez nadpisania
przechodzi), testy `require_section_access_any`, testy pulpitu i ustawień.

## Przegląd adwersarialny

Niezależny przegląd zmian znalazł i poprawiono: szkic zakończony z przyszłą datą
nie przechodził nigdy na `ended` (job statusów obsługiwał tylko `active`/`ending`);
admin na presecie DL tracił panel „Moi klienci”; `/api/champion/preview`
(płatne AI) wymagał tylko odczytu sekcji — teraz zapisu. Świadomie bez zmian:
widżet „Moje zadania” (kalendarz wymaga Pipeline) jest ukryty razem z resztą
widżetów rekrutacji, gdy Pipeline odebrano — powiadomienia zostają w dzwonku.

## Weryfikacja

- Backend (Docker, PostgreSQL 16): 104 testy F03; po rebase na `main` 580 testów
  kontraktów sekcji, RBAC, statusów kontraktu i joba statusów; 429 testów RBAC i kontraktów
  sekcji; szeroki przebieg 68 plików dotykających zmienionych modułów:
  1554 zielone, jedna regresja (upload DynaReportera) poprawiona i ponownie
  sprawdzona. `ruff check` i `ruff format --check` czyste.
- Frontend: `tsc --noEmit` czysty; vitest 123 pliki / 1516 testów zielonych.

## F08 — drill backupu: kroki operatorskie

Runbook: `docs/runbook-backup-201.md`; stan: `docs/disaster-recovery.md`.

1. Klucz age wyłącznie dla drillu (runbook §b).
2. Klucz B2 tylko do odczytu dla bucketu off-site (§c).
3. Coolify: `BACKUP_AGE_PUBLIC_KEY` z odbiorcą drillu, `BACKUP_S3_*`,
   `OBJECT_STORAGE_*`, na końcu `BACKUP_ENABLED=true` (§d.1). Klucz drillu musi
   być wpisany przed pierwszą kopią.
4. Poczekać na jedną nocną kopię.
5. Sekrety GitHub `BACKUP_AGE_PRIVATE_KEY`, `BACKUP_S3_ACCESS_KEY`,
   `BACKUP_S3_SECRET_KEY` i zmienne `BACKUP_S3_BUCKET/ENDPOINT/REGION` (§d.2),
   potem `BACKUP_MONITORING_ENABLED=true`.
6. Ręczny „Backup Restore Drill”; zapisać czas odtworzenia i wiek danych.

## F07 — zalogowane E2E: do decyzji

Produkcja ma wyłączone logowanie hasłem, a repo nie ma logowania testowego ani
stacku E2E. Warianty: (a) konto E2E na liście awaryjnego logowania hasłem —
najszybsze, ale testy idą na produkcję; (b) stack docker-compose w CI z logowaniem
hasłem tylko w tym stacku — zalecane, osobny PR; (c) E2E na stagingu w Coolify.
