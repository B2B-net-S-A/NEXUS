# Pipeline v4 — 6 kolumn, blokada 12 h, przegląd DL (0352, 23.09.2026)

Decyzje Artura 23.09.2026, makiety https://claude.ai/artifact/JQ8qdz16J6wG24WKTSgv6i.
Tablica: **Nowi · Zweryfikowany · CV wysłane · Rozmowa u klienta · Umowa ·
Zatrudniony** + pasek zamkniętych w czterech grupach (Zrezygnował / Odrzucony
przez nas / przez DL / przez klienta). Reguły, które łatwo cofnąć:

- **Etapy zostają, składa się render.** „Do przejrzenia” (propozycje na górze
  Nowych), „Screening” i „Akceptacja” są odznakami (kod etapu), nie kolumnami.
  Każda odznaka etapu jest wierszem `candidate_stages`, więc statystyki liczą
  ją osobno (`GET /api/insights/recruitment/stage-breakdown`, sekcja „Lejek po
  etapach” w Wynikach: „Doszło” vs „Teraz”). Kolumnę liczy JEDNA reguła
  w dwóch lustrach: `placeStage` i `board_stage_badges.board_column_for`
  (wspólny `__fixtures__/board-stage-cases.json`).
- **Blokada 12 h** (`services/candidate_claim.py`, kolumny
  `recruitment_processes.claimed_by_user_id/claimed_until`): osoba dodana
  ręcznie (każde ludzkie `open_process`, też „Biorę” na propozycji) jest 12 h
  dodającego w tej rekrutacji; inny rekruter dostaje 423 `CANDIDATE_CLAIMED`
  przy ruchu, ruchu zbiorczym i zapisie screeningu. Admin/DL/HoR omijają.
  `POST /api/pipeline/claim` = „Biorę” (wolna) / „Przejmij” (cudza aktywna —
  tylko DL/HoR/admin, dzwonek `candidate_claim_taken`). Wyjście poza Nowych
  czyści blokadę; wygaśnięcie liczy się przy odczycie. Automat
  (`auto_match`) nikogo nie blokuje.
- **Źródło wejścia** `recruitment_processes.entry_source`
  (added_manual|application|proposal|reassign|auto_match|import; NULL = proces
  sprzed 0352). Otwarta propozycja przepięcia (`JobProposal source=reassign`)
  daje `reassign` + `reassign_from_job_id`, niezależnie od ekranu dodania.
- **Rozmowa w Nowych.** Arkusz pytań Championa działa dla kart Nowych
  (`isNewColumn` w `lib/pipeline-flow.ts`). Luna
  (`AIFeatureKey.screening_reassign_suggest`, `services/screening_reassign.py`)
  podpowiada z wcześniejszych rozmów tej osoby: przy przepięciu z rekrutacji
  źródłowej (odpowiedzi i notatki), a od 02.10.2026 także z najwyżej trzech
  rozmów w innych rekrutacjach (same odpowiedzi, bez notatek). Rusza RAZ, po
  otwarciu arkusza, gdy jest puste pytanie i prawo zapisu; pod pytaniem stoi
  DOSŁOWNA wcześniejsza odpowiedź ze źródłem (rekrutacja, klient, data)
  i „Użyj tej odpowiedzi”. Tylko podpowiedź — awaria = `available:false`,
  a odpowiedzi przeniesione z podpowiedzi (`origin: reassign_suggested`) nie są
  materiałem dla kolejnych. Odpowiedź niesie `question_text` (stempel serwera,
  `services/screening_sheets.py`), bo identyfikatory pytań są pozycyjne i po
  edycji Championa wskazują inne pytanie. Odpowiedź `skipped` i `internal_note`
  („pominięte — przepięcie”) NIGDY nie idą do klienta: share portal i generator
  CV czytają `client_safe_screening` (bez `question_text`).
- **„CV wysłane” poza Nordeą wysyła DL** (`services/pipeline_move_rules.py`):
  rola admin/delivery_lead (403) i stawka do klienta w TYM SAMYM żądaniu ruchu
  (`client_rate_*` w `StageMove`/`BulkMoveRequest`, 422 bez niej; stawka
  zapisana wcześniej w tej rekrutacji wystarcza). Nordea bez zmian (DZ → Cpro,
  „Wysłane do Cpro” wysyła osoba wytypowana). Kolejka „Czeka na Twój przegląd
  (DL)” (`board_tasks.KIND_DL_REVIEW`, 30 dni) + `DlReviewPanel`; „Czeka na
  DZ” zostaje wyłącznie u Nordei.
- **Terminy od klienta przesuwają kartę** na „Rozmowę u klienta”
  (`pipeline_auto_move.auto_advance` w `create_slot_request`); odznaka karty =
  `interview_badges_for_job`. Wyjście z Rozmowy dalej wymaga debriefu
  (pytania klienta albo „klient nie zadawał pytań”, `services/debrief_gate.py`,
  409 `DEBRIEF_REQUIRED`) — pytania zasilają bank `client_debrief`: prep,
  follow-up i panel „Pytania klienta z rozmów” w Championie.
- **Podpis obustronny → „Zatrudniony”** (`ensure_hired=True`) +
  `hired_order_missing` do Finansów, gdy brak uzupełnionego zamówienia
  (`services/hired_order_status.py`; odznaka „Brak zamówienia” na karcie).
- **Kto zakończył**: `candidate_stages.ended_by` (candidate|recruiter|
  delivery_lead|client). Rezygnacja = zawsze kandydat; odrzucenie bez pola =
  „przez nas”; „przez DL” tylko admin/DL/HoR (403).
- **Stawka do klienta = sprawa DL** (decyzja 23.09.2026, `candidate_access`):
  zapisuje WYŁĄCZNIE admin i Delivery Lead (`CLIENT_RATE_WRITE_ROLES`, bez
  wyjątku dla właściciela rekrutacji), widzą dodatkowo HoR, TCM i Finanse
  (`CLIENT_RATE_VIEW_ROLES`, doprecyzowane tego samego dnia: nie widzą jej
  rekruter, sourcer i TAC). Rekruterowi serwer redaguje ją na tablicy,
  w historii etapów i w historii kandydata (`can_view_client_rate`) — widzi
  tylko oczekiwania kandydata i budżet Championa. Front: `lib/client-rate-access.ts`.
  Przegląd DL (pulpit i ruch „Zweryfikowany → CV wysłane” na tablicy)
  pokazuje stawkę kandydata, a od 08.10.2026 (D9) także marżę — wyłącznie
  osobie, która widzi kwoty klienta (`can_read_client_finance`); sekcja
  „Przegląd Delivery Leada v2”.
- **Screening i stawki należą do pary, nie do etapu.** `transition_process`
  kopiuje najnowszy wypełniony arkusz na nowy wiersz etapu (portal klienta,
  generator CV, przegląd DL czytają bieżący etap); `GET …/screening` dla
  wiersza bez arkusza oddaje arkusz pary (`screening_source_stage_id`), a karta
  tablicy niesie `screening_done`, stawkę kandydata i stawkę do klienta
  z wcześniejszych etapów.
- **„+ DZ” tylko u Nordei** (poza nią wysyła DL z przeglądu). **Integracja
  (token klienta OAuth, np. scraper pracuj.pl/JJIT) nie zakłada blokady** —
  wejście `auto_match` (`candidate_claim.is_integration_request`).
