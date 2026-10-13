# Rejestr aneksów i aneks w kontrakcie od wygenerowania (13.10.2026)

<!-- indeks: rejestr aneksów w „Generatorze aneksów”, jeden stan aneksu, aneks do umowy spoza Nexusa zapisany przy kontrakcie, „Bez kontraktu”, wybór osoby zamiast „Umowa spoza Nexusa”, dowiązanie umowy z Excela, skan podpisanego aneksu, zakładka „Aneksy” kontraktu jako rzut dokumentu, etykieta aneksu w „Umowach bieżących” -->

Ticket działu („Generator aneksów + zakładka Aneksy”) po przeglądzie z Arturem
13.10.2026: połowa opisanych braków już działała (`b2b_contract_documents`,
„Oznacz jako podpisany” ze skutkami), a prawdziwą luką był aneks do umowy
spoza Nexusa — nie był zapisywany wcale. Raport:
`docs/annex-registry-completion-report.md`. Bez migracji.

- **Każdy aneks jest zapisywany i ma kontrakt.** Aneks bez umowy w rejestrze
  (umowa spoza Nexusa, zlecenie) niesie w żądaniu `contract_id`; osobę,
  rekrutację i klienta dokumentu bierze SERWER z kontraktu
  (`_load_subject_contract`), nie żądanie. Wyjątek „Bez kontraktu”: osoba nie
  ma kontraktu w NEXUSIE — aneks zapisuje się przy kliencie (`client_id`
  wymagane, inaczej Delivery Lead by go nie widział), a podpis jest
  zablokowany do powiązania (`effects.NO_CONTRACT_BLOCKER`,
  `POST /documents/{id}/link-contract`). Nie przywracaj „pobierz bez zapisu”.
- **Jedno źródło powiązania.** Dokument z umową bazową bierze kontrakt
  z wiersza rejestru (`effects.current_contract_id`), dokument bez umowy —
  z własnej kolumny. Aneks do umowy bez kontraktu (wiersz z Excela działu)
  DOWIĄZUJE wiersz do trwającego kontraktu B2B tej osoby u tego klienta
  (`_lock_parent_linking_contract`): jedyny dopasowany sam, przy kilku tylko
  wskazany w żądaniu. Reguła i kolejność blokad (kontrakt, potem wiersz) jak
  w `contract_termination_sync` i wypowiedzeniu Partnera. Nie dokładaj
  drugiego, równoległego powiązania na dokumencie.
- **Jeden stan zamiast pary „status aneksu” + „status podpisu”** (decyzja D1):
  `effects.annex_state` → `waiting` (czeka na podpis) · `signed_pending`
  (podpisany, dzień wejścia w życie dopiero nadejdzie) · `in_force`
  (obowiązuje) · `cancelled`. Przy aneksie obie osie mówią to samo, a „aktywny”
  przed dniem wejścia w życie byłby nieprawdą. Stan i dzień liczy WYŁĄCZNIE
  serwer (`effects.annex_effective_date` — ta sama data, którą `apply` wpisuje
  do aneksu kontraktu; `business_today()`); front niczego nie wylicza.
- **Rejestr aneksów jest w zakładce „Generator aneksów”** (`AnnexRegister.tsx`,
  `GET /documents?family=annex`), zakładka „Dokumenty” pokazuje pozostałe
  rodziny. Zakładkę widzi KAŻDY użytkownik generatora — aneks potwierdzają
  osoby bez prawa generowania (podpis, Finanse); kreator w zakładce wymaga
  `canGenerate`. Nie chowaj zakładki za prawem generowania.
- **Wybór osoby zamiast przycisku „Umowa spoza Nexusa”**
  (`AnnexSubjectPicker.tsx`, `GET /documents/subjects`): jeden wynik niesie
  umowy z rejestru i kontrakty bez żywej umowy w rejestrze — tylko dla typów
  `allows_external` (B2B) i `annex_mandate` (zlecenie). Kontrakt osiągalny
  z umowy bez powiązania pokazuje się POD tą umową, nie osobno (osobny wybór
  ominąłby wiersz rejestru i kolejkę „Aneks uzupełnienia danych”). Odpowiedź
  nie niesie kwot. Trasa jest GET — POST w routerze generatora wymaga zapisu
  Sourcingu.
- **Kwoty tylko pod bramką stawek.** Skrót zmiany (`annex_summary.annex_change`)
  oddaje kwoty wyłącznie przy `_RateVisibility.visible`; bez niej lista mówi
  tylko „Zmiana stawki”. Nie zapisujemy migawki stawki kontraktu „przed”:
  autor aneksu przechodzi bramkę jako autor, więc migawka ujawniałaby mu
  stawkę kontraktu. „Przed → po” przy umowie spoza Nexusa pokazuje dopiero
  zakładka kontraktu, pod `_can_read_contract_finance`.
- **Przywrócenie anulowanego aneksu** (`POST /documents/{id}/restore`) to samo
  przeliczenie wiersza rejestru (`annex_register.restore`), NIE `apply`:
  aneks sprzed 29.09.2026 nie ma zapisu „sprzed” i `apply` wziąłby za niego
  wartość późniejszego aneksu. Późniejszy aktywny aneks nadal wygrywa.
  Historia („kto, kiedy”) czyta istniejące wpisy `Activity` — nie ma osobnej
  tabeli statusów aneksu.
- **Skan podpisanego aneksu** (`services/b2b_documents/signed_scan.py`): PDF,
  JPG albo PNG do 20 MB, rozszerzenie zgodne z pierwszymi bajtami. Trafia do
  Dokumentów kontraktu jako „Aneks” i wskazują na niego wszystkie aneksy
  kontraktu utworzone przez ten dokument (`effect_summary.amendment_ids`);
  kolejny skan podmienia poprzedni; wygenerowany DOCX zostaje obok. Okno
  podpisu woła `confirm-signed` (bez zmian), POTEM wysyła skan — nieudany skan
  nie cofa podpisu. Dwie trasy na jednej funkcji: generator (bramki jak
  podpis + skutek w kontrakcie) i kontrakt
  (`POST /contracts/{id}/amendments/{amendment_id}/document`, tylko aneksy
  z generatora — plik przedłużenia zasila Finanse → Zamówienia PDF).
- **Zakładka „Aneksy” kontraktu: aneks czekający na podpis jest RZUTEM
  dokumentu** (`GET /contracts/{id}/annex-documents`), nie wierszem
  `contract_amendments`. Tę tabelę czytają jako zmiany już zastosowane
  `order_facts.py`, `contract_analytics.py`, `b2b_contract_end_date.py`
  i `finance_order_pdfs.py` — aneks bez podpisu liczyłby się tam jako
  obowiązujący. `GET /amendments` dostaje pola addytywnie (`source`, `state`,
  `document`, `created_by_name`). „Brak aneksów” dopiero, gdy OBA odczyty się
  udały i oba są puste.
- **Wiersz „Umów bieżących”**: `latest_annex` + `annex_count` (bez
  anulowanych) i `start_date_before` jednym odczytem na stronę listy. Przed
  podpisem data startu to „stara → nowa, po podpisie aneksu”, po podpisie
  stara przekreślona. W komórce Partner nie pokazujemy nazwiska.
- Harness: `/preview/b2b-documents` (rejestr we wszystkich stanach, wybór
  osoby, zakładka kontraktu, okno ze skanem). Testy:
  `test_b2b_annex_rules.py`, `test_b2b_annex_generator.py`,
  `test_b2b_annex_signed_scan.py`, `test_contract_annex_tab.py`,
  `AnnexRegister.test.tsx`, `ContractAnnexTab.test.tsx`; kolejność blokad
  pilnuje `test_b2b_documents_round6.py`.
