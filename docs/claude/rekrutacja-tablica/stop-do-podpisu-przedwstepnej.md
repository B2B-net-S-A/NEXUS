# Stop do podpisu umowy przedwstępnej: rekrutacja i osoba (23.11.2026)
<!-- indeks: `jobs.pre_contract_rule`, `pre_contract_requests.blocks_move`, 409 `PRE_CONTRACT_NOT_SIGNED`, wyjątek od „Kanban bez bramek” i „DL przesuwa bez blokad” -->

Zgłoszenie Artura 23.11.2026: Delivery Lead i Olaf (Head of Recruitment) mają
móc ustawić, że kandydat nie idzie dalej w procesie, dopóki nie podpisze umowy
przedwstępnej — przy jednej osobie, ale też dla całej rekrutacji, z wyborem
etapu, już przy tworzeniu rekrutacji. Do tej daty brak podpisu tylko ostrzegał
(`kontrakty/generator-umow-b2b-trzy-zakladki-cyklu-zycia-umowy.md`, sekcja
„Umowa przedwstępna w rekrutacji”). Makieta na stagingu:
https://claude.ai/artifact/57oWdtaKX1nwK8WtuxkVmR.

## Decyzje Artura 23.11.2026

- **Dwa poziomy.**
  - *Rekrutacja* (`jobs.pre_contract_rule`): „Każda osoba podpisuje umowę
    przedwstępną” + etap (przed wysłaniem CV / przed rozmową u klienta /
    przed umową B2B) + „Zatrzymaj kartę do podpisu”. Ustawia się na
    `/jobs/new` (sekcja „Warunki”, pod „Procesem u klienta”, domyślnie
    wyłączone) i potem w nagłówku rekrutacji (fakt z kłódką obok procesu).
    Prośba o osobę zakłada się sama, gdy osoba wejdzie na „Zweryfikowany”;
    wystawia rekruter prowadzący, jak przy prośbie ręcznej.
  - *Osoba* (`pre_contract_requests.blocks_move`): w oknie prośby i w panelu
    osoby › Umowa. `null` = jak rekrutacja, `true` = stop, `false` = wyjątek
    (bez blokady). Bez ustawienia rekrutacji działa samodzielnie.
- **Blokada liczy się od etapu prośby:** wejście na kolumnę etapu i dalej
  (CV wysłane / Rozmowa u klienta / Zatrudniony). Ruch na wcześniejsze
  kolumny, odrzucenie i cofanie są wolne.
- **Obowiązuje każdego, także Delivery Leada** — wyjątek od
  `dl-przesuwa-bez-blokad.md` i od `kanban-bez-bramek.md`. DL, Head of
  Recruitment i admin mają „Zdejmij blokadę” / „Wyjątek dla tej osoby”
  (zapis w historii prośby, dzwonek do proszącego i obserwujących).
- **Kto ustawia:** DL (klienta rekrutacji), Head of Recruitment, admin.
  Rekruter widzi stan, nie zmienia go.
- **Blokada znika sama** po podpisie obu stron (`signed`, potem `fulfilled`).
  Prośba zamknięta bez podpisu (anulowana, wycofana, odmowa, wygasła):
  bez ustawienia rekrutacji blokady nie ma; przy ustawieniu rekrutacji karta
  dalej stoi, bo „każda osoba podpisuje” — potrzebna nowa prośba albo wyjątek
  DL-a / HoR (`blocks_move = false` na prośbie). Inaczej anulowanie prośby
  przez rekrutera byłoby furtką.

## Jak to działa w kodzie

- **Reguła:** `services/pre_contract_stop.py` — `stop_from` (czysta: prośby
  pary, ustawienie rekrutacji, kolumna docelowa i bieżąca), `stop_for_pair`,
  `assert_pre_contract_signed` (409 `PRE_CONTRACT_NOT_SIGNED` z `origin`
  `job` / `person`), `can_set_stop`, `ensure_rule_request`,
  `backfill_rule_requests`. Osoba bez żadnej prośby, która minęła etap
  jeszcze przed ustawieniem rekrutacji, nie staje w połowie procesu.
- **Bramka:** `api/pipeline.apply_move` (ruchy ludzi: Tablica, okno
  „Przesuń dalej”, przegląd DL, przeciągnięcie) i `/bulk-move`. Konta
  serwisowe API v1 i bot Cpro (`policy.viewer is None`) nie stają — zapisują
  fakty z zewnątrz. Okno „Przesuń dalej”: pozycja `pre_contract` z
  `blocking=True` (`move_requirements._pre_contract_item`), dokładana po
  `_skip_fill_gates`, więc DL jej nie omija; rekruter przekazujący do „QC CV”
  nie stoi (filtr kolumn do `cv_qc`).
- **Prośby z ustawienia:** `ensure_rule_request` w `apply_move` po zapisie
  ruchu (kolumny od „Zweryfikowanego” do etapu, bez prośby w toku i bez
  podpisanej), proszący = ustawiający, wystawia rekruter prowadzący
  (`pair_recruiter_id`), dzwonek tylko do niego. Ten sam przy zapisie
  ustawienia (`backfill_rule_requests`).
- **API:** `POST /api/pre-contracts` przyjmuje `blocks_move` (403
  `MSG_STOP_ROLE` dla rekrutera), `POST /api/pre-contracts/{id}/stop`
  (stop / wyjątek / jak rekrutacja; zdarzenia `stop_set`, `stop_exception`,
  `stop_inherit` z dzwonkiem), `PUT /api/jobs/{id}/pre-contract-rule`,
  `POST /api/jobs` z `pre_contract_rule`. `GET /pre-contracts/pair` niesie
  `job_rule`, `stop`, `can_set_stop`; plakietka karty — `stop_column`,
  `stop_origin`.
- **Front:** `lib/pre-contract-stop.ts` (kolumna blokady z serwera,
  `PRE_CONTRACT_STOP_GAP` na strzałce), `PreContractRuleEditor` (ten sam na
  `/jobs/new` i w nagłówku — `JobPreContractRuleFact`, przy 1280 px sama
  kłódka), `PreContractRequestDialog` (przełącznik), `PreContractSection`
  (wiersz „Ruch karty” z wyjątkiem), `MoveNextDialog` i `DlReviewPanel`
  („Zdejmij blokadę”).
- **Schemat:** migracja 0761, DDL w `pre_contract_schema.STOP_DDL`, lustro
  w `entrypoint.sh` (test w `test_pre_contracts_rules.py`).
