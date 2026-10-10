# Ścieżka kandydata: przekazania, „Zweryfikowany”, jeden panel osoby (04.10.2026)

Plan 6 PR-ów (#2010, #2011, #2012, #2014, #2015 i PR 6) po analizie lejka
rekruter + Delivery Lead (makiety https://claude.ai/artifact/R6yvH1ADUD8U8UZdgpLdbu,
decyzje Artura D1–D4 z 04.10.2026). Raport: `docs/candidate-funnel-completion-report.md`.

- **Ruch karty spoza Tablicy idzie przez `hooks/usePipelineMoveCore.tsx`**
  (rozpoznanie odmów: `lib/pipeline-move-core.ts` `classifyMoveError`).
  Warsztaty, przegląd DL, kolejka Cpro i wysyłka zbiorcza mają te same okna
  co Tablica: ostrzeżenie „Przenieś mimo to”, debrief przed wyjściem
  z „Rozmowy u klienta”, bramka „Zweryfikowany”, QC CV, konflikt wersji.
  Nowy ekran z własnym `POST /api/pipeline/move` = regresja. Hook Tablicy
  (`usePipelineMove`) czyta te same klasyfikatory, ale wysyła `api.post`.
- **D1: „Zweryfikowany” wymaga arkusza screeningu i stawki kandydata NA
  SERWERZE** (`pipeline_move_rules.assert_verified_requirements`, 409
  `VERIFIED_REQUIREMENTS_MISSING`, wyłącznik `VERIFIED_GATE_ENABLED`) — tylko
  przy wejściu z „Nowych”/„Screeningu”; zwrot DL z QC CV przechodzi.
- **D2: ręczny ruch na „Zatrudniony” wymaga `hired_signed_via`** (422 bez
  pola, `other` z notatką). „Oznacz jako podpisaną” w Generatorze bez zmian.
- **D3: jedna sprawa „uzupełnij zamówienie” dla DL i Finansów** — otwiera ją
  każda droga zatrudnienia, zamyka `commit_order_write`
  (`hired_order_status.resolve_hired_order_cases_safely`) dopiero, gdy
  zamówienie nie ma braków, także numeru.
- **Jeden panel osoby (#2017–PR 3/3, decyzja Artura „Sekcje + Rozwiń”):**
  na Tablicy jest JEDNO `aside` „Panel osoby” (`person/PersonPanelShell`),
  380 px dla doku, całe okno w trybie szerokim (od 09.10.2026 — sekcja „Duży
  podgląd po lewej stronie panelu osoby”). Tryby szerokie: „Rozwiń”
  (pełne narzędzia osoby, `person/PersonWorkbenchTabs` — zakładki CV,
  Screening, Rozmowy, Umowa, Dopasowanie, Notatki i historia pod głową doku)
  i przegląd DL (`DlReviewBody layout="panel"`). Osobnego okna warsztatu
  (`BoardWorkbenchDrawer`/`PersonPanel`) już nie ma; na pulpicie przegląd DL
  zostaje oknem (`DlReviewPanel`). Sekcje doku, zakładki i dok pod przeglądem
  są UKRYTE, nie odmontowane (`hidden` + `inert`) — niewysłana notatka i powrót
  fokusu muszą przeżyć. Esc / klik w tło zamykają najwyższą warstwę: przegląd,
  rozwinięcie, kartę. Okno „Przesuń dalej”, z którego rozwinięto panel, wraca
  przy każdym wyjściu z trybu szerokiego. Zakładka z własnym ruchem (screening
  w „Nowych”, CV na „Zweryfikowanym”) chowa ramkę „Następny etap”. Fakty o
  osobie liczy `lib/person-facts.ts` i pokazuje `person/PersonFacts` — ten sam
  wygląd w doku i w przeglądzie DL; notatki pary: `useJobNotes`/`JobNotesBlock`
  (`jobs/workbench-chrome.tsx`). Nie dokładaj czwartej kopii faktów, notatek
  ani drugiego panelu osoby obok.
- **Rozmowa u klienta i umowa są w panelu osoby:** odznaka rozmowy niesie
  `slot_request` i `preps` (`interview_badges_for_job`), panel wybiera
  i potwierdza termin oraz otwiera ocenę prepu; na „Umowie”/„Zatrudnionym”
  `DockContractSteps` pokazuje umowę, podpis i zamówienie. Podpis potwierdza
  się nadal w rejestrze Generatora — panel prowadzi tam z wyszukaną umową.
  Tablica nie otwiera już kalendarza w nowej karcie.
- **Karta Tablicy:** dni w wierszu „kto ma ruch” (od 1 dnia), źródło,
  blokada 12 h i stan karty rekomendacji jako ikony (`compactCardBadge`),
  bez paska 7 kroków rozmowy (kroki są w panelu).
- **Pulpit „Czeka na Ciebie”** ma grupy „Twój ruch” i „U innych” (CV w drodze,
  wysłane do Cpro).
