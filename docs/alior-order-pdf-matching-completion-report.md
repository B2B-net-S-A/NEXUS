# Alior Bank — odczyt zamówienia z PDF i dopasowanie do szkicu

Zgłoszenie 09.2026: jednoosobowe zamówienie Alior Bank z maila trafiało do
weryfikacji, choć osoba miała szkic zamówienia. Osoby, numery i kwoty
w testach i w tym raporcie są zmyślone — odtwarzają wyłącznie układ i formaty
dokumentu ze zgłoszenia.

## Przyczyna

Model przeczytał dokument poprawnie, a planer znalazł szkic („Uzupełni szkic").
Zatrzymywała go bramka automatu z trzema powodami — wszystkie z warstwy
deterministycznej:

1. **„Brak niezależnego potwierdzenia osób i stawek z pól dokumentu PDF"** —
   regex wiersza Aliora wymagał kwot „1 155,00" i marży „13,81%". Ten PDF miał
   stawkę bazową bez groszy, marżę bez przecinka i stawkę z jedną cyfrą po
   przecinku → zero wierszy z tabeli.
2. **„Nie rozpoznano tabeli Konsultantów — wpisz osoby ręcznie"** — ten sam
   powód, dopisany przez politykę Aliora.
3. **„Nie ustalono, czy każda stawka jest brutto czy netto"** — uniwersalna
   detekcja VAT szukała kwoty z dwoma miejscami po przecinku, a dokument miał
   jedno;
   nagłówek „[PLN netto]" stoi daleko od kwoty.

Przy okazji: na realnym PDF-ie wieloosobowym z korpusu stary odczyt nazwisk
(dwie linie nad wierszem liczbowym) ucinał 2 z 4 nazwisk (zostawało samo
nazwisko bez imienia).

## Zmiany

| Plik | Co |
|---|---|
| `backend/app/services/order_policies/alior.py` | Reguła czyta WYŁĄCZNIE 4 pola. Wiersz kotwiczy marża (token z „%"), kwoty w dowolnym formacie (bez groszy, z jedną cyfrą, ze spacją tysięcy); podział stawka/Total niejednoznaczny tylko bez groszy — rozstrzyga Total = Roboczodni × stawka (reguła czytania, nie kontrola). Blok wiersza zamyka zakres „dd.mm.rrrr)"; nazwisko = słowa bloku bez nagłówka i słownika kompetencji. Okres: nawias pod nazwiskiem, potem „Moment wejścia w życie" / „czas oznaczony"; okres odwrócony → weryfikacja. Roboczodni, Stawka bazowa, Marża, Total i suma kontrolna z „Maksymalną wartością" — usunięte z weryfikacji. Stawka netto z definicji; jawne „brutto" w nagłówku kolumn albo wierszu osoby → weryfikacja bez ÷1,23 (stopka „Razem PLN" się nie liczy). Model potwierdza nazwisko, stawkę i okres każdej osoby; rozbieżność, pusta wartość albo wątpliwość modelu co do tych pól → weryfikacja. Osoba z odczytu bez odczytanego wiersza tabeli zostaje jako niepewna (nic nie znika po cichu). Tabela jest porównywana z ZAPISANYM odczytem modelu (`model_rows`), więc „Przelicz plan" nie potwierdza wiersza samym sobą. Formularz osoby wybiera wiersz wspólnym ścisłym matcherem `_name_match_score`. |
| `backend/app/services/order_policies/registry.py` | `table_authoritative` (Nordea, Alior): formularze czytają wszystkie osoby jak mail, „Przelicz plan" stosuje regułę ponownie (`PolicyContext.reapplied`). `rate_rules` per polityka zamiast twardych `if nordea` / `if bik` — BIK (#1485) wchodzi w ten sam mechanizm, reguła może oddać decyzję przez `None`. |
| `backend/app/services/order_pdf_parser.py` | `OrderExtraction.model_rows` — niezależny odczyt osób przez model, utrwalany razem z odczytem. |
| `backend/app/services/order_mail_ingest.py` | „Przelicz plan" stosuje regułę Aliora na zapisanym odczycie (dokumenty sprzed wdrożenia); `restore_extraction` odtwarza `model_rows`. Zamówienia z Activity `order_mail_*` oznaczane dla planera. |
| `backend/app/services/order_mail_planner.py` | Szkic, który niesie już zamówienie (zapis z maila albo dołączony PDF), nie jest nadpisywany zamówieniem na rozłączny okres (zgłoszenie: wrzesień, a potem październik–grudzień osobnym mailem) — powstaje osobne zamówienie. Ten sam numer / nachodzący okres (korekta) nadal uzupełnia szkic; szkic linii grupy zostaje przy ścieżce grupy. |
| `backend/app/services/order_mail_gate.py` | Okres odwrócony w propozycji zatrzymuje automat (tabela zamówień by go nie odrzuciła; bezterminowe zamówienie BIK nie ma czego odwrócić — po rebase na #1485 porównanie z `None` wywracało bramkę, pilnuje tego istniejący test BIK); ogólny komunikat „niepewny odczyt wiersza osoby" zamiast „…stawki" (wiersz bywa niepewny przez nazwisko albo okres). |
| `backend/app/api/order_mail_queue.py` | `model_rows` niesie kwoty — redagowane dla ról bez uprawnień finansowych tak samo jak `consultant_rows`. |
| `backend/app/data/procedures/…` | Instrukcja DL (sekcja Alior, brutto/netto, szkic, „Przelicz plan", pozycje nieodczytane, dopasowanie w formularzu) + stempel. |
| `CLAUDE.md` | Wiersz Alior w tabeli polityk, `table_authoritative`, `model_rows`, reguła „nic nie znika po cichu", planer. |

Ścieżki: mail (`process_pdf_bytes`), „Przelicz plan" (`refresh_review_plan`),
„Zczytaj dane z dokumentu" / Uzupełnij / Przedłuż / Nowe zamówienie
(`POST /api/clients/{id}/orders/extract`) — ta sama reguła i ten sam odczyt
all-rows. W formularzu osoby wiersz wybiera wspólny ścisły matcher osoby
(imiona dokładnie, ta sama liczba członów) na nazwisku z tabeli —
deterministycznie, także bez modelu.

## Przegląd adwersarialny (przed PR)

Recenzent z sondami na replikach dokumentów znalazł osiem problemów w pierwszej
wersji. Każdy ma test regresyjny, który pada na wersji sprzed poprawek
(16 testów padało na ce81411b, wszystkie przechodzą po poprawkach):

| # | Problem | Poprawka |
|---|---|---|
| 1 | Osoba z odczytu modelu bez odczytanego wiersza tabeli (druga pozycja tej samej osoby, wiersz bez marży, wiersz na kolejnej stronie) znikała po cichu — zamówienie zapisywało się bez niej | pozycja zostaje jako niepewna, dokument idzie do weryfikacji; pomijane jest tylko identyczne powtórzenie |
| 2 | Pusta stawka/okres w odczycie modelu liczyły się jak zgoda (prompt każe zostawić puste, gdy model nie umie powiązać wartości z osobą) | brak potwierdzenia = weryfikacja; wątpliwość modelu co do nazwiska/stawki/okresu też |
| 3 | „Przelicz plan" porównywał tabelę z własnym wynikiem (po pierwszym zastosowaniu `consultant_rows` to wiersze tabeli) — rozbieżność znikała po jednym kliknięciu | `model_rows` utrwalane i porównywane zawsze z nim; zapis sprzed reguły na dokumencie w starym układzie nie potwierdza osób |
| 4 | Odwrócony okres dokumentu przechodził automat | powód w regule + warunek w bramce |
| 5 | Formularz osoby dopasowywał „wszystkie człony w bloku" — „Anna Nowak" dostawała stawkę „Anny Nowak-Kowalskiej" | wspólny ścisły matcher `_name_match_score` |
| 6 | Szkic linii zamówienia MD zapisany z maila tracił ścieżkę grupy przy dokumencie na inny okres | szkic linii grupy zawsze przy `ACTION_GROUP` |
| 7 | Szkic z ręcznie dołączonym PDF-em zamówienia był nadpisywany dokumentem na rozłączny okres | `has_file` też oznacza „szkic niesie zamówienie" |
| 8 | „Brutto" w stopce „Razem PLN" (suma z VAT) zatrzymywało poprawny dokument | obszar tabeli = nagłówek kolumn + wiersze osób |

Świadome decyzje (nie defekty):

- **Powody modelu na poziomie DOKUMENTU nie zatrzymują Aliora** (sonda P1c).
  `uncertain_reasons` z parsera to zlepek wolnego tekstu modelu i ogólnych
  reguł o polach dokumentu („Nie znaleziono numeru/tytułu zamówienia", „Nie
  znaleziono daty rozpoczęcia", „Niepewny odczyt: …"), które w trybie all-rows
  bywają puste, a u Aliora są ignorowane (numer i okres czyta reguła z etykiet).
  Po złączeniu nie da się ich rozdzielić, a honorowanie ich przywróciłoby
  dokładnie fałszywe weryfikacje ze zgłoszenia. Każdą osobę potwierdza odczyt
  wiersza przez model: jego rozbieżność, puste pole albo wątpliwość blokują.
- **Nachodzący okres z innym numerem nadal uzupełnia szkic** (sonda P2b) —
  korekta dokumentu; zachowanie sprzed zmiany, pilnowane istniejącym testem DB.
- **Szkic wypełniony ręcznie bez pliku jest nadal „pusty"** (sonda P2c) —
  system nie ma śladu, że niesie zamówienie. Instrukcja każe dołączyć PDF.

## Weryfikacja

- `tests/test_alior_order_policy.py` — 60 testów: 4 pola na przykładzie ze
  zgłoszenia w 4 układach tekstu, brak powodów o polach pomijanych, netto
  domyślnie / jawne brutto (nagłówek, kwota, nie stopka), priorytet okresu,
  okres odwrócony, układ wieloosobowy, rozbieżności z modelem i jego puste
  pola, pozycje nieodczytane, idempotencja i zapisany odczyt modelu przy
  „Przelicz plan" (także round-trip przez JSON bazy i zapis sprzed reguły),
  formularz osoby (ścisły matcher), bramka automatu, szkic z PDF-em / linii
  grupy, pełna ścieżka mailowa na bazie (szkic uzupełniony, drugi PDF osobno),
  endpoint „Zczytaj", redakcja kolejki. Na kodzie sprzed zmiany kluczowy test
  pada dokładnie z trzema powodami ze zgłoszenia; na wersji sprzed przeglądu
  pada 16 testów regresyjnych.
- Realny PDF Aliora z korpusu (4 osoby) przez pipeline (pdfplumber): wszystkie
  4 pełne nazwiska, okresy i stawki; harness korpusu `--no-llm`: jedyna
  różnica względem `main` to Alior `consultants ✗ → ✓`.
- Replika PDF-a ze zgłoszenia (DOCX → LibreOffice → pdfplumber): numer, osoba,
  okres i stawka odczytane zgodnie z dokumentem, zero powodów.
- Po rebase na #1485 (BIK): 1300 testów w 74 plikach dotykających zmienionych
  modułów (`test_order*`, Nordea, PFRON, BIK, kolejka, cykl życia, finanse,
  procedura) zielone, 1 pominięty poza tym obszarem; `ruff check`
  i `ruff format --check` czyste.

## Po wdrożeniu

Dokumenty już leżące w kolejce „Do weryfikacji" nie przeliczają się same —
Delivery Lead klika **„Przelicz plan"** na obu wpisach ze zgłoszenia
(wrzesień oraz październik–grudzień). Pewny plan zapisze się automatycznie: pierwszy przeliczony
uzupełni szkic, drugi założy osobne zamówienie na swój okres — żaden nie
nadpisze drugiego. Nowe PDF-y Aliora z maila przechodzą od razu.

Oba dokumenty mają układ ze zgłoszenia (stawka bazowa bez groszy, marża bez
przecinka), więc
zapisany odczyt jest traktowany jako odczyt modelu. Wpis z dokumentu
w starszym układzie tabeli (kwoty z groszami, marża „13,81%") zostanie po
przeliczeniu w weryfikacji z powodem „odczyt zapisany przed zmianą reguły
Aliora…" — wtedy DL sprawdza osobę, okres i stawkę i zapisuje ręcznie.
