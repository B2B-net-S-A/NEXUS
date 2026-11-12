# Sygnały i punkty do rozmowy z bota researchu (Grok Bot) — decyzje Artura 09.11.2026
<!-- indeks: Grok Bot, bieg i jednorazowy token, raport jako dane niezaufane, tylko nazwy i domeny firm do bota, źródło leada research, klient NEXUSA do DL, punkty do rozmowy first_call/ongoing, pętla sales_signals, flaga SALES_SIGNALS_ENABLED, skrypt próbnego biegu, punkty przy ofertach Do decyzji (bot_points, nic nowego) -->

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

## Punkty przy ofertach „Do decyzji” (decyzja Artura 12.11.2026)

Pomiar na kopii stagingu z 10.11: w „Do decyzji” 39 pozycji, ok. 930 tys. zł MRR, i żadna
nie miała punktów, bo pozycja „Do decyzji” z definicji nie ma kroku, a odświeżenie szło
tylko przed krokiem. Decydujący ma widzieć, co zmieniło się w firmie od wysłania oferty,
albo wprost, że bot nic nie znalazł.

- **Kiedy:** w tym samym poniedziałkowym odświeżeniu (od 7:30) idą firmy pozycji
  „Do decyzji”, od największego MRR (`signal_targets.to_decide_company_ids`). Sekcję
  wyznacza `offers.load_rows`, to samo co ekran; nie licz jej drugi raz. Te same progi:
  punkty starsze niż 6 dni albo brak punktów, najwyżej 100 firm, firma z biegu z ostatnich
  24 godzin nie wraca, najwyżej 25 firm na bieg. Rodzaj zawsze `ongoing` (oferta poszła).
- **„Nic nowego” to odpowiedź:** firma `ongoing`, którą bot odesłał w `no_signal` bez
  punktów, dostaje wiersz z pustą listą (`plan_intake`). Ekran Oferty mówi wtedy „Bot nie
  znalazł nic nowego od wysłania oferty.”, inne ekrany pustej listy nie pokazują. Firma
  `first_call` w `no_signal` wiersza nie dostaje i wraca do bota jak dotąd.
- **API:** `GET /api/sales/offers` daje przy pozycji „Do decyzji” `bot_points`
  (`generated_at`, `points`) jednym zapytaniem dla wszystkich wierszy; z wyłączoną flagą,
  w „W toku” i bez wiersza punktów `null`.
- **Ekran:** pod podpisem szansy do dwóch punktów „DD.MM.RRRR: tekst” z linkiem do źródła
  (tylko http(s), `safeHref`) i podpisem „Bot · wniosek, sprawdź źródło”. Punkty starsze
  niż wejście oferty na etap też widać. Tekst się zawija, link zostaje cały.
- Testy: `test_sales_signals_unit.py` (wybór firm, pusta odpowiedź), `test_sales_offers.py`
  (`bot_points`, wybór z bazą), `sales-offers.test.tsx`.

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

Testy: `backend/tests/test_sales_signals_unit.py`, `backend/tests/test_sales_signals_api.py`,
`frontend/src/components/sales/__tests__/sales-signals.test.tsx`.
