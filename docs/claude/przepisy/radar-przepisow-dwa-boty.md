# Przepisy: radar zmian w prawie, dwa Grok Boty i bramka NEXUSA
<!-- indeks: Przepisy, /compliance, radar przepisów, law_radar, Zbieracz law collect, Analityk law analyze, bramka API Sejmu ELI, sondy u nas, strażnicy, LEX kontem księgowej, Gofin kontem księgowej, gofin_skipped, LAW_RADAR_ENABLED, GROK_BOT_LAW_COLLECT_WEBHOOK, GROK_BOT_LAW_ANALYZE_WEBHOOK, bez maili, webhook v2 request_url obu rutyn -->

Decyzje Artura z 15.11.2026. Propozycja i makiety ze stagingu:
https://claude.ai/artifact/KuKN54kXDHXNVqeHdrGyL4 (wersja 5 z diagramem przepływu).

CFO, księgowa, kadry, umowy i rekrutacja dostają w NEXUSIE zmiany w prawie,
terminy i to, co znaczą dla firmy na naszych danych. Firma jest na estońskim CIT,
ma setki kontraktów B2B, KSeF i płace w NEXUSIE.

## Przepływ (bez maili)

1. **Grok Zbieracz** (`collect`, codziennie od 5:30, kalendarz firmy) czyta
   źródła i odsyła **surowe pozycje**: źródło, tytuł, link, data, numer aktu
   (`DU/2026/473`, `MP/2026/1098`) albo druku Sejmu, etap, krótki cytat.
   Bez oceny.
2. **Bramka NEXUSA** przyjmuje raport (token biegu, walidacja jak w Sprzedaży),
   usuwa powtórki i **sama sprawdza w API Sejmu** numer aktu (`/eli/acts/…`)
   i druk (`/sejm/term10/processes/{nr}`). Akt albo druk, którego API nie zna,
   odpada (`rejected`). Pozycja bez numeru zostaje, ale jako „praktyka” albo
   „LEX”, nigdy jako fakt urzędowy.
3. **Grok Analityk** (`analyze`) startuje zaraz po przyjęciu raportu Zbieracza,
   gdy są nowe pozycje. Dostaje **tylko sprawdzone pozycje**, profil tematów,
   listę otwartych zmian i listę sond. Odsyła zmiany: tytuł, skrót, role, etap,
   pilność, daty, pozycje, sondy z listy i zadania.
4. **NEXUS liczy „u nas”** (sondy) na własnych danych i pokazuje zmianę na
   ekranie „Przepisy”, w pasku modułu i w dzwonku. **Maili nie ma** w żadnym
   kroku (decyzja Artura 15.11.2026).

Boty nie rozmawiają ze sobą bezpośrednio: bramka stoi między nimi, więc
Analityk nie analizuje wymyślonego aktu, a żaden bot nie ma stałego klucza do
NEXUSA ani do drugiego bota.

**Webhook v2 obu rutyn (24.11.2026; Analityk od 17.11):** treść webhooka to
sama koperta (`schema_version` 2, `run_id`, `request_url`, `token`,
`expires_at`), a zlecenie (`task`, `report_format`, `request`, `callback_url`)
bot pobiera `GET /api/integrations/law-radar/runs/{id}` z `X-Run-Token`. Wersja
leży w zleceniu biegu (`_schema_version`); bieg v1 nie ma GET (401). Zapas:
`GROK_BOT_WEBHOOK_V1=law_collect` (albo `law_analyze`) daje rutynie dawną
treść. Wspólne zasady, log `bot_webhook … bytes=… response=…` i pusta treść
raportu jako 422: `sprzedaz/sygnaly-grok-bot.md`, sekcja „Webhook v2”.

## Co idzie do botów

- Do Zbieracza: profil tematów (`PROFILE_TOPICS`), lista źródeł, data
  ostatniego przyjętego biegu. **Bez danych firmy** (kontraktów, płac, faktur,
  nazw klientów i osób): komputery bota stoją w USA.
- Do Analityka: sprawdzone pozycje z bramki (dane publiczne), profil tematów,
  tytuły i numery otwartych zmian, klucze i opisy sond. **Liczb sond nie
  dostaje.**
- **LEX** (decyzja Artura 15.11.2026, wbrew rekomendacji i ze świadomością zasad
  Wolters Kluwer nr 1/2026 o udostępnianiu loginu): Zbieracz loguje się do LEX
  kontem księgowej z Vault Grok Bota. Hasło wpisuje do Vault Artur albo
  księgowa, nigdy sesja Claude ani kod. Z LEX-u do NEXUSA trafia tylko tytuł,
  link i cytat do 500 znaków (źródło `lex`), bez kopiowania komentarzy.
- **Gofin** (decyzja Artura z 16.11.2026, wbrew rekomendacji): Zbieracz loguje
  się do Gofina (www.gofin.pl) kontem księgowej z Vault Grok Bota, tak jak do
  LEX-u. Artur zna oba zakazy Gofina: regulamin serwisów (korzystanie „przez
  udostępnianie Danych identyfikacyjnych” bez pisemnej zgody) i zastrzeżenie
  eksploracji tekstów i danych (art. 26³ prawa autorskiego: bez zgody na
  systematyczne pobieranie automatem, także stron darmowych). Do NEXUSA trafia
  tylko tytuł, link i cytat do 500 znaków (źródło `gofin`, klasa `practice`:
  komentarz wydawnictwa, nigdy fakt urzędowy). Gdy Gofin nie wpuści bota, raport
  ma `gofin_skipped`, a linia biegu na ekranie mówi „Gofin pominięty”. Hasło
  wpisuje do Vault Artur albo księgowa, nigdy sesja Claude, Codex ani kod.

## Dane

- `law_radar_runs`: bieg `collect` albo `analyze`, token jednego biegu
  (2 godziny, raz), `request`, podsumowanie liczbowe, błąd.
- `law_radar_items`: surowa pozycja z odciskiem (bez powtórek), klasa
  `official` / `lex` / `practice`, wynik bramki `pending` (zapisana, czeka na
  API Sejmu) → `verified` / `unverified` / `rejected`, dane z API Sejmu (etap,
  data wejścia w życie), zmiana, `analyzed_at` (raport Analityka przyjęty).
- `law_changes`: zmiana z rolami (`board`, `accounting`, `payroll`,
  `contracts`, `recruitment`), etapem (`project` → `sejm` → `senate` →
  `president` → `journal` → `in_force`), pilnością, datami i statusem
  (`new`, `in_progress`, `done`, `not_applicable`). Kolejny bieg Analityka
  aktualizuje treść i etap, **nigdy status ani decyzję** człowieka.
- `law_change_tasks`, `law_change_events` (dziennik decyzji: „Nie dotyczy”
  z powodem, zmiana etapu, wykonane zadanie), `law_change_probes` (wynik sondy:
  liczba, tekst, link, czas).

## Sondy „u nas”

Rejestr w kodzie (`services/law_radar/probes.py`), klucz → zapytanie tylko do
odczytu, wynik to liczba i link do przefiltrowanej listy. Liczone po biegu
Analityka i raz dziennie. Same liczby, bez nazwisk i kwot. Start:
`b2b_long_contracts` (aktywne B2B ≥ 24 mies.), `postings_without_salary`
(opublikowane ogłoszenia bez stawki), `payroll_params_next_year` (brak wersji
parametrów płac od 1.01 następnego roku), `ksef_sales_invoices` (faktury
sprzedaży z numerem KSeF w ostatnim pełnym miesiącu),
`related_party_documents` (lista podmiotów powiązanych: dziś brak w NEXUSIE).

## Włączenie

- Flaga `LAW_RADAR_ENABLED` domyślnie wyłączona: pętla stoi, ekran mówi
  „Radar wyłączony”. Trasa przyjęcia raportu działa zawsze (bez biegu nie ma
  tokenu).
- Webhooki: `GROK_BOT_LAW_COLLECT_WEBHOOK_URL/_KEY` i
  `GROK_BOT_LAW_ANALYZE_WEBHOOK_URL/_KEY`, ustawiane workflowem „Coolify set
  env”. Rutyny zakłada Artur w aplikacji desktopowej Grok Bota (instrukcja
  w `docs/law-radar-grok-bots-setup.md`).
- Na stagingu pętla zablokowana (`STAGING_BLOCKED_TASKS`: `law_radar`).
- Logi są publiczne: same liczby, bez tytułów i nazw.

## Zbudowane: backend (PR1, migracja 0715)

- **Kod:** `services/law_radar/` (`schema`, `runs`, `collect`, `gate`, `analyze`,
  `probes`, `flow`), model `models/law_radar.py`, pętla `tasks/law_radar.py`,
  trasy `api/integrations_law_radar.py` i `api/law_radar.py`, próba
  `scripts/law_radar_run.py`. DDL z jednego źródła (`law_radar/schema.py`) dla
  migracji i entrypointu (`hr_schema_bundle`); sześć tabel ma sondy w
  `/api/health/deep`.
- **Bramka poza żądaniem bota.** Raport Zbieracza zapisuje pozycje jako
  `pending` i od razu odpowiada liczbami; sprawdzenie w API Sejmu (sekwencyjnie,
  limit 8 s, najwyżej 60 zapytań na bieg, transakcja zamknięta na czas sieci)
  i start Analityka biegną w tle (`flow.after_collect`). `pending` starsze niż
  20 minut (np. restart) dokańcza pętla.
- **Odcisk** = adres (bez kotwicy i końcowego `/`, host małymi literami) + numer
  aktu + numer druku + data publikacji: kolejny etap tego samego procesu z nową
  datą to nowa pozycja dla Analityka.
- **Klasa:** `lex` dla źródła `lex` (CHECK: `lex` ⇔ `lex`), `official` dla hosta
  z listy domen urzędowych albo `*.gov.pl`, inaczej `practice`. Źródła raportu:
  `sejm`, `rcl` (legislacja.gov.pl), `zus`, `mf`, `eureka`, `pip`, `uodo`, `nsa`,
  `eurlex`, `advisor`, `x`, `lex`, `gofin` (od 0726, 16.11.2026), `other`.
- **Analityk** dostaje pozycje `verified` i `unverified` z ostatnich 14 dni, które
  nie przeszły jeszcze przez przyjęty raport Analityka (najwyżej 200), z polem
  `gate`. Zmiana bez choć jednej pozycji ze zlecenia odpada; pozycja trafia do
  jednej zmiany; `change_ref` spoza listy otwartych zmian odpada. Przy
  aktualizacji bot dokłada tylko zadania, których zmiana jeszcze nie ma (bez
  wielkości liter). Nieudany albo wygasły bieg Analityka pętla ponawia po godzinie.
- **Dostęp do `/api/compliance`** (`require_compliance_access`): administrator
  i Head of Recruitment z roli, reszta z uprawnienia „Moduł Finanse”, „Płace”,
  „Kadry” albo „Kontrakty i zamówienia” (więc także Delivery Lead i Back office,
  które mają to ostatnie z roli). Bez nowego uprawnienia; trasy są w
  `_SECTIONLESS_ALLOWLIST` (osobna oś od sekcji), wzorzec w
  `tests/data/authz_golden/law_radar.json`. Ręczny start Zbieracza
  (`POST /runs/collect`) tylko admin, także przy wyłączonej fladze (próba).
- **Trasy:** `GET /changes?role=&status=`, `GET /changes/{id}` (pozycje, zadania,
  dziennik, sondy), `PATCH /changes/{id}` (status + powód; „Nie dotyczy” bez
  powodu = 422), `POST /changes/{id}/tasks`, `PATCH /tasks/{id}` (zrobione,
  osoba, termin), `GET /summary?role=` (do decyzji, terminy w 60 dni, 3 tytuły),
  `GET /runs` (10 ostatnich biegów, same liczby). Flaga wyłączona: odczyty dają
  `{"enabled": false, …}`, zapisy 409.
- **Pętla:** co 15 minut; Zbieracz od 5:30, jeden start na dzień (nieudany liczy
  się godzinę); `since` = dzień startu ostatniego przyjętego biegu, domyślnie
  dziś − 3 dni; sondy otwartych zmian raz dziennie od 6:30.

