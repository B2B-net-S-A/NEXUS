# Sygnały i punkty do rozmowy z bota researchu (Grok Bot) — decyzje Artura 09.11.2026
<!-- indeks: Grok Bot, bieg i jednorazowy token, raport jako dane niezaufane, tylko nazwy i domeny firm do bota, źródło leada research, klient NEXUSA do DL, punkty do rozmowy first_call/ongoing, pętla sales_signals, flaga SALES_SIGNALS_ENABLED, skrypt próbnego biegu, zadania bota, rejestr rodzajów bot_tasks, sales_bot_results, SALES_BOT_TASKS_ENABLED, polecenie v2, osoby decyzyjne od bota, punkty przy ofertach Do decyzji (bot_points, nic nowego), zapis od razu bez potwierdzania (13.11), pole człowieka zostaje, historia karty bot-history, uzupełnianie kart enrich, Uzupełnij dane, apply_now, konflikt domeny i NIP-u, noc 1–6, Zapytaj bota question, filtr danych osobowych pytania, wniosek bota, Warto wrócić winback przegrane szanse, Nowe centra IT discovery, Załóż konto w Fabrykach IT, Przejmij i zaplanuj, take-over leada, origin leada, haczyk przed telefonem call_hook, teczka przed spotkaniem meeting_prep, 16:00 na następny dzień roboczy -->

Bot robi research firm (strony, prasa, komunikaty, serwis X) i odsyła wynik przez
API. NEXUS decyduje, co z tego jest leadem, i pokazuje, kogo w firmie znamy.
Propozycja i makiety G1–G3: https://claude.ai/artifact/TJoEYka7Rf87ahfCWJBSYd,
stan z 09.11 wieczorem: https://claude.ai/artifact/4o8XBacuSzBgQK8iY1Jq8d.

To zmienia decyzję z 27.10.2026 „leady bez silnika” (`sprzedaz-w-nexusie-decyzje-i-reguly.md`,
sekcja Leady) i pozycję „skan prasy” z listy „Poza zakresem”: Artur 09.11 wybrał
„Buduj od razu”. Skan ogłoszeń z portali i LinkedIna dalej jest poza zakresem.

## Zapis od razu, bez potwierdzania (decyzja Artura 13.11.2026)

Artur 13.11.2026: dane od botów są od razu potwierdzone, bez „Przyjmij” i bez
oznaczeń „bot”, „wniosek”, „do weryfikacji”, „sprawdź źródło” na ekranach
roboczych. Każde pole i każdą osobę można poprawić jak zwykle. Ta sekcja ma
pierwszeństwo przed starszymi opisami przyjmowania niżej. Makiety:
https://claude.ai/artifact/2Hxqi6uLTSE4AYp1GPqtpV.

- **Pola firmy** (`enrich.apply_now`): puste pole i pole, które wcześniej wpisał
  bot, dostają wartość od razu. Pole wpisane przez człowieka zostaje (decyzja
  Artura: pól firmy bot nie nadpisuje), a wersja bota trafia tylko do historii.
  Pole „bota” rozpoznaje się po historii: karta ma dokładnie wartość, którą bot
  ostatnio wpisał (`_bot_owned`); po ręcznej zmianie pole należy do człowieka.
- **Stanowiska i odejścia osób** bot nadpisuje nowszą wartością (także wpisane
  ręcznie), stara idzie do historii; osoby z botów trafiają też do zakładki
  Kontakty, odejście to „nie pracuje”. Zbudowane 13.11 → `kontakty-jedna-lista.md`.
- **Osoby** (`people.add_now`): trafiają na mapę konta od razu, autor zapisu to
  osoba, która uruchomiła bieg, inaczej opiekun karty; pewność `confirmed`.
  Czeka tylko wynik, którego nie da się zapisać bez człowieka: marka z kilkoma
  kartami (trzeba wskazać kartę) i karta bez opiekuna przy biegu z pętli.
- **Dubel domeny albo NIP-u** z inną kartą niczego nie zmienia: wpis w historii
  z linkiem do tamtej karty, scalanie zostaje ręczne.
- **Historia karty** to jedyny ślad pochodzenia: `GET /api/sales/companies/{id}/bot-history`
  („Sprzedaż: podgląd”; osoby tylko z „Sprzedaż: edycja”), zakładka Aktywności
  (`bot/BotCardHistory.tsx`). Źródłem są wiersze `sales_bot_results` (status
  `accepted`, `payload.outcomes`: `applied` z `previous`, `kept` z `current`,
  `taken` z drugą kartą, `skipped` z uwagą), bez migracji. Kod:
  `services/sales/bot_card_history.py`.
- Etykiety „Bot · wniosek, sprawdź źródło”, „Research bota, sprawdź źródło”,
  „Bot · sprawdź źródło”, „wniosek bota (nie fakt)” zniknęły z Ofert, punktów do
  rozmowy, haczyka, panelu sygnału, „Warto wrócić” i „Zapytaj bota”. Link do
  źródła przy tekście zostaje.

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
- **„Dlaczego teraz” to wniosek bota.** Od 13.11.2026 ekran nie dokleja plakietki
  (decyzja Artura „bez oznaczeń”), obok stoi źródło sygnału. Lead nie
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
  (tylko http(s), `safeHref`) i linkiem do źródła (podpis „Bot · wniosek, sprawdź źródło” usunięty 13.11.2026). Punkty starsze
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
  wymuszać polami (bez pól kontaktu, których źródło nie podaje), a od 13.11.2026 wynik trafia
  od razu na mapę (sekcja „Zapis od razu”). Zbudowane: mapy z kontaktami ze
  źródeł publicznych, przegląd jak lista z researchu → `mapy-decydentow-od-bota.md`.
  Osobna rutyna Cognism odsyła dopasowanych decydentów do mapy karty firmy.
  Odczyt mapy wymaga „Sprzedaż: edycja”.
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
  linkami do źródeł (`calling/CallHook.tsx`, pole `call_hook` w
  `GET /api/sales/signals/briefings/{id}`, puste bez flagi zadań). Teczkę pokazują
  „Przygotowanie do spotkania” w „Moim dniu” i karta przekazanego spotkania
  (`TalkingPoints`, „Punkty do rozmowy przed spotkaniem”). Brak, wyłączona flaga
  i błąd zapytania nic nie pokazują.
- **Próba przed włączeniem:** `python -m scripts.sales_signals_run --kind briefing
  --mode call_hook --company-ids <id>` (albo `--mode meeting_prep`).

## „Warto wrócić” i „Nowe centra IT” (decyzja Artura 12.11.2026)

Artur 12.11.2026 zdecydował, że oba rodzaje powstają teraz. Warunek pilota z 09.11
(30% sygnałów kończy się telefonem, opinia IOD przed wyjściem poza 20 firm) dotyczy
sygnałów; dla „Warto wrócić” zastępuje go ta decyzja, bo to firmy, z którymi już
rozmawialiśmy, a „Nowe centra IT” działa wyłącznie na poziomie firm (bez osób, bez
danych z NEXUSA w zleceniu). Oba startują tylko przy `SALES_BOT_TASKS_ENABLED`
i tylko raz w miesiącu: pętla `tasks/sales_signals.py` w pierwszy poniedziałek
miesiąca od 7:00, a gdy wtedy nie wyszło, przy pierwszym obrocie po tej chwili
(nieudany webhook po godzinie). Próba: `--kind winback --company-ids …` i `--kind discovery`.
Makiety: `LeadsBotModes.tsx` z gałęzi makiet. Przetargów z makiety nie budujemy (Artur: nie).

### „Warto wrócić” (`winback`, G-E)

- **Firmy** (`signal_targets.winback_deals`): szansa przegrana w ostatnich 14 miesiącach
  kalendarza firmy z `lost_reason` dokładnie z `WINBACK_LOST_REASONS` („Klient zrezygnował
  z projektu”, „Projekt na bliżej nieokreśloną przyszłość”, „Cena za wysoka”, „Brak
  kontaktu z klientem”), karta poza archiwum, bez otwartej szansy, poza klientami NEXUSA
  (`client_gate`), najwyżej 50 firm od najświeższej przegranej. Kopia z 10.11.2026:
  31 takich przegranych w 29 firmach.
- **Do bota idą tylko nazwy i domeny.** Powód przegranej, tytuł szansy i opiekun zostają
  w NEXUSIE. Raport ma kształt sygnałów (`ReportSignal`, okno 120 dni), bez punktów.
- **Wynik to lead**, nie `sales_bot_results`: źródło `research`, odcisk firma + link jak
  przy sygnałach, `payload.origin = "winback"` z `lost_opportunity_id`, tytułem,
  `lost_reason` i `lost_at`. Przy przyjęciu raportu firma jest sprawdzana jeszcze raz:
  otwarta szansa albo klient NEXUSA od startu biegu = lead nie powstaje.
- **Osoba przy leadzie:** opiekun firmy, gdy pracuje w Sprzedaży (`offers.works_in_sales`),
  inaczej opiekun przegranej, gdy pracuje w Sprzedaży, inaczej nikt.
- **Leady → „Warto wrócić”** (`components/sales/bot-modes/WinBackInbox.tsx`, lista
  `GET /api/sales/leads?origin=winback`): przegrana (link do szansy, data, powód), co się
  zmieniło ze źródłem, „Dlaczego teraz” (bez plakietki od 13.11.2026).
  „Zaplanuj powrót” to zwykłe zadanie przy firmie (`POST /api/sales/activities`)
  u osoby z leada, a lead przechodzi na „W kontakcie”. Zadanie nie wisi na przegranej
  szansie, bo lista Zadania nie pokazuje pozycji przy przegranych. Bez osoby w Sprzedaży
  przycisk to „Przejmij i zaplanuj”: `POST /api/sales/leads/{id}/take-over`
  („Sprzedaż: edycja”, 409, gdy lead ma osobę w Sprzedaży), potem zadanie u klikającego.
  „Nie teraz” odrzuca lead z powodem z `REJECT_REASONS` (wraca do bota jak przy sygnałach).
  Żadnej automatyzacji kontaktu.
- Skrzynka sygnałów pyta o `origin=grok`, więc leady „Warto wrócić” są tylko w swoim widoku.

### „Nowe centra IT” (`discovery`, G-D)

- **Bieg bez firm** (`needs_firms=False`, `request` pusty): zapowiedzi z ostatnich 183 dni
  o nowych albo rozbudowywanych centrach IT, GBS, R&D i usług wspólnych w Polsce, najwyżej
  20 pozycji (firma, domena, miasto, co, skala, dlaczego, link, data). Bez osób.
- **Karta:** po domenie, potem po nazwie kanonicznej (`companies.find_duplicates`, ta sama
  reguła co 409 przy zakładaniu karty), potem po marce (`company_aliases.brand_of`; spółka
  grupy o innej nazwie to nie ta sama karta). Wynik w `sales_bot_results` z `company_id`
  albo bez, odcisk domena-albo-nazwa + link.
- **Leady → „Nowe centra IT”** (`bot-modes/NewFirmsInbox.tsx`, `GET /api/sales/bot-results?kind=discovery`):
  „W NEXUSIE” mówi, czy karta jest, kto jest opiekunem i czy pracuje w Sprzedaży (pola
  `owner`, `owner_in_sales` listy wyników). „Załóż konto w Fabrykach IT” (`accept`):
  karta, gdy jej nie ma (dopasowanie jeszcze raz, potem nowa karta z opiekunem = klikający),
  i szansa w `atlas-it-factories` na pierwszym otwartym etapie z opiekunem = klikający
  i wpisem w historii (`history.record_created`). Karta z otwartym kontem w tym lejku nie
  dostaje drugiego: wynik jest przyjęty i wskazuje istniejące (`existed`). „Nie teraz”
  to odrzucenie wyniku z powodem.

### Ekran

- Widoki pokazują się w przełączniku Leadów tylko przy `bot_tasks_enabled` z listy leadów.
  Błąd zapytania to komunikat z ponowieniem, wyłączony kanał to napis, nie pusta lista.
- Nowości: `sprzedaz-leady-warto-wrocic` i `sprzedaz-leady-nowe-centra-it` (kropki na
  przełączniku, `requires_setting = SALES_BOT_TASKS_ENABLED`).

## Uzupełnianie kart (G-A, rodzaj `enrich`, 12.11.2026)

Makieta zatwierdzona przez Artura: karta firmy, „Bot uzupełnił kartę” pod faktami.
Moduł `services/sales/bot_tasks/enrich.py`, trasy `api/sales_company_bot.py`.

- **Do bota idzie to co zawsze:** nazwa i domena firmy, bez pól `request`.
  Bot odsyła na firmę domenę, stronę www, NIP, miasto siedziby, branżę, przedział
  liczby pracowników (`1-49`, `50-249`, `250-999`, `1000+`) i nazwę spółki matki,
  każde pole z własnym `source` (http(s)) i opcjonalną datą.
- **Zła wartość odpada sama, raport przechodzi:** NIP z błędną sumą kontrolną,
  domena darmowej skrzynki albo nie-domena (`companies.mail_domain`), strona spoza
  http(s), spółka matka o nazwie tej samej firmy, wartości ponad długość kolumny.
  Pole równe temu, co już jest na karcie, też odpada. Podsumowanie biegu podaje
  tylko liczby (`invalid_fields`, `same_fields`).
- **Jeden wynik na firmę** w `sales_bot_results` (`payload.fields`), odcisk z wartości
  pól. Nowsza propozycja usuwa starszą, o której nikt nie zdecydował; decyzji nie
  cofa. Przedział pracowników to propozycja „Wielkości” (`tier`: do 249 osób „Mała”,
  250–999 „Średnia”, od 1000 „Duża”) z `size_range`; „Strategiczna” to decyzja
  handlowa, więc bot jej nie proponuje.
- **Zapis od razu** (od 13.11.2026, `apply_now` przy przyjęciu raportu): ta sama
  ścieżka co ekran Firmy (`companies.apply_fields`), reguły pól w sekcji „Zapis od
  razu” na górze. Wiersz wyniku dostaje status `accepted` i `payload.outcomes`;
  akcji przyjęcia nie ma (`accept` rodzaju to 409). Stare propozycje `new`/`partial`
  tej firmy znikają przy następnym raporcie.
- **Domena albo NIP z innej karty** (niezarchiwizowanej) nie trafia na kartę, wynik
  pola to `taken` z nazwą tamtej karty (historia): scalenie kart to osobny krok
  (`scalanie-kart-firm-i-domeny.md`). Domena wyliczona ze strony www (gdy karta nie
  ma domeny) przy takim konflikcie też nie trafia na kartę (`apply_fields` dostaje
  wprost `domain=None`), strona tak.
- **Spółka matka** staje się `parent_company_id` tylko wtedy, gdy po nazwie
  kanonicznej pasuje dokładnie jedna inna karta, która nie ma tej firmy za swoją
  matkę. Inaczej pole ma wynik `skipped` z uwagą w historii.
- **Przycisk „Uzupełnij dane”** w nagłówku karty („Sprzedaż: edycja”,
  `POST /api/sales/companies/{id}/enrich`, 20 na godzinę na osobę). Ta sama karta
  nie wraca do bota przez 2 godziny od poprzedniego biegu, który nie padł (409).
  Stan karty: `GET /{id}/enrich` (ostatni bieg; karta pokazuje tylko „Szukam
  danych firmy” i po biegu odświeża fakty i historię).
- **Noc:** krok pętli `tasks/sales_signals.py` między 1:00 a 6:00 (kalendarz firmy),
  najwyżej jeden bieg na godzinę i 5 na noc, po 20 kart: bez domeny, z opiekunem
  albo trwającą szansą i niesprawdzane nocą przez 30 dni.
  Liczą się tylko biegi pętli (`requested_by_user_id` puste). Pętla startuje, gdy
  włączona jest `SALES_SIGNALS_ENABLED` albo `SALES_BOT_TASKS_ENABLED`; każda część
  pilnuje swojej flagi. Na stagingu pętla jest zablokowana.

## Zapytaj bota (G-B, rodzaj `question`, 12.11.2026)

Moduł `services/sales/bot_tasks/question.py`, trasy `api/sales_company_bot.py`,
karta `AskBotCard` w prawej kolumnie Przeglądu nad „Kogo znamy”.

- `POST /api/sales/companies/{id}/ask {question}` („Sprzedaż: edycja”, 10 na godzinę
  na osobę). Pytanie 5–300 znaków po czyszczeniu. **Filtr danych osobowych**
  (`personal_data_reason`) odmawia 422 z polskim zdaniem: adres e-mail, numer konta
  (IBAN), PESEL i każdy ciąg co najmniej 7 cyfr z separatorami telefonu (spacja,
  kreska, nawiasy, plus), więc też NIP i kwota „1 000 000”. Daty („1.10.2026”,
  „2026-10-01”) przechodzą. Ten sam filtr siedzi w `request_model`, który przyjmuje
  tylko `question`. Kto pytał, zostaje w `requested_by_user_id`, do bota nie idzie.
- **Odpowiedź:** `{answer: [{text, url?, published?}]}`, najwyżej 6 linii po 400
  znaków. Linia bez linku jest dozwolona i ekran podpisuje ją „wniosek bota”. Pusta
  lista to „Bot nie znalazł odpowiedzi”. Wynik to jeden wiersz `sales_bot_results`
  na bieg, bez akcji przyjęcia.
- **Lista na karcie:** `GET /{id}/questions` zwraca 5 ostatnich biegów `question`
  tej firmy (kto, kiedy, po ilu minutach, odpowiedź). Trwający bieg to „Bot szuka
  odpowiedzi, zwykle kilka minut” i ekran odpytuje co 20 s; `failed` i `expired`
  mają komunikat i „Zapytaj ponownie”. Błąd zapytania to komunikat z ponowieniem,
  nie pusta lista.
- Wyłączona flaga `SALES_BOT_TASKS_ENABLED`: obie karty i przycisk znikają, starty
  odpowiadają 409 „Zadania bota są wyłączone.”, odczyty `enabled: false`. Bot bez
  adresu webhooka: 409 z prośbą o administratora.
- Logi: numer biegu, numer firmy i status, bez nazw i bez treści pytań.

Testy: `backend/tests/test_sales_bot_company_unit.py`,
`backend/tests/test_sales_bot_company_api.py`,
`frontend/src/components/sales/__tests__/sales-company-bot.test.tsx`, a także
`backend/tests/test_sales_signals_unit.py`, `backend/tests/test_sales_signals_api.py`,
`backend/tests/test_sales_bot_tasks_unit.py`, `backend/tests/test_sales_bot_tasks_api.py`,
`backend/tests/test_sales_hook_prep_unit.py`, `backend/tests/test_sales_hook_prep_api.py`,
`backend/tests/test_sales_bot_winback_discovery_unit.py`, `backend/tests/test_sales_bot_winback_discovery_api.py`,
`frontend/src/components/sales/__tests__/sales-signals.test.tsx`,
`frontend/src/components/sales/__tests__/sales-hook-prep.test.tsx`,
`frontend/src/components/sales/__tests__/sales-bot-modes.test.tsx`.
