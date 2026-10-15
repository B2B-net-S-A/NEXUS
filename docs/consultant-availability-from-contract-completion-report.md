# Dostępność i stawka osoby, która pracuje u nas — z umowy (15.10.2026)

Zgłoszenie pracownika: „W sytuacji, kiedy konsultant pracuje u nas, mogłoby dane
o jego dostępności i stawce czytać z jego kontraktu w Nexusie, a nie z notatek
screeningowych — teraz jest »Pracuje u nas do 30.11.2026« i jednocześnie
»Dostępność: 1.09.2026«”. Makiety i decyzje D1–D6:
https://claude.ai/artifact/1oJ9qiLdPFKTsEXTwdLpSN — Artur zatwierdził wszystkie
rekomendacje (D4 = B, D5 = tak). Reguła: `docs/claude/kandydaci-wyszukiwanie/znacznik-pracuje-u-nas.md`,
sekcja „Dostępność i stawka z umowy”, oraz „Żywa umowa” w
`docs/claude/screening-notatki/stawka-od-i-historia-stawek-kandydata.md`.

## Co było nie tak (pomiar produkcji 15.10.2026, tylko odczyt)

- 483 osoby z żywą umową po starcie; 308 z nich miało minioną datę „Dostępny od”
  (profil czytał się „dostępny”, tabela Tablicy pisała „od razu”), 112 — datę
  w odległości do 14 dni od startu umowy (zapisany był ich start u nas).
- 135 pracujących miało pigułkę „Szuka aktywnie” obok „Pracuje u nas”.
- 99 miało „Stawkę od” niższą o ponad 5 zł/h niż stawka z umowy (filtr „Stawka
  do”, plakietka budżetu i AI brały za niską kwotę); 153 nie miało jej wcale.
- Filtr „Dostępny do daty” przepuszczał pracujących z minioną datą, ocena
  dopasowania dawała im pełne punkty za dostępność.
- Tekst dostępności liczyło dziewięć miejsc na froncie, każde po swojemu.

## Co weszło

| Decyzja | Zmiana | Pliki |
|---|---|---|
| D1 | Termin = później z dat: dzień po końcu pracy u nas (`free_from` w znaczniku, z wszystkich umów przed wyborem jednej na klienta) i data z profilu; „Bez daty końca zamówienia”, „Zaczyna u nas …”, „Zamówienia skończyły się …” | `employment_marker.py`, `schemas/candidate.py`, `lib/contract-availability.ts` |
| D2 | Ekrany: karta „Do propozycji”, panel osoby, „Co już wiemy”, Tablica, lista, propozycje i filtr „dostępny teraz”, podgląd, przegląd DL, porównanie. Serwer: filtr „Dostępny do daty”, ocena dopasowania (+ kara za kolizję ze startem Championa), „Start” w przeglądzie DL, kolejka Cpro, data startu w Generatorze B2B, prompt uzasadnienia dopasowania | `contract_availability.py`, `structured_candidate_search.py`, `scoring_service.py` i ścieżki wsadowe, `dl_review.py`, `board_tasks.py`, `b2b_agreement_prefill.py`, `match_justification_service.py`, 10 plików frontu |
| D3 | „Szuka aktywnie / Otwarty na oferty” ukryte przy żywej umowie (pasek osoby, lista); status w bazie bez zmian | `ProfileHeader.tsx`, `CandidatesListV2.tsx` |
| D4 | Stawkę konsultanta z żywej umowy widzi każdy, kto widzi stawkę kandydata: „Stawka od”, historia stawek, „ostatni kontrakt” w przeglądzie DL. Stawka do klienta, marża, zakończone umowy — bez zmian | `candidate_rates.py`, `dl_review.py` |
| D5 | Żywa umowa nadpisuje „Stawkę od” (obserwacja `contract:`), wyzwalacze na umowach i harmonogramie stawek (migracja 0448 + entrypoint), przeliczenie raz dziennie; „Stawka u nas” z zieloną kropką w profilu | `candidate_rate_observations.py`, `candidate_rate_from.py`, `contract_rate_from_schema.py`, `0448_rate_from_contracts.py`, `entrypoint.sh`, `tasks/candidate_rate_from.py`, `CandidateProfileFactsBar.tsx`, `RateHistoryDialog.tsx` |
| D6 | Okno „Dostępność kandydata” z ramką: do kiedy osoba pracuje, kto ustala wcześniejsze odejście, że późniejsza data zastąpi termin z umowy | `CandidateProfileFactsBar.tsx` |

**Korekta D5 po przeglądzie kodu:** „jawne minimum z datą startu umowy” nie
wygrałoby u większości z 99 osób — stawka profilu ma datę importu, późniejszą
niż start umowy. Dlatego żywa umowa nadpisuje „Stawkę od”, dopóki trwa.

Do tego: inwentarz profilu (`f.availability_contract`, `f.rate_contract`),
przewodnik Jarvisa `candidate.profile` (zielona kropka, „Stawka u nas”),
przestemplowane `candidate.profile`, `candidates.list`, `jobs.person`; harnessy
`/preview/candidate-profile?employed=1`, `/preview/candidates-list`,
`/preview/job-detail` (dane fikcyjne).

## Weryfikacja

- Testy bez bazy lokalnie: 27 nowych (`test_contract_availability_rule.py`) +
  73 istniejących reguły znacznika i „Stawki od”, strażnicy przewodników
  i indeksu `CLAUDE.md`.
- Pełne CI na gałęzi (`gh workflow run CI`): zielone; 5 testów z bazą
  (`test_contract_availability_db.py`) — zgodność loadera z znacznikiem, filtr
  na granicy dnia końca pracy, wyzwalacze i powrót stawki po końcu umowy, krok
  harmonogramu, rekruter widzi kwotę żywej umowy, a zakończonej nie.
- Front: vitest dla 20+ plików testów (nowy `contract-availability.test.ts`,
  testy karty, pigułki, listy, Tablicy, propozycji, „Co już wiemy”), `tsc`.
- Przeklikane w 1280 × 720 na harnessach: karta „Do propozycji” („od
  01.01.2027”, „Stawka u nas 160 PLN netto/h”, zielone kropki, dymek z datą
  z profilu), okno edycji z ramką, lista („od 01.01 · z kontraktu”, bez „Szuka
  aktywnie”), panel osoby i „Co już wiemy” na Tablicy.

## Poza zakresem i ryzyka

- Ocena dopasowania nie unieważnia się przy samym przedłużeniu zamówienia
  (brak sygnału z zamówień) — punkty za dostępność (5/100) mogą chwilę odstawać.
- `order_end_date` znacznika to „koniec bez kontynuacji w zakresie alertów” —
  linie MD poza listą rozszerzoną dają „bez daty końca” (zgodnie z ramką
  „Zamówienie bez daty końca” na tym samym ekranie).
- Stawka umowy ≠ stawka z zamówienia u części osób; bierzemy umowę, jak historia
  stawek. Umowy nie w PLN zostają przy notatkach.
- Rola „Automatyzacje” zobaczy w aplikacji stawkę z umowy w „Stawce od”
  (D4: każdy, kto widzi stawkę kandydata). API kluczy dalej za zakresem kosztów.
- Po końcu umowy „Stawka od” wraca do starych notatek (decyzja z 04.10.2026 dla
  zakończonych umów).
- Bramka ruchu „dostępność znana” (`move_requirements`), `CandidateHighlights`
  („bezterminowo” z daty umowy) i filtr statusu „Szuka aktywnie” na liście — bez zmian.
- Po wdrożeniu: backfill 0448 kolejkuje ~480 osób; pętla „Stawki od” przelicza
  je paczkami po 500 co 30 s.
