# Zamówienia z maila `zamowienia@b2bnetwork.pl` — czytnik app-only, skrzynka współdzielona

`zamowienia@b2bnetwork.pl` NIE jest skrzynką na hostingu, tylko **listą
dystrybucyjną w Exchange Online** (właścicielka i jedyna osoba: Marta
Kozarzewska; nadawcy zewnętrzni dozwoleni). Kopię zamówień robi więc sama
lista: jej członkiem jest skrzynka współdzielona **`nexus-zamowienia@b2bnetwork.pl`**
(bez licencji, bez logowania, zero kont z hasłem). Hosting `hosting.b2bnetwork.pl`
nie ma żadnej reguły do utrzymania.

- **Czytnik pracuje app-only** (`ORDER_MAIL_AUTH_MODE=app`): client_credentials
  rejestracji **„NEXUS ATS - Mailbox and Login"** (`b5be7c77-…`, tenant
  `e277180c-…`) — tej samej, którą rekruterzy łączą delegowanie. Dołożone
  APPLICATION `Mail.Read` ze zgodą administratora (02.09.2026) i **Application
  Access Policy** `RestrictAccess` na grupę `NEXUS-OrderMail-Scope`
  (`nexus-ordermail-scope@b2bnetwork.pl`, mail-enabled security group, ukryta
  w GAL, jedyny członek: skrzynka zamówień). `Test-ApplicationAccessPolicy`:
  skrzynka zamówień → Granted, dowolna inna → Denied. **Skrzynka współdzielona
  NIE może być zakresem polityki wprost** („not a security principal") — stąd
  grupa. Bez tej polityki uprawnienie aplikacyjne czytałoby każdą skrzynkę
  w firmie; jej brak to błąd konfiguracji, nie „szerszy dostęp".
- **`AppGraphClient`** (`services/m365/app_graph_client.py`) to subklasa
  `GraphClient`: ta sama pętla retry/throttle, nadpisane tylko konstruktor,
  bramka `_authorize` (brak właściciela do rewalidacji) i `_refresh_and_persist`
  (nowy token klienta, nic do zapisania). Graph nie ma `/me` bez użytkownika,
  więc `mailbox_prefix()` daje `/users/{ORDER_MAIL_UPN}`; wiersz
  `order_mail_documents.connection_id` zostaje NULL (kolumna NULL-owalna od 0264).
- **Tryb delegowany zostaje** (`ORDER_MAIL_AUTH_MODE=delegated`, domyślny w kodzie)
  — wymaga konta-bota z licencją, hasłem i OAuth; na prodzie nieużywany.
- Health: `checks.order_mail = misconfigured`, gdy tryb `app` nie ma
  `M365_CLIENT_ID/SECRET` albo realnego tenanta w `M365_MAIL_TENANT_ID`
  (`M365_TENANT_ID` bywa `common`, a client_credentials z `common` nie działa).
  Status: `GET /api/admin/order-mail/status` → `auth_mode`, `app_only_ready`.
- Env na prodzie (workflow „Coolify set env", `redeploy=false`, potem jeden
  zwykły deploy): `ORDER_MAIL_AUTH_MODE=app`, `ORDER_MAIL_UPN=nexus-zamowienia@b2bnetwork.pl`,
  `M365_MAIL_TENANT_ID=<GUID tenanta>`, `ORDER_MAIL_INGEST_ENABLED=true`.
- **Odczyt awaryjny (bez AI) jest ponawiany sam** (`retry_ai_fallback_documents`,
  bieg skrzynki po ponownej weryfikacji): wpis `needs_review` z
  `extraction.source == "regex"` dostaje ponowny odczyt AI z zachowanego PDF-a,
  najwyżej `MAX_AI_RETRY_ATTEMPTS` (3) razy (`document_meta.ai_retry_*`,
  przeżywa „Przelicz plan"). Model idzie POZA blokadą wiersza, zapis po
  ponownym sprawdzeniu pod `FOR UPDATE` (`populate_existing`). Udany odczyt =
  ścieżka nowego maila (reguły, rodzaj stawki) + `replan_and_apply`. Powód
  porażki AI (`OrderExtraction.ai_failure`: klasa błędu / HTTP, bez treści)
  jest na wpisie i w powodzie bramki „Odczyt awaryjny (AI: …)". Do 09.2026
  szedł tylko do logu kontenera, który znika przy deployu (PKO BP, 14.09:
  mail odczytany w trakcie deployu). Bez klucza albo przy
  `ORDER_EXTRACTION_ENABLED=false` ponowienie nic nie robi.
- **Skrzynka jest sprawdzana co godzinę, nie w slotach.** Do 03.09.2026 pętla
  miała dwa sloty dobowe (08:00/15:00 Europe/Warsaw): zamówienie VeloBank
  przyszło o 08:37 i czekałoby do 15:00. Teraz bieg jest należny, gdy od KOŃCA
  ostatniego minęło `ORDER_MAIL_POLL_INTERVAL_MINUTES` (default 60, podłoga 5;
  `ORDER_MAIL_SLOTS_LOCAL` nie istnieje). Odstęp liczony od końca ma dwie
  konsekwencje, na których stoi ticket: bieg ręczny przesuwa zegar (nie ma
  dwóch biegów tuż po sobie), a bieg przerwany restartem końca NIE zapisuje,
  więc po deployu skrzynka jest sprawdzana od razu, nie za godzinę.
- **„Pobierz zamówienia z maila" jest w kolejce (`/contracts?view=order-mail`, dawniej `/order-mail`)**, nie tylko
  w API admina: `POST /api/order-mail/sync` (admin / finance / delivery_lead —
  bramka ROLOWA, bo dotyczy całej skrzynki, nie dokumentu; TCM ma sam odczyt)
  i `GET /api/order-mail/sync/status` (każda rola kolejki; TCM bez treści
  błędów, bo te cytują nazwy załączników). Bieg idzie w tle, front odpytuje
  stan co 2 s i uznaje koniec po ZMIANIE `finished_at` z serwera, nigdy po
  zegarze przeglądarki (`lib/order-mail-sync.ts`). 409 = bieg już trwa, front
  dołącza do niego. Liczby w pasku (nowe wiadomości / zapisane automatycznie /
  do weryfikacji) dotyczą CAŁEJ skrzynki — kolejka DL jest zawężona do
  portfela, więc „1 do weryfikacji" i pusta lista to nie sprzeczność.
- **Wynik biegu żyje w `order_mail_sync_state.stats` jako rekord** (`reason`,
  `started_at`, `finished_at`, `status`, `error` + liczniki), bo wiersz stanu ma
  jedną parę start/koniec, a bieg, który właśnie trwa, nadpisuje start.
  `last_status='running'` bez blokady w procesie = bieg PRZERWANY (deploy
  w trakcie — u nas kilka razy dziennie) i tak jest pokazywany
  (`interrupted`), a health traktuje `running` jako brak informacji, nie awarię
  (degraduje po 3 odstępach albo na `error`). Trzy rzeczy, które trzymają ten
  stan uczciwym: bieg z requestu startuje przez `start_ingest_task` (trzymana
  referencja — zebrane zadanie nie zapisuje końca), padnięte powiadomienie DL
  robi `rollback()` (bez niego zapis końca leci na `PendingRollbackError`),
  a watermark nigdy się nie cofa (backfill `since_days` oglądał starsze maile
  i przesuwał okno wstecz).
### Godzinowa ponowna weryfikacja wstrzymanych wpisów (0316, 16.09.2026)

- **Bieg AUTOMATYCZNY rusza tylko 8:00–18:00** (`ORDER_MAIL_RECHECK_START_HOUR_LOCAL`
  .. `_END_HOUR_LOCAL`, `BUSINESS_TZ`, półotwarte — ostatni bieg o 17:xx;
  wyrównane godziny = okno wyłączone, escape hatch bez deployu). Bramka siedzi
  na wejściu `run_recheck`, PRZED `_candidate_ids`, i czyta `trigger`: bieg
  RĘCZNY („Pobierz zamówienia z maila") okna nie pyta i zapisuje wiersz zawsze.
  **Zawężenie dotyczy WYŁĄCZNIE recheku** — pobieranie poczty
  (`ORDER_MAIL_POLL_INTERVAL_MINUTES`) i sonda `checks.order_mail` zostają
  dobowe. Nie zamykaj na noc całego `run_order_mail_ingest`: zamówienie
  przysłane o 18:30 czekałoby do rana, a sonda zdrowia (`stale_after =
  max(3 × poll_interval, 180)` min) degradowałaby co noc.
- **Wiersz historii powstaje TYLKO przy zmianie** (09.2026). Do tego dnia
  kolejka rzadko bywała pusta, więc tabela dostawała 24 wiersze dziennie,
  w większości identyczne. `outcome_fingerprint(details)` liczy odcisk STANU
  wstrzymanych zamówień (`document_id`, `outcome`, `category`, `reasons`,
  `alerted`, `order_number`, `people`; posortowane po `document_id`, bo rotacja
  `last_at NULLS FIRST` tasuje kolejność); `changed = trigger == "manual" or
  applied > 0 or odcisk != poprzedni`. Bieg bez zmian przesuwa tylko znacznik
  `app_settings['order_mail_recheck_state']` (`last_checked_at`,
  `last_change_at`, `fingerprint`, `unchanged_runs`; upsert scaleniem `||`, bez
  migracji — to stan pętli, nie konfiguracja). **Poza oknem marker NIE jest
  przesuwany** — „sprawdzone ostatnio 17:05" ma zostać prawdą przez całą noc.
  `GET /recheck-runs` zwraca marker i okno obok `items`; są GLOBALNE (opisują
  mechanizm, nie dokument klienta), więc nie podlegają zawężeniu po portfelu
  ani redakcji TCM. Front: zdanie „Sprawdzone ostatnio: …" nad tabelą i pusty
  stan „Tu trafiają tylko te sprawdzenia, które coś zmieniły".
- **Pominięty wiersz NIE pomija stempla `last_at`, licznika prób ani karty DL.**
  Karta wychodzi po trzeciej próbie z rzędu, więc gdyby licznik wisiał na
  zapisie wiersza, przestałaby wychodzić dokładnie wtedy, gdy nic się nie
  zmienia. Retencja (`_prune_history`) też jest wołana w KAŻDYM biegu — inaczej
  tydzień bez zmian to tydzień bez sprzątania.
- **Próg bezpiecznika alertu jest WYPROWADZONY z okna**
  (`order_mail_recheck_reasons.alert_after_hours()` =
  `max(ORDER_MAIL_RECHECK_ALERT_AFTER_HOURS, godziny_zamknięcia + 2)`, domyślnie
  16 h). Nie wołaj `should_alert` z surową wartością z konfiguracji: recheck
  stoi w nocy, więc o 01:00 stempel `last_at` KAŻDEGO wstrzymanego wpisu ma
  ~14 h i sześciogodzinny próg kazałby dobowemu `rule_order_mail_review`
  wystawić kartę całej kolejce — a `dl_alerts_loop` chodzi co 24 h od startu
  kontenera, więc trafienie w noc jest kwestią godziny ostatniego deployu.
- **W testach okno jest WYŁĄCZONE** (autouse `_open_the_order_mail_recheck_window`
  w `conftest.py`): zegar w suicie jest prawdziwy, więc bramka zamieniłaby każdy
  test recheku w test „czy jest teraz dzień". Testy okna włączają je jawnie
  i podróżują zegarem — ale NIE o lata w przód: retencja liczy się od `now()`,
  więc skasowałyby wiersze innych testów na wspólnej bazie.

- **Wstrzymany wpis nie wracał sam.** Jedyne automatyczne przeliczenie
  (`replan_outdated_documents`, USUNIĘTE) odpalało się tylko po zmianie
  `rule_version`. Przyczyna wstrzymania znika najczęściej GDZIE INDZIEJ:
  po podpisaniu umowy B2B nowego kontraktora albo po uzupełnieniu NIP-u
  u klienta. Teraz `order_mail_recheck.run_recheck` przelicza KAŻDY wstrzymany
  wpis w każdym biegu skrzynki — lokalnie i przed Graphem, więc także przy
  awarii skrzynki. Bez nowej pętli: ta sama kadencja, jeden heartbeat, jedna oś
  czasu w historii.
- **Dwie ścieżki.** `needs_review` (ma klienta i odczyt) → `replan_and_apply`,
  bez modelu AI. `unrecognized_client` → SAMO ponowne rozpoznanie klienta
  (tekst z PDF-a + rejestr NIP-ów); dopiero rozpoznany klient przechodzi na
  pierwszą ścieżkę. **Nie wołaj tu `process_pdf_bytes`** — ta funkcja czyta
  modelem PRZED sprawdzeniem klienta, więc płaciłaby za AI w każdym biegu.
- **Kody powodów, nie proza** (`order_mail_gate.CODE_*`, kolumna
  `order_mail_documents.gate_reason_codes`, równoległa do `gate_reasons`).
  KAŻDE dopisanie powodu MUSI nieść kod — pilnuje tego test czytający AST
  bramki. Powody wstrzykiwane poza bramką idą przez `set_gate_hold`.
- **Cicha jest WYŁĄCZNIE kategoria „czeka na podpis" (i wpis bez klienta).**
  `config` (wyłącznik automatu globalny albo per klient) **eskaluje jak każda
  inna przyczyna**: wyłącznik gasi tylko zapis automatyczny — ręczne
  „Zastosuj" go nie czyta — więc taki dokument zapisze WYŁĄCZNIE człowiek.
  Wyciszenie tej kategorii znaczyłoby, że przestawienie
  `ORDER_MAIL_AUTOAPPLY_ENABLED` kasuje alarmowanie całej kolejki i zamyka
  karty już wystawione.
- **„Czeka na podpis umowy" = `classify_hold` zwraca `awaiting_contract`**:
  WSZYSTKIE kody dokumentu należą do `{person_decision_new,
  person_known_elsewhere_idle}`, czyli osoby nie ma na rosterze klienta i nie ma
  żywej umowy NIGDZIE w systemie. Taki wpis czeka bezterminowo, licznik prób
  stoi na zerze i **nie wysyła karty do DL nigdy**. Jeden dodatkowy powód
  (stawka poza pasmem, niepewny odczyt) przesuwa dokument do `other` — to
  bezpieczny kierunek pomyłki. Świadomie NIE są `awaiting_contract`: zakończona
  współpraca u tego klienta, imiennicy i osoba z otwartą umową u INNEGO klienta
  (to pytanie o zdublowany rekord klienta, nie o podpis).
- **Karta DL wychodzi dopiero po TRZECH nieudanych próbach z rzędu**
  (`document_meta["recheck"] = {attempts, category, last_at}`; zmiana kategorii
  zeruje licznik). Do 0316 `notify_review` wołane z `_process_message`
  wystawiało kartę przy PIERWSZYM wstrzymaniu — to wywołanie zniknęło.
  Regułę ma JEDNO miejsce: `should_alert` — czyta ją i recheck, i dobowy
  `rule_order_mail_review` (dwie kopie rozjechałyby się, a skaner wystawiałby
  nazajutrz karty, które recheck wyciszył). Bezpiecznik: dokument bez ustalonej
  kategorii (pętla nigdy go nie widziała) **albo ze stemplem `last_at`
  starszym niż okno** (pętla przestała go widzieć) alarmuje po
  `ORDER_MAIL_RECHECK_ALERT_AFTER_HOURS` (6 h). Bez DRUGIEGO przypadku pętla
  zatrzymana po pierwszej próbie zamrażała dokument na `attempts = 1` na
  zawsze, a dobowy skaner — nie widząc go w `live` — zamykał nawet kartę
  wystawioną wcześniej. Udany zapis kasuje ślad i zamyka kartę od razu
  (`resolve_entity_alerts`).
- **KAŻDY dokument, który zjadł budżet biegu, MUSI dostać stempel `last_at`
  i trafić do `details` biegu** — także ten, którego nie da się przeliczyć,
  i ten, na którym bieg padł (stempel idzie wtedy osobną transakcją PO
  rollbacku). Czy `details` staną się WIERSZEM historii, rozstrzyga odcisk
  (wyżej) — ale stempel i tak musi paść.
  Sortowanie `last_at NULLS FIRST` jest rotacją tylko pod tym warunkiem: wpis
  bez stempla wraca na czoło w każdym biegu, a sto takich wierszy zatrzymuje
  całą funkcję — niewidzialnie, bo historia pokazuje wtedy bieg „sprawdzono 0".
- **`_replannable` ODPOWIADA „nie da się", nie rzuca.** Helper magazynu
  (`get_order_mail_attachment_path`) rzuca `FileNotFoundError` dla ścieżki,
  której nie ma; bez przechwycenia recheck wywracał się na takim wpisie
  w każdym biegu, licznik prób stał w miejscu i karta nie wychodziła nigdy.
- **Historia: `order_mail_recheck_runs`** (`GET /api/order-mail/recheck-runs`,
  sekcja na dole `/order-mail`). `details` są ZDENORMALIZOWANE — historia
  pokazuje powód z chwili biegu, nie dzisiejszy stan dokumentu. DL widzi wpisy
  swojego portfela, a **liczniki są przeliczane z widocznych wpisów** (globalne
  „sprawdzono 12" nad listą z jednym wierszem to ekran, który sam sobie
  przeczy). Retencja `ORDER_MAIL_RECHECK_HISTORY_DAYS` (30 dni) — po niej znikną
  też bezzmianowe wiersze sprzed 09.2026, więc nie ma czego czyścić ręcznie.
- **Sufit `ORDER_MAIL_RECHECK_MAX_DOCS` (100) i rotacja po `last_at NULLS
  FIRST`** — każdy recheck to ekstrakcja tekstu z PDF-a, a skan idzie przez OCR.
  Wpisy `unrecognized_client` starsze niż
  `ORDER_MAIL_RECHECK_UNRECOGNIZED_DAYS` (90) odpadają: znikają z kolejki tylko
  ręcznie, więc bez sufitu OCR-owalibyśmy je co godzinę bez końca.
- **Test na wspólnej bazie MUSI asertować po WŁASNYM dokumencie** — bieg
  przegląda każdy wstrzymany wpis, a baza testowa nie jest czyszczona, więc
  globalne liczniki i globalny mock `notify_review` mierzą cudze wiersze.
- **`ORDER_MAIL_AUTOAPPLY_ENABLED` jest żywym wyłącznikiem (od 10.09.2026).**
  #1472 zrobił z niej flagę „legacy” — bramka jej nie czytała, a status zwracał
  na sztywno `true`. Teraz działa w jednym miejscu,
  `hold_when_autoapply_disabled` (`order_mail_ingest.py`), przy TRZECH zapisach
  bez człowieka: odczyt maila, „Przelicz plan” i jednorazowe czyszczenie
  kolejki. Wyłączona flaga zostawia werdykt „auto” w kolejce z powodem
  „Automatyczny zapis jest wyłączony…”. `evaluate()` jej NIE czyta (zostaje
  czyste), a ręczne „Zastosuj” ją ignoruje.
- **Powrót po przerwie = NOWE zamówienie (decyzja Artura, 10.09.2026).** Do
  10.09 automat „reaktywował” zakończone zamówienie: przepisywał w nim tytuł,
  okres, stawkę, koszt i PDF — tak w nocy 9/10.09 nadpisał PFRON 507–509.
  Teraz powrót idzie tą samą ścieżką co nowe zamówienie, a zakończone jest
  tylko czytane (`FOR SHARE`, ponowne sprawdzenie warunków planera). Link do
  poprzedniego żyje w Activity `order_mail_renewal` (`renewal_of_order_id`,
  `gap_days`, `previous_end_date`) — NIE w `notes` (tam jest znacznik
  idempotencji porównywany dosłownie) i NIE w `predecessor_order_id` (to
  zamiana kontraktora na linii grupy MD). Linie grup MD nigdy nie są
  „poprzednim zamówieniem”. Nowe zamówienie dziedziczy z poprzedniego pola,
  których PDF nie niesie: `project_part` (bez niej e-Zdrowie nie przejdzie
  walidacji), `framework_contract_id`, `job_id`, `billing_hours_per_month`,
  `description` — reaktywacja w miejscu zostawiała je w wierszu.
- **Mail nie wskrzesza wypowiedzianej umowy — ale tylko poza jej okresem.**
  `termination_allows` (w `order_mail_signature.py`, przed sprawdzeniem
  podpisu, także w `complete_signed_mail_drafts`): przy umowie z
  `terminated_at`/`termination_reason` zamówienie z maila aktywuje się tylko
  wtedy, gdy CAŁY jego okres mieści się przed bieżącą `end_date` umowy;
  wychodzące poza nią zostaje szkicem. `terminated_at` NIE jest czyszczone przy
  aneksie ani przywróceniu (`reopen_contract`), więc reguła czyta bieżącą datę
  końca: aneks przesuwa okres, a umowa przywrócona bezterminowo (`end_date`
  pusta) wraca do zwykłych zasad. Bez tego jedno wypowiedzenie blokowałoby
  automat dla tej osoby na zawsze (przegląd adwersarialny 10.09).
- **Jedyny imiennik w bazie wymaga człowieka.** Nowa osoba z maila jest
  szukana po nazwisku ze zwiniętymi polskimi znakami po obu stronach. Jeden
  imiennik bez umowy u tego klienta zostaje dopięty tylko przy ręcznym
  „Zastosuj”; automat odsyła dokument do kolejki (samo nazwisko to za mało,
  żeby dać komuś cudze zamówienie). **Blokadę zdejmuje `confirmed_by_human`,
  nie `actor_user_id`** — „Przelicz plan” podaje klikającego wyłącznie do
  audytu (`apply_document(actor_user_id=…, confirmed_by_human=False)`), więc
  imiennik i dopasowanie niedokładne nadal wracają do kolejki, a wyłącznik
  automatu dalej działa.
- **Zamówienie nadpisane w miejscu da się odtworzyć z historii.** Activity
  `order_mail_reactivate` niesie `before` (stan sprzed nadpisania), `message`
  i `created_at` = chwila nadpisania; `before` NIE zapisuje `rate_unit`.
  Jednorazowa korekta PFRON 507–509 (migracja `0306_pfron_renewal_split_repair`,
  SQL w `services/pfron_renewal_split_repair.py`, lustro w `entrypoint.sh`):
  nowy okres 01.09–30.11 przechodzi do NOWEGO wiersza, oryginał wraca do stanu
  z `before` (koszt z harmonogramu umowy na ostatni dzień okresu), a konsumpcje,
  alerty i dokument maila od 09.2026 idą za nowym wierszem. Każde zamówienie
  jest przypięte tożsamością biznesową i pomijane z powodem, gdy stan produkcji
  się nie zgadza — w tym gdy po T0 ktoś je edytował (`edited_after_incident`:
  PATCH/PDF/anulowanie/zakończenie), gdy tytuł albo jednostka różni się od planu
  z maila, i gdy TA SAMA OSOBA ma u klienta inne zamówienie na którykolwiek
  z dwóch okresów, także na innej umowie („Nowy kontraktor / zamówienie” zakłada
  nową umowę). Blok ma `lock_timeout` 15 s i blokuje wiersz klienta jak writer
  maila; po timeoucie nic nie zapisuje i ponawia przy następnym starcie.
  Harmonogram przychodu umów domyka krok `pfron_revenue_resync` (entrypoint, tuż
  po korekcie) przez `resync_contract` — ten sam kod co zwykły zapis zamówienia.
  **Dwa klucze w `app_settings`:** paragon `0306_pfron_renewal_split_repair`
  (liczniki, ID, daty, powody — czyta go `coolify-ops` `migration-receipts`,
  którego log jest PUBLICZNY) i szczegóły `repair_details_0306_…` (migawki,
  tytuły, stawki, notatki, ścieżki — do ręcznego odwrócenia; kształt klucza
  sprawia, że workflow ich nie wydrukuje). Wynik weryfikuje Delivery Lead.
  **Nowy paragon naprawy danych = tylko liczniki i ID pod kluczem `NNNN_…`**;
  wszystko z kwotą, tytułem albo nazwiskiem idzie pod klucz innego kształtu.
- **Dedup alertów wygasania = (odbiorca, obiekt, próg, data końca)**
  (`dl_portal_expiry_scanner.py`, także umowy ramowe). Data pochodzi z treści
  komunikatu („kończy się/wygasa RRRR-MM-DD”), którą alerty niosą od maja —
  **nie zmieniaj tego sformułowania bez `_end_phrase`**, bo stare powiadomienia
  przestaną się deduplikować. Przedłużona umowa z nową datą końca dostaje nowy
  alert; do 11.09 próg raz wysłany milczał przy każdej kolejnej dacie.
- **Pierwszy szkic z maila u klienta bez DL** dostaje alert z dziennego
  backstopu (`dl_alerts.py`), gdy tylko DL zostanie przypisany — ten sam klucz
  co zapis, więc bez duplikatów. Do adminów świadomie nie idzie (jak #1394).
- **Migracja uruchamiana przez `text()` nie może zawierać `:słowo`** (SQLAlchemy
  zrobi z tego parametr) — czas przez `make_timestamptz(...)`, nie literał.
