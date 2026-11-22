# Lista kontraktów: „Co dalej”, „Grupuj: klient”, „Kończące się” i panel A (20.11.2026)
<!-- indeks: `ContractsListV2` wariant A, `lib/contract-list-next.ts`, `lib/contract-ending.ts`, `?group=client`, `?timeline=1`, `contractPanelWarnings`, „Otwórz kontrakt” w stopce panelu -->

Etap 2 przebudowy modułu po makietach z 19.11.2026 (Artur wybrał wariant A
listy z „Grupuj: klient” z B, „Kończące się” A z osią czasu z B i panel A;
makiety: gałąź `claude/contract-module-redesign-f8f030`,
`frontend/src/components/makiety-kontrakty/list/`).

- **Kolumna „Co dalej”** liczy `listNextSteps` (`lib/contract-list-next.ts`)
  z tych samych progów i zdań co pas „Co się dzieje” na stronie kontraktu
  (`buildContractHappening`): odejście, zamówienie w 60 dni (czerwone do 14)
  z decyzją o przedłużeniu, nierozwiązana umowa B2B, brak stawki klienta.
  Dokłada brak aktywnego zamówienia (ta sama reguła co panel,
  `lacksActiveOrder`) i start w przyszłości. Bez zapytania na wiersz — każdy
  klient osoby niesie fakty zakończenia w `group_members` (schemat
  `ContractGroupMember`). Brak stawki tylko tam, gdzie konto widzi kwoty
  tego klienta (`canViewClientFinance`), bo serwer zeruje stawki spoza
  portfela Delivery Leada. Nowa sprawa = dopisek w `buildContractHappening`,
  nie osobna kolumna.
- **Bez kolumn „Typ” i „Status”**: prawie zawsze „B2B”/„Aktywny”. Inna
  wartość stoi drobnym drukiem przy kliencie (`ContractRowNote`, etykiety
  z `CONTRACT_STATUS_BADGE`). Okres to jedna kolumna (start → koniec
  bieżącego zamówienia, pełna data dd.mm.rrrr), szeroka tabela dokłada
  rekrutację, koniec umowy i start zamówienia. Nagłówki stawek: „Koszt”,
  „Przychód”, „Marża” (zł/h raz w nagłówku). „Co dalej” sortuje po końcu
  zamówienia.
- **Status, typ i daty są w „Więcej filtrów”** — status w pasku dublował
  pigułki („Status: 2” = „Aktywne”). Wybór spoza pigułek stoi chipem.
- **„Grupuj: klient”** (`?group=client`) i **„Kończące się”** biorą cały zbiór
  naraz, umowa po umowie (`group_by_candidate=false`, strony po 100, najwyżej
  1000; więcej = komunikat). Klucz zapytania zaczyna się od `contracts-v2`,
  więc odświeżenie listy odświeża i je. Grupa: liczba osób, marża
  miesięczna (tylko z marżą na liście), kto odchodzi i startuje; rozwinięta
  pierwsza, w niej 10 wierszy i „Pokaż wszystkie”. Wiersz na całą szerokość
  dostaje osobne komórki dla kolumn szerokiej tabeli — `colSpan` większy niż
  liczba widocznych kolumn dokładał puste kolumny.
- **„Kończące się”** to odejścia do domknięcia (`ContractsEndingView`):
  ostatni dzień i ile zostało, powód, stan umowy B2B, marża miesięczna,
  niespójność z zamówieniem (zamówienie trwa po odejściu albo bez daty
  końca, `orderConflict`) i „Zapisz rozwiązanie umowy” (bramka „Zakończenie
  współpracy”). „Oś czasu” (`?timeline=1`) pokazuje ten sam zbiór w grupach
  po miesiącu. Zbiór i licznik pigułki bez zmian (`bucket=ending`).
- **Panel podglądu A** (`ContractSidePanel`): jedno ostrzeżenie z akcją
  (`contractPanelWarnings` w `lib/contract-panel.ts`: sprawy paska strony +
  szkic, przywrócenie, brak zamówienia, koniec umowy z datą), reszta jednym
  zdaniem „Także: …”. Pieniądze w jednej linii, okres w dwóch liniach z „ile
  zostało”, kontakt zwięźle (`ContractCandidateContactRow compact`), trzy
  ostatnie dokumenty i zmiany ludzi (`humanizeActivity`, bez automatycznych).
  Stopka: „Otwórz kontrakt” (jedyna akcja główna, kotwica
  `contract.panel.open`), „Dodaj aneks” (to samo `AddAnnexMenu` co na stronie,
  wybór otwiera zakładkę z oknem `?aneks=`) i „⋯” (`contract.panel.more`)
  z „Zakończ współpracę…” (`contract.panel.end`). Status to
  `ContractStatusControl` w nagłówku. Opieki panel nie pyta (dodatkowe
  zapytanie przy każdym ↑/↓) — jej powody są na stronie kontraktu.
- Testy: `components/v2/pages/__tests__/ContractsListV2RedesignA.test.tsx`,
  `lib/__tests__/contract-list-next.test.ts`, `contract-ending.test.ts`,
  `contract-panel.test.ts`, `components/contracts/__tests__/ContractSidePanel.test.tsx`;
  spis: `k.next-steps`, `k.more-filters`, `k.group-by-client`,
  `k.ending-view`, `k.p.warning`.
