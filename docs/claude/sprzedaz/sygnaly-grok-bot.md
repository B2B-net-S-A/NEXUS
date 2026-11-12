# Sygnały i punkty do rozmowy z bota researchu (Grok Bot) — decyzje Artura 09.11.2026
<!-- indeks: Grok Bot, bieg i jednorazowy token, raport jako dane niezaufane, tylko nazwy i domeny firm do bota, źródło leada research, klient NEXUSA do DL, punkty do rozmowy first_call/ongoing, pętla sales_signals, flaga SALES_SIGNALS_ENABLED, skrypt próbnego biegu, zadania bota, rejestr rodzajów bot_tasks, sales_bot_results, SALES_BOT_TASKS_ENABLED, polecenie v2, osoby decyzyjne od bota, haczyk przed telefonem call_hook, teczka przed spotkaniem meeting_prep, 16:00 na następny dzień roboczy -->

Bot robi research firm (strony, prasa, komunikaty, serwis X) i odsyła wynik przez
API. NEXUS decyduje, co z tego jest leadem, i pokazuje, kogo w firmie znamy.
Propozycja i makiety G1–G3: https://claude.ai/artifact/TJoEYka7Rf87ahfCWJBSYd,
stan z 09.11 wieczorem: https://claude.ai/artifact/4o8XBacuSzBgQK8iY1Jq8d.

To zmienia decyzję z 27.10.2026 „leady bez silnika” (`sprzedaz-w-nexusie-decyzje-i-reguly.md`,
sekcja Leady) i pozycję „skan prasy” z listy „Poza zakresem”: Artur 09.11 wybrał
„Buduj od razu”. Skan ogłoszeń z portali i LinkedIna dalej jest poza zakresem.

## Przepływ

- **NEXUS startuje bieg** (`services/sales/signals.py`, `start_run`): wiersz
  `sales_signal_runs` z listą firm i SHA-256 jednorazowego tokenu, potem webhook
  bota (`GROK_BOT_WEBHOOK_URL`, nagłówek `Authorization: Bearer GROK_BOT_WEBHOOK_KEY`).
  Bieg jest zapisany przed wywołaniem webhooka, bo bot może odpowiedzieć szybciej niż
  NEXUS skończy żądanie. **Zmiana stanu biegu tylko warunkowo** (`status = 'started'`
  w `UPDATE`): błąd webhooka ani wygaśnięcie nie nadpiszą przyjętego raportu.
  Timeout webhooka zostawia bieg otwarty z tokenem (nie wiadomo, czy bot dostał
  zlecenie), błąd HTTP zamyka go jako `failed`. Nieudany przegląd w poniedziałek
  pętla ponawia po godzinie.
- **Do bota idą tylko nazwy i domeny firm** (`webhook_body`), plus powody odrzuceń
  wyłącznie z listy `REJECT_REASONS` (API przyjmuje dowolny tekst, a ten mógłby mieć
  nazwisko albo telefon) i znane już linki. Żadnych osób, CV, kontaktów ani NIP-ów: komputery bota stoją
  w USA, bez regionu UE.
- **Bot odsyła jeden raport** na `POST /api/integrations/sales-signals/runs/{id}`
  z nagłówkiem `X-Run-Token`. Token działa dla jednego biegu, raz, najwyżej 2 godziny.
  Brak biegu, zły, zużyty i wygasły token dają to samo 401. Sesja użytkownika go nie
  zastępuje. Własne poświadczenie trasy to `require_signal_run_token`
  (marker w `tests/test_route_authz_contract.py`).
- **Raport to dane niezaufane**, bo bot czyta cudze strony: `extra=forbid` (pola osób
  nie istnieją), limity długości, tylko linki http(s), najwyżej 50 sygnałów i 4 punkty
  na firmę, firma tylko z listy biegu, znaki sterujące wycięte. Tytuł i punkt puste
  po czyszczeniu oraz link dłuższy niż kolumna po dopisaniu `https://` to 422, nie 500. Żadnych automatycznych
  działań poza zapisem leada i punktów.

## Sygnał → lead

- Źródło `research` (migracja 0676 podmienia CHECK), odcisk
  `research|sha256(firma|link)`. Ponowny bieg aktualizuje treść i siłę, **nigdy status
  ani powód odrzucenia** ustawiony przez handlowca.
- Odpada: firma spoza biegu, sygnał starszy niż 120 dni albo z przyszłości (kalendarz
  firmy), ten sam link drugi raz, **firma powiązana z klientem NEXUSA** (`client_gate`,
  raport podaje klienta i Delivery Leada; lead nie powstaje, jak przy ręcznym leadzie).
- Lead dostaje opiekuna firmy jako osobę przypisaną. Siła → `score`: silny 85,
  średni 60, słaby 30.
- **„Dlaczego teraz” to wniosek bota, nie fakt.** Ekran tak to podpisuje. Lead nie
  daje prawa do zimnego kontaktu (art. 398 PKE), wejście przez istniejące relacje.

## Punkty do rozmowy

- `sales_company_briefings`: jeden wiersz na firmę, nadpisywany kolejnym biegiem.
  Rodzaj `first_call` (nie było rozmowy ani spotkania) albo `ongoing`
  (`signal_targets.modes_for`); bot dostaje go w `firms[].mode`.
- **Kiedy** (decyzja Artura): nowy lead albo nowa szansa z ostatnich 7 dni bez punktów,
  a w poniedziałek od 7:30 odświeżenie dla otwartych szans z krokiem albo spotkaniem
  w ciągu 14 dni i punktami starszymi niż 6 dni. Firma z biegu z ostatnich 24 godzin
  nie wraca, żeby firma bez punktów nie szła do bota co godzinę.
- Widać je w panelu sygnału, na karcie firmy (Przegląd) i na karcie szansy. Brak
  punktów, wyłączony kanał i błąd zapytania nic nie pokazują: to dodatek, nie warunek.

## Pętla i włączenie

- `tasks/sales_signals.py` w kontenerze worker, co 15 minut: wygasza biegi bez
  raportu (ostrzeżenie w logu = alarm), w poniedziałek od 7:00 przegląd sygnałów firm
  z tagiem `SALES_SIGNALS_TAG` (domyślnie „sygnały”, pilot 20 firm), punkty najwyżej
  raz na godzinę. Na stagingu zablokowana (`STAGING_BLOCKED_TASKS`).
- **Flaga `SALES_SIGNALS_ENABLED` domyślnie wyłączona** (rejestr flag). Wyłączona:
  pętla stoi, ekrany nie pokazują sygnałów ani punktów. Trasa przyjęcia raportu działa
  zawsze, bo bez biegu nie ma tokenu.
- **Próba przed włączeniem** (instrukcja rutyny i kroki: `docs/sales-grok-bot-setup.md`): ustaw `GROK_BOT_WEBHOOK_URL` i `_KEY` workflowem „Coolify
  set env”, potem w kontenerze backendu
  `python -m scripts.sales_signals_run --kind signals --company-ids <3 id>` i sprawdź,
  czy bieg przeszedł na `received` bez klikania zgody w bocie.
- Logi są publiczne: same liczby, bez nazw firm. Nazwy firm i Delivery Leadów leżą
  tylko w `sales_signal_runs.report` (ekran „Raport bota”).

## Pilot i warunek rozszerzenia

Pilot 4 tygodnie na 20 firmach, raz w tygodniu; oceniają dwa konta handlowców.
Rozszerzenie na 84 firmy tylko, gdy co najmniej 30% sygnałów „do sprawdzenia” kończy
się telefonem i jest choć jedno spotkanie. Przed wyjściem poza 20 firm opinia IOD:
łączenie sygnałów z CV to szersze użycie danych.

## Zadania bota (decyzje Artura 12.11.2026)

Artur 12.11 zdecydował, że bot robi więcej niż sygnały i punkty: uzupełnienie karty
firmy (`enrich`), pytania na żądanie (`question`), sprawdzenie przegranych szans
(`winback`), szukanie nowych centrów IT (`discovery`), mapy osób decyzyjnych
(`people`) i nowe rodzaje punktów: haczyk do telefonu (`call_hook`) i przygotowanie
spotkania (`meeting_prep`). Każde to osobny PR; fundament (migracja 0684) jest wspólny,
więc kolejny rodzaj to nowy moduł bez migracji i bez zmiany rutyny bota.

- **Rejestr rodzajów** `services/sales/bot_tasks/` (`REGISTRY`, wzór w `base.py`):
  `BotTask` ma `kind`, `task_text(run, ctx)` (polecenie po polsku), `report_format()`
  (przykład raportu), `report_model` (pydantic, `extra="forbid"`, limity, linki przez
  `SourceUrl`), `ingest(db, run, report, now)` (podsumowanie z liczbami), opcjonalnie
  `needs_firms`, `request_model`, `lead_feedback`, `reply`, `accept`. `signals`
  i `briefing` to opakowanie dotychczasowego kodu (`bot_tasks/signals_briefing.py`),
  zachowanie bez zmian. Rodzaj spoza rejestru: `start_run` nic nie startuje,
  a raport biegu takiego rodzaju dostaje 409 i bieg jest zamykany jako `failed`.
- **Przyjęcie raportu per rodzaj:** ta sama trasa, ten sam token i te same 401.
  Treść czytana jako JSON, najwyżej 512 KB (413), sprawdzana modelem rodzaju (422,
  token zostaje ważny), potem `ingest` rodzaju i bieg `received`. Odpowiedź dla bota
  i logi to same liczby.
- **Do bota dalej idą tylko nazwy i domeny firm** oraz pola, które rodzaj sam
  wkłada do `request` (`sales_signal_runs.request`, model `request_model`; rodzaj bez
  modelu nie przyjmuje żadnych pól). Każde pole ma w module rodzaju uzasadnienie.
  Tekst pytania od handlowca (`question`) przed wysyłką przejdzie przez filtr danych
  osobowych. `requested_by_user_id` zostaje w NEXUSIE, do bota nie idzie.
- **Bot może ODSYŁAĆ osoby** dla rodzaju `people` (decyzja Artura 12.11.2026): osoby
  decyzyjne tylko z opublikowanego źródła z linkiem, bez zgadywanych e-maili
  i telefonów. NEXUS osób do bota nie wysyła. Model raportu `people` musi to
  wymuszać polami (bez pól kontaktu, których źródło nie podaje), a wynik idzie do
  decyzji handlowca, nie od razu do kontaktów.
- **Wyniki do decyzji** `sales_bot_results` (0684): rodzaj, firma, `payload`
  (dane z raportu po walidacji), status `new` / `accepted` / `rejected` / `partial`,
  kto i kiedy zdecydował, powód odrzucenia (`decision_reason`, do bota nie wraca).
  Zapis przez `bot_tasks.save_results` z odciskiem `result_fingerprint`: kolejny bieg
  z tym samym wynikiem odświeża treść tylko przy `new`, decyzji nie cofa. Wyniki idą
  za firmą przy scaleniu kart.
- **API wyników** `api/sales_bot_results.py`: `GET /api/sales/bot-results`
  (`kind`, `status`, `company_id`, `limit` do 200; „Sprzedaż: podgląd”),
  `POST /{id}/reject` z opcjonalnym `reason` i `POST /{id}/accept` („Sprzedaż:
  edycja”). Przyjęcie robi rodzaj (`BotTask.accept`); domyślnie 409 „Ten rodzaj nie
  ma jeszcze akcji.”. Decyzja tylko dla `new` i `partial`, inaczej 409.
- **Flaga `SALES_BOT_TASKS_ENABLED` domyślnie wyłączona** (rejestr flag). Wyłączona:
  startują tylko `signals` i `briefing`, lista wyników mówi `enabled: false`.
- **Polecenie rutyny v2** (`docs/sales-grok-bot-setup.md`, sekcja 4): bot robi to,
  co mówi `task`, z zasadami ogólnymi (źródło otwarte, adres i data, bez portali
  ogłoszeń i bez LinkedIna, bez zgadywania e-maili i telefonów) i odsyła jeden
  `POST` w kształcie `report_format`. Kolejność: wdrożenie → wklejenie v2 → próba
  skryptem (`--kind`, `--request '{json}'`) → włączenie flagi.
- Logi, kod i testy bez nazw firm i osób (repo i logi Actions są publiczne).

## Haczyk i teczka (decyzje Artura 12.11.2026)

Dwa nowe rodzaje punktów z „Zadań bota”, liczone w dzień roboczy od 16:00
(`local_now()`, kalendarz firmy ze świętami) na **następny dzień roboczy**: w piątek
na poniedziałek, przed świętem na dzień po nim. Kod: `services/sales/hook_prep_targets.py`
(wybór firm), `bot_tasks/call_hook.py` (haczyk), `bot_tasks/signals_briefing.py`
(tryby w poleceniu i zapisie), `tasks/sales_signals.py` (`hooks_and_prep`).

- **Bez nowego rodzaju biegu i bez migracji.** CHECK `sales_signal_runs.kind` nie zna
  `call_hook` ani `meeting_prep`, więc oba to tryby firm w biegu `briefing`
  (`firms[].mode`, CHECK trybów poszerzyła 0684). Bieg trybu startuje raz dziennie;
  nieudany liczy się tylko przez godzinę, potem ponowienie. Start i zapis tylko przy
  `SALES_BOT_TASKS_ENABLED`, a pętla chodzi tylko z `SALES_SIGNALS_ENABLED` (obie flagi);
  na stagingu stoi jak cała pętla sygnałów. Logi: same liczby.
- **Haczyk (`call_hook`)**: firmy z kolejki dzwonienia, które staną w niej następnego
  dnia roboczego, wybrane tą samą selekcją co kolejka (`calling.companies_due_by`
  na `_own_campaign_records`): powroty z datą po dziś i najpóźniej w tym dniu, potem
  nowe rekordy aktywnych kampanii w kolejności kolejki, po jednym od każdej osoby na
  zmianę. Najwyżej 40 firm na bieg, bez firm z haczykiem młodszym niż 14 dni. Bot
  dostaje nazwę i domenę i odsyła w `hooks` jedno zdanie otwarcia związane z faktem
  i do 2 faktów z adresem i datą (najwyżej rok wstecz) o firmie ogólnie i o tym, jak
  używa automatyzacji, AI i IT. Pól osób i kontaktów model raportu nie ma.
- **Gdzie leży haczyk — decyzja:** `sales_company_briefings` ma jeden wiersz na
  firmę, więc haczyk nadpisałby punkty do prowadzonej szansy albo teczkę, a firma
  z kolejki często ma jedno i drugie. Haczyk ma też inny kształt (zdanie + fakty).
  Dlatego leży w `sales_bot_results` (rodzaj `call_hook`, firma, `payload`), jeden
  wiersz na bieg i firmę, ze statusem `new` (to podpowiedź, nie wynik do przyjęcia).
  Punkty, które bot przyśle dla firmy w trybie `call_hook`, odpadają przy zapisie.
- **Teczka (`meeting_prep`)**: firmy ze spotkaniami od jutra do końca następnego dnia
  roboczego (w piątek z weekendem), wybrane jak „Spotkania dziś” w „Moim dniu”
  (`my_day.meeting_company_ids`, bez odwołanych i automatów). Termin z „Umów
  spotkanie” jest tam też, bo przekazanie zapisuje go jako spotkanie prowadzącego
  (`handoff._sync_meeting`). Bez firm z punktami młodszymi niż 3 dni, najwyżej 40.
  Polecenie mówi, z którą firmą to pierwsze spotkanie (`request.first_meeting`, same
  numery firm z biegu, liczone jak `first_call`), a z którą rozmowy już trwają.
  Punkty (≤4, ze źródłami) nadpisują wiersz firmy jak dotąd.
- **Ekrany:** karta rozmowy w „Dzwonieniu” pokazuje haczyk pod nazwą firmy z podpisem
  „Bot · sprawdź źródło” (`calling/CallHook.tsx`, pole `call_hook` w
  `GET /api/sales/signals/briefings/{id}`, puste bez flagi zadań). Teczkę pokazują
  „Przygotowanie do spotkania” w „Moim dniu” i karta przekazanego spotkania
  (`TalkingPoints`, „Punkty do rozmowy przed spotkaniem”). Brak, wyłączona flaga
  i błąd zapytania nic nie pokazują.
- **Próba przed włączeniem:** `python -m scripts.sales_signals_run --kind briefing
  --mode call_hook --company-ids <id>` (albo `--mode meeting_prep`).

Testy: `backend/tests/test_sales_signals_unit.py`, `backend/tests/test_sales_signals_api.py`,
`backend/tests/test_sales_bot_tasks_unit.py`, `backend/tests/test_sales_bot_tasks_api.py`,
`backend/tests/test_sales_hook_prep_unit.py`, `backend/tests/test_sales_hook_prep_api.py`,
`frontend/src/components/sales/__tests__/sales-signals.test.tsx`,
`frontend/src/components/sales/__tests__/sales-hook-prep.test.tsx`.
