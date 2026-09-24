# Audyt Klienci · Kontrakty · Finanse (24.09.2026) — raport z naprawy

Raport z audytu (dowody, lista błędów): https://claude.ai/artifact/9CTwFFNjUM3yBwdg2EyebH
Hotfix 500 w `GET /api/my-clients` (K-01): PR #1784, na produkcji.

Ten PR zbiera poprawki kodu z audytu (bloki A–G) i trzy tickety z 24.09.
Korekty danych produkcyjnych idą osobno — lista na końcu.

## Co się zmieniło

### Wspólne słowniki (G)
- `lib/status-labels.ts` — jedna nazwa każdego statusu kontraktu, zamówienia,
  grupy i umowy B2B (z kolorem); `lib/money.ts` — kwota + waluta + jednostka
  (`zł/h`, `zł/MD`, `zł/mc`, EUR ≠ zł). Rejestr kontraktów i skrzynka
  zamówień czytają je zamiast lokalnych kopii.

### MD, zamiany, przejęcia, import MD (A)
- Zamiana i przejęcie nie rozdają tych samych MD dwa razy; przekierowanie
  importu na poprzednika tylko przy potwierdzonym przeniesieniu.
- Zamknięcie zamówienia anuluje zaplanowane zastępstwa; korekty budżetu
  następcy/celu pod blokadą wiersza, kolejność blokad kontrakt → linie → grupa.
- Parser importu: kwoty „20.900,00” i „1,234.56”, numery bez zer wiodących,
  wspólna pula nie kasuje osób spoza pliku; liczniki importu rozróżniają
  rozliczenie kwotowe i nieudaną fakturę.
- **Ticket 4500030067:** zamówienie MD per osoba, w którym każda osoba
  wyczerpała pulę, przechodzi samo do „Zakończonych” (data zamknięcia =
  ostatni dzień miesiąca ostatniego zejścia) — u każdego klienta, nie tylko
  BIK. Sprawa offboardingu z pulą 0 MD nie wymaga decyzji: zamyka się
  automatycznie (`services/md_pool_used_up.py`, wpis w historii zamówienia),
  a zakończenie współpracy przy pustej puli nie zakłada sprawy wcale.
  Okno „Zakończ zamówienie” blokuje tylko sprawa z MD > 0.

### Poczta zamówień (B)
- Plan zapisu przy kilku osobach nie dziedziczy MD ani stawki z nagłówka;
  ręczne „Zastosuj” odmawia wspólnej puli i zamówienia kosztowego dla kilku
  osób. Bank Pocztowy przelicza też wiersze osób, Nordea porównuje tabelę
  z zachowanym odczytem modelu, Polkomtel/BIK przywracają kwotę po ÷ 1,23.
- Brak pliku = 404, „Nierozpoznane” da się odrzucić, waluta w kolejce.

### Zamówienia okresowe i synchronizacja z kontraktem (C)
- Zamówienie w nowej walucie nie kasuje historii przychodu kontraktu.
- Jedna serwerowa reguła „zamówienie bez kontynuacji” (`services/order_continuation.py`)
  czytana przez pigułkę 30d, alerty i Finanse; porzucony szkic nie jest następcą,
  aktywna linia MD z pozostałą pulą jest kontynuacją.
- Nocny przebieg uzupełnia wyłącznie brak przychodu kontraktu (różnice → raport);
  zaślepka „(bez numeru)” nie jest źródłem przychodu.
- Eksport Excel: kolumny „Jednostka stawki” i „Waluta”, stawka kontraktu
  w jednostce zamówienia.
- **Ticket OIT/0569/2026/ITVM:** ręczne zamówienie z końcem przed startem →
  422 przy polu i w API; ten sam numer na nachodzący okres tej samej osoby →
  409 `duplicate_order_number` (lustro `lib/order-period.ts` w oknach
  przedłużenia, edycji, nowego zamówienia i edycji w miejscu). Przyczyną nie
  był parser Aliora, tylko „Dodaj przedłużenie” podpowiadające start „dzień po
  ostatnim zamówieniu”, którym było już zamówienie przyszłe. Odczyt z maila
  z odwróconym okresem trzymała już bramka (`period_reversed`). Świadomie
  **bez** CHECK w bazie: Postgres sprawdza `NOT VALID` przy każdym UPDATE
  wiersza, więc istniejące złe wiersze blokowałyby każdą edycję.

### Kontrakty (D)
- Zmiana jednostki przelicza kwoty; harmonogram bez gubienia notatek;
  benchmark, void, przedłużenia; zakładka w adresie; bramki faktur i benchmarku
  zgodne z backendem.

### Klienci (E)
- Analityka klienta liczy zamówienia MD/kosztowe; jedna reguła „obecny
  kontrakt” (katalog klientów w SQL pyta zamówienia o datę startu, o końcu
  decyduje status umowy); pełne archiwum profilu.
- Zapisy na usuniętym kliencie → 404 (`assert_client_writable`); pliki
  kasowane po commicie; 409/422 zamiast 500. Awarie z „Ponów”, przyciski
  tylko dla uprawnionych, bez `window.confirm`.

### Finanse i analityka kontraktów (F)
- Analityka kontraktów liczy marżę wspólną `fold_money` (jak Rada); procent
  tylko z kontraktów ze znaną marżą + licznik `contracts_without_cost_leg`.
- „Zmiany w zamówieniach” bez dubla „bez kontynuacji”/Braki; anulowane
  zamówienia MD poza „Zamówieniami PDF”; Analityka za sekcją Finanse.

### Ticket 1460/2026 → kontrakt #341
- `POST /api/b2b-generator/generated/{id}/link-contract` (admin/DL) i akcja
  „Powiąż z kontraktem” przy umowie ze znacznikiem „Kontrakt usunięty — brak
  kontraktora”. Wiąże umowę z istniejącym kontraktem, wyrównuje osobę i klienta
  wiersza, dołącza DOCX do Dokumentów kontraktu (gdy da się go odtworzyć) i
  zostawia wpis w historii statusów (`source = linked_to_contract`). Numer,
  statusy, podpis i daty bez zmian.
- Przyczyna: umowę wygenerowano dla zdublowanego rekordu osoby i rekrutacji
  wewnętrznej; kontrakt założony przy podpisie usunięto wymuszeniem.

## Weryfikacja
- CI na gałęzi (`gh workflow run CI --ref fix/audit-clients-contracts-finance`),
  vitest 35 zmienionych plików (602 testy), `tsc` bez nowych błędów
  (13 znanych, niezwiązanych: tiptap/pdfjs).
- Hotfix #1784: `/api/health` z SHA maina + wywołanie trasy na produkcji.

## Poza tym PR-em
- Korekty danych (po decyzjach): scalenie kontraktów 578/643, duplikat grupy
  72/74, stawki linii 488/489/601 (Wedel — przed kolejnym zapisem), przychód
  ERSTE 614, wiersz importu MD 546, zamówienia 6/13/15/199, kontrakt 668 →
  klient 115, grupa-sierota 67, duplikaty klientów 51/88, 5124/32, 5244/5249.
- Ticket OIT/0569: usunięcie zamówienia 653 (01.01.2027 → 31.12.2026) —
  ręcznie w UI (Alior → Zamówienia → Marta Goceł).
- Ticket 1460/2026: kliknięcie „Powiąż z kontraktem” (#341) po wdrożeniu.
- Ticket 4500030067: zamknie się samo przy pierwszym odczycie listy zamówień
  klienta albo w nocnym skanie po wdrożeniu.
- Wspólna pula MD po wyczerpaniu zostaje `exhausted` (osobny stan z alertami),
  nie „Zakończone” — reguła ticketu dotyczy puli per osoba.
- Faza makiet: integracja trzech modułów w jeden obszar (D3, D5).
