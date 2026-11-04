# Rejestr aneksów i aneks w kontrakcie od wygenerowania (13.10.2026)

<!-- indeks: jeden stan aneksu, aneks do umowy spoza Nexusa, zakładka „Aneksy” -->

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
  `POST /documents/{id}/link-contract`) — przy KAŻDYM typie, który wybiera
  kontrakt (`effects.annex_takes_contract`), także przy zleceniu: podpisany
  bez kontraktu nie dałby się już powiązać. Nie przywracaj „pobierz bez
  zapisu”.
- **Kontrakt to dane Delivery — wiąże go osoba, która prowadzi kontrakty**
  (`_binds_contracts`: „Kontrakty i zamówienia: tworzenie i edycja” + zapis
  w sekcji Delivery, Delivery Lead w granicy portfela
  `resolve_delivery_lead_client_ids`). Generator jest otwarty dla każdej roli
  operacyjnej, a `_assert_generator_client_access` przepuszcza wszystkich poza
  Delivery Leadem, więc samo prawo generatora pozwalało rekruterowi zobaczyć
  w wyszukiwarce cudze kontrakty i powiązać z nimi aneks (przegląd
  bezpieczeństwa 13.10.2026). Bramka stoi w czterech miejscach: wybór kontraktu
  (`_load_subject_contract` — także `prefill`), dowiązanie wiersza przy
  generowaniu (`may_link`; bez prawa aneks powstaje, wiersz zostaje bez
  kontraktu), `link-contract` i pole `can_link_contract`. Pozostali
  przygotowują aneks do umowy z rejestru albo „Bez kontraktu”. Powiązania NIE
  ograniczamy do autora: aneks „Bez kontraktu” przygotowany przez rekrutera
  wiąże Delivery.
- **Jedno źródło powiązania.** Dokument z umową bazową bierze kontrakt
  z wiersza rejestru (`effects.current_contract_id`), dokument bez umowy —
  z własnej kolumny. Aneks do umowy bez kontraktu (wiersz z Excela działu)
  DOWIĄZUJE wiersz do trwającego kontraktu B2B tej osoby u tego klienta
  (`_lock_parent_linking_contract`): jedyny dopasowany sam, przy kilku tylko
  wskazany w żądaniu. Reguła i kolejność blokad (kontrakt, potem wiersz) jak
  w `contract_termination_sync` i wypowiedzeniu Partnera. Nie dokładaj
  drugiego, równoległego powiązania na dokumencie.
- **Powiązanie aneksu nie zmienia osoby ani klienta (14.10.2026)**, bo audyt
  13.10 (pkt 7) pokazał, że „Powiąż z kontraktem” przy aneksie „Bez
  kontraktu” albo z unieważnionym kontraktem brało kontrakt dowolnej osoby
  i nadpisywało nim osobę i klienta dokumentu — podpis zapisywał wtedy firmę,
  NIP i stawkę osoby A w kontrakcie osoby B.
  `_assert_annex_link_same_subject`: osoba jak przy „Powiąż z kontraktem”
  w rejestrze umów (`_assert_link_same_person` — zdublowany rekord tej samej
  osoby przechodzi), klient dokumentu = klient kontraktu (duplikat scalony
  z klientem kontraktu przechodzi, bo scalenie nie przenosi dokumentów
  generatora); inaczej 409. Aneks „Bez kontraktu” nie zna osoby, więc wiąże
  się tylko z kontraktem u klienta, przy którym go zapisano — inny klient to
  nowy aneks. Kontrakt z żywą umową w rejestrze
  (`active`/`suspended`/`in_progress`) nie przyjmuje aneksu wprost: 422 przy
  generowaniu i przy powiązaniu (`_reject_contract_with_own_agreement`), jak
  w wyszukiwarce osoby. Sprawdzenie NIE siedzi w `_load_subject_contract`, bo
  tę funkcję dzielą podgląd i prefill „Popraw”, a kontrakt mógł dostać umowę
  już po aneksie. Dowiązanie wiersza rejestru przez aneks (przy generowaniu
  i w `link-contract`) idzie rdzeniem `apply_contract_link`: numer umowy na
  kontrakcie, wpis `linked_to_contract` na osi czasu umowy
  i `generated_contract_linked` na kontrakcie — do 14.10.2026 ustawialiśmy
  samo `contract_id`. Okno „Powiąż z kontraktem” ma pole wyszukiwania także
  przy aneksie do umowy z rejestru (numer umowy na start bywał pusty i okno
  zostawało bez wyjścia).
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
  Sourcingu. Umowy z rejestru widzi każdy, kto generuje (jak `GET /generated`);
  wiersze `kind="contract"`, kontrakty pod umową bez powiązania i datę startu
  kontraktu — tylko osoba z `_binds_contracts`. Odmowa to pusta lista, nie 403
  (bez zgadywania, czy kontrakt istnieje); front dobiera teksty tym samym
  warunkiem (`canManageOrderLifecycle`), żeby nie twierdzić „tej osoby nie ma
  w kontraktach” komuś, kto kontraktów nie widzi.
- **Wejście z kontraktu (`?contract_id=`)** wymaga podglądu Delivery tego
  kontraktu. Kreator bierze pierwszy wynik bez pytania, więc umowa POWIĄZANA
  z kontraktem wygrywa; umowa tej osoby bez powiązania wchodzi tylko dla
  aneksu i tylko gdy jest jedna (przy kilku pusta lista — człowiek wybiera).
  Rozwiązanie i wypowiedzenie nie zgadują umowy po osobie.
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
- **„Popraw” przenosi `register_applied`** (`annex_register.carried`,
  `superseded` w `_recompute`). Bez tego wiersz po poprawce trzymał starą
  wartość na zawsze: nie było jej już w żadnym aneksie, więc wyglądała na
  zmianę spoza generatora i przestawały ją ruszać anulowanie, przywrócenie
  i kolejne aneksy (błąd sprzed tej zmiany; wierszy zamrożonych wcześniej
  kod sam nie rozpozna).
  Historia („kto, kiedy”) czyta istniejące wpisy `Activity` — nie ma osobnej
  tabeli statusów aneksu.
- **Skan podpisanego aneksu** (`services/b2b_documents/signed_scan.py`): PDF,
  JPG albo PNG do 20 MB, rozszerzenie zgodne z pierwszymi bajtami. Trafia do
  Dokumentów kontraktu jako „Aneks” i wskazują na niego wszystkie aneksy
  kontraktu utworzone przez ten dokument (`effect_summary.amendment_ids`);
  kolejny skan podmienia poprzedni (ten sam dokument kontraktu; nowy plik
  zapisuje się pod kluczem z treści, stary znika dopiero po commicie —
  `signed_scan.discard`; skan wysłany już do SharePointa wraca do wysyłki
  i podmienia tam ten sam plik — `dokumenty-kontraktow-z-sharepointa.md`);
  wygenerowany DOCX zostaje obok. `signed_scan_document_id` na liście
  oddajemy tylko, gdy ten dokument kontraktu nadal istnieje
  (`signed_scan.existing_scan_ids`, 14.10.2026) — skan usunięty z Dokumentów
  albo z kontraktem dawał „Podmień skan” przy skanie, którego nie ma. Okno
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
  pilnuje `test_b2b_documents_round6.py`. Po audycie 13.10: powiązanie,
  skan i portfel Delivery Leada w czterech trasach aneksów —
  `test_fix48_ws02_annex_link_rules.py` (bez bazy),
  `test_fix48_ws02_annex_api.py`, `fix48-ws02-link-contract.test.tsx`.
