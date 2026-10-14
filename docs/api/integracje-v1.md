# NEXUS — API integracyjne v1

API dla automatyzacji procesów firmy. Na start: **rozliczanie klientów**
(klienci, kontrakty, zamówienia, zużycie MD, Finanse, faktury).

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
| `md:read` | Zużycie MD linii, importy raportów MD |
| `md:write` | Import raportu MD, przypisanie wiersza, korekta MD za miesiąc |
| `finance:read` | Finanse → Zmiany w zamówieniach, Zamówienia PDF, wyniki miesiąca |
| `finance:write` | „Zrobione” w Zmianach, import arkusza wyników |
| `invoices:read` | Rejestr faktur, DSO |
| `invoices:write` | Wystawienie, zmiana i anulowanie faktury |
| `amounts:read` | Stawki i kwoty w zamówieniach i kontraktach |

- `X:write` obejmuje `X:read`.
- Bez `amounts:read` pola kwot są `null`, a odpowiedź ma `"amounts_redacted": true`.
- API **nie udostępnia** danych kandydatów, rekrutacji ani notatek (RODO).

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
| GET | `/contracts/{contract_id}/rate-history` | `contracts:read` + `amounts:read` |
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
  - Pozycja, której nie ma już w audycie (zamówienie zmieniło się w międzyczasie),
    daje `409 item_not_in_month`. Pobierz audyt ponownie.
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
- `status`: `issued` | `sent` | `paid` | `overdue` | `cancelled`.
- Kwota: > 0, najwyżej 2 miejsca po przecinku.
- Ten sam numer, kierunek i kontrakt drugi raz daje `409 duplicate_invoice`.
- Faktury się **nie usuwa** — anuluje się je z powodem.
- Każdy zapis zostawia wpis w Historii zdarzeń NEXUSA, z kontem serwisowym
  jako autorem.

---

## Zapisy: Idempotency-Key i dry_run

**Każdy** zapis (POST, PUT, PATCH) wymaga nagłówka `Idempotency-Key` z nowym
UUID dla każdej operacji.

| Sytuacja | Odpowiedź |
|---|---|
| Ten sam klucz i ta sama treść | Zapisana odpowiedź, bez ponownego zapisu; nagłówek `Idempotent-Replayed: true` |
| Ten sam klucz i inna treść | `409 idempotency_key_reused` |
| Operacja z tym kluczem jeszcze trwa | `409 idempotency_in_progress` — ponów za kilka sekund |
| Brak klucza | `400 idempotency_key_required` |
| Błąd 4xx | Nie jest zapamiętywany — popraw żądanie i wyślij z tym samym kluczem |

Wygeneruj UUID **przed** pierwszą próbą i użyj go we wszystkich ponowieniach
tej samej operacji.

**`dry_run=true`** liczy wszystko, ale nic nie zapisuje (odpowiedź `200`
z `"dry_run": true`). Używaj go do budowy i testów automatyzacji — NEXUS nie ma
środowiska testowego. Działa na: `POST /md/imports`, `POST /finance/imports`,
`POST /invoices`. Uwaga: `dry_run` importu MD na kilka sekund blokuje
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
| 404 | `not_found` | Rekord nie istnieje |
| 409 | `conflict`, `duplicate_import`, `duplicate_invoice`, `idempotency_key_reused`, `idempotency_in_progress`, `item_not_in_month`, `requires_screen_approval`, `conflict_retry` | Konflikt — szczegóły w `message` |
| 413 | `payload_too_large` | Plik za duży (MD: 10 MB, wyniki: 15 MB) |
| 415 | — | Zły typ pliku (tylko XLSX) |
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
