# Zamówienia z maila — brutto/netto z dokumentu + tolerancja literówek w dopasowaniu konsultanta

Ticket: automatyczny odczyt zleceń z maila (`zamowienia@b2bnetwork.pl`).
Zgłoszenie: zamówienie ERSTE `K/2026/194208/JP/828/26ERSTE8`, konsultant
Marcin Żółtaniecki, trafiło do „Do weryfikacji" z dwoma błędami.

## Diagnoza (co naprawdę było nie tak)

**Błąd 1 — brutto traktowane jak netto.** Przeliczenie brutto→netto było
bramkowane po **liście `client_id` z env** (`ERSTE_GROSS_RATE_CLIENT_IDS`,
`PFRON_ORDER_EXTRACTION_CLIENT_IDS`). Klient ERSTE był rozpoznawany po NIP
(`registry_id`), więc `client_id` był ustawiony, ale bez wpisu w tym env
polityka Erste **nie aktywowała się** i stawka BRUTTO z dokumentu lądowała
w bazie jako netto. To dokładnie to, przed czym ostrzega ticket: „nigdy na
podstawie stałego ustawienia klienta".

**Błąd 2 — konsultant niedopasowany mimo zgodnych danych.** Zwijanie
diakrytyków działało poprawnie (`Żółtaniecki` → `zoltaniecki`), ale tolerancja
literówek w resolverze poczty obejmowała **wyłącznie transpozycję sąsiednich
znaków**. Pojedyncza substytucja / wstawienie / usunięcie (typowa literówka,
błąd OCR) → `MATCH_NONE` → „Brak takiej osoby wśród konsultantów tego klienta".

## Rozwiązanie

### Błąd 1 — rodzaj stawki czytany z DOKUMENTU, per zamówienie

`app/services/order_pdf_parser.py`:

- **`detect_rate_gross_marking(document_text, rate_amounts)`** → `gross` / `net`
  / `None`. Sygnał jest **zakotwiczony na kwocie stawki** (nie na gołym słowie
  „brutto"), więc osobna „wartość brutto" (total z VAT) w dokumencie netto nie
  myli detektora. Bezpieczny wobec fałszywego `gross`: `gross` zwraca wyłącznie,
  gdy przy kwocie stawki widać „brutto" i przy żadnej kwocie stawki nie widać
  „netto"; konflikt → `None` → brak przeliczenia.
- **`apply_document_rate_kind(result, document_text)`** — uniwersalne, dla
  KAŻDEGO klienta i niezależnie od env: `gross` → `rate_client` (i każdy wiersz
  konsultanta) ÷ 1,23, oryginał w `rate_client_gross`. Idempotentne (znacznik
  `rate_client_gross`), więc nie koliduje z polityką Erste/PFRON.
- **Dokument wygrywa z regułą klientową:** `apply_gross_to_net_rate_policy`
  (Erste/PFRON) pomija przeliczenie, gdy przy stawce jest jawne „netto". Brak
  oznaczenia → reguła klientowa działa jak dotąd (ci klienci rozliczają zwykle
  brutto). Nowe pole `ConsultantOrderRow.rate_client_gross` (dataclass, brak
  migracji — leci w JSONB `extraction`).

Wpięte w obie ścieżki odczytu: pocztową (`order_mail_ingest.process_pdf_bytes`)
i ręczną (`client_orders.extract_order_pdf`). W ręcznej `rate_client_gross` już
był wystawiany w odpowiedzi (redagowany finansowo), więc UI pokazuje brutto obok
netto bez dodatkowych zmian.

### Błąd 2 — szersza tolerancja literówek w resolverze poczty

`app/services/order_pdf_parser.py`:

- **`_osa_distance` / `_edit1_token_distance`** — pojedyncza edycja (substytucja,
  wstawienie, usunięcie, transpozycja) w członie ≥ 5 znaków.
- `_name_match_score` / `_name_token_multiset_score` dostały parametr
  `distance_fn` (domyślnie stara, wąska transpozycja).

`app/services/order_mail_resolver.py`: `resolve_rows` używa
`distance_fn=_edit1_token_distance`.

**Dlaczego bezpieczne, mimo że luźniejsze:** dopasowanie „rescued" trafia do
KOLEJKI (człowiek potwierdza), pula jest zawężona do rostera JEDNEGO klienta,
kotwicą jest **dokładne imię**, a >1 trafienie w tolerancji → `MATCH_AMBIGUOUS`
(„wybierz ręcznie"). Auto-zapis nadal wymaga `MATCH_EXACT`, więc luźniejszy
„rescued" nie zmienia bramki automatu. **Ścieżka ręczna
(`apply_consultant_row_match`) zostaje przy transpozycji** — tam człowiek
wskazał już osobę, nie ma kolejki, a testy `test_close_but_real_other_person_is_not_a_typo`
(Kowalski/Kowalska, Nowak/Nowik) pilnują tej węższej reguły.

## Weryfikacja

Obraz `nexus-verify:img` + Postgres `nexus-test-pg` (własna baza, `alembic upgrade heads`).

- `tests/test_order_pdf_parser.py` — 179 passed (+15: detekcja brutto/netto,
  nadpisanie przez „netto", OSA/edit1, score edit1 vs domyślny).
- `tests/test_order_mail_gate_and_planner.py` — 18 passed (+5: literówka →
  rescued, przypadek ERSTE Żółtaniecki: exact/folded/typo, niejednoznaczność).
- `tests/test_order_mail_ingest.py` — DB e2e (nowy test): dokument ERSTE bez
  polityki env → stawka brutto ÷ 1,23 (top + wiersz) i konsultant dopasowany do
  rostera klienta.
- Regresja modułu zamówień: `test_order_policies_corpus`,
  `test_order_pdf_parser_all_rows`, `test_order_mail_apply_and_queue`,
  `test_order_extract_endpoint` — zielone (łącznie 234 no-DB + 51 DB).
- `ruff check` i `ruff format --check` — zielone na zmienionych plikach.

Zmiana jest backend-only; brak nowej powierzchni UI (pole brutto już było
renderowane), więc weryfikacja przez testy/JSON, nie przez Chrome.

## Uwagi / follow-up (poza zakresem tego PR)

- **Auto-zapis dla ERSTE nadal wymaga env polityki.** Poprawka odblokowuje
  poprawny odczyt i dopasowanie (zamówienie zapisuje się bez błędu, gotowe do
  ręcznego przyjęcia), ale bez `ERSTE_GROSS_RATE_CLIENT_IDS` w Coolify bramka
  automatu i tak kieruje je do kolejki (reguły „klient nie ma własnej polityki"
  i „brak deterministycznego potwierdzenia wierszy"). Dodanie tego env — i/lub
  `PFRON_ORDER_EXTRACTION_CLIENT_IDS` — włączyłoby deterministyczny ekstraktor
  wierszy (czystsze nazwisko + potencjalny auto-zapis). To decyzja wdrożeniowa,
  nie kodowa.
- Jeśli okaże się, że konsultant realnie nie jest w rosterze klienta (kontrakt
  wskazuje inny `client_id` z rodziny ERSTE/ex-Santander), to problem danych,
  nie dopasowania — do sprawdzenia po stronie przypisań kontraktów.
