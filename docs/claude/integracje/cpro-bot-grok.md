# Bot Cpro: Grok Bot wrzuca kandydatów Nordei do Cpro (17.11.2026)
<!-- indeks: bot Cpro, cpro_bot, rutyna NEXUS Cpro, Grok Bot, nordea.onevms.se, Add Consultant, Offer, Submit Offer, ściągawka lokalizacji, Available from, why_points, Motivation, nazwa pliku bez #, CPRO_BOT_ENABLED, GROK_BOT_CPRO_WEBHOOK, cpro_bot_runs, Ponów botem, dane z innej rekrutacji, Marcin kilka requestów, scripts.cpro_bot_run -->

Osoba od Cpro (Sandra) przepisywała każdego kandydata z kolejki „Do Cpro”
do portalu dostawcy Nordei (`nordea.onevms.se`, Inkopio): profil konsultanta,
oferta, CV, motywacja, dostępność, lokalizacja, dopasowanie, „Submit Offer”.
Około 5 minut na osobę, a przy osobie wrzucanej na kilka requestów — kopiowanie
danych między kartami. Nagrania Sandry z 28.10.2026, decyzje Artura z 17.11.2026.

## Robot NEXUSA zamiast Grok Bota (decyzje Artura 24.11.2026)

- **Dlaczego:** biegi rutyny Grok Bota uruchamiane bez człowieka nie dostają
  hasła z Vault i kończą się przed logowaniem (biegi 2 i 6 w `cpro_bot_runs`).
  Szkice powstawały tylko wtedy, gdy ktoś wklejał token biegu do otwartej
  rozmowy (biegi 3–5). Artur wybrał własnego robota zamiast półautomatu.
- **Gdzie:** pakiet `backend/cpro_robot/` (bez importów `app`), obraz
  `backend/Dockerfile.cpro-robot` (Playwright + Chromium), usługa `cpro-robot`
  w `docker-compose.yml` za profilem `cpro-robot`. Worker budzi go tym samym
  webhookiem biegu (`GROK_BOT_CPRO_WEBHOOK_URL=http://cpro-robot:8090/wake`,
  klucz Bearer `GROK_BOT_CPRO_WEBHOOK_KEY`). Robot pobiera zlecenie, CV
  i oddaje raport trasami z tokenem jak rutyna, z tymi samymi kontrolami
  originu i ścieżek (`cpro_robot/nexus.py`). Reguły pól i wyników są wspólne:
  `task_text.py` opisuje je dla człowieka i Groka, `cpro_robot/portal.py`
  wykonuje.
- **Konta:** samo hasło, bez MFA. `CPRO_ROBOT_{IGOR,MARCIN}_{USERNAME,PASSWORD}`
  ustawia Artur przez workflow „Coolify set env” (`value_from_secret`).
  Ta zmiana zastępuje regułę „hasło tylko w Hints Groka”. Skarbiec Coolify
  trafia do `.env`, więc hasła widzi też backend; świadomie. Tożsamość konta
  w portalu to podpis w bocznym pasku (`.vmsSideBarProfileUser`) równy
  `CPRO_ROBOT_*_DISPLAY_NAME`. Trasa konta według DL jest bez zmian
  (`cpro_robot/rules.py`, test równości z `cpro_bot/accounts.py`).
- **Tylko szkice.** Bieg z `submit=true` robot kończy wynikiem `failed`/`other`.
  `CPRO_ROBOT_DRY_RUN` (domyślnie `true` w compose) zatrzymuje pozycję przed
  pierwszym zapisem w Cpro (Add Consultant, Upload CV, Save). Raport mówi
  wtedy, do którego kroku robot doszedł. Po udanej próbie ustaw `false`.
  „Former consultant/employee” bez danych z karty: brak „Nordea” w tekście
  PDF daje oba „No”, a Nordea w CV oznacza `failed`, bo rozstrzyga człowiek.
- **Włączenie** (kolejność): sekrety kont → `CPRO_ROBOT_*_DISPLAY_NAME` →
  `GROK_BOT_CPRO_WEBHOOK_URL` na adres robota → `COMPOSE_PROFILES` z `cpro-robot`
  → Deploy → `CPRO_BOT_AUTO_DRAFT_ENABLED=true` → jedna karta w próbie
  bez zapisu → `CPRO_ROBOT_DRY_RUN=false` → szkic do oceny Sandry.
- Rutyna Grok Bota „NEXUS Cpro” i tryb `--interactive-draft` zostają jako
  zapas. Poniższe zasady (konto według DL, braki karty, tylko szkic,
  bezpieczeństwo tokenu) obowiązują robota tak samo.

## Decyzje Artura (17.11.2026)

- **Robi to Grok Bot z pełnymi danymi.** Rutyna „NEXUS Cpro” loguje się do
  Cpro osobnym wpisem Hints właściwym dla Delivery Leada rekrutacji (reguła
  kont poniżej) i dostaje dane osoby: imię i nazwisko,
  narodowość, miasto, dostępność, stawkę do klienta, punkty „Why our
  candidate” i plik CV firmowego. To **świadomy wyjątek** od reguły „żadnych
  osób, CV ani kontaktów do bota w USA” (`sprzedaz/sygnaly-grok-bot.md`,
  `przepisy/radar-przepisow-dwa-boty.md`); dotyczy tylko tej rutyny. Do
  rejestru czynności przetwarzania i do IOD: transfer poza EOG (Grok Bot).
- **Docelowo bot sam klika „Submit Offer”.** Po przyszłym włączeniu przez
  Artura NEXUS przesuwa kartę na „Wysłane do Cpro” tym samym ruchem co
  „✓ Wrzucone”. Obecny pilotaż obejmuje wyłącznie szkic (`--start` bez
  `--submit`), przy `CPRO_BOT_ENABLED=false`. Najpierw Sandra ocenia szkic;
  pierwszą wysyłkę i późniejsze włączenie wykonuje Artur.
- Gdy rutyna w tle nie może zalogować się wpisem właściwego Delivery Leada,
  operator może przekazać aktywnej rozmowie Grok Bota jedno nowe zlecenie
  przez `--interactive-draft`. NEXUS sprawdza aktualną gotowość karty,
  numer requestu i konto. Jednorazowy token trafia do chronionego pola sesji.
  Potwierdzeniem próby są status DRAFT po ponownym otwarciu oferty w Cpro
  oraz raport tego samego biegu w NEXUSIE. Procedurę opisuje
  [instrukcja konfiguracji](../../cpro-grok-bot-setup.md).
- **Osoba na kilku requestach bez screeningu** (Marcin wrzuca ludzi do „Do
  Cpro” bez arkusza i bez rekrutera): brakujące Warunki i brakujące CV bot
  bierze z najnowszej karty tej osoby w **innej rekrutacji tego samego
  klienta**. Kolejka pokazuje „Dane z rekrutacji 42480”. Bez zmian dla Marcina
  i rekruterów.

## Konto Cpro według rekrutacji (24.11.2026)

- Źródłem jest wyłącznie `jobs.delivery_lead_id` bieżącej rekrutacji:
  Igor (`14`) → Hints **„Nordea Cpro – Igor”**,
  Marcin (`27`) i Dominik (`32`) → Hints **„Nordea Cpro – Marcin”**.
  Bot pomija kartę, jeśli DL jest nieaktywny, brakuje przypisania lub ID
  wykracza poza tę listę.
- Każda pozycja pełnego zlecenia zawiera `cpro_account` z `delivery_lead_id`,
  `delivery_lead_name` i `vault_entry` (nazwa wpisu Hints). Dla Dominika
  zlecenie zachowuje jego ID i imię oraz wskazuje wpis Marcina. Nie zawiera loginu ani hasła.
  Rekruter, autor przesunięcia karty oraz DL karty źródłowej z uzupełnieniami
  Warunków/CV nie wybierają konta.
- Bot dla **każdej pozycji** zaczyna nową, odizolowaną sesję portalu,
  loguje się wskazanym wpisem Hints i potwierdza tożsamość widoczną w Cpro
  względem tego wpisu przed zapisami. Powtarza weryfikację przed każdym
  Save i „Submit Offer”; zamyka sesję po pozycji. Nigdy nie dziedziczy sesji
  poprzedniej osoby, także gdy obie mają tego samego DL.
- Brak lub nieznana trasa → `skipped/account_unknown`; nie da się
  potwierdzić konta → `skipped/account_unverified`; portal pokazuje inne
  konto → `skipped/account_mismatch`. Przy wyborze lub weryfikacji konta
  nie zapisuje profilu, szkicu ani oferty. Brak dostępu nie uprawnia do
  próby innym kontem. Błąd logowania → `failed/login_failed`.

## Kiedy bot bierze kartę

- Źródło to kolejka Cpro (`board_tasks`, `cpro_to_send`) — ta sama co okno
  „Do wrzucenia do Cpro”, więc tylko karty po akceptacji Delivery Leada.
- **Braki zatrzymują kartę** (`cpro_bot/items.py`, `BLOCK_*`), kolejka pokazuje
  „Bot czeka: …”: bez akceptacji DL, bez stawki do Cpro albo stawka nie w zł
  za godzinę, rekrutacja bez numeru requestu (`jobs.client_reference`), brak
  **zatwierdzonego** CV firmowego (szkic „SZKIC_…” nigdy nie idzie), QC CV
  z błędami blokującymi, CV bez punktów „Why our candidate”, brak miasta
  (karta albo `candidates.city`), brak narodowości, nieobsługiwany albo
  nieaktywny DL rekrutacji. Po uzupełnieniu w NEXUSIE
  następna pętla bierze kartę sama.
- Pętla `cpro_bot` w workerze co 5 minut, **jeden bieg naraz**, najwyżej
  5 osób na bieg, najstarsze w kolejce pierwsze.
- **Bot nigdy nie wysyła karty drugi raz.** Wynik `submitted` zostaje przy
  karcie; gdy NEXUS nie zdołał jej przesunąć (karta ruszona w tym czasie,
  brak osoby od Cpro, bramka ruchu), kolejka mówi „kliknij Wrzucone”.
  `failed` i `skipped` (bot powiedział, czemu się nie da) pętla nie ponawia:
  kartę wrzuca człowiek albo klika „Ponów botem”. Bieg bez raportu albo
  z błędem webhooka (`retry`) pętla ponawia najwyżej 3 razy, co 30 minut.
- „Ponów botem” (`POST /api/board-tasks/cpro/bot/{stage_id}/retry`): osoba od
  Cpro, admin, DL, HoR (`cpro_sender.can_send_to_cpro`), tylko karty bez braków
  i nie wysłane przez bota.

## Co bot wpisuje (reguły z nagrań, `cpro_bot/offer_text.py`)

- **Offered rate** = stawka do Cpro z akceptacji DL-a, PLN za godzinę.
- **Available from:** karta screeningu wygrywa z datą z NEXUSA (osoba od Cpro
  26.11.2026: profil 25.12 przy „2 tyg wypowiedzenia” dawał złą datę).
  Z karty: ASAP → dziś; okres wypowiedzenia od dziś; data albo miesiąc
  („od grudnia” → 01.12, „od 1 grudnia” → 01.12 — 27.11.2026 robot wpisał
  datę z profilu 18.12) → ta data. Termin bez roku, który minął najwyżej
  90 dni temu, to „od zaraz”, a nie ten dzień za rok. Bez dostępności
  w karcie data z NEXUSA w przyszłości (profil albo koniec umowy), inaczej dziś.
- **Wypowiedzenie:** 1–4 tygodnie, „30 dni” i **każdy „1 miesiąc”, także UoP**
  → `a N-week notice period` (1 miesiąc = `a 4-week notice period`, data dziś +
  28 dni) — osoba od Cpro i decyzja Artura 26.11.2026. Dłuższe okresy:
  `a N-month notice period`.
- **Physical location** („ściągawka” Sandry): `<miasto>, willing to come to the
  Nordea office in <biuro> <N>x/week, <dostępność>`, gdzie dostępność to
  `available ASAP`, `available from DD.MM.RRRR` albo `a N-week notice period`;
  na końcu `a former employee at Nordea` albo `a former consultant at Nordea`.
  Biuro = biuro z trybu pracy karty („3 dni w tyg/Łódź” → Lodz, 26.11.2026);
  bez niego miasto osoby, gdy rekrutacja je wymienia (Trójmiasto →
  Gdynia/Gdańsk z rekrutacji), inaczej pierwsze miasto rekrutacji. **Dni z karty kandydata**
  („2 dni w tygodniu w biurze” → `2x/week`, 26.11.2026), bez nich
  z `jobs.onsite_days_per_week`, domyślnie 3. Praca zdalna → `working remotely`.
- **Narodowość** nie blokuje karty (27.11.2026): potrzebna tylko do nowego
  profilu w Cpro — robot staje przed „Add Consultant”, gdy osoby nie ma
  w Cpro, a narodowości brak. Wyszukiwarka profili na requeście bywa ukryta —
  robot wpisuje nazwisko i klika „Search” skryptem.
- **QC CV:** „przepuszczone mimo QC” (`overridden`) nie zatrzymuje bota,
  choć licznik błędów blokujących zostaje (26.11.2026).
- **Former employee / consultant:** z karty „Czy pracował u Klienta” (UoP =
  pracownik, B2B = konsultant, „nie” = oba No). Od 26.11.2026 samo „tak” bez
  rodzaju umowy nie liczy się jako wypełnione pole karty (`has_value`), a
  Nordea ma to pole i „Narodowość” w minimum przed „Zweryfikowany” (karta
  klienta) — bot nie staje już na „do rozstrzygnięcia ręcznie”.
- **Motivation** i opis nowego profilu = punkty „Why our candidate?” z HTML
  zatwierdzonej wersji CV (`data-cv-section="why_points"`), każdy od myślnika,
  bez pustych linii.
- **CV do oferty** to firmowy PDF z zatwierdzonej wersji zapisanej w zleceniu.
  Bot pobiera go z `GET /api/integrations/cpro-bot/runs/{id}/cv/{stage_id}`
  na token biegu. Nazwa pliku ma końcówkę `.pdf` i nie zawiera `#`.
  Po zapisaniu szkicu bot otwiera ofertę ponownie i sprawdza zaznaczony PDF
  w podglądzie Cpro, w tym firmowy układ strony. Cpro po „Save as draft” sam
  przechodzi na stronę oferty, więc otwarcie listy ofert w tym czasie
  przeglądarka przerywa (`net::ERR_ABORTED`, 8 kart 27.11.2026 z wynikiem
  `draft_unconfirmed` mimo zapisanego szkicu). Robot otwiera strony przez
  `_goto` w `cpro_robot/portal.py`: przy przerwanym przejściu czeka i próbuje
  do trzech razy.
- Stałe pola (w poleceniu rutyny, `cpro_bot/task_text.py`): Self-employed
  (B2B), subcontractor `B2B.net S.A.`, subcontractor rate 0,00, UK tax No,
  Gender Other, pięć suwaków Matching na „Perfect”, imiennik w Cpro → Title =
  nazwa rekrutacji. Osoba ma już ofertę inną niż DRAFT → `skipped`.
  Po „Submit Offer” bot sprawdza na requeście status SELECTION (jak Sandra).

## Bezpieczeństwo

- Webhook do rutyny (`GROK_BOT_CPRO_WEBHOOK_URL`, `_KEY`, nagłówek Bearer).
  **Schema 2:** webhook jest wyłącznie krótkim pobudzeniem z polami
  `schema_version`, `run_id`, `kind`, `token`, `task_url`. Nie przenosi polecenia,
  raportu wzorcowego ani danych kandydatów, które platforma mogłaby uciąć.
  Bot pobiera pełne zapisane zlecenie przez
  `GET /api/integrations/cpro-bot/runs/{run_id}/task` z `X-Run-Token`.
  Odpowiedź ma `Cache-Control: private, no-store`; GET nie zużywa tokenu.
- Zanim bot wyśle token, wymaga dokładnego originu
  `https://api.nexus.dynaminds.pl` i ścieżki task z tym samym `run_id`.
  Nie śledzi przekierowań; odrzuca userinfo, query, fragment i obce adresy.
  Pobranie musi dać pełny JSON 200 z pasującymi `schema_version`, `run_id`
  i `kind`, a także kompletnymi `task`, `report_format`, `items`, `submit`,
  `callback_url` i `expires_at`. Dopiero po kontroli całego zlecenia wolno
  rozpocząć pracę. Uciętego wejścia nie odtwarza z historii ani domysłów.
- Ten sam dokładny origin obowiązuje `callback_url` i każde `offer.cv_url`.
  Dozwolone ścieżki to odpowiednio `/api/integrations/cpro-bot/runs/{run_id}`
  oraz `/api/integrations/cpro-bot/runs/{run_id}/cv/{ref}` z tej pozycji.
  Kontrola następuje przed dołączeniem tokenu; bez przekierowań, userinfo,
  query ani fragmentu.
- Bot nie ma stałego klucza do NEXUSA: jednorazowy token biegu (2 godziny,
  do raportu) otwiera tylko zlecenie, CV kart z tego biegu i jeden raport. Trasy
  `require_cpro_run_token` (marker w `tests/test_route_authz_contract.py`).
- Raport to dane niezaufane (`cpro_bot/ingest.py`): `extra=forbid`, tylko karty
  z biegu, link do oferty tylko `https://*.onevms.se`, znaki sterujące wycięte,
  `submitted` w próbie liczy się jako szkic. Licznik `draft` wymaga dodatkowo
  potwierdzenia rzeczywistego statusu DRAFT w Cpro przez Sandrę.
- Hasło do Cpro wpisuje Artur: do Hints Grok Bota albo (robot, od 24.11.2026)
  jako sekret repo dla workflow „Coolify set env”. Nigdy sesja Claude, Codex
  ani kod. Wpisy kont Igora i Marcina pozostają oddzielne; hasła i loginy
  nie trafiają do webhooka ani raportu. Logi są publiczne: same liczby
  i identyfikatory; bez tokenu, pełnego zlecenia, treści CV i danych osób.
- Na stagingu pętla stoi (`STAGING_BLOCKED_TASKS`: `cpro_bot`).
- Narodowość z karty czyta `cpro_bot/items.py` wyłącznie do pola „Country of
  citizenship” (wpis w strażniku `test_only_listed_modules_read_recommendation_cards`).

## Gdzie to siedzi

- `services/cpro_bot/`: `offer_text` (reguły pól), `items` (kolejka → pozycje
  i braki), `runs` (bieg, token, stan karty), `flow` (pętla, ponowienie),
  `ingest` (raport, ruch karty), `task_text` (polecenie rutyny), `schema` (DDL).
- Tabela `cpro_bot_runs` (migracja 0732, lustro przez `hr_schema_bundle`):
  bieg, `stage_ids`, `request.items` (bot pobiera je z endpointu task), `request.cards`
  (etap docelowy, CV — zostaje w NEXUSIE), `report.items` (wynik karty, `moved`).
- Pętla `tasks/cpro_bot.py`, trasy `api/integrations_cpro_bot.py`, stan przy
  osobie w `GET /api/board-tasks/cpro/queue` (`bot`), ekran
  `components/v2/dashboard/CproBotStatus.tsx`.
- `CPRO_BOT_AUTO_DRAFT_ENABLED=true` uruchamia w workerze przegląd kolejki
  co pięć minut. Worker zleca jedną gotową kartę na koncie właściwego DL.
  Potwierdzony szkic czeka na ocenę Sandry. Stan i odnośnik z raportu
  widać w kolejce. W tym trybie również ręczne ponowienie dotyczy szkicu.
- Tryb szkiców ma pierwszeństwo przed `CPRO_BOT_ENABLED`. Przy obu flagach
  wyłączonych pętla stoi. Trasy z tokenem pojedynczego biegu działają także
  przy wyłączonej pętli.
- Włączenie krok po kroku: `docs/cpro-grok-bot-setup.md`.
- Testy: `test_cpro_bot_unit.py` (reguły, raport, stan), `test_cpro_bot_db.py`
  (kolejka → bieg → CV na token → raport → karta wysłana).
