# Okno „Nowe zamówienie" — jeden odczyt PDF-a, karty wszystkich osób (09.2026)

„Nowe zamówienie" (MD/kosztowe) i „Uzupełnij zamówienie" połączone w JEDNO okno
(`OrderGroupFormModal` w trybie nowego zamówienia): PDF → **„Zczytaj i uzupełnij całe
zamówienie"** (`POST /api/clients/{id}/order-groups/extract`) → karta na każdą osobę
z dokumentu (`OrderPlanLineCard`, logika w `lib/order-plan.ts`) → JEDNO
`POST /order-groups` z `lines` (atomowo — endpoint od zawsze przyjmował linie).
Tryb edycji istniejącego zamówienia zostaje przy starym „Zczytaj dane z dokumentu".

- **Typy bez blokady per klient.** `order_types.allowed_order_types` zwraca wszystkie
  trzy typy dla każdego klienta (dawne `_PINNED_ALLOWED_ORDER_TYPES`: BNP/BIK tylko MD,
  Polkomtel/Wedel MD+kosztowe — ZNIESIONE). Mapa czterech klientów przetrwała
  wyłącznie jako **interpretacja legacy `NULL`** (`_LEGACY_NULL_ORDER_TYPES` →
  `ClientSafeResponse.legacy_null_order_type`) — bez niej historyczne karty MD
  przeskoczyłyby do sekcji „Okresowe". Front: `MultiConsultantOrdersTab` ma stałe
  `ALL_ORDER_TYPES`, a propsy `costOrdersEnabled`/`periodicOrdersEnabled` zniknęły.
  Konsekwencja zamierzona: jednorazowa korekta sierpniowa (`nexus_data_correction`)
  jest teraz zablokowana `order_type_runtime_policy_drift` — jej przesłanka („te typy
  są niedozwolone") przestała obowiązywać, a ponowne uruchomienie skasowałoby
  poprawne zamówienia. Nie „naprawiaj" tego blokera.
- **Domyślny typ = NAJCZĘSTSZY u klienta** (`most_common_order_type`: grupy +
  samodzielne bez anulowanych; remis → ostatni typ; brak historii → typ legacy).
  Zasila `OrderGroupListResponse.suggested_order_type`. Automaty (szkic po zatrudnieniu,
  poczta) nadal biorą OSTATNI typ (`suggested_order_type`) — świadomie nie ruszone.
- **Odczyt = ten sam pipeline co poczta zamówień**: `extract_order_text` → polityki →
  `parse_order_document(all_rows=True)` (dokument jednoosobowy BNP → tryb zwykły, jedna
  karta bez osoby) → `apply_policies` → `apply_rate_kind`. Pola dokumentu (stawka/MD
  z nagłówka) zastępują brak w wierszu TYLKO przy jednej osobie. Nic nie zapisuje.
- **Dopasowanie osoby do KONTRAKTU — `order_consultant_match`, NIE `order_mail_resolver`.**
  Resolver poczty toleruje odmianę i literówkę (trafia do kolejki), tu trafienie
  zapisałoby cudzą stawkę jednym kliknięciem. Reguła z ticketu: rdzeń = od
  przedostatniego wyrazu z wielkiej litery do końca, wcześniej dopisek („Active",
  „UR –", „Projekt 2"); tolerowane tylko dopisek, polskie znaki, wielkość liter,
  myślnik/spacja. `auto` = identyczne; `confirm` = dopisek / odwrotna kolejność
  (jedno kliknięcie DL); `inactive` = jedyny pasujący kontrakt jest ZAKOŃCZONY —
  karta mówi to wprost i każe wybrać: zapis historyczny / wznów / zastąp / usuń
  (od 09.2026; wcześniej był to cichy `confirm`, którego zapis wznawiał kontrakt);
  `ambiguous` = >1 RÓŻNA osoba w puli
  (także gdy jedna ma kontrakt aktywny, a druga szkic ALBO zakończony — powrót po
  przerwie) albo ta sama osoba z >1 żywym
  kontraktem; `none` = reszta. Pula: żywe + szkice (+ `ready_for_signature`); dopiero
  bez nich — zakończone (powrót osoby). `nearest_names` (difflib ≥ 0,75) to WYŁĄCZNIE
  podpowiedź tekstowa, nigdy wybór.
- **Osoba nieaktywna/nieznaleziona — JEDEN mechanizm na trzech ścieżkach (ticket B,
  09.2026, reguła ogólna dla zamówień MD i kosztowych każdego klienta).** Komunikat
  ma jedno źródło: `inactive_consultant_reason` / `unknown_consultant_reason`
  (`order_consultant_match`). Czytają go: karta okna „Nowe zamówienie", ten sam
  odczyt w „Uzupełnij zamówienie" (tryb edycji `OrderGroupFormModal` od 09.2026
  czyta PDF przez `/order-groups/extract`, karty tylko dla osób spoza zamówienia —
  `splitPlanForGroup`, zapis `POST …/lines/batch`, razem albo wcale), planer poczty
  i kontrakty zakończone na liście „kilka osób" (`OrderPlanContractRead.inactive_reason`
  — wybór zakończonego kontraktu przechodzi w pytanie zostaw / wznów / zastąp /
  usuń, a nie w ciche wznowienie). **Poczta: `ACTION_DECIDE_PERSON`** dla wierszy
  `order_type ∈ {md, cost}`, gdy osoby nie ma u klienta albo jej jedyny kontrakt
  do zapisu jest `ended` — nieautomatyczna akcja, „Zastosuj" wyłączone. Kolejka
  prowadzi przyciskiem **„Rozstrzygnij w oknie zamówienia"** do
  `/clients/{id}?tab=zamowienia&orderMailDoc={doc}`: zakładka pobiera PDF
  (`GET /order-mail/queue/{id}/order-target` + `/file`), otwiera „Uzupełnij
  zamówienie" dla otwartej grupy o tym numerze (`titles_collide`) albo „Nowe
  zamówienie", czyta PDF sama, a po zapisie `POST …/resolved-in-order` zdejmuje
  dokument z kolejki (`outcome=applied`, `proposal.resolved_in_order`). Świadomie
  BEZ `applied_order_id`: to pole czyta `complete_signed_mail_drafts`, który
  aktywuje szkice z maila po podpisie — linii grupy dotykać nie może. PDF z maila
  przy grupie, która MA już plik, domyślnie służy tylko do odczytu (podmiana
  pliku = checkbox). **Zamówienie okresowe zostaje przy decyzji z 10.09**: powrót
  po przerwie = nowe zamówienie (nie wskrzeszenie zakończonego).
- **Osoby spoza rostera klienta automat NIE zakłada — na ŻADNYM typie
  zamówienia** (zgłoszenie 09.2026, Nordea, umowa 1506/2026). Kontraktor rodzi
  się z podpisanej umowy B2B, nie z PDF-a klienta: zamówienie, które przyszło
  wcześniej, **czeka**. Rozstrzyga BRAMKA, nie planer — `match_kind == "none"`
  zawsze daje powód (`CODE_PERSON_NEW_TO_SYSTEM`, gdy osoby nie ma też w bazie;
  `_known_elsewhere_code` z #1561, gdy jest). Oba kody są
  w `AWAITING_CONTRACT_CODES`, więc wpis wisi **cicho**: bez licznika prób,
  bez karty dla Delivery Leada, z godzinową ponowną weryfikacją. Gdy ktoś
  oznaczy umowę „podpisana obustronnie", `confirm-fully-signed` zakłada kontrakt
  (`active`) i najbliższy recheck dopisze zamówienie sam. **Plan ZOSTAJE przy
  `ACTION_NEW_DRAFT`** (poza MD/kosztowymi, gdzie planer i tak daje
  `ACTION_DECIDE_PERSON`): ręczne „Zastosuj" bramki nie czyta, więc DL zachowuje
  drogę dla kontraktora bez umowy B2B (UoP, zlecenie, klient spoza generatora).
  Do 09.2026 zamówienie okresowe na nieznaną osobę jechało automatem i zakładało
  kandydata + szkic kontraktu + zamówienie — tak powstał kontrakt #657.
  `DECIDE_PERSON_ORDER_TYPES` **nie jest** listą typów, dla których nowa osoba
  jedzie automatem; opisuje wyłącznie, gdzie decyzję podejmuje się w oknie
  zamówienia.
- **Wiersze modelu weryfikowane regułą klienta.** Gdy aktywna polityka ma
  `extract_rows` (deterministyczny regex tabeli), wartość z tabeli wygrywa z modelem
  (`_reconcile_with_evidence`; lustro `order_mail_gate._row_evidence_reasons`),
  a rozbieżność i brak osoby w tabeli są ostrzeżeniem na karcie. Orlen (`requires_target`,
  więc tu jego polityka się nie odpala): MD z PDF-a zawsze pomijane, wiersze on/off-site
  tej samej stawki zlewane. Bank Pocztowy: linia MD dostaje oryginalne `rate_client_md`,
  nie godzinówkę ×8 (zaokrąglenie w górę zawyżałoby stawkę). Dokument wieloosobowy
  bez wierszy NIE tworzy karty z pól nagłówka — tylko jednoosobowy BNP. Brak jednostki
  stawki blokuje kartę (`revenueUnit: null`), a nie domyślnie „MD".
- **Stawka kosztowa z TEGO kontraktu** (`client_order_lines.contract_cost_rate`,
  wyciągnięte z `_rate_suggestion` — ta sama arytmetyka co picker), nie z „najnowszego
  żywego" osoby. Kwoty redagowane jak na liście (`_can_see_finance`); MD operacyjne.
- **Źródło każdej wartości** jedzie z odpowiedzi (`position_label` = numer pozycji
  tabeli PDF-a, szukany deterministycznie nad linią z nazwiskiem, nigdy wyżej niż linia
  poprzedniej osoby; brak pewności → „N. osoba w dokumencie"). Ręczna poprawka na karcie
  przestawia źródło na „wpisano ręcznie" — opis nie może twierdzić „z PDF", gdy liczbę
  wpisał człowiek.
- **Nowe MD jest domyślnie „Aktywne"** (dotąd wyłącznie „Draft"). `create_order_group`
  przy `status="active"` + `md_budget_mode` waliduje jak aktywacja szkicu (PATCH):
  per osoba — ≥1 linia i każda z `input_value > 0`; wspólna pula — `md_budget_total > 0`.
- **Zmiana typu na „Okresowe" przenosi wgrany PDF** do `NewContractorOrderDialog`
  (`initialFile`) i z powrotem — formularze są różne, plik ten sam.
- Harness wizualny (publiczny, zero zapytań): `/preview/order-new-from-pdf`.
