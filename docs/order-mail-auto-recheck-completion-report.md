# Automatyczna ponowna weryfikacja wstrzymanych zamówień z maila

Ticket: „Zamówienia → automatyczny odczyt zamówień z maila". Migracja `0316`.

## Problem

Wpis, który trafił do kolejki „Do weryfikacji", **nie wracał sam**. Jedyne
automatyczne przeliczenie (`replan_outdated_documents`) odpalało się wyłącznie
po zmianie `rule_version` polityki klienta. Tymczasem przyczyna wstrzymania
znika najczęściej **gdzie indziej**: po podpisaniu umowy B2B nowego kontraktora
albo po uzupełnieniu NIP-u na karcie klienta. Taki wpis wisiał ze starym
powodem, dopóki człowiek nie kliknął „Przelicz plan" — a nikt nie miał powodu
wiedzieć, że trzeba.

Lustrzany problem: `notify_review` wystawiało Delivery Leadowi kartę
**natychmiast**, dla każdego wstrzymanego dokumentu — także dla tych, które
system i tak dokończyłby sam w ciągu godziny.

## Co powstało

**Godzinowy recheck** (`app/services/order_mail_recheck.py`) wpięty w istniejący
bieg skrzynki (`ORDER_MAIL_POLL_INTERVAL_MINUTES`, domyślnie 60 min), lokalnie
i **przed Graphem** — więc działa też przy awarii skrzynki. Bez nowej pętli:
ta sama kadencja, jeden heartbeat, jedna oś czasu. `replan_outdated_documents`
usunięte — recheck je zawiera.

Dwie ścieżki:

| Stan wpisu | Co robi recheck |
|---|---|
| `needs_review` | `replan_and_apply` — dokładnie to, co „Przelicz plan"; pewny plan zapisuje się sam. **Bez modelu AI.** |
| `unrecognized_client` | SAMO ponowne rozpoznanie klienta (tekst z PDF-a + rejestr NIP-ów). Dopiero rozpoznany klient idzie ścieżką pierwszą. |

Świadomie **nie** wołamy ponownie `process_pdf_bytes`: ta funkcja czyta modelem
PRZED sprawdzeniem klienta, więc płaciłaby za AI w każdym biegu.

**Klasyfikacja przyczyny** (`order_mail_recheck_reasons.classify_hold`) po
KODACH, nigdy po prozie:

* `awaiting_contract` — WSZYSTKIE kody dokumentu to „nowy kontraktor bez żywej
  umowy gdziekolwiek". Czeka bezterminowo, licznik prób stoi na zerze,
  **zero kart dla DL**.
* `config` — automat wyłączony globalnie albo dla klienta. **Eskaluje jak
  każda inna przyczyna**: wyłącznik gasi tylko zapis automatyczny, a ręczne
  „Zastosuj" go nie czyta, więc taki dokument zapisze wyłącznie człowiek.
* `unrecognized` — brak klienta, więc nie ma komu wystawić karty.
* `other` — po **trzech nieudanych próbach z rzędu** idzie karta
  `order_mail_review`. Zmiana kategorii zeruje licznik.

Jeden dodatkowy powód (stawka poza pasmem, niepewny odczyt) przesuwa dokument
do `other`. To bezpieczny kierunek pomyłki: DL dostanie kartę, zamiast nie
dostać jej nigdy.

**Historia** — tabela `order_mail_recheck_runs`, `GET /api/order-mail/recheck-runs`,
sekcja „Historia automatycznej weryfikacji" na dole `/order-mail`: data i godzina,
ile sprawdzono, ile zaakceptowano, ile wstrzymano, a po rozwinięciu — konkretne
dokumenty z powodem i linkiem.

## Decyzje, które łatwo cofnąć

1. **Kody powodów w bramce** (`order_mail_gate.CODE_*`, kolumna
   `order_mail_documents.gate_reason_codes`). Klasyfikowanie regexem po polskich
   zdaniach zepsułoby się przy pierwszej korekcie stylistycznej, a cena pomyłki
   to albo zalanie DL kartami, albo cisza przy realnym problemie. Test czytający
   AST bramki pilnuje, że KAŻDE dopisanie powodu niesie kod (sprawdzone mutacją).
2. **Karta DL przesunięta na 3. próbę** — wywołanie `notify_review`
   z `_process_message` usunięte. Regułę ma JEDNO miejsce (`should_alert`),
   czytane i przez recheck, i przez dobowy `rule_order_mail_review`; dwie kopie
   rozjechałyby się, a skaner wystawiałby nazajutrz karty, które recheck
   wyciszył. Bezpiecznik: wpis bez ustalonej kategorii (pętla wyłączona albo
   zatrzymana) alarmuje po 6 h — inaczej awaria pętli zamieniłaby „powiadom po
   trzech próbach" w „nigdy".
3. **„Brak kontraktu" = NOWY kontraktor**, nie każda sprawa dotycząca osoby.
   Świadomie NIE są `awaiting_contract`: zakończona współpraca u tego klienta
   (DL decyduje: historia / wznów / zastąp / usuń), imiennicy i osoba z otwartą
   umową u INNEGO klienta (to pytanie o zdublowany rekord klienta, nie o podpis).
4. **Savepoint wokół karty DL + `flush` przed nim.** Bez tego błąd SQL
   w powiadomieniu wycofywałby CAŁE przeliczenie razem z licznikiem prób —
   wpis wracałby co godzinę na tę samą próbę i karta nie wyszłaby nigdy.
   Test `test_a_failing_alert_does_not_undo_the_recheck` (sprawdzony mutacją:
   po usunięciu savepointu czerwienieje).
5. **Sufit na bieg i rotacja** (`ORDER_MAIL_RECHECK_MAX_DOCS` = 100,
   `ORDER BY last_at NULLS FIRST`) — każdy recheck to ekstrakcja tekstu z PDF-a,
   a skan idzie przez OCR. Wpisy „Nie rozpoznano klienta" starsze niż 90 dni
   odpadają: znikają z kolejki tylko ręcznie, więc bez sufitu OCR-owalibyśmy je
   co godzinę bez końca.
6. **Liczniki historii przeliczane z WIDOCZNYCH wpisów.** Globalne
   „sprawdzono 12" nad listą z jednym wierszem to ekran, który sam sobie
   przeczy. Historia jest zdenormalizowana — pokazuje powód z chwili biegu,
   nie dzisiejszy stan dokumentu.

## Co zmienił przegląd adwersarialny

Przegląd znalazł trzy defekty, z których dwa **na stałe ukrywały zamówienie
przed Delivery Leadem**. Wszystkie naprawione, każdy z testem:

1. **`_replannable` rzucał zamiast odpowiadać.** `get_order_mail_attachment_path`
   rzuca `FileNotFoundError` dla ścieżki, której nie ma (plik znika przy
   retencji, przeniesieniu wolumenu, ręcznym sprzątaniu). Recheck wywracał się
   wtedy na takim wpisie w KAŻDYM biegu, rollback kasował licznik prób, próg
   trzech prób nigdy nie padał — a dobowy skaner, nie widząc dokumentu
   w `live`, zamykał nawet kartę wystawioną wcześniej. Teraz helper odpowiada
   „nie da się przeliczyć". Test: `test_every_document_the_run_touches_leaves_a_timestamp`
   (sprawdzony mutacją).
2. **Rotacja `last_at NULLS FIRST` nie rotowała.** Dwie ścieżki kończyły bieg
   bez stempla — wpis nieprzeliczalny i wpis, na którym bieg padł. Bez stempla
   wracały na czoło sortowania w każdym biegu i zjadały budżet **niewidzialnie**
   (`result.checked` ich nie liczyło, historii nie było). Sto takich wierszy
   zatrzymywało całą funkcję przy ekranie pokazującym „sprawdzono 0". Teraz
   każdy dokument, który zjadł budżet, dostaje stempel i wiersz w historii —
   po awarii osobną transakcją po rollbacku.
3. **`config` było ciche i to było odwrotnie.** `ORDER_MAIL_AUTOAPPLY_ENABLED`
   gasi wyłącznie zapis automatyczny; ręczne „Zastosuj" flagi nie czyta. Czyli
   dokument wstrzymany tylko tym powodem to dokument, który zapisze WYŁĄCZNIE
   człowiek. Przy wyciszeniu przestawienie wyłącznika kasowałoby alarmowanie
   całej kolejki i zamykało karty już wystawione. Teraz eskaluje normalnie.
   Test: `test_turning_the_automation_off_does_not_silence_the_queue`.

Do tego: bezpiecznik `should_alert` łapie teraz także pętlę, która **przestała**
patrzeć (stempel `last_at` starszy niż okno), nie tylko taką, która nigdy nie
zaczęła; `order_mail_cleanup` przestał zapisywać powód bez kodu (parowanie po
indeksie dawało tam kod BŁĘDNY, nie brakujący); historia tłumaczy powody tym
samym `polish_gate_reason` co kolejka; w historii jest klasa wyjątku zamiast
`repr` (ten niósł ścieżki z dysku); strażnik AST przestał przepuszczać
`reasons.extend(dowolne_wywołanie())`; test sufitu pyta wprost o listę
kandydatów (asercja `<= 2` przechodziła też dla zera).

## Ustawienia (Coolify)

Wszystkie mają działające domyślne wartości — **wdrożenie nie wymaga zmian
w env**:

| Zmienna | Domyślnie | Po co |
|---|---|---|
| `ORDER_MAIL_RECHECK_ENABLED` | `true` | wyłącznik całości |
| `ORDER_MAIL_RECHECK_MAX_DOCS` | `100` | sufit dokumentów na bieg |
| `ORDER_MAIL_RECHECK_UNRECOGNIZED_DAYS` | `90` | jak długo ponawiać rozpoznanie klienta |
| `ORDER_MAIL_RECHECK_ALERT_AFTER_ATTEMPTS` | `3` | próby przed kartą do DL |
| `ORDER_MAIL_RECHECK_ALERT_AFTER_HOURS` | `6` | bezpiecznik przy martwej pętli |
| `ORDER_MAIL_RECHECK_HISTORY_DAYS` | `30` | retencja historii |

**Warunek wstępny:** `ORDER_MAIL_AUTOAPPLY_ENABLED` musi być `true`
(`GET /api/order-mail/sync/status` → `autoapply_enabled`). Przy wyłączonym
automacie recheck dalej odświeża plany, ale niczego nie zapisze — wpisy
lądują wtedy w kategorii `config` i nie alarmują.

## Weryfikacja

Lokalnie (kontener z obrazem prod + własny Postgres 16, migracja `upgrade heads`
na czystej bazie przeszła):

* `ruff check app/` + `ruff format --check app/` — czysto.
* `tests/test_order_mail_auto_recheck.py` (24), `test_order_mail_gate_and_planner.py`
  (36), `test_order_mail_ingest.py` (28), `test_order_mail_apply_and_queue.py`,
  `test_order_mail_sync_endpoint.py` (5), `test_alior_order_policy.py` (65),
  `test_order_mail_recheck_entrypoint_mirror.py` — zielone.
* Kontrakty: `test_route_authz_contract`, `test_section_ceiling_contract`,
  `test_section_access`, `test_dl_alerts*`, `test_entrypoint_dl_alerts_check_mirror`,
  `test_orders_procedure_freshness`, `test_client_tab_links`, `test_loop_heartbeat`,
  `test_delivery_contract`, `test_ci_coverage_contract` — zielone.
* **Lustro entrypointu sprawdzone wykonaniem**: DDL z `entrypoint.sh` odpalone
  na świeżej bazie daje kolumna-w-kolumnę ten sam kształt co migracja `0316`.
* Front: `tsc --noEmit` (bez błędów w zmienionych plikach), `next lint`,
  `vitest` — 26 testów order-mail zielonych.
* Wizualnie: harness `/preview/order-mail` (publiczny, zero zapytań) —
  sekcja historii, rozwinięcie wiersza, odznaki i powody; przy 400 px strona
  nie przewija się w poziomie (tabela ma własny `overflow-x-auto`).

## Po wdrożeniu na produkcji

1. `GET /api/order-mail/sync/status` → `autoapply_enabled == true`.
2. `POST /api/order-mail/sync`, potem `GET /api/order-mail/recheck-runs?limit=3` —
   liczba sprawdzonych powinna odpowiadać sumie wpisów
   `GET /api/order-mail/queue?outcome=needs_review` i `?outcome=unrecognized_client`.
3. `GET /api/dl-alerts/cards` — żaden wpis z kategorią `awaiting_contract` nie
   wystawił karty.

## Znane ograniczenia (świadome)

* **`awaiting_contract` nie ma limitu czasu** — to jawna decyzja z ticketu.
  Zamówienie z martwego dealu (literówka w nazwisku, umowa nigdy niepodpisana)
  będzie więc czytane z dysku co godzinę bez końca, bez karty i bez wygaśnięcia.
  Odczyt idzie w puli wątków i nie woła modelu, ale to realne CPU w procesie
  web. Jeśli zacznie boleć, właściwą odpowiedzią jest wygaszanie kategorii po
  N dniach — czyli zmiana decyzji produktowej, nie obejście w kodzie.
* **Ręczne „Pobierz zamówienia z maila" uruchamia recheck PRZED czytaniem
  skrzynki** (tak jak dotąd robiły to przeliczenie po zmianie reguły i ponowny
  odczyt AI). Przy dużej zaległości opóźnia to odczyt nowych maili; blokada
  wiersza jest przy tym trzymana przez czas odczytu PDF-a, więc DL klikający
  „Przelicz plan" na tym samym dokumencie poczeka.
* Wpis „Nie rozpoznano klienta" **nigdy nie alarmuje** — odbiorcą karty są
  Delivery Leadzi KLIENTA, a klienta nie ma. Widać go w kolejce i w historii.
* Retencja historii kasuje CAŁY wiersz biegu, nie przycina pojedynczych wpisów,
  i odpala się tylko wtedy, gdy bieg ma co zapisać.
* Przy 400 px rozwinięte powody scrollują się razem z tabelą (wspólny wzorzec
  z `FinanceArchiveTab`); strona jako całość nie przewija się w poziomie.
