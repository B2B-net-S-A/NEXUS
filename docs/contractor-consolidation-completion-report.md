# Konsolidacja kontraktorów wieloklientowych + walidacja i usuwanie kontraktów

> Trzy tickety z 2026-08-25 w jednym PR. Zero migracji — wszystkie zmiany są
> read-time/serializacyjne, więc entrypoint.sh nie wymaga lustra DDL.

## 1. Konsolidacja: jedna osoba × N klientów

**Problem:** Paweł Małek pracujący naraz u Banku Pocztowego i VeloBanku
istniał w module Kontrakty jako dwa niepowiązane wiersze, a profil kandydata
pokazywał tylko jednego klienta.

**Lista** (`GET /api/contracts?group_by_candidate=true`,
[contracts.py](../backend/app/api/contracts.py)):
- Jeden wiersz na OSOBĘ (klucz `coalesce(candidate_id, -id)` — umowy odpięte
  od usuniętych kandydatów zostają osobnymi wierszami pod ujemnym kluczem).
- Grupowanie i stronicowanie PO STRONIE SERWERA (`total` = liczba grup);
  grupowanie strony wyników w FE rozdzielałoby osobę między strony paginacji.
- Wszystkie umowy grupy (spełniające aktywne filtry!) w `group_members`
  z kompletem: klient, okres, stawki z harmonogramów, marża, status.
- Redakcja VIEW_FINANCE obejmuje członków grupy (`_redact_contract_finance`),
  scope Delivery Leada aplikowany w obu zapytaniach (klucze + wiersze).
- FE ([ContractsListV2.tsx](../frontend/src/components/v2/pages/ContractsListV2.tsx)):
  kolumna „Stawka klient" → **„Stawka przychodowa"**, nowa kolumna
  **„Stawka kosztowa"**; dla wierszy wieloklientowych okres/stawki/marża
  rozbite per klient („Bank Pocztowy: 175,00 zł / VeloBank: 162,50 zł");
  licznik nagłówka mówi o kontraktorach, nie umowach.
- Tryb płaski (bez parametru) bez zmian — historia kandydata, rejestr
  klienta i eksport dalej widzą pojedyncze umowy.

**Szczegóły kontraktu** (`related_contracts` w `ContractDetailResponse`):
- Chipy-zakładki nazwane po KLIENCIE (bez „Projekt 1/2") nad zakładkami
  widoku; klik = pełny widok tamtej umowy, więc okres, stawki, marża,
  dokumenty, aneksy ORAZ **benchmark stawki liczą się per klient** (benchmark
  zawsze był per kontrakt — nawigacja per klient załatwia wymóg z ticketu).
- Rodzeństwo bez `void` i w scope DL (DL ograniczony do swojego portfela nie
  odczyta z chipów, u jakich innych klientów pracuje konsultant).
- Nagłówek: „pracuje u N klientów" (liczone z żywych statusów).

**Profil kandydata:**
- `EmploymentInfo.engagements` — wszystkie AKTYWNE kontrakty (ta sama
  populacja co dotychczasowa gałąź `contract`, więc lista nigdy nie przeczy
  pojedynczym polom). Banner na profilu/liście pokazuje
  **„Pracuje u: Bank Pocztowy, VeloBank"** z datami końca per klient.
- `UmowaTab`: `.filter` zamiast `.find` — sekcja „Aktualne umowy (N)"
  renderuje kartę per klient (wcześniej druga równoległa umowa nie istniała
  NIGDZIE na profilu: nie była `ended`, więc nie trafiała nawet do historii).

**„+ Dodaj kolejny projekt"**
([AddProjectDialog.tsx](../frontend/src/components/contracts/AddProjectDialog.tsx)):
- Przycisk obok Edytuj/Usuń na widoku kontraktu (role jak tworzenie:
  admin/DL/TAC; ukryty dla umów odpiętych od usuniętego kandydata).
- Pola: Klient (WYMAGANY — walidacja blokuje zapis, czerwone pole + opis),
  Rekrutacja (opcjonalna, z listy rekrutacji WYBRANEGO klienta), stawka
  kosztowa/przychodowa + jednostka (tylko role finansowe), daty (koniec
  opcjonalny = bezterminowo), typ, tryb pracy, status (Szkic/Aktywny;
  bez dostępu finansowego tylko Szkic — stawek wymaganych do aktywacji
  i tak nie dałoby się wpisać).
- Zapis = zwykły `POST /api/contracts` → grupowanie i zakładki włączają się
  automatycznie. Duplikat (ta sama osoba u tego samego klienta) → komunikat
  z backendu pod polem klienta.

## 2. BUG: „Missing required fields" w Nowym kontrakcie

**Przyczyna:** trzy nakładające się defekty.
1. Backend (lifecycle) zwraca 409 `{message: "Missing required fields",
   missing: [...]}` gdy status „Aktywny" bez kompletu
   `ACTIVATION_REQUIRED_FIELDS` — a `extractErrorMsg` oddawał samo `message`,
   GUBIĄC listę pól.
2. Formularz w ogóle **nie miał pola `work_mode`** (Tryb pracy) — wymagania
   aktywacji nie dało się spełnić z tego ekranu ani jednym kliknięciem.
3. Walidacja lokalna znała tylko 3 pola i jeden zbiorczy banner.

**Naprawa:**
- Walidacja per pole po polsku: banner „Uzupełnij brakujące pola" + czerwone
  obramowanie + opis pod KAŻDYM brakującym polem; wymagalność pól
  aktywacyjnych (data zakończenia, tryb pracy, obie stawki) podnosi się
  dynamicznie przy statusie Aktywny/Kończący się (gwiazdki przy etykietach).
- Nowe pole **Tryb pracy** w sekcji Warunki; `noValidate` na formularzu
  (natywne dymki przeglądarki mówiły w jej języku i tylko o pierwszym polu).
- `extractErrorMsg` tłumaczy `missing[]` na etykiety
  (`CONTRACT_FIELD_LABELS` w [api.ts](../frontend/src/lib/api.ts)) — naprawia
  też inne powierzchnie bijące w ten sam 409 (PATCH statusu w rejestrze).
- **Duplikat kontraktora po E-MAILU** (case/whitespace-insensitive), nie po
  nazwisku: `POST /api/contracts` → 409
  `{code: "duplicate_contractor", message: "Kontrakt dla tego kontraktora
  u klienta „X" już istnieje (e-mail: …)"}`. Zakres: ta sama osoba + TEN SAM
  klient + żywy status (draft/ready_for_signature/active/ending). Drugi
  klient tej samej osoby NIE jest duplikatem (to feature wieloklientowy),
  powrót po `ended`/`void` też nie. Kandydat bez e-maila porównywany po
  własnym id. Do tego jawne 404 PL dla nieistniejących id kandydata/klienta
  (wcześniej FK IntegrityError → 500).
- Stawka progresywna i stawka z umowy ramowej pozostają OPCJONALNE
  (etykieta to teraz mówi wprost) i nie blokują zapisu.

## 3. BUG: „Usuń" nie usuwał kontraktu

**Przyczyna:** dwie warstwy ciszy.
1. Backend odmawiał hard delete WSZYSTKIEMU poza szkicem (409), a szkic
   z niepodpisaną wygenerowaną umową B2B przechodził guard i wywracał się na
   FK RESTRICT → nieobsłużony 500.
2. FE: `deleteMutation` bez `onError` — spinner gasł, kontrakt zostawał,
   zero komunikatu; do tego natywny `window.confirm` (wzorzec zbanowany
   w repo) i inwalidacja nieistniejącego klucza cache.

**Naprawa:**
- `hard_delete_blocker` ([contract_lifecycle.py](../backend/app/services/contract_lifecycle.py)):
  DELETE działa dla KAŻDEGO statusu; blokują wyłącznie PODPISANE dowody —
  ukończony podpis kwalifikowany (kaskada zniszczyłaby dowód) albo umowa B2B
  potwierdzona obustronnie (`signed_both`, audytowane `confirm-fully-signed`;
  symetria z nieedytowalnością samego wiersza wygenerowanego). Odmowa po
  polsku, z kodem i wskazaniem alternatywy (`/void`).
- Usuwany jest WYŁĄCZNIE rekord kontraktu: kandydat zostaje, NIEPODPISANE
  wygenerowane umowy B2B są odpinane (`contract_id` → NULL, stan „umowa bez
  projektu") i zostają w „Wygenerowane umowy"; notatki/rozmowy odpięte
  (SET NULL); pod-zasoby kontraktu (dokumenty, aneksy, harmonogramy,
  onboarding, sprzęt, faktury, zamówienia) idą FK CASCADE zgodnie ze
  schematem.
- FE: modal AppModal z opisem skutków, stan błędu WEWNĄTRZ modala,
  inwalidacja właściwych kluczy (`contracts-v2` + `contracts`).

## Weryfikacja

- Backend: **101 passed, 4 skipped** (pytest w `nexus-verify:img`, świeża
  baza po `alembic upgrade heads`): nowy `test_contractor_consolidation.py`
  (11 testów: grupowanie, filtry w grupie, redakcja członków, rodzeństwo,
  duplikaty po e-mailu ×4, 404, delete z odpięciem, delete `signed_both`),
  zaktualizowany `test_contract_lifecycle_invariant.py`, do tego bez zmian
  zielone: finance redaction, contractors API, contracts CRUD, b2b signature
  automation, employment filter. `ruff check` + `ruff format --check` czyste.
- OpenAPI smoke: `group_by_candidate` + `group_members` + `related_contracts`
  + `engagements` obecne w schemacie.
- Frontend: `tsc --noEmit` czysty, `next lint` czysty, `next build` 86/86
  stron, nowe vitesty (grupowanie listy, `extractErrorMsg` missing[]),
  middleware 95/95.
- Wizualnie (Chrome, harness `/preview/contracts-consolidation` — publiczny,
  same mocki, zasiany cache react-query): zgrupowany wiersz Pawła Małka
  (BP+VeloBank, rozbicie stawek per klient, „pracuje u 2 klientów"),
  dialog „+ Dodaj kolejny projekt" z walidacją (baner + czerwone pola
  + opisy PL przy próbie zapisu bez klienta).

## Znane ograniczenia / świadome decyzje

- Widok operacyjny `/api/contractors` (roster) nadal jest per-umowa — ticket
  dotyczył rejestru (`ContractsListV2`); podwójne liczenie w statsach rostera
  to osobny temat.
- `engagements` liczy wyłącznie status `active` (lustro dotychczasowej
  logiki stanu zatrudnienia) — kontrakt w `ending` pokazuje się w zakładkach
  i na liście, ale nie zmienia stanu „zatrudniony" (tak jak dotąd).
- Akcje masowe na liście operują na umowie głównej zgrupowanego wiersza
  (checkbox = primary id).
- Eksport XLSX/CSV pozostaje płaski (jedna umowa = jeden wiersz) — arkusz
  z komórkami wielowartościowymi nie nadaje się do pivotów.
