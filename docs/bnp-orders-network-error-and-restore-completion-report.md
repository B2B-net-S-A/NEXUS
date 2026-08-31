# Zamówienia: odczyt PDF BNP, „Network Error" przy zapisie, przywrócenie konsultanta

Trzy zgłoszenia z jednej sesji, jeden PR. Łączy je moduł Zamówienia i klient
BNP, ale przyczyny są niezależne i każda ma własny dowód.

---

## 1. Odczyt PDF dla BNP — identyfikacja po numerze ID konsultanta

### Objaw

Dla zamówień BNP „Zczytaj dane z dokumentu" nie dawało ani stawki, ani liczby
MD. Formularz zostawał pusty przy każdym pliku.

### Przyczyna (odtworzona)

Nie model, tylko **tożsamość**. PDF-y BNP nie zawierają imienia ani nazwiska
konsultanta — niosą wyłącznie jego numer ID. Ścieżka z `candidate_id` przechodzi
przez matcher fail-closed po nazwisku, a ten:

1. `parse_order_document` odrzuca wszystkie wiersze modelu, gdy
   `_document_mentions_consultant` nie znajdzie nazwy w tekście
   (dla BNP: zawsze),
2. `apply_consultant_row_match` bezwarunkowo zeruje `rate_client`, `rate_unit`
   i `md_total` przed rozstrzygnięciem dopasowania,
3. `enforce_consultant_policy_safety` czyści je **drugi raz**, bo
   `consultant_rate_matched` jest `False`.

To poprawne zachowanie dla dokumentu wielopozycyjnego i błędne dla BNP, gdzie
**cały PDF jest zamówieniem jednej osoby** — tej, z której karty operator
uruchomił odczyt.

### Rozwiązanie

Nowa polityka klientowa `apply_bnp_order_policy`, bramkowana
`BNP_ORDER_EXTRACTION_CLIENT_IDS` (CSV `client_id`, fail-closed — jak sześć
pozostałych). Dla klientów z tej listy `extract_order_pdf` woła parser **bez
`consultant_name`** i **pomija** bramkę bezpieczeństwa matchera.

| Pole | Reguła |
|---|---|
| Okres | `MM-RRRR do MM-RRRR` → pierwszy dzień miesiąca początkowego, **ostatni** dzień końcowego (`calendar.monthrange`, więc luty 28/29) |
| Stawka | „Cena netto" → stawka za 1 MD, `rate_unit="day"` |
| Liczba MD | „Szt." → `md_total` |
| Tożsamość | numer ID konsultanta → `consultant_ref` (informacyjnie) |

### Decyzje, które nie są oczywiste

- **ID nie jest nigdzie zapisywane.** Nexus nie przechowuje identyfikatorów
  nadanych przez klienta. `candidates.external_id` to ID z Traffita — objęte
  unikalnością per źródło i nadpisywane przy każdym syncu; wpisanie tam numeru
  BNP zerwałoby idempotencję importu. Numer jedzie więc wyłącznie w odpowiedzi
  odczytu i służy WZROKOWEMU potwierdzeniu. Zapisanie niezweryfikowanego
  identyfikatora tworzyłoby dane wyglądające na prawdę.
- **`consultant_ref` przeżywa redakcję finansową** (jak `title_needs_review`) —
  nie jest kwotą, a rola bez `VIEW_FINANCE` też musi wiedzieć, czyjego
  zamówienia dotyczy plik.
- **Brak etykiety NIE czyści pola** (inaczej niż w Credit Agricole). Tam
  kasowanie było odpowiedzią na udokumentowaną pomyłkę dwóch sąsiednich
  etykiet; tu takiego incydentu nie ma, a wyczyszczenie zostawiłoby operatora
  BNP z pustym formularzem — czyli z tym, na co się skarży. Wartość modelu
  zostaje, ale zawsze z komunikatem „sprawdź".
- **Układ tabelaryczny:** cena ODMAWIA (wzorzec Credit Agricole), ilość działa,
  bo kotwicą jest jednostka tuż za liczbą, nie kolejność kolumn.
- **Dwie rzeczy w wyrażeniu ilości są obroną przed cichą pomyłką:**
  `[^\S\n]*` zamiast `\s*` (zwykłe `\s*` przechodzi przez nową linię, więc
  kwota z wiersza wyżej sklejała się z „Szt." z wiersza niżej i do liczby MD
  trafiała STAWKA — 1040 zamiast 105) oraz brak spacji w klasie cyfr
  (separator tysięcy sklejał numer porządkowy z ilością: „1 105 szt." → 1105).
- **Front: BNP jest klientem WIELO-KONSULTANTOWYM.** Numer ID pokazują
  `ConsultantLineModal`, `OrderGroupFormModal` i `ExtendOrderGroupModal` (widok,
  w którym BNP realnie pracuje) oraz — dla spójności — `EditOrderDialog`
  i `ExtendOrderDialog`. Pole dołożone tylko do widoku jednoosobowego byłoby
  dla użytkownika BNP martwe.

### Ograniczenie do odnotowania

Wzorce powstały **bez próbki prawdziwego PDF-a BNP** (potwierdzone z Arturem).
Są tolerancyjne (warianty separatorów, brak diakrytyków, oba układy ilości)
i zweryfikowane na 15 wariantach okresu, 7 ceny i 8 ilości, ale pierwszy realny
dokument trzeba obejrzeć — a gdy etykieta okaże się inna, odczyt nie zgadnie:
zostawi wartość modelu z komunikatem „sprawdź".

---

## 2. „Network Error" przy zapisie zamówienia

### Objaw

„Przy próbie zapisania zamówienia otrzymuje komunikat network error,
a zamówienie nie zostaje zapisane."

### Przyczyna (odtworzona, cztery niezależne ścieżki)

Wszystkie to NIEOBSŁUŻONE wyjątki przy `commit()`. Lecą ponad
`CORSMiddleware` do starlette'owego `ServerErrorMiddleware`, które odpowiada
gołym 500 bez `Access-Control-Allow-Origin` → przeglądarka blokuje odpowiedź →
axios raportuje „Network Error", bez statusu i bez treści.

| # | Ścieżka | Mechanizm |
|---|---|---|
| 1 | `POST /orders` z `md_quantity` | `_apply_md_order_quantity` ustawiał `md_total`, ale nie `md_remaining`; CHECK `ck_client_orders_md_coherence` wymaga kompletu. **Regresja PR #1276** (27.08) — PATCH miał parę z `recompute_remaining`, POST dostał `md_quantity` osobno i wywołania nie przeniósł |
| 2 | Nazwa PDF > 255 znaków | `_attach_po_bytes` pisał do `VARCHAR(255)` nazwę SUROWĄ, choć na dysk zapisuje już obciętą |
| 3 | `PATCH {job_id}` / `{framework_contract_id}` | brak walidacji FK; wartości leciały ślepym `setattr` do commitu |
| 4 | Materializacja grupy | `md_rate_*` (Numeric 12,2 = 10 cyfr) przepisywane do `rate_*` (Numeric 12,3 = 9 cyfr) |

Ścieżka **1 jest tą ze zgłoszenia**: gdy kontraktor nie ma jeszcze zamówienia,
„Uzupełnij zamówienie" zapisuje przez `createDraftOrder` → `POST /orders`
(FormData, razem z PDF-em w JEDNYM żądaniu), doklejając `md_quantity`.
Objaw „zamówienie nie zostaje zapisane" był dosłownie prawdziwy — całe
tworzenie się cofało (0 wierszy w bazie).

Odrzucone jako fałszywe tropy (zwracają czytelne 4xx): brak kursu FX,
niezgodny budżet grupy, zerowa stawka, plik > 25 MB, `end_date < start_date`,
oraz cała ścieżka PATCH z pełnym payloadem dialogu (200 w kilkunastu
wariantach).

### Rozwiązanie

1. **Naprawa każdej z czterech przyczyn** (`md_remaining` ustawiane razem
   z budżetem, nazwa pliku przycinana z zachowaniem rozszerzenia, walidacja FK
   w PATCH, zakres stawki sprawdzany przed zapisem).
2. **`UnhandledErrorMiddleware`** — dodane jako PIERWSZE, czyli NAJGŁĘBIEJ
   w stosie, pod `CORSMiddleware`. Nieprzewidziany wyjątek wraca teraz jako
   JSON 500 **z nagłówkami CORS** i zdaniem po polsku. To poprawka
   ogólnosystemowa: dotąd KAŻDY nieobsłużony błąd w tej aplikacji wyglądał dla
   użytkownika jak zerwane połączenie, a w zgłoszeniu jak nic.
3. **`commit_order_write`** — znane naruszenia więzów modułu zamówień wracają
   jako 409 z komunikatem wskazującym pole, zamiast ogólnego 500.

---

## 3. Trzecia decyzja Delivery Leada: „Przywróć jako aktywne"

### Objaw

Trzy sprawy (Płonka 90 MD, Dynek 120 MD, Krawczyk 85 MD, wszyscy
„zakończył(a) współpracę 2026-08-31") czekały na decyzję, której nie było
w systemie: współpraca trwa dalej. `remove` oddaje pulę, `transfer` przekazuje
ją komuś innemu — obie zakładają, że współpraca się skończyła. Jedynym wyjściem
było zapisanie decyzji, która się nie wydarzyła.

### Rozwiązanie

Trzecia wartość rozstrzygnięcia `restore` (migracja `0253` + lustro DDL
w `entrypoint.sh`).

- **Pula MD zostaje NIETKNIĘTA** — gałąź omija `_reduce_legacy_md_budget`.
  To jest cała jej istota: nikt puli nie rozdysponował.
- **Kontrakt wraca razem z linią** (`sync_contract_to_live_order`). Bez tego
  decyzja kasuje samą siebie: konsultant zostaje w „Zakończonych" mimo
  aktywnej linii, a nocny cron widzi `end_date < today`, stawia `ended`
  i domyka linię z powrotem — po cichu, bo `_ensure_md_case` trafia
  w istniejący wiersz.
- **Data zakończenia jest DECYZJĄ, nie odtworzeniem.** Oryginalna `end_date`
  linii przepadła przy offboardingu (sprawa snapshotuje pulę, stawki i numer
  zamówienia — nie okres). Przy zamówieniu z datą końca pole jest wymagane
  i ograniczone jego okresem; przy bezterminowym puste = bezterminowo. Data
  z przeszłości jest odrzucana, bo linia ze WSPÓLNEJ puli ma `md_total IS NULL`
  i nie chroni jej `sync_md_line_status` — domknąłby ją nocny skaner.
- **Osobny typ zdarzenia** `przywrocenie_konsultanta`, różny od `przywrocenie`
  (= przywrócenie CAŁEGO zamówienia). Wspólny slug zlałby w historii dwie
  operacje na dwóch różnych poziomach.
- **Osobny CHECK** `ck_..._restore_target`: dwa istniejące guardy używają
  `IS DISTINCT FROM`, więc trzecia wartość omijała OBA.

### Co jeszcze trzeba zrobić

Feature jest gotowy, ale **trzy zgłoszone sprawy czekają na kliknięcie**: po
wdrożeniu Delivery Lead otwiera Klienci → BNP → Zamówienia → „Podejmij decyzję"
i wybiera „Przywróć jako aktywne" z datą do końca zamówienia. Nie robimy tego
migracją: to decyzja handlowa o konkretnej osobie, a data jest jej częścią.

---

## Aktywacja na produkcji

Polityka BNP jest fail-closed i **nie działa, dopóki nie ustawisz zmiennej**:

```
BNP_ORDER_EXTRACTION_CLIENT_IDS=<client_id BNP>
```

Numer wyciągnij `backend/scripts/list_clients.py` (`BNP`), ustaw workflow
**„Coolify set env"** (`.github/workflows/coolify-set-env.yml`,
`workflow_dispatch`) — panel i SSH są niedostępne. Uwaga na rodzinę rekordów:
„BNP" jako podciąg wciąga też „BNP Paribas Bank Polska", odrębnego klienta
(patrz `GET /api/admin/client-mixups`).

Pozostałe dwie zmiany nie mają przełącznika — działają od wdrożenia.

## Weryfikacja

| Warstwa | Wynik |
|---|---|
| `tests/test_order_pdf_parser.py` | 148 passed (w tym 22 nowe dla BNP) |
| `tests/test_order_extract_endpoint.py` | 21 passed (w tym 3 nowe) |
| `tests/test_order_write_unhandled_500.py` | 7 passed (nowy plik) |
| `tests/test_offboarding_restore_decision.py` | 10 passed (nowy plik) |
| Przebieg celowany (59 plików modułu zamówień) | patrz sekcja „Regresja" w PR |
| Frontend (vitest) | nowe: 5 + 2; baseline 17 plików / 218 passed |
| `ruff check app/` + `ruff format --check app/` | zielone |
| `tsc --noEmit` | zielone |

Baseline backendu na czystym HEAD: 891 passed / 1 failed / 4 skipped. Jedyny
fail — `test_dl_portal_scheduler.py::test_order_alert_dispatched` — reprodukuje
się przed zmianą i jest na liście `--ignore` w `ci.yml` (zastany dług).
