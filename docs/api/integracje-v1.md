# NEXUS — API integracyjne v1

API dla automatyzacji procesów firmy: **rozliczanie klientów** (klienci,
kontrakty, zamówienia, zużycie MD, Finanse, faktury) oraz **rekrutacja
i kandydaci** (rekrutacje, Tablica, kandydaci, CV, notatki — od 15.10.2026).

- Adres bazowy: `https://api.nexus.dynaminds.pl/api/integrations/v1`
- Specyfikacja OpenAPI (do importu w Postmanie, n8n, Power Automate):
  `GET /api/integrations/v1/openapi.json` — z kluczem w nagłówku.
- Uwierzytelnienie: nagłówek **`X-API-Key`** (klucz konta serwisowego).
- Zapisy: nagłówek **`Idempotency-Key`** (UUID).
- Wdrożenia NEXUSA: **19:00–07:00** (Europe/Warsaw). W tym oknie możliwa jest
  ~2-minutowa przerwa — patrz [Ponawianie](#ponawianie-i-wdrożenia).

## Spis treści

1. [Klucz API i uprawnienia](#klucz-api-i-uprawnienia)
2. [Zasady wspólne](#zasady-wspólne)
3. [Trasy](#trasy)
4. [Zapisy: Idempotency-Key i dry_run](#zapisy-idempotency-key-i-dry_run)
5. [Błędy](#błędy)
6. [Ponawianie i wdrożenia](#ponawianie-i-wdrożenia)
7. [Przykłady: curl, Python, n8n, Power Automate, Make](#przykłady)
8. [Zmiany API (wersjonowanie)](#zmiany-api-wersjonowanie)

---

## Klucz API i uprawnienia

Klucz wydaje administrator NEXUSA w **Ustawienia → Klucze API**. Klucz należy
do **konta serwisowego** (np. „Automatyzacje — rozliczenia”), nie do osoby:
odejście czy awans pracownika nie zmienia uprawnień automatyzacji.

- Klucz widać **raz** — przy wydaniu. Trzymaj go w sejfie platformy
  automatyzacji (Credentials w n8n, Connections w Power Automate, Keychain
  w Make), **nigdy w repozytorium ani w mailu**.
- Klucz ma termin ważności (domyślnie 90 dni). `GET /me` pokazuje, ile dni
  zostało; ostatnie 14 dni = ostrzeżenie. Rotacja bez przestoju: admin wydaje
  drugi klucz, podmieniasz go w automatyzacji, admin odwołuje pierwszy.
- Jedna automatyzacja = jedno konto serwisowe (osobne uprawnienia i ślad).

### Scope'y (uprawnienia konta)

| Scope | Co daje |
|---|---|
| `clients:read` | Klienci: nazwa, NIP, REGON, status, Delivery Leadzi |
| `contracts:read` | Kontrakty: osoba, klient, okres, status, jednostka i waluta |
| `orders:read` | Zamówienia i zamówienia MD/kosztowe z liniami |
| `md:read` | Zużycie MD linii, importy raportów MD (liczby MD, bez kwot) |
| `md:write` | Import raportu MD, przypisanie wiersza, korekta MD za miesiąc |
| `finance:read` | Finanse → Zmiany w zamówieniach, Zamówienia PDF, wyniki miesiąca — **z kwotami sprzedaży** (stawka do klienta, przychód, faktura, PDF-y zamówień); koszty i marża tylko z `amounts:read` |
| `finance:write` | „Zrobione” w Zmianach, import arkusza wyników |
| `invoices:read` | Rejestr faktur, DSO — **z kwotami faktur do klientów**; kwota faktury od kontraktora tylko z `amounts:read` |
| `invoices:write` | Wystawienie, zmiana i anulowanie faktury |
| `sales_amounts:read` | **Kwoty sprzedaży** — to, co płaci klient: stawka do klienta, wartość i budżet zamówienia, przychód, kwoty faktur w importach MD |
| `amounts:read` | **Wszystkie kwoty** — kwoty sprzedaży oraz stawki konsultantów, koszty i marża; obejmuje `sales_amounts:read` |
| `orders:write` | Zamówienia: zakończenie, przedłużenie i anulowanie zamówienia MD/kosztowego, zakończenie zamówienia okresowego, data końca i notatka, PDF zamówienia |
| `contracts:write` | Kontrakty: data końca w przyszłości |
| `contracts:status` | Kontrakty: zmiana statusu i data końca, która kończy albo przywraca współpracę |
| `amounts:write` | Zmiana stawek i kwot przy zapisie zamówień (stawki zamówienia, osoby i budżety w przedłużeniu) — obejmuje `amounts:read` |
| `recruitments:read` | Rekrutacje: lista, szczegóły, wymagania (Champion), Tablica z kartami, historia ruchów, kolumny |
| `recruitments:write` | Dodanie osób do rekrutacji, przesunięcie karty — obejmuje `recruitments:read` |
| `candidates:read` | Kandydaci: lista i profil **bez danych kontaktowych** (umiejętności, miasto, dostępność, kategoria, „W bazie od”, „Pracuje u nas”, rekrutacje) |
| `candidates:contact` | Pola kontaktowe w profilu: e-mail, telefon, LinkedIn, NIP/REGON/nazwa firmy; szukanie po e-mailu |
| `candidates:cv` | Pliki kandydata (lista i pobranie) oraz tekst CV |
| `candidates:write` | Nowy kandydat, wgranie CV — obejmuje `candidates:read` |
| `notes:read` | Notatki kandydata, odpowiedzi screeningu, karta rekomendacji |
| `notes:write` | Nowa notatka (notatka systemowa) — obejmuje `notes:read` |

- `X:write` obejmuje `X:read`, a `amounts:read` obejmuje `sales_amounts:read`.
- **Zapis kwot** wymaga `amounts:write` niezależnie od `orders:write` — zapis bez
  niego dostaje `403 insufficient_scope` z listą pól (`details.fields`).
- **Kwoty są w dwóch poziomach.** Automatyzacja, która rozlicza faktury klientów,
  potrzebuje tylko `sales_amounts:read`. Stawki konsultantów, koszty i marżę daje
  wyłącznie `amounts:read`.

  | Gdzie | Kwoty sprzedaży (`sales_amounts:read`) | Koszty i marża (tylko `amounts:read`) |
  |---|---|---|
  | Kontrakty (`rates`) | `rate_client`, `monthly_rate_client` | `rate_candidate`, `monthly_rate_candidate`, `margin`, `monthly_margin` |
  | Historia stawek kontraktu | `client` | `candidate` |
  | Zamówienia i linie | `rate_revenue` | `rate_cost` |
  | Zamówienia MD/kosztowe | `budget_amount`, `budget_remaining` | — |
  | Importy MD | `invoice_amount` i „Uwagi” wierszy, pominięte wiersze | — |
  | Finanse → Zmiany w zamówieniach (`finance:read`) | `rate_revenue`, kwoty zmiany stawki przychodowej | `rate_cost`, kwoty zmiany stawki kosztowej, koszt w opisach historii |
  | Finanse → wyniki (`finance:read`) | `revenue_rate_md`, `invoice_amount`, kafel `revenue` | `cost_rate_md`, `compensation`, `margin_pln`, `margin_pct`, `margin_percent`, kafle `cost`, `margin`, `avg_margin_pct`, `cost_without_margin` |
  | Faktury (`invoices:read`) | `amount` faktur do klientów, DSO | `amount` faktur od kontraktorów |

  W Finansach i fakturach kwoty sprzedaży są widoczne już z `finance:read`
  i `invoices:read` (to moduły rozliczeń).
- **Pola ukryte mają wartość `null`.** Dwie flagi mówią, co ukryto:
  - `amounts_redacted: true` — klucz nie widzi żadnych kwot (zamówienia, zamówienia
    MD/kosztowe, kontrakty); bez kwot `rates` kontraktu jest `null`;
  - `costs_redacted: true` — klucz nie widzi kosztów i marży (kontrakty, historia
    stawek, zamówienia, Zmiany w zamówieniach i ich historia, wyniki miesiąca,
    faktury). W historii stawek lista `candidate` jest wtedy pusta.

  Wiersze importu MD bez kwot sprzedaży nie mają kwot faktur ani „Uwag”.
- **Dane osobowe:** kontrakty i zamówienia podają konsultanta — imię i nazwisko,
  identyfikator osoby, a kontrakty także e-mail kontaktowy (potrzebne do rozliczeń
  i łączenia z innymi systemami). Dane kandydatów są podzielone na profil
  (`candidates:read`), kontakt (`candidates:contact`), CV (`candidates:cv`)
  i notatki (`notes:read`) — daj automatyzacji tylko to, czego potrzebuje.
  Uwaga: plik i tekst CV zawierają zwykle dane kontaktowe, więc `candidates:cv`
  w praktyce je odsłania. Każde pobranie pliku kandydata zostawia wpis w historii
  kandydata z nazwą konta serwisowego. Dane trzymaj tylko tak długo, jak wymaga
  tego automatyzacja; nie przenoś ich do narzędzi, które nie mają umowy
  powierzenia.
- **Kwoty w rekrutacji:** oczekiwania stawkowe kandydata, budżet rekrutacji dla
  kandydata, stawka Championa, `expected_rate_*` i `budget_max_at_move` na kartach
  to **koszt** (`amounts:read`); stawka do klienta na karcie (`client_rate_*`) to
  **sprzedaż** (`sales_amounts:read`).

---

## Zasady wspólne

- **Format:** JSON, kodowanie UTF-8, nazwy pól `snake_case`.
- **Daty:** ISO 8601 (`2026-10-14`, `2026-10-14T19:23:00+02:00`). „Dziś” to
  kalendarz firmy (Europe/Warsaw).
- **Kwoty:** napis dziesiętny z groszami (`"1234.50"`) + osobne pole waluty.
  Liczby zmiennoprzecinkowe gubią grosze — nie zamieniaj kwot na float.
- **Liczby MD:** liczba (np. `12.5`).
- **Stronicowanie:** `page` (od 1) i `page_size` (domyślnie 200, max 500).
  Odpowiedź: `items`, `page`, `page_size`, `total`, `has_more`. Kolejność po
  `id` — stabilna między stronami.
- **Przyrostowo:** `updated_since=<ISO>` zwraca tylko rekordy zmienione od
  tej chwili. Zapamiętaj czas startu synchronizacji i podaj go następnym razem.
- **Limity:** 120 odczytów/min i 30 zapisów/min na konto i trasę.
  Przekroczenie = `429` z `Retry-After: 60`.

---

## Trasy

### Meta

| Metoda | Ścieżka | Scope | Opis |
|---|---|---|---|
| GET | `/me` | dowolny klucz | Konto, scope'y, termin klucza — test połączenia |
| GET | `/openapi.json` | dowolny klucz | Specyfikacja tras v1 |

### Klienci, kontrakty, zamówienia

| Metoda | Ścieżka | Scope |
|---|---|---|
| GET | `/clients?q=&updated_since=` | `clients:read` |
| GET | `/clients/{client_id}` | `clients:read` |
| GET | `/contracts?status=&client_id=&active_on=&updated_since=` | `contracts:read` |
| GET | `/contracts/{contract_id}?as_of=` | `contracts:read` |
| GET | `/contracts/{contract_id}/rate-history` | `contracts:read` + `sales_amounts:read` (stawki konsultanta z `amounts:read`) |
| GET | `/orders?client_id=&contract_id=&order_group_id=&status=&active_on=&updated_since=` | `orders:read` |
| GET | `/orders/{order_id}` | `orders:read` |
| GET | `/orders/{order_id}/md-consumptions` | `md:read` |
| GET | `/order-groups?client_id=&status=&updated_since=` | `orders:read` |
| GET | `/order-groups/{group_id}` | `orders:read` |

- **Zamówienie** to samodzielne zamówienie okresowe albo **linia** zamówienia
  MD/kosztowego (`order_group_id`).
- `start_date` i `end_date` to **okres efektywny**: daty linii, a gdy ich brak —
  grupy. Koniec linii MD zakończonej wyczerpaniem budżetu to miesiąc ostatniego
  zejścia. Ta sama reguła co w Finanse → Zmiany w zamówieniach.
- `number` to numer zamówienia (grupy albo samodzielnego zamówienia).
- `status` grupy to stan zapisany. `scheduled` przechodzi w `active` przy
  nocnym przebiegu albo otwarciu karty klienta.

### Zużycie MD

| Metoda | Ścieżka | Scope |
|---|---|---|
| GET | `/md/imports?period_month=RRRR-MM` | `md:read` |
| GET | `/md/imports/{import_id}` | `md:read` |
| POST | `/md/imports` (multipart: `file`, `period_month`; `?dry_run=&force=`) | `md:write` |
| POST | `/md/imports/{import_id}/rows/{row_id}/assign` (`{"order_id": …}`) | `md:write` |
| PUT | `/orders/{order_id}/md-consumptions/{RRRR-MM}` (`{"md_reported": …, "status": …, "note": …}`) | `md:write` |

- **Import** to ta sama droga co „Importy MD” w Finansach (arkusz XLSX).
  - Wiersze bez jednoznacznego dopasowania (`needs_assignment`) i przekroczenia
    salda (`overflow`) czekają na człowieka.
  - Ten sam plik za ten sam miesiąc drugi raz daje `409 duplicate_import`
    (powtórka podwoiłaby zużycie). Świadoma powtórka: `force=true`.
- **Przypisanie** działa tylko dla wierszy `needs_assignment` i linii z listy
  dopasowań wiersza. Przekroczenia salda i wspólne pule MD zatwierdza człowiek
  na ekranie (`409 requires_screen_approval`).
- **Korekta za miesiąc** **nadpisuje** miesiąc i przelicza saldo — nigdy nie
  dokłada. `status`: `accepted` | `protocol` | brak.

### Zamówienia i kontrakty — zapis

| Metoda | Ścieżka | Scope |
|---|---|---|
| POST | `/order-groups/{group_id}/close` (`{"closure_date", "closure_reason"}`) | `orders:write` |
| POST | `/order-groups/{group_id}/extend` (`{"order_number", "start_date", "end_date", "notes", "budget_amount", "md_budget_total", "lines": […]}`) | `orders:write` (+ `amounts:write` dla `lines`, `budget_amount`, `md_budget_total`) |
| POST | `/order-groups/{group_id}/cancel` (`{"reason"}`) | `orders:write` |
| POST | `/orders/{order_id}/close` (`{"closure_date", "closure_reason"}`) | `orders:write` |
| PATCH | `/orders/{order_id}` (`end_date`, `notes`; stawki: `rate_client`, `rate_candidate`, `rate_client_currency`, `rate_candidate_currency`) | `orders:write` (+ `amounts:write` dla stawek i walut) |
| PUT | `/orders/{order_id}/file` (multipart: `file`, tylko PDF, do 25 MB) | `orders:write` |
| PATCH | `/contracts/{contract_id}` (`{"end_date": … \| null}`) | `contracts:write` (+ `contracts:status`, gdy data kończy albo przywraca współpracę) |
| POST | `/contracts/{contract_id}/status` (`{"status": "draft" \| "active" \| "ending" \| "ended"}`) | `contracts:status` |

- Reguły są **te same co na ekranie NEXUSA** (ta sama logika, te same odmowy).
  API nie zakłada i nie usuwa zamówień ani kontraktów.
- **Zakończenie** (zamówienia MD/kosztowego i okresowego): data końca zapisuje
  się od razu, status `completed` linie i zamówienie okresowe dostają, gdy dzień
  zakończenia nadejdzie. Data wstecz jest dozwolona, ale nie wcześniejsza niż
  start zamówienia (422). Szkicu się nie kończy (`409 order_is_draft`), a linię
  zamówienia MD/kosztowego kończy się przez jej zamówienie
  (`409 order_belongs_to_group`).
- **Przedłużenie** to **nowe** zamówienie (nowy numer, okres, budżety);
  poprzednie zostaje bez zmian. Typ rozliczenia dziedziczy się po poprzedniku:
  kosztowe wymaga `budget_amount`, wspólna pula MD — `md_budget_total`. Osoby
  (`lines`) wskazuje się **kontraktem** u klienta (`contract_id`), ze stawkami
  (`rate_cost`, `rate_revenue`) i — przy budżecie per osoba — `input_mode`
  (`md` | `amount`) z `input_value`. Odpowiedź `201` z nowym zamówieniem.
- **Anulowanie** tylko zamówienia bez rozliczeń (zejścia MD, faktury) —
  inaczej `409 order_group_has_settlements`; takie zamówienie się kończy.
  Przywrócenie anulowanego — na ekranie.
- Zamówienie z otwartą decyzją o puli MD po odejściu konsultanta daje
  `409 offboarding_decision_required` — decyzję podejmuje Delivery Lead na ekranie.
- **`PATCH /orders/{id}`** przyjmuje wyłącznie wymienione pola (inne = `422`),
  co najmniej jedno. `null` czyści (`"end_date": null` = bezterminowo). Działa
  dla zamówień okresowych; linia zamówienia MD/kosztowego daje
  `409 order_belongs_to_group`. Nowy okres nie może nachodzić na inne
  zamówienie tej osoby (422), a zamówienie, które trwa, przywraca zakończony
  kontrakt.
- **PDF zamówienia:** nowy plik zastępuje poprzedni. Tylko PDF (inny plik `415`).
- **Data końca kontraktu** działa jak w rejestrze umów: data skracająca umowę
  skraca też otwarte zamówienia tej osoby, nowa data na zakończonej umowie ją
  przywraca, a data wstecz na trwającej umowie kończy ją przy nocnym
  przeliczeniu. Umowa B2B bez zakończenia współpracy daty końca nie dostaje
  (`422`). Stawek kontraktu API nie zmienia — stawki zamówienia zmienia
  `PATCH /orders/{id}`.
- **Status kontraktu** przechodzi przez maszynę stanów: `active` sprawdza komplet
  danych szkicu albo przywraca zakończoną umowę, `ending` wymaga daty końca
  (`409`, `details.reason = ending_requires_end_date`), `ended` daje `409`
  (`details.reason = termination_required`) — zakończenie z powodem jest na
  ekranie („Zakończ współpracę”).
- Te trasy **nie mają `dry_run`** — zapis zamówień zatwierdza się w trakcie,
  a PDF zapisuje się na dysk przed zatwierdzeniem.
- Autorem zmian jest konto serwisowe: Finanse → Zmiany w zamówieniach pokazują
  „Integracja: <nazwa>”, a historia zamówienia MD ma wpisy bez osoby.

### Finanse

| Metoda | Ścieżka | Scope |
|---|---|---|
| GET | `/finance/order-changes?year=&month=&q=&client_id=&date_from=&date_to=` | `finance:read` |
| GET | `/finance/order-changes/summary` | `finance:read` |
| GET | `/finance/order-changes/history?order_id=` albo `?order_group_id=` | `finance:read` |
| POST | `/finance/order-changes/checks` (`{"year", "month", "item_key", "done"}`) | `finance:write` |
| GET | `/finance/order-pdfs/months` | `finance:read` |
| GET | `/finance/order-pdfs?year=&month=` | `finance:read` |
| GET | `/finance/order-pdfs/zip?year=&month=&client_id=&files=order:1,group:2` | `finance:read` |
| GET | `/finance/order-pdfs/{kind}/{entry_id}/file` | `finance:read` |
| GET | `/finance/periods` | `finance:read` |
| GET | `/finance/results?year=&month=` | `finance:read` |
| POST | `/finance/imports` (multipart: `file`, `year`, `month`, `replace`; `?dry_run=`) | `finance:write` |

- **„Zmiany w zamówieniach”** to audyt miesiąca w zakładkach: Zmiany, Wejścia,
  Zejścia, Kończące się, Braki. Domyślnie bieżący miesiąc.
  - Każda pozycja ma `item_key` — tym kluczem odhacza się ją jako „Zrobione”.
    Podaj klucz dokładnie taki, jaki zwrócił odczyt tym samym kluczem API: klucz
    szkicu zamówienia zawiera stawki, więc bez `amounts:read` przychodzi w postaci
    skrótu (`…:draft:h…`).
  - Pozycja, której nie ma już w audycie (zamówienie zmieniło się w międzyczasie),
    daje `409 item_not_in_month`. Pobierz audyt ponownie.
- **Koszty w Finansach** (stawka kosztowa, wynagrodzenie, marża, zmiana stawki
  kosztowej) są tylko z `amounts:read` — bez niego `null` i `costs_redacted: true`.
  Opisy w historii zamówienia nie podają wtedy kwot kosztu.
- **Aneksy przedłużające umowę** (pliki `kind = "amendment"`) mogą podawać stawkę
  konsultanta, więc lista, ZIP i pobranie pokazują je tylko z `amounts:read`
  (bez niego aneksu nie ma na liście, a pobranie daje `403 insufficient_scope`).
- **Pobranie PDF-a przez API nie zmienia** statusu „Nowy / Pobrane” w Finansach —
  ten status należy do ludzi.
- **Import arkusza wyników:** miesiąc z istniejącym importem bez `replace=true`
  daje 409. `dry_run=true` sprawdza arkusz i konflikt okresu, nic nie zapisując.

### Faktury

| Metoda | Ścieżka | Scope |
|---|---|---|
| GET | `/invoices?contract_id=&status=&direction=&issued_from=&issued_to=&overdue_only=&updated_since=` | `invoices:read` |
| GET | `/invoices/dso` | `invoices:read` |
| GET | `/invoices/{invoice_id}` | `invoices:read` |
| POST | `/invoices` (`?dry_run=`) | `invoices:write` |
| PATCH | `/invoices/{invoice_id}` | `invoices:write` |
| POST | `/invoices/{invoice_id}/cancel` (`{"reason": …}`) | `invoices:write` |

- `direction`: `to_client` | `from_contractor`.
- Kwota faktury od kontraktora (`from_contractor`) to koszt — bez `amounts:read`
  jest `null` (`costs_redacted: true`), także w odpowiedzi na zapis. DSO liczy
  wyłącznie faktury do klientów.
- Zmiana kierunku (`direction`) faktury od kontraktora albo na `from_contractor`
  wymaga `amounts:read` — bez niego `403 insufficient_scope`.
- `status`: `issued` | `sent` | `paid` | `overdue` | `cancelled`.
- Kwota: > 0, najwyżej 2 miejsca po przecinku.
- Ten sam numer, kierunek i kontrakt drugi raz daje `409 duplicate_invoice`.
- Faktury się **nie usuwa** — anuluje się je z powodem.
- Każdy zapis zostawia wpis w Historii zdarzeń NEXUSA, z kontem serwisowym
  jako autorem.

### Rekrutacje

| Metoda | Ścieżka | Scope |
|---|---|---|
| GET | `/recruitments?status=&priority=&client_id=&recruiter_id=&delivery_lead_id=&q=&updated_since=` | `recruitments:read` |
| GET | `/recruitments/{job_id}` | `recruitments:read` |
| GET | `/recruitments/{job_id}/requirements` | `recruitments:read` |
| GET | `/recruitments/{job_id}/board` | `recruitments:read` |
| GET | `/recruitments/{job_id}/moves?candidate_id=` | `recruitments:read` |
| GET | `/recruitments/{job_id}/stages` | `recruitments:read` |
| GET | `/recruitments/{job_id}/candidates/{candidate_id}/screening` | `notes:read` |

- `status`: `open`, `closed`, `all`, `draft`, `published` (można powtórzyć);
  `priority`: `p1`, `p2`, `accepting`. `recruiter_id` liczy osoby, które pracują
  przy rekrutacji, jak filtr „Rekruter” na liście.
- Lista podaje liczby kart per kolumna (`stage_counts`); `updated_since` liczy się
  od zmiany samej rekrutacji — zmiany na Tablicy śledź przez `/moves`.
- `/requirements` to wymagania jak w Profilu Championa: słowa do szukania,
  MUST/NICE, umiejętności krytyczne, „sprawdź w rozmowie”, pytania screeningowe.
  Odczyt niczego nie oznacza jako przeczytane.
- `/board` to Tablica: kolumny z kartami (kandydat, etap, `process_state_version`
  potrzebny do przesunięcia, znaczniki). Bez danych kontaktowych.
- `/moves` — historia ruchów kart od najnowszych.
- `/screening` — odpowiedzi ze screeningu i karta rekomendacji osoby w tej
  rekrutacji (bez narodowości; stawki kandydata tylko z `amounts:read`).

### Kandydaci

| Metoda | Ścieżka | Scope |
|---|---|---|
| GET | `/candidates?q=&updated_since=&ids=&competence_category_id=&availability=&city=` | `candidates:read` |
| GET | `/candidates/{candidate_id}` | `candidates:read` (+ `candidates:contact` dla kontaktu) |
| GET | `/candidates/{candidate_id}/documents` | `candidates:cv` |
| GET | `/candidates/{candidate_id}/documents/{document_id}/file` | `candidates:cv` |
| GET | `/candidates/{candidate_id}/cv-text` | `candidates:cv` |
| GET | `/candidates/{candidate_id}/notes?job_id=` | `notes:read` |
| POST | `/candidates` (`?dry_run=`) | `candidates:write` |
| POST | `/candidates/{candidate_id}/cv` (multipart: `file`, `make_primary`) | `candidates:write` |
| POST | `/candidates/{candidate_id}/notes` | `notes:write` |

- `q` szuka po imieniu i nazwisku; `q` z „@” to dokładny adres e-mail i wymaga
  `candidates:contact`. `ids` — do 200 identyfikatorów po przecinku.
- Profil bez `candidates:contact` ma pola kontaktowe `null` i
  `contact_redacted: true`.
- Pliki i CV w kwarantannie tożsamości (CV innej osoby wgrane do profilu) nie
  wychodzą; tekst CV takiego źródła ma `quarantined: true`.
- Notatki ze stawką do klienta mają `content: null` i `content_hidden: true`
  bez `sales_amounts:read`. Notatka zapisana kluczem ma autora
  „Integracja: <nazwa konta>”.
- **Nowy kandydat** — `first_name`, `last_name`, `email` (wymagany), `phone`,
  `linkedin_url` (`linkedin.com/in/…`), `city`, `country`, `skills`, `source`.
  - Ta sama osoba = ten sam e-mail: istniejący adres daje
    `409 duplicate_candidate` z `details.candidate_id` (bez danych profilu).
  - Adres osoby, której dane usunięto na jej żądanie (RODO), daje
    `409 candidate_erased` — taką osobę dodaje tylko człowiek na ekranie.
  - Dopisek w imieniu („[ACTIVE]”, „(czarna lista)”) → `422` przy polu.
  - `dry_run=true` sprawdza to wszystko bez zapisu.
- **CV** — PDF, DOC albo DOCX (inny plik `415`), limit jak na ekranie. NEXUS czyta
  CV w tle po zapisie (uzupełnia profil, sprawdza, czy to ta sama osoba). Bez
  `dry_run`.
- **Notatka** — `content`, opcjonalnie `job_id` i `note_type`. Zawsze notatka
  systemowa (w historii za „Pokaż systemowe”); `@` w treści nikogo nie oznacza
  i nie wysyła powiadomień.

### Rekrutacje — zapis

| Metoda | Ścieżka | Scope |
|---|---|---|
| POST | `/recruitments/{job_id}/candidates` (`?dry_run=`) | `recruitments:write` |
| POST | `/recruitments/{job_id}/moves` | `recruitments:write` |

- **Dodanie osób** — `{"candidate_ids": [..., do 50], "stage_def_id": …, "note": …}`.
  Reguła integracji jak przy scraperach: osoba, która **zgłosiła się** do tej
  rekrutacji, trafia na Tablicę (`added`), każda inna — do **propozycji**
  (`proposed`) do akceptacji przez ludzi. Wynik per osoba: `added`, `proposed`,
  `already_in_job`, `closed_in_job` (zamkniętą kartę przywraca się ruchem karty)
  albo `blocked` z powodem (czarna lista, weto hiring managera); konflikty z klientem
  są ostrzeżeniem. `stage_def_id` — tylko kolumna wejściowa. `dry_run=true` zwraca
  same werdykty. Notatka zapisuje się tylko przy osobach dodanych na Tablicę.
- **Przesunięcie karty** — `{"candidate_id", "to_stage_def_id",
  "expected_state_version", "rejection_reason_id" | "rejection_reason",
  "acknowledge_eligibility"}`. Te same reguły co na Tablicy: QC CV, wymagania
  „Zweryfikowany”, rozmowa przed kontraktem, wersja karty
  (`expected_state_version` z `/board`, inna = `409`), ostrzeżenie o konflikcie
  (`409`, ponów z `acknowledge_eligibility: true`), powód przy zamknięciu.
  - **Klucz może:** przesuwać kartę między kolumnami w toku (Nowi, Screening,
    Zweryfikowany, QC CV, a po wysłaniu do klienta: CV wysłane, Rozmowa u klienta,
    Kontrakt), zamknąć kartę z powodem (odrzucenie, rezygnacja) i przywrócić
    zamkniętą.
  - **Tylko człowiek na ekranie** (`403 requires_screen_decision`, powód
    w `details.reason`): zatrudnienie i każdy ruch karty zatrudnionej (`hire`),
    wysłanie CV do klienta (`client_send`), kolejka Cpro (`cpro_queue`), zmiana
    stawki do klienta albo stawki kandydata (`client_rate`, `candidate_rate`),
    decyzje Delivery Leada (`delivery_lead_decision`).
  - Osoba spoza rekrutacji → `409 not_in_recruitment` (najpierw dodanie).
  - Ruch z klucza: bez 12-godzinnej blokady, bez maila odrzucenia do kandydata,
    bez automatycznego CV po „Zweryfikowanym”; w historii karty autorem jest
    konto serwisowe.
  - Bez `dry_run` (ruch zatwierdza się w trakcie).


---

## Zapisy: Idempotency-Key i dry_run

**Każdy** zapis (POST, PUT, PATCH) wymaga nagłówka `Idempotency-Key` z nowym
UUID dla każdej operacji.

| Sytuacja | Odpowiedź |
|---|---|
| Ten sam klucz i ta sama treść | Zapisana odpowiedź, bez ponownego zapisu; nagłówek `Idempotent-Replayed: true` |
| Ten sam klucz i inna treść | `409 idempotency_key_reused` |
| Operacja z tym kluczem jeszcze trwa | `409 idempotency_in_progress` — ponów za kilka sekund |
| Operacja z tym kluczem przerwana (> 10 min bez wyniku) | `409 idempotency_outcome_unknown` — sprawdź stan odczytem; jeśli zmiany nie ma, wyślij z NOWYM kluczem |
| Brak klucza | `400 idempotency_key_required` |
| Błąd 4xx | Nie jest zapamiętywany — popraw żądanie i wyślij z tym samym kluczem |

Wygeneruj UUID **przed** pierwszą próbą i użyj go we wszystkich ponowieniach
tej samej operacji. Paragony z kluczami są przechowywane 90 dni.

**`dry_run=true`** liczy wszystko, ale nic nie zapisuje (odpowiedź `200`
z `"dry_run": true`). Używaj go do budowy i testów automatyzacji — NEXUS nie ma
środowiska testowego. Działa na: `POST /md/imports`, `POST /finance/imports`,
`POST /invoices`. Zapis zamówień i kontraktów `dry_run` nie ma. Uwaga: `dry_run` importu MD na kilka sekund blokuje
przeliczane linie zamówień.

---

## Błędy

Każdy błąd ma ten sam kształt:

```json
{
  "error": {
    "code": "insufficient_scope",
    "message": "Opis po polsku",
    "details": {"required": ["md:write"], "missing": ["md:write"]}
  }
}
```

| HTTP | `code` | Znaczenie |
|---|---|---|
| 400 | `idempotency_key_required` | Zapis bez `Idempotency-Key` |
| 401 | `unauthenticated` | Brak, zły, wygasły albo odwołany klucz |
| 403 | `insufficient_scope` | Konto nie ma scope'u (`details.missing`) |
| 403 | `requires_screen_decision` | Ruch karty, który podejmuje człowiek na ekranie (`details.reason`) |
| 404 | `not_found` | Rekord nie istnieje |
| 409 | `conflict`, `duplicate_import`, `duplicate_invoice`, `idempotency_key_reused`, `idempotency_in_progress`, `idempotency_outcome_unknown`, `item_not_in_month`, `requires_screen_approval`, `conflict_retry`, `order_belongs_to_group`, `order_is_draft`, `order_already_closed`, `order_group_has_settlements`, `offboarding_decision_required`, `duplicate_candidate`, `candidate_erased`, `not_in_recruitment` | Konflikt — szczegóły w `message` i `details` |
| 413 | `payload_too_large` | Plik za duży (MD: 10 MB, wyniki: 15 MB, PDF zamówienia: 25 MB) |
| 415 | — | Zły typ pliku (importy: XLSX, zamówienie: PDF) |
| 422 | `validation_error` | Złe dane (`details.errors`) |
| 429 | `rate_limited` | Za dużo zapytań — `Retry-After` |
| 502/503 | — | NEXUS się wdraża albo restartuje — ponów |

Każda odpowiedź ma nagłówek `X-Request-Id`. Podaj go przy zgłaszaniu problemu.

---

## Ponawianie i wdrożenia

- NEXUS wdraża się **wyłącznie 19:00–07:00** (czas Warszawy). Wdrożenie to
  około 2 minut, w czasie których API może odpowiadać 502/503 albo nie
  odpowiadać.
- Ponawiaj 502, 503, 504, 429 i błędy sieci z rosnącym odstępem
  (np. 5 s, 15 s, 45 s, 2 min, 5 min). Zapisy ponawiaj z **tym samym**
  `Idempotency-Key`.
- Zapisy wysyłaj **po jednym**, nie równolegle — równoległe zapisy do tych
  samych zamówień mogą dać 409 i wymagać ponowienia.
- Długie synchronizacje planuj w dzień (07:00–19:00), wtedy nie ma wdrożeń.

---

## Przykłady

Klucz i adres w zmiennych środowiskowych — nigdy w kodzie:

```bash
export NEXUS_URL="https://api.nexus.dynaminds.pl/api/integrations/v1"
export NEXUS_KEY="nxs_v2_…"   # z sejfu, nie z repozytorium
```

### curl

```bash
# Test połączenia
curl -sS "$NEXUS_URL/me" -H "X-API-Key: $NEXUS_KEY"

# Zamówienia obowiązujące dziś (strona 1)
curl -sS "$NEXUS_URL/orders?active_on=$(date +%F)&page_size=200" -H "X-API-Key: $NEXUS_KEY"

# Audyt zmian w zamówieniach za październik 2026
curl -sS "$NEXUS_URL/finance/order-changes?year=2026&month=10" -H "X-API-Key: $NEXUS_KEY"

# Próba importu raportu MD (nic nie zapisuje)
curl -sS -X POST "$NEXUS_URL/md/imports?dry_run=true" \
  -H "X-API-Key: $NEXUS_KEY" \
  -F "period_month=2026-09" -F "file=@raport-wrzesien.xlsx"

# Import naprawdę — z kluczem idempotencji
curl -sS -X POST "$NEXUS_URL/md/imports" \
  -H "X-API-Key: $NEXUS_KEY" -H "Idempotency-Key: $(uuidgen)" \
  -F "period_month=2026-09" -F "file=@raport-wrzesien.xlsx"
```

### Python (`requests`)

```python
import os, time, uuid
import requests

BASE = os.environ["NEXUS_URL"]
S = requests.Session()
S.headers["X-API-Key"] = os.environ["NEXUS_KEY"]
RETRY = {429, 502, 503, 504}


def call(method, path, *, idempotency_key=None, **kw):
    headers = kw.pop("headers", {})
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    for delay in (0, 5, 15, 45, 120, 300):
        time.sleep(delay)
        try:
            r = S.request(method, BASE + path, headers=headers, timeout=60, **kw)
        except requests.ConnectionError:
            continue
        if r.status_code not in RETRY:
            return r
    r.raise_for_status()


def all_pages(path, **params):
    page = 1
    while True:
        body = call("GET", path, params={**params, "page": page, "page_size": 500}).json()
        yield from body["items"]
        if not body["has_more"]:
            return
        page += 1


orders = list(all_pages("/orders", active_on="2026-10-14"))

key = str(uuid.uuid4())  # jeden klucz na operację, ten sam przy ponowieniach
r = call("POST", "/invoices", idempotency_key=key, json={
    "contract_id": 123, "direction": "to_client", "invoice_number": "FV/10/2026/001",
    "issue_date": "2026-10-14", "due_date": "2026-11-13",
    "amount": "12300.00", "currency": "PLN",
})
r.raise_for_status()
```

### n8n

- **Credentials:** *Header Auth* — Name `X-API-Key`, Value = klucz.
- **Odczyt:** węzeł *HTTP Request*, metoda GET, URL `{{$env.NEXUS_URL}}/orders`,
  Authentication = Header Auth.
  - Stronicowanie: *Pagination* → *Update a Parameter in Each Request*:
    `page` = `{{$pageCount + 1}}`.
  - Warunek końca: `{{$response.body.has_more === false}}`.
- **Zapis:** dodaj nagłówek `Idempotency-Key` = `{{$execution.id}}-{{$runIndex}}`
  (stały przy ponowieniu tego samego wykonania) albo UUID z węzła *Crypto*.
- **Ponawianie:** w ustawieniach węzła *Retry On Fail* (np. 5 prób co 30 s),
  *On Error* → *Continue (using error output)*. Błąd 4xx obsłuż w gałęzi błędu,
  nie ponawiaj go.
- **Import specyfikacji:** `/openapi.json` można wczytać do węzła HTTP Request
  („Import cURL/OpenAPI”) albo do Postmana.

### Power Automate

- **Custom connector:** *Import an OpenAPI from URL* → `…/api/integrations/v1/openapi.json`.
  Jeśli import z URL wymaga klucza, pobierz plik curl-em i zaimportuj z pliku.
  - Security: *API Key*, Parameter label „Klucz NEXUS”, Parameter name
    `X-API-Key`, Location *Header*.
- **Zapisy:** w akcji dodaj nagłówek `Idempotency-Key` = `guid()` zapisany do
  zmiennej **przed** pętlą ponowień.
- **Ponawianie:** *Settings* → *Retry Policy* → *Exponential*, 4 próby.
  Ponawiane są 408/429/5xx.
- **Stronicowanie:** pętla *Do until* `body('…')?['has_more']` równe `false`,
  z rosnącym `page`.

### Make

- **Moduł:** *HTTP → Make a request*.
  - URL: `…/api/integrations/v1/orders`.
  - Headers: `X-API-Key` = klucz (z *Keychain* albo zmiennej organizacji).
  - Parse response: Yes.
- **Zapisy:** nagłówek `Idempotency-Key` = `{{uuid}}` wygenerowany w module
  *Set variable* przed modułem HTTP. Przy ponowieniu użyj tej samej zmiennej.
- **Ponawianie:** *Error handler* → *Break* z automatycznym ponowieniem
  (np. 3 razy co 15 min) dla 5xx i 429.
- **Pliki XLSX:** *HTTP → Make a request*, Body type *Multipart/form-data*,
  pola `file` (plik) i `period_month`.

---

## Zmiany API (wersjonowanie)

- Wersja jest w ścieżce (`/v1`).
- W v1 mogą **dochodzić** nowe pola i nowe trasy. Automatyzacja ma ignorować
  nieznane pola.
- **Usunięcie** pola albo **zmiana jego znaczenia** to nowa wersja (`/v2`),
  z okresem przejściowym, w którym działają obie.
- Kształt v1 pilnuje w NEXUSIE test (snapshot specyfikacji), więc zmiana
  nie przejdzie niezauważona.
