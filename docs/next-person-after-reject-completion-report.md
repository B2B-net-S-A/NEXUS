# Po odrzuceniu z panelu osoby — od razu następna osoba — raport

Gałąź `claude/auto-next-candidate-09ce68`, 13.10.2026. Reguły: `docs/claude/rekrutacja-tablica/nastepna-osoba-po-odrzuceniu.md`.
Makiety (stan sprzed zmiany, propozycja, warianty): https://claude.ai/artifact/JMfDAZdjFJtGjFxwHNyta6.

## Skąd ta zmiana

Prośba rekrutera przekazana przez Artura 13.10.2026: po odrzuceniu kandydata system ma sam przejść do kolejnej
osoby z tej rekrutacji. Stan sprzed zmiany, sprawdzony chwilowym testem Tablicy: po „Potwierdź” panel zostawał
na odrzuconej osobie, „‹ N z M ›” zamieniał się w napis „Panel osoby”, znikały „Odrzuć z powodem”
i „Zrezygnował”, a potwierdzenia nie było. W widoku „Rozwiń” trzeba było zwinąć panel i szukać następnej karty.
Artur zatwierdził decyzje D1–D4 z makiet.

## Co się zmieniło

- **Panel przechodzi do osoby, która stała dalej w kolejności „›”**, po „Odrzuć z powodem”, „Zrezygnował”
  i „Odrzuć” w stopce formularza screeningu. Dopiero po ruchu potwierdzonym przez serwer, także po
  „Przenieś mimo to” i debriefie. W widoku „Rozwiń” następna osoba z „Nowych” albo „Screeningu” dostaje formularz.
- **Pasek „Odrzucono: X · powód · Pokaż”** (przy rezygnacji „Rezygnacja: …”) nad następną osobą; „Pokaż”
  otwiera zamkniętą osobę, a tam „Wróć do kolejki ›” zastępuje napis „Panel osoby”.
- **Ostatnia osoba**: panel się zamyka, komunikat „To była ostatnia osoba w kolejności Tablicy.” z „Pokaż”.
- **Okno odrzucenia** pokazuje imię i nazwisko zamykanej osoby (każde zamknięcie jednej osoby), a z panelu
  także kolumnę i „Dalej: …” albo „To ostatnia osoba na Tablicy — panel się zamknie.”.
- Sam frontend: `usePipelineMove.tsx` (`onMoved`, `followUp`), `KanbanBoardV2.tsx`, `PipelineCandidateDock.tsx`,
  `RejectionV2.tsx`, `ScreeningFullForm.tsx` z `ScreeningWorkbench.tsx` i `PersonWorkbenchTabs.tsx`,
  typ `lib/reject-follow-up.ts`. Bez backendu i migracji. Przewodnik Jarvisa `jobs.person` mówi o przejściu.

## Jak sprawdzone

- Testy: `KanbanBoardV2.test.tsx` (następna osoba, pasek znika po „›”, „Zrezygnował”, ostatnia osoba,
  konflikt wersji, „Przenieś mimo to”, panel przeniesiony w trakcie ruchu, widok „Rozwiń”, „Odrzuć” z formularza),
  `RejectionV2.test.tsx`, `PipelineCandidateDock.test.tsx`, `ScreeningFullForm.test.tsx`; `npm run type-check`, eslint.
- Przeklikane na harnessie `/preview/pipeline-v4` w oknie 1280×720 (z chwilową lokalną odpowiedzią na ruch karty,
  niezacommitowaną): okno z „Tomasz Zieliński · Nowi” i „Dalej: Paweł Fikcyjny · Nowi”, po „Potwierdź” panel
  na Pawle („1 z 18”) z paskiem, „Pokaż” i „Wróć do kolejki”.

## Poza zakresem

- „Zapisz i przekaż dalej” nie przenosi panelu (D1). Gdy zespół zechce tego samego po przekazaniu, wariant C
  z makiet („Przejrzyj po kolei” w „Nowych”).
- Odrzucenie z karty, przeciągnięcie, pasek zaznaczonych osób, okno „Przesuń dalej” i przegląd Delivery Leada — bez zmian.
